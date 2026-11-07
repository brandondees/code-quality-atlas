# SPDX-License-Identifier: MIT
"""One disposable, credential-free runner per review.

Lifecycle, in order, every step deadline-checked and recorded as a
telemetry event (`atlas_reviewer.telemetry`):

1. record the runner name in the ledger (before anything exists remotely)
2. create a fresh Sprite -- never reuse one: guests can restore checkpoints
   and create Tasks, so a used Sprite is contaminated
3. set deny-all egress from the outside API, then read it back; nothing
   executes unless the read-back is exactly deny-all
4. cap memory; probe which tool binaries exist (tool check); upload the
   head-SHA tarball over exec stdin to a file, confirming the byte count
   the runner received; unpack it in a second exec; run each available tool
5. destroy -- in `finally`, and from a watchdog timer at the deadline.
   Destroy is idempotent and is verified by a follow-up existence check;
   only a verified destroy clears the ledger entry.

Upload and unpack are separate execs so a transport stall and a slow or
stuck extraction fail with different labels. Every exec error names its
purpose, its timeout, how long it ran and how far into the run it failed.

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
parsed (telemetry counts them as `frames_seen`), and the exit code comes
from an in-band marker each script prints.
"""

from __future__ import annotations

import re
import secrets
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import CleanupStatus, RunnerReport, RunnerStatus
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    Json,
    NotFoundError,
    RunnerLedger,
    SpritesApi,
)
from atlas_reviewer.telemetry import ERROR, Fields, Telemetry

DENY_ALL: tuple[Json, ...] = ({"action": "deny", "domain": "*"},)
MEMORY_LIMIT_MB = 1024
WORKDIR = "/work"
SOURCE_ARCHIVE = "/tmp/atlas-source.tar.gz"
EXIT_MARKER = "__ATLAS_EXIT__="
EXIT_NOT_FOUND = 127
PROBE_TAG = "atlas-probe"
FRAMING_CHECK = "atlas-framing-check"
_EXIT_RE = re.compile(re.escape(EXIT_MARKER) + r"(\d+)")
_PROBE_RE = re.compile(re.escape(PROBE_TAG) + r":(present|absent):([A-Za-z0-9._+-]+)")
_BINARY_RE = re.compile(r"[A-Za-z0-9._+-]+")
_INT_RE = re.compile(r"\d+")
_EXEC_SLACK_S = 15.0
PROBE_BUDGET_S = 60.0
UPLOAD_BUDGET_S = 300.0
UNPACK_BUDGET_S = 120.0
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


