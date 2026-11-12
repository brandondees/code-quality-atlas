# SPDX-License-Identifier: MIT
"""Webhook receiver: verify, admit, queue, and run one review at a time.

``python -m atlas_reviewer.service`` listens for GitHub App deliveries and
answers before it runs a review, so the request does not wait on the
controller. Publishing a finished review is a separate step; with no
publisher the receiver records the draft and writes nothing to GitHub.

The webhook secret stays in this process. The review child is started
without it.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.redact import Redactor
from atlas_reviewer.service_admit import (
    EVENT_HEADER,
    SIGNATURE_HEADER,
    Admitted,
    admit,
    parse_delivery,
    signature_matches,
)
from atlas_reviewer.service_queue import Board, Job, JobState
from atlas_reviewer.service_run import (
    WEBHOOK_SECRET_ENV,
    ReviewReport,
    ReviewRun,
    RunConfig,
    make_runner,
)
from atlas_reviewer.telemetry import ERROR, Telemetry

DEFAULT_REPO = "brandondees/code-quality-atlas"
# A pool past this is a bad environment value, not a review budget. Each
# review still has the controller's own call and cost caps.
MAX_CONCURRENCY = 32
MAX_BODY_BYTES = 5_000_000
_POLL_S = 0.2

Publisher = Callable[[PrEvent, ReviewReport], None]
Runner = Callable[[PrEvent, threading.Event], ReviewRun]


class ServiceError(Exception):
    """Startup configuration that must stop the process before it listens."""


@dataclass(frozen=True)
class ServiceConfig:
    secret: str
    allowlist: frozenset[str]
    concurrency: int = 1
    host: str = "127.0.0.1"
    port: int = 8080
    state_dir: Path = Path(".atlas-reviewer-state")
    provider: str = "offline"
    allow_live_inference: bool = False
    max_body_bytes: int = MAX_BODY_BYTES

    def __post_init__(self) -> None:
        if len(self.secret) < 16:
            raise ServiceError("the webhook secret must be at least 16 characters")
        if not self.allowlist:
            raise ServiceError("the repository allowlist is empty")
        if (
            isinstance(self.concurrency, bool)
            or not isinstance(self.concurrency, int)
            or not 1 <= self.concurrency <= MAX_CONCURRENCY
        ):
            raise ServiceError(
                f"concurrency must be an integer from 1 to {MAX_CONCURRENCY}"
            )
        if self.provider not in {"offline", "openrouter"}:
            raise ServiceError("provider must be offline or openrouter")
        if self.provider == "openrouter" and not self.allow_live_inference:
            raise ServiceError(
                "openrouter reviews need live inference enabled on the service"
            )


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes


def handle_delivery(
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: bytes,
    config: ServiceConfig,
    board: Board,
) -> HttpResult:
    """One HTTP request. A bad signature is refused. Everything else that
    is not a queued review is acknowledged so GitHub does not keep the
    delivery open, and nothing is enqueued."""
    route = path.split("?", 1)[0]
    if method == "GET" and route == "/health":
        return HttpResult(200, b"ok\n")
    if method != "POST" or route != "/webhook":
        return HttpResult(404, b"not found\n")
    if len(body) > config.max_body_bytes:
        return HttpResult(413, b"body too large\n")
    if not signature_matches(body, _header(headers, SIGNATURE_HEADER), config.secret):
        return HttpResult(401, b"bad signature\n")
    event_name = _header(headers, EVENT_HEADER)
    if event_name == "ping":
        return HttpResult(200, b"pong\n")
    if event_name != "pull_request":
        return HttpResult(202, b"ignored\n")
    payload = parse_delivery(body)
    if payload is None:
        return HttpResult(202, b"ignored\n")
    decision = admit(payload, config.allowlist)
    if isinstance(decision, Admitted):
        result = board.enqueue(decision.event)
        return HttpResult(202, f"{result.value}\n".encode())
    return HttpResult(202, b"ignored\n")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    return lowered.get(name.lower())


class Worker:
    """Claims queued jobs and runs them. A publisher, when set, is called
    only after a review that was not superseded and did not fail."""

    def __init__(
        self,
        board: Board,
        runner: Runner,
        telemetry: Telemetry,
        publisher: Publisher | None = None,
        concurrency: int = 1,
        state_root: Path | None = None,
    ) -> None:
        self._board = board
        self._runner = runner
        self._telemetry = telemetry
        self._publisher = publisher
        self._concurrency = concurrency
        self._state_root = state_root or Path(".atlas-reviewer-state")
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for index in range(self._concurrency):
            thread = threading.Thread(
                target=self._loop, name=f"atlas-review-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._board.wake()
        for thread in self._threads:
            thread.join(timeout=timeout)

    def run_one(self) -> bool:
        job = self._board.claim()
        if job is None:
            return False
        self._execute(job)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._board.wait_for_work(_POLL_S, self._stop)
            if self._stop.is_set():
                return
            self.run_one()
            self._retry_post()

    def _retry_post(self) -> None:
        if self._publisher is None:
            return
        job = self._board.claim_post()
        if job is None:
            return
        self._publish_saved(job)

    def _execute(self, job: Job) -> None:
        try:
            run = self._runner(job.event, job.cancel)
        except Exception as exc:  # noqa: BLE001 -- a review bug must not post
            run = ReviewRun(False, error=f"{type(exc).__name__}: {exc}")
        fields = _fields(job.event)
        if job.superseded or job.cancel.is_set():
            self._board.finish(job, JobState.SUPERSEDED)
            self._telemetry.record("service", "review superseded", fields)
            return
        if not run.ok or run.report is None:
            self._board.finish(job, JobState.FAILED)
            self._telemetry.record(
                "service",
                "review failed",
                fields,
                status=ERROR,
                error=run.error or "review failed",
            )
            return
        if not self._board.still_current(job):
            self._board.finish(job, JobState.SUPERSEDED)
            self._telemetry.record("service", "review superseded", fields)
            return
        self._publish(job, run.report)

    def _publish(self, job: Job, report: ReviewReport) -> None:
        if not self._board.still_current(job):
            self._board.finish(job, JobState.SUPERSEDED)
            self._telemetry.record("service", "review superseded", _fields(job.event))
            return
        if self._publisher is None:
            self._board.finish(job, JobState.DONE)
            self._telemetry.record("service", "review finished", _fields(job.event))
            return
        try:
            self._publisher(job.event, report)
        except Exception as exc:  # noqa: BLE001 -- a post failure must not post again here
            self._board.finish(job, JobState.POST_PENDING)
            self._telemetry.record(
                "service",
                "review post failed",
                _fields(job.event),
                status=ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self._board.finish(job, JobState.DONE)
        self._telemetry.record("service", "review posted", _fields(job.event))

    def _publish_saved(self, job: Job) -> None:
        """A post that failed after the draft was written. The review is
        not run again. A missing draft posts nothing."""
        from atlas_reviewer.service_run import run_dir, summarize_draft

        path = run_dir(self._state_root, job.event) / "draft.md"
        if not path.is_file() or self._publisher is None:
            self._board.finish(job, JobState.FAILED)
            self._telemetry.record(
                "service",
                "review post failed",
                _fields(job.event),
                status=ERROR,
                error="no draft to post",
            )
            return
        try:
            report = summarize_draft(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            self._board.finish(job, JobState.POST_PENDING)
            self._telemetry.record(
                "service",
                "review post failed",
                _fields(job.event),
                status=ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self._publish(job, report)


def _fields(event: PrEvent) -> dict[str, str | int]:
    return {"pr": event.pr_number, "sha12": event.head_sha[:12], "repo": event.repo}


class _Handler(BaseHTTPRequestHandler):
    server: ReviewServer

    def do_GET(self) -> None:
        self._respond(b"")

    def do_POST(self) -> None:
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.isascii() or not raw.isdigit():
            self._send(411, b"length required\n")
            return
        length = int(raw)
        if length > self.server.config.max_body_bytes:
            self._send(413, b"body too large\n")
            return
        self._respond(self.rfile.read(length))

    def log_message(self, fmt: str, *args: object) -> None:
        """The access log would record the request line only, and a body
        never belongs there. The handler's result line is the record."""
        return

    def _respond(self, body: bytes) -> None:
        result = handle_delivery(
            self.command,
            self.path,
            {key: value for key, value in self.headers.items()},
            body,
            self.server.config,
            self.server.board,
        )
        self._send(result.status, result.body)
        route = self.path.split("?", 1)[0]
        self.server.log(f"atlas-reviewer: http {result.status} {self.command} {route}")

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ReviewServer(ThreadingHTTPServer):
    def __init__(
        self,
        config: ServiceConfig,
        board: Board,
        log: Callable[[str], None],
    ) -> None:
        super().__init__((config.host, config.port), _Handler)
        self.config = config
        self.board = board
        self.log = log


