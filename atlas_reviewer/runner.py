# SPDX-License-Identifier: MIT
"""One disposable, credential-free runner per review.

Lifecycle, in order, every step deadline-checked:

1. record the runner name in the ledger (before anything exists remotely)
2. create a fresh Sprite -- never reuse one: guests can restore checkpoints
   and create Tasks, so a used Sprite is contaminated
3. set deny-all egress from the outside API, then read it back; nothing
   executes unless the read-back is exactly deny-all
4. cap memory, probe which tool binaries exist, upload the head-SHA
   tarball over exec stdin, run each available tool
5. destroy -- in `finally`, and from a watchdog timer at the deadline.
   Destroy is idempotent and is verified by a follow-up existence check;
   only a verified destroy clears the ledger entry.

Exec-session kill is untested against the live API, so it is never relied
on: destroying the Sprite is the only cleanup primitive used.

Exec output: the HTTP exec endpoint (`POST /v1/sprites/{name}/exec`,
Sprites API OpenAPI 0.1.12, https://docs.fly.io/sprites/api/exec/execute-command)
documents its request but not its 200 response body. Live validation on
2026-11-06 saw `application/octet-stream` with SOH-prefixed stdout, which
matches the stream-id prefixes the WebSocket exec spec documents
(0x00 stdin, 0x01 stdout, 0x02 stderr, 0x03 exit code, 0x04 stdin EOF;
https://docs.fly.io/sprites/api/websockets/execute-command). Because HTTP
framing is undocumented, those prefix bytes are stripped rather than
parsed, and the exit code comes from an in-band marker each script prints.
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
PROBE_TAG = "atlas-probe"
FRAMING_CHECK = "atlas-framing-check"
_EXIT_RE = re.compile(re.escape(EXIT_MARKER) + r"(\d+)")
_PROBE_RE = re.compile(re.escape(PROBE_TAG) + r":(present|absent):([A-Za-z0-9._+-]+)")
_BINARY_RE = re.compile(r"[A-Za-z0-9._+-]+")
_EXEC_SLACK_S = 15.0
UPLOAD_BUDGET_S = 300.0
STDIN_CHECK_BYTES = 3 * 1024 * 1024
_FRAMING_BYTES = dict.fromkeys(range(0x05))


class DeadlineExceededError(RuntimeError):
    pass


class PolicyNotEnforcedError(BoundaryError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    """A review tool run inside the runner. Commands are trusted controller
    configuration; the code they run over is not."""

    name: str
    binary: str
    version_cmd: str
    run_cmd: str
    timeout_s: int = 120

    def __post_init__(self) -> None:
        if not _BINARY_RE.fullmatch(self.binary):
            raise ValueError(
                f"tool binary must be a bare command name: {self.binary!r}"
            )


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


@dataclass(frozen=True)
class ProbeOutcome:
    report: RunnerReport
    available: dict[str, bool]
    framing_sample: bytes
    stdin_check: str


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
    return raw.decode("utf-8", errors="replace").translate(_FRAMING_BYTES)


def parse_exit(text: str) -> tuple[int | None, str]:
    hits = list(_EXIT_RE.finditer(text))
    if not hits:
        return None, text
    last = hits[-1]
    return int(last.group(1)), text[: last.start()].rstrip("\n")


def probe_script(binaries: tuple[str, ...]) -> str:
    names = " ".join(dict.fromkeys(binaries))
    return (
        f'for b in {names}; do if command -v "$b" >/dev/null 2>&1; '
        f'then echo "{PROBE_TAG}:present:$b"; else echo "{PROBE_TAG}:absent:$b"; fi; done'
    )


def parse_probe(text: str, binaries: tuple[str, ...]) -> dict[str, bool]:
    """Unreported binaries count as absent: the guest is untrusted, and a
    missing answer must become UNKNOWN, not an assumed install."""
    seen = {name: state == "present" for state, name in _PROBE_RE.findall(text)}
    return {b: seen.get(b, False) for b in binaries}


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


Body = Callable[[SpritesApi, str, Deadline], str]


def _disposable(
    api: SpritesApi,
    ledger: RunnerLedger,
    body: Body,
    *,
    name: str,
    deadline_s: float,
    clock: Clock,
) -> RunnerReport:
    """Run `body` on a fresh, policy-verified Sprite; always destroy it."""
    deadline = Deadline(clock, deadline_s)
    destroyer = _Destroyer(api, ledger, name)
    ledger.record(name)
    watchdog = threading.Timer(max(deadline_s, 0.0), destroyer.destroy)
    watchdog.daemon = True
    watchdog.start()
    try:
        status, note = _guarded(api, name, deadline, body)
    finally:
        watchdog.cancel()
        cleanup = destroyer.destroy()
    return RunnerReport(status, cleanup, name, note)


def _guarded(
    api: SpritesApi, name: str, deadline: Deadline, body: Body
) -> tuple[RunnerStatus, str]:
    try:
        _provision(api, name, deadline)
        return RunnerStatus.COMPLETED, body(api, name, deadline)
    except DeadlineExceededError as exc:
        return RunnerStatus.DEADLINE_EXCEEDED, str(exc)
    except BoundaryError as exc:
        if deadline.remaining() <= 0:
            return RunnerStatus.DEADLINE_EXCEEDED, f"deadline reached: {exc}"
        return RunnerStatus.FAILED, str(exc)


def run_disposable(
    api: SpritesApi,
    ledger: RunnerLedger,
    job: RunnerJob,
    *,
    name: str,
    deadline_s: float,
    clock: Clock,
) -> RunnerOutcome:
    results: list[ToolResult] = []

    def body(api: SpritesApi, name: str, deadline: Deadline) -> str:
        available = _probe(api, name, job.tools, deadline)
        _upload(api, name, job.source_tarball, deadline)
        for tool in job.tools:
            results.append(_run_if_available(api, name, tool, available, deadline))
        return f"{len(results)} tool(s) attempted"

    report = _disposable(
        api, ledger, body, name=name, deadline_s=deadline_s, clock=clock
    )
    return RunnerOutcome(report, tuple(results))


def probe_runner(
    api: SpritesApi,
    ledger: RunnerLedger,
    tools: tuple[ToolSpec, ...],
    *,
    name: str,
    deadline_s: float,
    clock: Clock,
) -> ProbeOutcome:
    """The live-protocol check: provision, probe tools, capture one raw exec
    response for framing, destroy. Uploads and runs nothing from a PR."""
    found: dict[str, bool] = {}
    sample: list[bytes] = []
    stdin_check: list[str] = []

    def body(api: SpritesApi, name: str, deadline: Deadline) -> str:
        found.update(_probe(api, name, tools, deadline))
        timeout = deadline.check("framing check")
        sample.append(api.exec(name, _sh(f"echo {FRAMING_CHECK}"), b"", timeout))
        stdin_check.append(_stdin_roundtrip(api, name, deadline))
        return f"probed {len(found)} binar{'y' if len(found) == 1 else 'ies'}"

    report = _disposable(
        api, ledger, body, name=name, deadline_s=deadline_s, clock=clock
    )
    return ProbeOutcome(
        report, found, b"".join(sample), stdin_check[0] if stdin_check else "not run"
    )


def _stdin_roundtrip(api: SpritesApi, name: str, deadline: Deadline) -> str:
    """Send the size of a real upload through the upload's own `head -c`
    mechanism and read back how many bytes the runner saw."""
    sent = STDIN_CHECK_BYTES
    try:
        code, text = _exec(
            api,
            name,
            f"head -c {sent} | wc -c",
            deadline,
            "stdin round-trip",
            stdin=bytes(sent),
            budget_s=UPLOAD_BUDGET_S,
        )
    except BoundaryError as exc:
        return f"FAILED sending {sent} bytes: {exc}"
    digits = text.strip().split()
    if code != 0 or not digits or not digits[-1].isdigit():
        return f"FAILED sending {sent} bytes: exit {code}: {text[-200:]!r}"
    got = int(digits[-1])
    verdict = "ok" if got == sent else "MISMATCH"
    return f"{verdict}: sent {sent} bytes, runner received {got}"


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


def _probe(
    api: SpritesApi, name: str, tools: tuple[ToolSpec, ...], deadline: Deadline
) -> dict[str, bool]:
    binaries = tuple(t.binary for t in tools)
    if not binaries:
        return {}
    code, text = _exec(
        api, name, probe_script(binaries), deadline, "tool probe", budget_s=60.0
    )
    if code != 0:
        return dict.fromkeys(binaries, False)
    return parse_probe(text, binaries)


def _upload(api: SpritesApi, name: str, tarball: bytes, deadline: Deadline) -> None:
    """`head -c` stops reading after exactly the bytes sent, so extraction does
    not depend on the exec channel delivering a stdin EOF (an unverified
    hypothesis for the pilot's timed-out upload; see the README)."""
    script = (
        f"mkdir -p {WORKDIR} && head -c {len(tarball)} | "
        f"tar -xzf - -C {WORKDIR} --strip-components=1"
    )
    try:
        code, text = _exec(
            api,
            name,
            script,
            deadline,
            "source upload",
            stdin=tarball,
            budget_s=UPLOAD_BUDGET_S,
        )
    except BoundaryError as exc:
        raise BoundaryError(
            f"source upload of {len(tarball)} bytes did not complete: {exc}"
        ) from exc
    if code != 0:
        raise BoundaryError(f"source upload failed (exit {code}): {text[-500:]}")


def _run_if_available(
    api: SpritesApi,
    name: str,
    tool: ToolSpec,
    available: dict[str, bool],
    deadline: Deadline,
) -> ToolResult:
    if not available.get(tool.binary, False):
        return ToolAbsent(tool, f"`{tool.binary}` not found by the availability probe")
    return _run_tool(api, name, tool, deadline)


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
