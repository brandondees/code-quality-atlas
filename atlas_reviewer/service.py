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

import contextvars
import os
import random
import shutil
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.ledger import make_private_dirs
from atlas_reviewer.redact import Redactor
from atlas_reviewer.service_admit import (
    EVENT_HEADER,
    SIGNATURE_HEADER,
    Admitted,
    admit,
    parse_delivery,
    signature_matches,
)
from atlas_reviewer.service_queue import Board, Enqueue, Job, JobState, QueueError
from atlas_reviewer.service_run import (
    WEBHOOK_SECRET_ENV,
    ReviewReport,
    ReviewRun,
    RunConfig,
    make_runner,
    run_dir,
)
from atlas_reviewer.stops import install_interrupts
from atlas_reviewer.telemetry import ERROR, Event, EventSink, JsonlSink, Telemetry

DEFAULT_REPO = "brandondees/code-quality-atlas"
# A pool past this is a bad environment value, not a review budget. Each
# review still has the controller's own call and cost caps.
MAX_CONCURRENCY = 32
MAX_BODY_BYTES = 5_000_000
MAX_POST_ATTEMPTS = 5
# A failed post is tried again on this schedule, then given up. The fifth
# attempt does not wait: it is the last try, so there is no fifth delay.
# Each wait is stretched by up to 20% so several machines do not retry
# together. The waits stop a dead GitHub endpoint from turning into a
# tight loop. They are not a cost cap: the review itself has already finished.
_POST_BACKOFF_S = (5.0, 15.0, 30.0, 60.0)
# One current file plus one rotated file. The cap is the operator log,
# not the review queue.
_SERVICE_LOG_BYTES = 1_048_576
_BACKOFF_JITTER = 0.2


class PostNotCurrent(Exception):
    """The head moved before the review was sent. Do not retry."""


class PostAuthError(Exception):
    """GitHub refused the credential. Do not retry."""


