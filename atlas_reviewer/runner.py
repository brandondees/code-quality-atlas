# SPDX-License-Identifier: MIT
"""One disposable, credential-free runner per review.

Lifecycle, in order, every step deadline-checked:

1. record the runner name in the ledger (before anything exists remotely)
2. create a fresh Sprite -- never reuse one: guests can restore checkpoints
   and create Tasks, so a used Sprite is contaminated
3. set deny-all egress from the outside API, then read it back; nothing
   executes unless the read-back is exactly deny-all
4. cap memory, upload the head-SHA tarball over exec stdin, run each tool
5. destroy -- in `finally`, and from a watchdog timer at the deadline.
   Destroy is idempotent and is verified by a follow-up existence check;
   only a verified destroy clears the ledger entry.

Exec-session kill is untested against the live API, so it is never relied
on: destroying the Sprite is the only cleanup primitive used.
"""

from __future__ import annotations

import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from atlas_reviewer.domain import CleanupStatus, RunnerReport, RunnerStatus
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    Json,
    NotFoundError,
    RunnerLedger,
    SpritesApi,
)

DENY_ALL: tuple[Json, ...] = ({"action": "deny", "domain": "*"},)
MEMORY_LIMIT_MB = 1024
WORKDIR = "/work"
EXIT_MARKER = "__ATLAS_EXIT__="
EXIT_NOT_FOUND = 127
_EXIT_RE = re.compile(re.escape(EXIT_MARKER) + r"(\d+)")
_EXEC_SLACK_S = 15.0
_FRAMING_BYTES = dict.fromkeys(range(0x04))


class DeadlineExceededError(RuntimeError):
    pass