TRIVIAL_TOOL = ToolSpec(
    "source-file-count", "sh", "echo posix-sh", "find . -type f | wc -l", timeout_s=30
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


@dataclass(frozen=True)
class _Run:
    api: SpritesApi
    name: str
    deadline: Deadline
    telemetry: Telemetry


def runner_name(
    clock: Clock, token_hex: Callable[[int], str] = secrets.token_hex
) -> str:
    return f"cqa-rev-{clock.now():%Y%m%d-%H%M%S}-{token_hex(3)}"


def decode_exec_output(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace").translate(_FRAMING_BYTES)


def frames_seen(raw: bytes) -> str:
    """Counts of each stream-id byte (0x00-0x04) in a raw exec response,
    e.g. `0x01:1,0x03:1`. Output bytes can collide with these values, so
    this is a diagnostic, not a parse."""
    counts = Counter(b for b in raw if b in _FRAMING_BYTES)
    return ",".join(f"0x{b:02x}:{n}" for b, n in sorted(counts.items())) or "none"


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


def _last_int(text: str) -> int | None:
    found = _INT_RE.findall(text)
    return int(found[-1]) if found else None


class _Destroyer:
    """Idempotent, thread-safe destroy shared by `finally` and the watchdog."""

    def __init__(
        self, api: SpritesApi, ledger: RunnerLedger, name: str, telemetry: Telemetry
    ) -> None:
        self._api, self._ledger, self._name = api, ledger, name
        self._telemetry = telemetry
        self._lock = threading.Lock()
        self._status: CleanupStatus | None = None

    def destroy(self) -> CleanupStatus:
        with self._lock:
            if self._status is None:
                self._status = self._destroy()
            return self._status

    def _destroy(self) -> CleanupStatus:
        deleted = any(self._attempt_delete(n) for n in (1, 2))
        status = (
            self._verified_status() if deleted else CleanupStatus.DESTROY_UNVERIFIED
        )
        self._telemetry.record("destroy", "outcome", {"cleanup": status.value})
        return status

    def _verified_status(self) -> CleanupStatus:
        if not self._verified_absent():
            return CleanupStatus.DESTROY_UNVERIFIED
        self._ledger.clear(self._name)
        return CleanupStatus.DESTROYED_VERIFIED

    def _attempt_delete(self, attempt: int) -> bool:
        try:
            self._telemetry.span(
                "destroy",
                f"delete attempt {attempt}",
                lambda: self._api.delete(self._name),
            )
        except NotFoundError:
            return True
        except BoundaryError:
            return False
        return True

    def _verified_absent(self) -> bool:
        try:
            present = self._telemetry.span(
                "verify",
                "existence check",
                lambda: self._api.exists(self._name),
                after=lambda found: {"present": found},
            )
        except BoundaryError:
            return False
        return not present


def destroy_runner(
    api: SpritesApi,
    ledger: RunnerLedger,
    name: str,
    telemetry: Telemetry | None = None,
) -> CleanupStatus:
    return _Destroyer(api, ledger, name, telemetry or _quiet()).destroy()


def _quiet() -> Telemetry:
    return Telemetry(SystemClock())


Body = Callable[[_Run], str]


def _disposable(
    api: SpritesApi,
    ledger: RunnerLedger,
    body: Body,
    *,
    name: str,
    deadline_s: float,
    clock: Clock,
    telemetry: Telemetry,
) -> RunnerReport:
    """Run `body` on a fresh, policy-verified Sprite; always destroy it."""
    run = _Run(api, name, Deadline(clock, deadline_s), telemetry)
    destroyer = _Destroyer(api, ledger, name, telemetry)
    ledger.record(name)
    telemetry.record("ledger", "record runner name", {"runner": name})
    watchdog = threading.Timer(max(deadline_s, 0.0), destroyer.destroy)
    watchdog.daemon = True
    watchdog.start()
    try:
        status, note = _guarded(run, body)
    finally:
        watchdog.cancel()
        cleanup = destroyer.destroy()
    return RunnerReport(status, cleanup, name, note)


def _guarded(run: _Run, body: Body) -> tuple[RunnerStatus, str]:
    try:
        _provision(run)
        return RunnerStatus.COMPLETED, body(run)
    except DeadlineExceededError as exc:
        run.telemetry.record("deadline", "exceeded", status=ERROR, error=str(exc))
        return RunnerStatus.DEADLINE_EXCEEDED, str(exc)
    except BoundaryError as exc:
        if run.deadline.remaining() <= 0:
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
    telemetry: Telemetry | None = None,
) -> RunnerOutcome:
    """The review's exec sequence: tool check, upload, unpack, then each
    available tool. `probe-runner --sequence review` calls this too."""
    results: list[ToolResult] = []

    def body(run: _Run) -> str:
        available = _probe(run, job.tools)
        _upload(run, job.source_tarball)
        _unpack(run)
        results.extend(_tool(run, tool, available) for tool in job.tools)
        return f"{len(results)} tool(s) attempted"

    report = _disposable(
        api, ledger, body, name=name, deadline_s=deadline_s, clock=clock,
        telemetry=telemetry or Telemetry(clock),
    )  # fmt: skip
    return RunnerOutcome(report, tuple(results))


def probe_runner(
    api: SpritesApi,
    ledger: RunnerLedger,
    tools: tuple[ToolSpec, ...],
    *,
    name: str,
    deadline_s: float,
    clock: Clock,
    telemetry: Telemetry | None = None,
) -> ProbeOutcome:
    """The live-protocol check: provision, probe tools, capture one raw exec
    response for framing, round-trip stdin, destroy. Uploads and runs
    nothing from a PR."""
    found: dict[str, bool] = {}
    sample: list[bytes] = []
    stdin_check: list[str] = []

    def body(run: _Run) -> str:
        found.update(_probe(run, tools))
        sample.append(_raw_exec(run, f"echo {FRAMING_CHECK}", "framing check"))
        stdin_check.append(_stdin_roundtrip(run))
        return f"probed {len(found)} binar{'y' if len(found) == 1 else 'ies'}"

    report = _disposable(
        api, ledger, body, name=name, deadline_s=deadline_s, clock=clock,
        telemetry=telemetry or Telemetry(clock),
    )  # fmt: skip
    return ProbeOutcome(
        report, found, b"".join(sample), stdin_check[0] if stdin_check else "not run"
    )


def _stdin_roundtrip(run: _Run) -> str:
    """Send the size of a real upload through the upload's own `head -c`
    mechanism and read back how many bytes the runner saw."""
    sent = STDIN_CHECK_BYTES
    try:
        code, text = _exec(
            run,
            f"head -c {sent} | wc -c",
            "stdin round-trip",
            stdin=bytes(sent),
            budget_s=UPLOAD_BUDGET_S,
        )
    except BoundaryError as exc:
        return f"FAILED sending {sent} bytes: {exc}"
    got = _last_int(text)
    if code != 0 or got is None:
        return f"FAILED sending {sent} bytes: exit {code}: {text[-200:]!r}"
    verdict = "ok" if got == sent else "MISMATCH"
    return f"{verdict}: sent {sent} bytes, runner received {got}"


def _provision(run: _Run) -> None:
    api, name, t = run.api, run.name, run.telemetry
    run.deadline.check("create")
    t.span("create", "create sprite", lambda: api.create(name))
    run.deadline.check("network policy")
    t.span(
        "egress", "set deny-all",
        lambda: api.set_network_policy(name, DENY_ALL), {"rules": len(DENY_ALL)},
    )  # fmt: skip
    t.span(
        "egress", "read back",
        lambda: _require_deny_all(api.get_network_policy(name)),
        after=lambda _: {"deny_all": True},
    )  # fmt: skip
    run.deadline.check("resource policy")
    t.span(
        "resources", "memory limit",
        lambda: api.set_memory_limit(name, MEMORY_LIMIT_MB),
        {"memory_mb": MEMORY_LIMIT_MB},
    )  # fmt: skip


def _require_deny_all(policy: Json) -> None:
    rules = policy.get("rules")
    if not isinstance(rules, list) or [dict(r) for r in rules] != [
        dict(r) for r in DENY_ALL
    ]:
        raise PolicyNotEnforcedError(
            f"network policy read-back is not deny-all: {rules!r}"
        )


def _raw_exec(
    run: _Run,
    script: str,
    purpose: str,
    stdin: bytes = b"",
    budget_s: float | None = None,
) -> bytes:
    left = run.deadline.check(purpose)
    timeout = left if budget_s is None else min(left, budget_s)
    fields: Fields = {
        "purpose": purpose,
        "timeout_s": round(timeout, 1),
        "bytes_sent": len(stdin),
    }
    return run.telemetry.span(
        "exec",
        purpose,
        lambda: run.api.exec(run.name, _sh(script), stdin, timeout),
        fields,
        _exec_fields,
    )


def _exec_fields(raw: bytes) -> Fields:
    code, _ = parse_exit(decode_exec_output(raw))
    return {
        "bytes_received": len(raw),
        "frames_seen": frames_seen(raw),
        "exit_status": code,
    }


def _exec(
    run: _Run,
    script: str,
    purpose: str,
    stdin: bytes = b"",
    budget_s: float | None = None,
) -> tuple[int | None, str]:
    return parse_exit(
        decode_exec_output(_raw_exec(run, script, purpose, stdin, budget_s))
    )


def _probe(run: _Run, tools: tuple[ToolSpec, ...]) -> dict[str, bool]:
    binaries = tuple(t.binary for t in tools)
    if not binaries:
        return {}
    code, text = _exec(
        run, probe_script(binaries), "tool check", budget_s=PROBE_BUDGET_S
    )
    found = parse_probe(text, binaries) if code == 0 else dict.fromkeys(binaries, False)
    run.telemetry.record(
        "tool check", "availability", {f"has_{b}": ok for b, ok in found.items()}
    )
    return found


def _upload(run: _Run, tarball: bytes) -> None:
    """`head -c` stops reading after exactly the bytes sent, so the upload
    does not depend on the exec channel delivering a stdin EOF; the runner
    reports back how many bytes it wrote."""
    size = len(tarball)
    script = f"head -c {size} > {SOURCE_ARCHIVE} && wc -c < {SOURCE_ARCHIVE}"
    run.telemetry.span(
        "upload",
        f"{size}-byte tarball",
        lambda: _confirm_upload(
            _exec(
                run, script, "source upload", stdin=tarball, budget_s=UPLOAD_BUDGET_S
            ),
            size,
        ),
        {"bytes": size},
        lambda got: {"runner_received": got},
    )


def _confirm_upload(result: tuple[int | None, str], size: int) -> int:
    code, text = result
    got = _last_int(text)
    if code != 0 or got != size:
        raise BoundaryError(
            f"source upload: runner wrote {got} of {size} bytes "
            f"(exit {code}): {text[-300:]}"
        )
    return got


def _unpack(run: _Run) -> None:
    script = (
        f"mkdir -p {WORKDIR} && tar -xzf {SOURCE_ARCHIVE} -C {WORKDIR} "
        f"--strip-components=1 && rm -f {SOURCE_ARCHIVE}"
    )
    run.telemetry.span(
        "unpack",
        "tar -xzf",
        lambda: _confirm_unpack(
            _exec(run, script, "source unpack", budget_s=UNPACK_BUDGET_S)
        ),
        after=lambda code: {"exit_status": code},
    )


def _confirm_unpack(result: tuple[int | None, str]) -> int:
    code, text = result
    if code != 0:
        raise BoundaryError(f"source unpack failed (exit {code}): {text[-500:]}")
    return code


def _tool(run: _Run, tool: ToolSpec, available: dict[str, bool]) -> ToolResult:
    return run.telemetry.span(
        "tool",
        tool.name,
        lambda: _run_if_available(run, tool, available),
        after=_tool_fields,
    )


def _tool_fields(result: ToolResult) -> Fields:
    match result:
        case ToolRan(version=version, exit_code=code):
            return {"result": "ran", "version": version, "exit_status": code}
        case ToolAbsent():
            return {"result": "not run"}
    raise TypeError(f"not a tool result: {result!r}")  # pragma: no cover


def _run_if_available(
    run: _Run, tool: ToolSpec, available: dict[str, bool]
) -> ToolResult:
    if not available.get(tool.binary, False):
        return ToolAbsent(tool, f"`{tool.binary}` not found by the availability probe")
    return _run_tool(run, tool)


def _run_tool(run: _Run, tool: ToolSpec) -> ToolResult:
    budget = tool.timeout_s + _EXEC_SLACK_S
    v_code, v_text = _exec(
        run, f"cd {WORKDIR} && {tool.version_cmd}", f"{tool.name} version",
        budget_s=budget,
    )  # fmt: skip
    if v_code != 0:
        return ToolAbsent(tool, f"version probe exited {v_code}: {v_text[-300:]}")
    script = f"cd {WORKDIR} && timeout --kill-after=5 {tool.timeout_s} {tool.run_cmd}"
    code, text = _exec(run, script, f"{tool.name} run", budget_s=budget)
    return ToolRan(tool, _first_line(v_text), code, text)


def _first_line(text: str) -> str:
    stripped = text.strip()
    return stripped.splitlines()[0] if stripped else "unknown"


def sweep(
    api: SpritesApi, ledger: RunnerLedger, telemetry: Telemetry | None = None
) -> dict[str, CleanupStatus]:
    """Destroy every runner a previous (possibly crashed) review left behind."""
    t = telemetry or _quiet()
    return {name: destroy_runner(api, ledger, name, t) for name in ledger.pending()}