def config_from_env(env: Mapping[str, str]) -> ServiceConfig:
    secret = env.get(WEBHOOK_SECRET_ENV, "")
    repos = env.get("ATLAS_REVIEW_REPOS", DEFAULT_REPO)
    allowlist = frozenset(part.strip() for part in repos.split(",") if part.strip())
    concurrency = int(env.get("ATLAS_REVIEW_CONCURRENCY", "1"))
    provider = env.get("ATLAS_SERVICE_PROVIDER", "offline")
    live = env.get("ATLAS_ALLOW_LIVE_INFERENCE", "") == "1"
    host = env.get("ATLAS_SERVICE_HOST", "0.0.0.0")
    port = int(env.get("ATLAS_SERVICE_PORT", "8080"))
    state = Path(env.get("ATLAS_REVIEWER_STATE_DIR", ".atlas-reviewer-state"))
    return ServiceConfig(
        secret=secret,
        allowlist=allowlist,
        concurrency=concurrency,
        host=host,
        port=port,
        state_dir=state,
        provider=provider,
        allow_live_inference=live,
    )


def serve(
    config: ServiceConfig,
    env: Mapping[str, str],
    *,
    runner: Runner | None = None,
    publisher: Publisher | None = None,
    log: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
) -> int:
    board = Board(config.state_dir / "queue.json")
    redactor = Redactor(known_secrets=(config.secret,))
    telemetry = Telemetry(
        SystemClock(),
        scrub=lambda text: redactor(text).text,
    )
    if runner is None:
        runner = make_runner(
            RunConfig(
                config.provider,
                config.allow_live_inference,
                config.state_dir,
            ),
            env,
        )
    worker = Worker(
        board, runner, telemetry, publisher, config.concurrency, config.state_dir
    )
    server = ReviewServer(config, board, log)
    worker.start()
    log(
        "atlas-reviewer: service listening"
        f" on {config.host}:{config.port};"
        f" concurrency {config.concurrency} (refuses above {MAX_CONCURRENCY});"
        f" repos {', '.join(sorted(config.allowlist))}"
    )
    try:
        server.serve_forever()
    finally:
        worker.stop()
        server.server_close()
    return 0


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    del argv
    env = os.environ if env is None else env
    try:
        config = config_from_env(env)
    except (ServiceError, ValueError) as exc:
        print(f"atlas-reviewer: {exc}", file=sys.stderr)
        return 2
    try:
        return serve(config, env)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"atlas-reviewer: {exc}", file=sys.stderr)
        return 2