class RateLimited(Exception):
    """GitHub asked the caller to wait. ``retry_after`` is seconds."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# The poster reads this in the worker thread, immediately before the
# create, and sends nothing when it returns false.
before_send: contextvars.ContextVar[Callable[[], bool] | None] = contextvars.ContextVar(
    "atlas_review_before_send", default=None
)
_POLL_S = 0.2
_REQUEST_TIMEOUT_S = 20.0
# How long one request body may take, separate from the socket's idle
# timeout so a test can shorten it without also shortening every read.
_BODY_BUDGET_S = _REQUEST_TIMEOUT_S
_MAX_HTTP_HANDLERS = 16

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
    detail: str = ""


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
        return HttpResult(413, b"body too large\n", "body too large")
    if not signature_matches(body, _header(headers, SIGNATURE_HEADER), config.secret):
        return HttpResult(401, b"bad signature\n", "bad signature")
    event_name = _header(headers, EVENT_HEADER)
    if event_name == "ping":
        return HttpResult(200, b"pong\n", "ping")
    if event_name != "pull_request":
        return HttpResult(202, b"ignored\n", "ignored:event")
    payload = parse_delivery(body)
    if payload is None:
        return HttpResult(202, b"ignored\n", "ignored:body")
    decision = admit(payload, config.allowlist)
    if isinstance(decision, Admitted):
        result = board.enqueue(decision.event, at=decision.updated_at)
        if result is Enqueue.FULL:
            return HttpResult(503, b"full\n", "full")
        return HttpResult(202, f"{result.value}\n".encode(), result.value)
    return HttpResult(202, b"ignored\n", f"ignored:{decision.reason}")


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
        now: Callable[[], float] | None = None,
    ) -> None:
        self._board = board
        self._runner = runner
        self._telemetry = telemetry
        self._publisher = publisher
        self._concurrency = concurrency
        self._state_root = state_root or Path(".atlas-reviewer-state")
        self._now = now or time.time
        self._random = random.random
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def healthy(self) -> bool:
        """False once a worker thread has died. ``/health`` then fails
        so a dead worker is not hidden behind a 200."""
        return bool(self._threads) and all(
            thread.is_alive() for thread in self._threads
        )

    def start(self) -> None:
        for index in range(self._concurrency):
            thread = threading.Thread(target=self._loop, name=f"atlas-review-{index}")
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 30.0) -> None:
        """Cancel an in-flight review so its child can delete the Sprite,
        then wait for the workers. ``timeout`` is per worker thread."""
        self._stop.set()
        self._board.cancel_active()
        self._board.wake()
        for thread in self._threads:
            thread.join(timeout=timeout)

    def run_one(self) -> bool:
        if self._stop.is_set():
            return False
        job = self._board.claim()
        if job is None:
            return False
        if self._stop.is_set():
            self._board.release_claim(job)
            return False
        try:
            self._execute(job)
        except Exception as exc:  # noqa: BLE001 -- one job must not kill the worker
            self._fail_closed(job, exc)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._board.wait_for_work(
                    _POLL_S,
                    self._stop,
                    self._now(),
                    posts=self._publisher is not None,
                )
                if self._stop.is_set():
                    return
                self.run_one()
                if self._stop.is_set():
                    return
                self._retry_post()
            except Exception as exc:  # noqa: BLE001 -- the thread has to outlive one failure
                event = getattr(exc, "event", None)
                try:
                    self._telemetry.record(
                        "service",
                        "worker error",
                        _fields(event) if event is not None else {},
                        status=ERROR,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                except Exception:  # noqa: BLE001, S110 -- the log itself failed
                    pass

    def _retry_post(self) -> None:
        if self._publisher is None:
            return
        if self._stop.is_set():
            return
        job = self._board.claim_post(self._now(), stop=self._stop)
        if job is None:
            return
        try:
            self._publish_saved(job)
        except Exception as exc:  # noqa: BLE001 -- a post retry must not kill the worker
            self._fail_closed(job, exc)

    def _fail_closed(self, job: Job, exc: BaseException) -> None:
        """The job stays FAILED when the save works. When the save itself
        raises, the in-memory state is left as it was so a restart can
        queue a ``running`` job again, and the thread keeps going."""
        note = f"{type(exc).__name__}: {exc}"
        if job.state in {
            JobState.DONE,
            JobState.FAILED,
            JobState.SUPERSEDED,
            JobState.POST_PENDING,
        }:
            note += "; left the settled job alone"
            self._telemetry.record(
                "service",
                "worker error",
                _fields(job.event),
                status=ERROR,
                error=note,
            )
            return
        try:
            self._board.finish(job, JobState.FAILED)
        except Exception as save_exc:  # noqa: BLE001 -- the thread still has to record why
            note += f"; queue save failed: {type(save_exc).__name__}"
        self._telemetry.record(
            "service",
            "worker error",
            _fields(job.event),
            status=ERROR,
            error=note,
        )

    def _execute(self, job: Job) -> None:
        try:
            run = self._runner(job.event, job.cancel)
        except Exception as exc:  # noqa: BLE001 -- a review bug must not post
            run = ReviewRun(False, error=f"{type(exc).__name__}: {exc}")
        fields = _fields(job.event)
        if job.superseded:
            self._note(job, self._settle(job, JobState.SUPERSEDED), fields)
            return
        if job.cancel.is_set():
            # Stop is not a supersede. The same commit can be reviewed
            # again after the process starts.
            self._board.release_claim(job)
            return
        if not run.ok or run.report is None:
            committed = self._settle(job, JobState.FAILED)
            if committed is JobState.SUPERSEDED:
                self._note(job, committed, fields)
                return
            self._telemetry.record(
                "service",
                "review failed",
                fields,
                status=ERROR,
                error=run.error or "review failed",
            )
            return
        if not self._board.still_current(job):
            self._note(job, self._settle(job, JobState.SUPERSEDED), fields)
            return
        self._publish(job, run.report)

    def _publish(self, job: Job, report: ReviewReport) -> None:
        fields = _fields(job.event)
        if not self._board.still_current(job):
            self._note(job, self._settle(job, JobState.SUPERSEDED), fields)
            return
        if self._publisher is None:
            # Keep the draft. This process publishes nothing, and the
            # draft is the record of the review. The child's stderr is
            # not: it can hold a secret the log scrubber would remove.
            committed = self._board.finish(job, JobState.DONE)
            stderr = run_dir(self._state_root, job.event) / "stderr.txt"
            if stderr.is_file():
                try:
                    stderr.unlink()
                except OSError as exc:
                    self._telemetry.record(
                        "service",
                        "stderr not removed",
                        fields,
                        status=ERROR,
                        error=f"{type(exc).__name__}: {exc}",
                    )
            step = (
                "review superseded"
                if committed is JobState.SUPERSEDED
                else "review finished"
            )
            self._telemetry.record("service", step, fields)
            return
        token = before_send.set(lambda: self._board.begin_post(job))
        try:
            self._send(job, report)
        finally:
            before_send.reset(token)

    def _send(self, job: Job, report: ReviewReport) -> None:
        assert self._publisher is not None
        fields = _fields(job.event)
        if not self._board.begin_post(job):
            self._stopped_or_superseded(job, fields)
            return
        try:
            self._publisher(job.event, report)
        except PostNotCurrent:
            self._note(job, self._settle(job, JobState.SUPERSEDED), fields)
            return
        except PostAuthError as exc:
            committed = self._settle(job, JobState.FAILED)
            if committed is JobState.SUPERSEDED:
                self._note(job, committed, fields)
                return
            self._telemetry.record(
                "service",
                "review post failed",
                fields,
                status=ERROR,
                error=f"post auth refused: {exc}",
            )
            return
        except RateLimited as exc:
            self._defer_post(job, str(exc), retry_after=exc.retry_after)
            return
        except Exception as exc:  # noqa: BLE001 -- a post failure must not post again here
            self._defer_post(job, f"{type(exc).__name__}: {exc}")
            return
        committed = self._settle(job, JobState.DONE)
        step = (
            "review superseded" if committed is JobState.SUPERSEDED else "review posted"
        )
        self._telemetry.record("service", step, fields)

    def _publish_saved(self, job: Job) -> None:
        """A post that failed after the draft was written. The review is
        not run again. A missing draft posts nothing."""
        from atlas_reviewer.service_run import summarize_draft

        path = run_dir(self._state_root, job.event) / "draft.md"
        if not path.is_file() or self._publisher is None:
            committed = self._settle(job, JobState.FAILED)
            if committed is not JobState.SUPERSEDED:
                self._telemetry.record(
                    "service",
                    "review post failed",
                    _fields(job.event),
                    status=ERROR,
                    error="no draft to post",
                )
            else:
                self._note(job, committed, _fields(job.event))
            return
        try:
            report = summarize_draft(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            self._defer_post(job, f"{type(exc).__name__}: {exc}")
            return
        self._publish(job, report)

    def _defer_post(
        self, job: Job, error: str, *, retry_after: float | None = None
    ) -> None:
        """Try the post again later, up to ``MAX_POST_ATTEMPTS``. After
        that the review stays unpublished and the job is failed, so a
        dead endpoint cannot spin the worker. A rate-limit wait replaces
        the schedule when it is longer."""
        if job.superseded or job.cancel.is_set():
            self._stopped_or_superseded(job, _fields(job.event))
            return
        job.attempts += 1
        fields = _fields(job.event)
        if job.attempts >= MAX_POST_ATTEMPTS:
            committed = self._settle(job, JobState.FAILED)
            if committed is JobState.SUPERSEDED:
                self._note(job, committed, fields)
                return
            self._telemetry.record(
                "service",
                "review post failed",
                {**fields, "attempts": job.attempts},
                status=ERROR,
                error=f"post attempts exhausted: {error}",
            )
            return
        base = _POST_BACKOFF_S[min(job.attempts - 1, len(_POST_BACKOFF_S) - 1)]
        delay = base * (1 + self._random() * _BACKOFF_JITTER)
        if retry_after is not None:
            delay = max(delay, retry_after)
        job.retry_at = self._now() + delay
        committed = self._settle(job, JobState.POST_PENDING)
        if committed is JobState.SUPERSEDED:
            self._note(job, committed, fields)
            return
        self._telemetry.record(
            "service",
            "review post failed",
            {**fields, "attempts": job.attempts, "retry_s": round(delay, 3)},
            status=ERROR,
            error=error,
        )

    def _stopped_or_superseded(self, job: Job, fields: dict[str, str | int]) -> None:
        """A real supersede ends the job. A stop puts it back so the same
        commit is reviewed or posted after the process starts again."""
        if job.superseded:
            self._note(job, self._settle(job, JobState.SUPERSEDED), fields)
            return
        if job.state is JobState.POSTING:
            self._board.pause_post(job)
            return
        self._board.release_claim(job)

    def _settle(self, job: Job, state: JobState) -> JobState:
        committed = self._board.finish(job, state)
        if committed in {JobState.DONE, JobState.FAILED, JobState.SUPERSEDED}:
            path = run_dir(self._state_root, job.event)
            if path.is_dir():
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    self._telemetry.record(
                        "service",
                        "run dir not removed",
                        _fields(job.event),
                        status=ERROR,
                        error=f"{type(exc).__name__}: {exc}",
                    )
        return committed

    def _note(
        self, job: Job, committed: JobState, fields: dict[str, str | int]
    ) -> None:
        del job
        step = (
            "review superseded"
            if committed is JobState.SUPERSEDED
            else "review finished"
        )
        self._telemetry.record("service", step, fields)


def _fields(event: PrEvent) -> dict[str, str | int]:
    return {"pr": event.pr_number, "sha12": event.head_sha[:12], "repo": event.repo}


class _Handler(BaseHTTPRequestHandler):
    server: ReviewServer
    timeout = _REQUEST_TIMEOUT_S

    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        worker = getattr(self.server, "worker", None)
        if route == "/health" and (
            (worker is not None and not worker.healthy())
            or not self.server.board.saves_ok()
        ):
            self._send(503, b"unhealthy\n")
            self.server.log("atlas-reviewer: http 503 GET /health")
            return
        self._respond(b"")

    def do_POST(self) -> None:
        if not self.server.slots.acquire(blocking=False):
            self._send(429, b"busy\n")
            self.server.log("atlas-reviewer: http 429 POST /webhook busy")
            return
        try:
            self._read_post()
        finally:
            self.server.slots.release()

    def _read_post(self) -> None:
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.isascii() or not raw.isdigit():
            self._send(411, b"length required\n")
            return
        # Longer than the decimal length of the body cap. Reject before int().
        if len(raw) > len(str(self.server.config.max_body_bytes)):
            self._send(413, b"body too large\n")
            return
        length = int(raw)
        if length > self.server.config.max_body_bytes:
            self._send(413, b"body too large\n")
            return

        # arm() narrows the socket timeout to the body budget. The
        # response write uses the handler timeout again.
        previous = self.connection.gettimeout()

        def arm(seconds: float) -> None:
            # The buffered reader otherwise waits for the whole chunk.
            # The socket timeout is the time left on the body deadline.
            self.connection.settimeout(max(seconds, 0.05))

        try:
            body = read_bounded(
                self.rfile.read1,
                length,
                _monotonic() + _BODY_BUDGET_S,
                _monotonic,
                arm=arm,
            )
        finally:
            self.connection.settimeout(previous)
        if body is None:
            self._send(408, b"timeout\n")
            self.server.log("atlas-reviewer: http 408 POST /webhook slow body")
            return
        self._respond(body)

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
        route = self.path.split("?", 1)[0][:200]
        detail = f" {result.detail}" if result.detail else ""
        self.server.log(
            f"atlas-reviewer: http {result.status} {self.command} {route}{detail}"
        )

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def read_bounded(
    read: Callable[[int], bytes],
    length: int,
    deadline: float,
    now: Callable[[], float],
    *,
    arm: Callable[[float], None] | None = None,
) -> bytes | None:
    """Read ``length`` bytes, or None when ``now`` passes ``deadline``.

    ``read`` must return whatever is already available (``BufferedReader.read1``)
    rather than blocking until ``n`` bytes arrive. ``arm`` sets the socket
    timeout to the time still left, so a trickle cannot hold the handler
    by delivering one byte inside each long timeout.
    """
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        left = deadline - now()
        if left <= 0:
            return None
        if arm is not None:
            arm(left)
        try:
            block = read(min(remaining, 4096))
        except TimeoutError:
            return None
        if not block:
            break
        chunks.append(block)
        remaining -= len(block)
    if remaining:
        return None
    return b"".join(chunks)


def _monotonic() -> float:
    return time.monotonic()


class ReviewServer(ThreadingHTTPServer):
    worker: Worker | None = None

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
        self.slots = threading.BoundedSemaphore(_MAX_HTTP_HANDLERS)
        # Covers the thread, including a client that never finishes its
        # headers. The body slots alone start after the headers arrive.
        self.connections = threading.BoundedSemaphore(_MAX_HTTP_HANDLERS)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 429 Too Many Requests\r\n"
                    b"Content-Length: 5\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                    b"busy\n"
                )
            except OSError:
                pass
            request.close()
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


def config_from_env(env: Mapping[str, str]) -> ServiceConfig:
    secret = env.get(WEBHOOK_SECRET_ENV, "")
    repos = env.get("ATLAS_REVIEW_REPOS", DEFAULT_REPO)
    allowlist = frozenset(part.strip() for part in repos.split(",") if part.strip())
    concurrency = int(env.get("ATLAS_REVIEW_CONCURRENCY", "1"))
    provider = env.get("ATLAS_SERVICE_PROVIDER", "offline")
    live = env.get("ATLAS_ALLOW_LIVE_INFERENCE", "") == "1"
    # Local default is the loopback. The Fly app sets
    # ATLAS_SERVICE_HOST=0.0.0.0 because the proxy is not on loopback.
    host = env.get("ATLAS_SERVICE_HOST", "127.0.0.1")
    raw_port = env.get("ATLAS_SERVICE_PORT", "8080")
    if raw_port != "8080":
        raise ServiceError("ATLAS_SERVICE_PORT must be 8080, the port Fly checks")
    port = 8080
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


def _state_is_writable(path: Path) -> bool:
    try:
        make_private_dirs(path)
        probe = path / ".writable"
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(fd)
    except OSError:
        return False
    return True


class _LoggingSink:
    """Writes each service event to the JSONL sink and to the operator log.
    The event is already scrubbed by the time it is emitted."""

    def __init__(self, inner: EventSink, log: Callable[[str], None]) -> None:
        self._inner = inner
        self._log = log

    def emit(self, event: Event) -> None:
        self._inner.emit(event)
        pr = event.fields.get("pr", "")
        sha = event.fields.get("sha12", "")
        attempts = event.fields.get("attempts", "")
        retry = event.fields.get("retry_s", "")
        line = f"atlas-reviewer: {event.step} status={event.status} pr={pr} sha={sha}"
        if attempts != "":
            line += f" attempts={attempts}"
        if retry != "":
            line += f" retry_s={retry}"
        if event.error:
            line += f" error={event.error}"
        self._log(line)


def serve(
    config: ServiceConfig,
    env: Mapping[str, str],
    *,
    runner: Runner | None = None,
    publisher: Publisher | None = None,
    log: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
    secret_sources: tuple[Callable[[], Sequence[str]], ...] = (),
) -> int:
    install_interrupts()
    if not _state_is_writable(config.state_dir):
        log(f"atlas-reviewer: state dir {config.state_dir} is not writable")
        return 2
    board = Board(config.state_dir / "queue.json")
    redactor = Redactor(known_secrets=(config.secret,), sources=secret_sources)
    sink = JsonlSink(config.state_dir / "service.jsonl", max_bytes=_SERVICE_LOG_BYTES)
    sink.__enter__()
    try:
        telemetry = Telemetry(
            SystemClock(),
            scrub=lambda text: redactor(text).text,
            sink=_LoggingSink(sink, log),
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
        server.worker = worker
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
    finally:
        sink.__exit__(None, None, None)
    return 0


def _child_secrets(env: Mapping[str, str]) -> tuple[str, ...]:
    """Values the review child is allowed to hold. The service log has to
    scrub them, because the child's stderr is recorded here."""
    names = (
        "ATLAS_SPRITES_TOKEN",
        "ATLAS_OPENROUTER_API_KEY",
        "ATLAS_GITHUB_INSTALLATION_TOKEN",
    )
    return tuple(value for name in names if len(value := env.get(name, "")) >= 8)


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    del argv
    env = os.environ if env is None else env
    try:
        config = config_from_env(env)
    except (ServiceError, ValueError) as exc:
        print(f"atlas-reviewer: {exc}", file=sys.stderr)
        return 2
    try:
        return serve(config, env, secret_sources=(lambda: _child_secrets(env),))
    except KeyboardInterrupt:
        return 0
    except QueueError as exc:
        print(f"atlas-reviewer: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"atlas-reviewer: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