class PolicyNotEnforcedError(BoundaryError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    """A review tool run inside the runner. Commands are trusted controller
    configuration; the code they run over is not."""

    name: str
    version_cmd: str
    run_cmd: str
    timeout_s: int = 120


@dataclass(frozen=True)
class RunnerJob:
    source_tarball: bytes
    tools: tuple[ToolSpec, ...]


@dataclass(frozen=True)
class ToolRan:
    tool: ToolSpec
    version: str
    exit_code: int | None
    output: str


@dataclass(frozen=True)
class ToolAbsent:
    tool: ToolSpec
    detail: str


ToolResult = ToolRan | ToolAbsent


@dataclass(frozen=True)
class RunnerOutcome:
    report: RunnerReport
    results: tuple[ToolResult, ...]


@dataclass
class Deadline:
    clock: Clock
    seconds: float
    _start: float = field(init=False)

    def __post_init__(self) -> None:
        self._start = self.clock.monotonic()

    def remaining(self) -> float:
        return self.seconds - (self.clock.monotonic() - self._start)

    def check(self, step: str) -> float:
        left = self.remaining()
        if left <= 0:
            raise DeadlineExceededError(
                f"deadline of {self.seconds:g}s reached before {step}"
            )
        return left


def runner_name(
    clock: Clock, token_hex: Callable[[int], str] = secrets.token_hex
) -> str:
    return f"cqa-rev-{clock.now():%Y%m%d-%H%M%S}-{token_hex(3)}"


def decode_exec_output(raw: bytes) -> str:
    """Exec stdout came back SOH-framed in live validation (exact framing
    unverified); strip low control bytes rather than parse frames."""
    return raw.decode("utf-8", errors="replace").translate(_FRAMING_BYTES)


def parse_exit(text: str) -> tuple[int | None, str]:
    hits = list(_EXIT_RE.finditer(text))
    if not hits:
        return None, text
    last = hits[-1]
    return int(last.group(1)), text[: last.start()].rstrip("\n")


def _sh(script: str) -> tuple[str, ...]:
    return ("sh", "-c", f"{script}; echo {EXIT_MARKER}$?")


class _Destroyer:
    """Idempotent, thread-safe destroy shared by `finally` and the watchdog."""

    def __init__(self, api: SpritesApi, ledger: RunnerLedger, name: str) -> None:
        self._api, self._ledger, self._name = api, ledger, name
        self._lock = threading.Lock()
        self._status: CleanupStatus | None = None

    def destroy(self) -> CleanupStatus:
        with self._lock:
            if self._status is None:
                self._status = self._destroy()
            return self._status

    def _destroy(self) -> CleanupStatus:
        if not any(self._attempt_delete() for _ in range(2)):
            return CleanupStatus.DESTROY_UNVERIFIED
        if not self._verified_absent():
            return CleanupStatus.DESTROY_UNVERIFIED
        self._ledger.clear(self._name)
        return CleanupStatus.DESTROYED_VERIFIED

    def _attempt_delete(self) -> bool:
        try:
            self._api.delete(self._name)
        except NotFoundError:
            return True
        except BoundaryError:
            return False
        return True

    def _verified_absent(self) -> bool:
        try:
            return not self._api.exists(self._name)
        except BoundaryError:
            return False


def destroy_runner(api: SpritesApi, ledger: RunnerLedger, name: str) -> CleanupStatus:
    return _Destroyer(api, ledger, name).destroy()


def run_disposable(
    api: SpritesApi,
    ledger: RunnerLedger,
    job: RunnerJob,
    *,
    name: str,
    deadline_s: float,
    clock: Clock,
) -> RunnerOutcome:
    deadline = Deadline(clock, deadline_s)
    destroyer = _Destroyer(api, ledger, name)
    ledger.record(name)
    watchdog = threading.Timer(max(deadline_s, 0.0), destroyer.destroy)
    watchdog.daemon = True
    watchdog.start()
    results: list[ToolResult] = []
    try:
        status, note = _execute(api, name, job, deadline, results)
    finally:
        watchdog.cancel()
        cleanup = destroyer.destroy()
    return RunnerOutcome(RunnerReport(status, cleanup, name, note), tuple(results))


def _execute(
    api: SpritesApi,
    name: str,
    job: RunnerJob,
    deadline: Deadline,
    results: list[ToolResult],
) -> tuple[RunnerStatus, str]:
    try:
        _provision(api, name, deadline)
        _upload(api, name, job.source_tarball, deadline)
        results.extend(_run_tool(api, name, tool, deadline) for tool in job.tools)
    except DeadlineExceededError as exc:
        return RunnerStatus.DEADLINE_EXCEEDED, str(exc)
    except BoundaryError as exc:
        if deadline.remaining() <= 0:
            return RunnerStatus.DEADLINE_EXCEEDED, f"deadline reached: {exc}"
        return RunnerStatus.FAILED, str(exc)
    return RunnerStatus.COMPLETED, f"{len(results)} tool(s) attempted"


def _provision(api: SpritesApi, name: str, deadline: Deadline) -> None:
    deadline.check("create")
    api.create(name)
    deadline.check("network policy")
    api.set_network_policy(name, DENY_ALL)
    _require_deny_all(api.get_network_policy(name))
    deadline.check("resource policy")
    api.set_memory_limit(name, MEMORY_LIMIT_MB)


def _require_deny_all(policy: Json) -> None:
    rules = policy.get("rules")
    if not isinstance(rules, list) or [dict(r) for r in rules] != [
        dict(r) for r in DENY_ALL
    ]:
        raise PolicyNotEnforcedError(
            f"network policy read-back is not deny-all: {rules!r}"
        )


def _exec(
    api: SpritesApi,
    name: str,
    script: str,
    deadline: Deadline,
    step: str,
    stdin: bytes = b"",
    budget_s: float | None = None,
) -> tuple[int | None, str]:
    left = deadline.check(step)
    timeout = left if budget_s is None else min(left, budget_s)
    raw = api.exec(name, _sh(script), stdin, timeout)
    return parse_exit(decode_exec_output(raw))


def _upload(api: SpritesApi, name: str, tarball: bytes, deadline: Deadline) -> None:
    script = f"mkdir -p {WORKDIR} && tar -xzf - -C {WORKDIR} --strip-components=1"
    code, text = _exec(api, name, script, deadline, "source upload", stdin=tarball)
    if code != 0:
        raise BoundaryError(f"source upload failed (exit {code}): {text[-500:]}")


def _run_tool(
    api: SpritesApi, name: str, tool: ToolSpec, deadline: Deadline
) -> ToolResult:
    budget = tool.timeout_s + _EXEC_SLACK_S
    v_code, v_text = _exec(
        api,
        name,
        f"cd {WORKDIR} && {tool.version_cmd}",
        deadline,
        f"{tool.name} version",
        budget_s=budget,
    )
    if v_code != 0:
        return ToolAbsent(tool, f"version probe exited {v_code}: {v_text[-300:]}")
    script = f"cd {WORKDIR} && timeout --kill-after=5 {tool.timeout_s} {tool.run_cmd}"
    code, text = _exec(api, name, script, deadline, f"{tool.name} run", budget_s=budget)
    return ToolRan(tool, _first_line(v_text), code, text)


def _first_line(text: str) -> str:
    stripped = text.strip()
    return stripped.splitlines()[0] if stripped else "unknown"


def sweep(api: SpritesApi, ledger: RunnerLedger) -> dict[str, CleanupStatus]:
    """Destroy every runner a previous (possibly crashed) review left behind."""
    return {name: destroy_runner(api, ledger, name) for name in ledger.pending()}
