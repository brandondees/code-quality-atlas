# SPDX-License-Identifier: MIT
"""One disposable, credential-free runner per review.

Lifecycle, in order, every step checked against the deadline before it
starts and recorded as a telemetry event (`atlas_reviewer.telemetry`).
Execs get the remaining deadline as their window; a control-plane call is
bounded by the client's own window (`sprites_api`, 30s by default), and
all of a runner's cleanup by `CLEANUP_BUDGET_S` from its first destroy, so
cleanup ends at most that plus one call window after it starts:

0. refuse a source archive the exec stdin cannot carry, or one that is
   unreadable or unpacks past its size or member cap (`source_archive`)
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
   only the final verified destroy clears the ledger entry, never the
   watchdog's, which can run while `create` is still in flight, and not
   after a create whose outcome is unknown or once the cleanup budget is
   spent: those report DESTROY_UNVERIFIED and leave the entry for `sweep`.

Upload and unpack are separate execs so a transport stall and a slow or
stuck extraction fail with different labels. Every exec error names its
stage, its purpose, its timeout, how long it ran and how far into the run
it failed.

Every exec has one shape (`exec_argv` here, `sprites_api.exec_request` for
the HTTP request): `/usr/bin/env -i` with `MINIMAL_ENV` runs `/bin/sh -c`,
which prints a start marker, runs the script with a stdin of exactly the
bytes sent and then EOF (`head -c N` with input, `/dev/null` without, so no
command waits on the exec channel's stdin), and prints the exit marker. The
minimal environment keeps the image's pyenv shims (`/.sprite/bin`) and any
`PYENV_*` setting off the PATH; Python tools run the interpreter the
controller resolved by absolute path before unpack (`interpreter.py`), so
nothing in the PR can choose an interpreter or a tool binary. Only the
probe's labelled diagnostics run in the Sprite's default environment. A
command that sends no input must produce its first output byte within
`first_frame_s`; the start marker makes that immediate for any command
that actually started.

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
from dataclasses import dataclass, field, replace
from typing import Literal

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import CleanupStatus, RunnerReport, RunnerStatus
from atlas_reviewer.guest_unpack import unpack_refusal, unpack_script
from atlas_reviewer.interpreter import (
    PYTHON_PLACEHOLDER,
    SYSTEM_PYTHON,
    DiagnosticSpec,
    TrustedPython,
    bounded,
    choose_python,
    diagnostics_after_unpack,
    diagnostics_before_unpack,
    resolve_script,
    summarize,
    with_python,
)
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    Json,
    NotFoundError,
    RunnerLedger,
    SpritesApi,
    StreamTimeoutError,
)
from atlas_reviewer.source_archive import DEFAULT_UNPACK, UnpackLimits, measure
from atlas_reviewer.sprites_api import EXEC_STDIN_MAX_BYTES
from atlas_reviewer.telemetry import ERROR, Fields, Telemetry

DENY_ALL: tuple[Json, ...] = ({"action": "deny", "domain": "*"},)
MEMORY_LIMIT_MB = 1024
# Under the exec stdin limit, so one upload exec always carries a tarball.
MAX_TARBALL_BYTES = 9 * 1024 * 1024
WORKDIR = "/work"
SOURCE_ARCHIVE = "/tmp/atlas-source.tar.gz"
EXIT_MARKER = "__ATLAS_EXIT__="
START_MARKER = "__ATLAS_START__"
EXIT_NOT_FOUND = 127
PROBE_TAG = "atlas-probe"
FRAMING_CHECK = "atlas-framing-check"
_EXIT_RE = re.compile(re.escape(EXIT_MARKER) + r"(\d+)")
_PROBE_RE = re.compile(re.escape(PROBE_TAG) + r":(present|absent):([A-Za-z0-9._+-]+)")
_PATH_RE = re.compile(
    re.escape(PROBE_TAG)
    + r":present:([A-Za-z0-9._+-]+):([A-Za-z0-9._/+-]{0,200}):([A-Za-z0-9._/+-]{0,200})"
)
_BINARY_RE = re.compile(r"[A-Za-z0-9._+-]+")
_NOT_ISOLATED_RE = re.compile(
    re.escape(PYTHON_PLACEHOLDER) + r"(?! -I[A-Za-z]*(?:\s|$))"
)
_INT_RE = re.compile(r"\d+")
_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|.)")
_UNPRINTABLE_RE = re.compile(r"[^\x21-\x7e]+")
GUEST_TAIL_CHARS = 300
EGRESS_TAG = "atlas-egress"
EGRESS_TARGETS = ("1.1.1.1:443", "example.com:443")
EGRESS_BOUND_S = 8
_EGRESS_RE = re.compile(
    re.escape(EGRESS_TAG)
    + r":([A-Za-z0-9.-]+:\d+):(?:untested|tried:([a-z0-9-]*):(\d+))"
    r"\s*$",
    re.MULTILINE,
)
_EGRESS_TIMED_OUT = 124
VERSION_CHARS = 120
_EXEC_SLACK_S = 15.0
PROBE_BUDGET_S = 60.0
UPLOAD_BUDGET_S = 300.0
UNPACK_BUDGET_S = 120.0
FIRST_FRAME_BUDGET_S = 30.0
# From the first destroy of a runner, shared by the watchdog's and the
# final one: no control-plane call starts after it, so cleanup ends
# within this plus one call window (`SpritesClient` timeout_s, 30s).
CLEANUP_BUDGET_S = 60.0
DIAGNOSTIC_BOUND_S = 15
PYTHON_BINARY = "python3"
MINIMAL_ENV = ("PATH=/usr/bin:/bin", "HOME=/tmp", "LANG=C.UTF-8")
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
        """A `python3` tool must name the interpreter as `{python} -I` in
        both commands, so it can only ever run the resolved absolute path,
        isolated from modules in the checkout."""
        if not _BINARY_RE.fullmatch(self.binary):
            raise ValueError(
                f"tool binary must be a bare command name: {self.binary!r}"
            )
        placeholders = [
            PYTHON_PLACEHOLDER in c for c in (self.version_cmd, self.run_cmd)
        ]
        if self.needs_python != all(placeholders) or any(placeholders) != all(
            placeholders
        ):
            raise ValueError(
                f"a {PYTHON_BINARY} tool must use {PYTHON_PLACEHOLDER} in both "
                "commands, and only a python3 tool may use it"
            )
        if any(_NOT_ISOLATED_RE.search(c) for c in (self.version_cmd, self.run_cmd)):
            raise ValueError(
                f"every {PYTHON_PLACEHOLDER} must be followed by -I, so a PR file "
                "cannot shadow the module a tool runs"
            )

    @property
    def needs_python(self) -> bool:
        return self.binary == PYTHON_BINARY


TRIVIAL_TOOL = ToolSpec(
    "source-file-count", "sh", "echo posix-sh", "find . -type f | wc -l", timeout_s=30
)

DEFAULT_TOOLS = (
    ToolSpec(
        "python-compileall",
        "python3",
        "{python} -I --version",
        "{python} -I -m compileall -q .",
    ),
)


@dataclass(frozen=True)
class RunnerJob:
    """`diagnose` adds the probe-only Python diagnostics; a review never
    sets it."""

    source_tarball: bytes
    tools: tuple[ToolSpec, ...]
    diagnose: bool = False
    unpack: UnpackLimits = DEFAULT_UNPACK


def refused_archive(data: bytes, limits: UnpackLimits = DEFAULT_UNPACK) -> str | None:
    """Why a source archive may not go to a runner, or None: over the exec
    stdin it is uploaded through, unreadable, or past an unpack cap
    (`source_archive.measure`)."""
    if len(data) > EXEC_STDIN_MAX_BYTES:
        return (
            f"source archive is {len(data)} bytes, over the {EXEC_STDIN_MAX_BYTES}-byte "
            "limit of the exec stdin it is uploaded through"
        )
    try:
        measure(data, limits)
    except BoundaryError as exc:
        return str(exc)
    return None


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
class ExecFailed:
    """A check-style exec (the availability probe, interpreter resolution)
    that did not answer. Its tools are not run, and the reason names the
    failure instead of claiming the tool or interpreter is absent."""

    what: str
    exit_code: int | None
    tail: str

    @property
    def detail(self) -> str:
        return f"the {self.what} failed (exit {self.exit_code}): {self.tail}"


@dataclass(frozen=True)
class Diagnostic:
    name: str
    expectation: str
    exit_code: int | None
    detail: str


@dataclass(frozen=True)
class RunnerOutcome:
    """Every text field (the report's note, each tool's version, output or
    detail, each diagnostic's detail) has been through the run's
    `Telemetry.scrub`, the same credential-aware redactor as its events.
    Tool output keeps its lines; it is otherwise bounded only by the exec
    response cap."""

    report: RunnerReport
    results: tuple[ToolResult, ...]
    python: TrustedPython | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class ProbeOutcome:
    """`stdin_check`, `egress_check`, `framing_sample` and the report's note
    have been through `Telemetry.scrub`. `framing_sample` is the raw
    response to a fixed `echo`; it is scrubbed through a surrogate-escape
    decode, so every byte outside a redacted value keeps the framing it
    shows."""

    report: RunnerReport
    available: dict[str, bool]
    framing_sample: bytes
    stdin_check: str
    egress_check: str = "not run"


@dataclass
class Deadline:
    """Measured on the injected clock. `expired` is set by the wall-clock
    watchdog when it fires, and ends the run whatever the clock says."""

    clock: Clock
    seconds: float
    expired: threading.Event = field(default_factory=threading.Event)
    _start: float = field(init=False)

    def __post_init__(self) -> None:
        self._start = self.clock.monotonic()

    def remaining(self) -> float:
        left = self.seconds - (self.clock.monotonic() - self._start)
        return min(left, 0.0) if self.expired.is_set() else left

    def check(self, step: str) -> float:
        left = self.remaining()
        if left <= 0:
            raise DeadlineExceededError(
                f"deadline of {self.seconds:g}s reached before {step}"
            )
        return left


CreateOutcome = Literal["not started", "unknown", "settled"]


@dataclass
class _Create:
    """Whether the runner's `create` settled. `unknown` while it is in
    flight and after it raised: a client-side failure (a timeout, a 5xx a
    proxy sent after forwarding) does not show the server never made the
    Sprite, and nothing here bounds when it might still land."""

    outcome: CreateOutcome = "not started"


@dataclass(frozen=True)
class _Run:
    api: SpritesApi
    name: str
    deadline: Deadline
    telemetry: Telemetry
    first_frame_s: float = FIRST_FRAME_BUDGET_S
    create: _Create = field(default_factory=_Create)


@dataclass(frozen=True)
class _Exec:
    """One exec: the lifecycle stage it belongs to, what it is for (its
    telemetry step), the script, the stdin bytes, and its own budget."""

    stage: str
    purpose: str
    script: str
    stdin: bytes = b""
    budget_s: float | None = None
    sprite_env: bool = False


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
    """The status on the last `__ATLAS_EXIT__=<n>` line the wrapper prints,
    and the output before it; None when there is no marker.

    The marker is in-band and reported by the guest, so it is evidence,
    not proof: code in the runner that prints its own marker and then
    stops the wrapper before the real one (by killing its shell, say)
    supplies the last one seen. A per-run nonce would not prevent that,
    since the guest can read the wrapper's argv, nonce included, under
    /proc. No tool here executes PR code (compileall only compiles), and
    a forged status could only change what a human-read draft reports.
    An authoritative status needs the exec API's own exit frame, which
    is not documented well enough to rely on (see `frames_seen`)."""
    hits = list(_EXIT_RE.finditer(text))
    if not hits:
        return None, text
    last = hits[-1]
    return int(last.group(1)), text[: last.start()].rstrip("\n")


def probe_script(binaries: tuple[str, ...]) -> str:
    """Resolves each binary without executing it, reporting where it
    resolved to and what that path finally links to."""
    names = " ".join(dict.fromkeys(binaries))
    return (
        f'for b in {names}; do if p=$(command -v "$b" 2>/dev/null); '
        f'then echo "{PROBE_TAG}:present:$b:$p:$(readlink -f "$p" 2>/dev/null)"; '
        f'else echo "{PROBE_TAG}:absent:$b"; fi; done'
    )


def parse_probe(text: str, binaries: tuple[str, ...]) -> dict[str, bool]:
    """Unreported binaries count as absent: the guest is untrusted, and a
    missing answer must become UNKNOWN, not an assumed install."""
    seen = {name: state == "present" for state, name in _PROBE_RE.findall(text)}
    return {b: seen.get(b, False) for b in binaries}


def parse_paths(text: str) -> dict[str, str]:
    """`binary -> resolved path -> link target`, as the untrusted guest
    reported them; a diagnostic only."""
    return {b: f"{p} -> {real}" for b, p, real in _PATH_RE.findall(text)}


def exec_argv(script: str, stdin_len: int, sprite_env: bool = False) -> tuple[str, ...]:
    """`sprite_env` drops the `env -i` prefix and so runs in the Sprite's
    default environment; only probe diagnostics ask for it."""
    feed, redirect = (
        (f"head -c {stdin_len} | ", "") if stdin_len else ("", " </dev/null")
    )
    env = () if sprite_env else ("/usr/bin/env", "-i", *MINIMAL_ENV)
    return (
        *env,
        "/bin/sh",
        "-c",
        f"echo {START_MARKER}; {feed}{{ {script}\n}}{redirect}; echo {EXIT_MARKER}$?",
    )


def strip_start(text: str) -> str:
    _, found, rest = text.partition(f"{START_MARKER}\n")
    return rest if found else text


def guest_text(text: str, max_chars: int) -> str:
    """Untrusted runner output made fit for a one-line note or telemetry
    field: ANSI escape sequences dropped, every run of whitespace or other
    unprintable characters (newlines, carriage returns, control bytes,
    non-ASCII) collapsed to one space, and only the last `max_chars` kept,
    where a failure usually is."""
    flat = _UNPRINTABLE_RE.sub(" ", _ANSI_RE.sub("", text)).strip()
    return flat[-max_chars:] if max_chars > 0 else ""


def _last_int(text: str) -> int | None:
    found = _INT_RE.findall(text)
    return int(found[-1]) if found else None


Trigger = Literal["watchdog", "final", "sweep"]


class _Destroyer:
    """Idempotent, thread-safe destroy shared by `finally` and the watchdog.
    Every event it records carries the trigger that caused it."""

    def __init__(
        self,
        api: SpritesApi,
        ledger: RunnerLedger,
        name: str,
        telemetry: Telemetry,
        create: _Create,
        clock: Clock,
    ) -> None:
        self._api, self._ledger, self._name = api, ledger, name
        self._telemetry, self._create, self._clock = telemetry, create, clock
        self._lock = threading.Lock()
        self._status: CleanupStatus | None = None
        self._budget_start: float | None = None

    def _budget_left(self) -> float:
        if self._budget_start is None:
            self._budget_start = self._clock.monotonic()
        return CLEANUP_BUDGET_S - (self._clock.monotonic() - self._budget_start)

    def destroy(self, trigger: Trigger) -> CleanupStatus:
        """Only the watchdog can run while `create` is still in flight.
        Any other trigger destroys again even after the watchdog did,
        because a create in flight when the watchdog fired can add the
        Sprite after the watchdog verified it absent; for the same reason
        the watchdog never clears the ledger entry, and neither does any
        destroy while the create's outcome is unknown: absence then is only
        momentary, so the entry stays for a later `sweep` and the result is
        DESTROY_UNVERIFIED. A telemetry write
        failure must not stop cleanup, so cleanup is redone untraced and
        the error re-raised, carrying the cleanup result as a note.

        Cleanup has `CLEANUP_BUDGET_S` from the first destroy: a destroy
        waits for another one only that long, and starts no call once it
        is spent. Cut short, it reports DESTROY_UNVERIFIED and leaves the
        ledger entry for a sweep."""
        if not self._lock.acquire(timeout=max(self._budget_left(), 0.0)):
            return self._budget_spent(self._telemetry, trigger, "waiting for a destroy")
        try:
            if self._status is None or trigger != "watchdog":
                try:
                    self._status = self._destroy(self._telemetry, trigger)
                except OSError as exc:
                    self._status = self._destroy(_quiet(), trigger)
                    exc.add_note(
                        f"runner {self._name} cleanup after the telemetry write "
                        f"failure: {self._status.value}"
                    )
                    raise
            return self._status
        finally:
            self._lock.release()

    def _budget_spent(
        self, telemetry: Telemetry, trigger: Trigger, during: str
    ) -> CleanupStatus:
        telemetry.record(
            "destroy", "cleanup budget spent", {"trigger": trigger},
            status=ERROR,
            error=f"cleanup budget of {CLEANUP_BUDGET_S:g}s spent {during}",
        )  # fmt: skip
        return self._outcome(telemetry, trigger, CleanupStatus.DESTROY_UNVERIFIED)

    def _destroy(self, telemetry: Telemetry, trigger: Trigger) -> CleanupStatus:
        if trigger == "watchdog":
            telemetry.record("watchdog", "fired", {"runner": self._name})
        for n in (1, 2):
            if self._budget_left() <= 0:
                return self._budget_spent(telemetry, trigger, "before a delete")
            if self._attempt_delete(telemetry, trigger, n):
                break
        else:
            return self._outcome(telemetry, trigger, CleanupStatus.DESTROY_UNVERIFIED)
        if self._budget_left() <= 0:
            return self._budget_spent(telemetry, trigger, "before the existence check")
        return self._outcome(
            telemetry, trigger, self._verified_status(telemetry, trigger)
        )

    def _outcome(
        self, telemetry: Telemetry, trigger: Trigger, status: CleanupStatus
    ) -> CleanupStatus:
        telemetry.record(
            "destroy", "outcome", {"trigger": trigger, "cleanup": status.value}
        )
        return status

    def _verified_status(self, telemetry: Telemetry, trigger: Trigger) -> CleanupStatus:
        if not self._verified_absent(telemetry, trigger):
            return CleanupStatus.DESTROY_UNVERIFIED
        if trigger == "watchdog":
            return CleanupStatus.DESTROYED_VERIFIED
        if self._create.outcome == "unknown":
            telemetry.record(
                "ledger", "keep runner name",
                {"runner": self._name, "trigger": trigger, "create": "unknown"},
            )  # fmt: skip
            return CleanupStatus.DESTROY_UNVERIFIED
        self._ledger.clear(self._name)
        return CleanupStatus.DESTROYED_VERIFIED

    def _attempt_delete(self, telemetry: Telemetry, trigger: Trigger, n: int) -> bool:
        try:
            telemetry.span(
                "destroy",
                f"delete attempt {n}",
                self._delete,
                {"trigger": trigger},
                lambda result: {"result": result},
            )
        except BoundaryError:
            return False
        return True

    def _delete(self) -> str:
        """A 404 is the outcome cleanup wants (the watchdog got there
        first, or create never landed), so it is not an error."""
        try:
            self._api.delete(self._name)
        except NotFoundError:
            return "already absent"
        return "deleted"

    def _verified_absent(self, telemetry: Telemetry, trigger: Trigger) -> bool:
        try:
            present = telemetry.span(
                "verify",
                "existence check",
                lambda: self._api.exists(self._name),
                {"trigger": trigger},
                lambda found: {"present": found},
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
    """For a runner no live review is creating (a sweep): whatever create
    the review that recorded it made is taken to have settled by now."""
    return _Destroyer(
        api, ledger, name, telemetry or _quiet(), _Create("settled"), SystemClock()
    ).destroy("sweep")


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
    first_frame_s: float,
) -> RunnerReport:
    """Run `body` on a fresh, policy-verified Sprite; always destroy it."""
    deadline = Deadline(clock, deadline_s)
    run = _Run(api, name, deadline, telemetry, first_frame_s)
    destroyer = _Destroyer(api, ledger, name, telemetry, run.create, clock)
    ledger.record(name)
    telemetry.record("ledger", "record runner name", {"runner": name})

    def on_deadline() -> None:
        deadline.expired.set()
        destroyer.destroy("watchdog")

    watchdog = threading.Timer(max(deadline_s, 0.0), on_deadline)
    watchdog.daemon = True
    watchdog.start()
    try:
        status, note = _guarded(run, body)
    finally:
        watchdog.cancel()
        cleanup = destroyer.destroy("final")
    return RunnerReport(status, cleanup, name, note)


def _guarded(run: _Run, body: Body) -> tuple[RunnerStatus, str]:
    """Steps that are never fatal (diagnostics, the stdin check) swallow
    their own errors, so a body can return normally after the deadline
    passed; that run is not complete either."""
    try:
        _provision(run)
        note = body(run)
    except DeadlineExceededError as exc:
        return _deadline_reached(run, str(exc))
    except BoundaryError as exc:
        if run.deadline.remaining() <= 0:
            return _deadline_reached(run, f"deadline reached: {exc}")
        return RunnerStatus.FAILED, run.telemetry.scrub(str(exc))
    if run.deadline.remaining() <= 0:
        return _deadline_reached(run, f"deadline reached by the last step ({note})")
    return RunnerStatus.COMPLETED, run.telemetry.scrub(note)


def _deadline_reached(run: _Run, note: str) -> tuple[RunnerStatus, str]:
    run.telemetry.record("deadline", "exceeded", status=ERROR, error=note)
    return RunnerStatus.DEADLINE_EXCEEDED, run.telemetry.scrub(note)


@dataclass(frozen=True)
class Session:
    """One live, policy-verified runner handed to a `run_session` body.
    Every exec goes through the one exec wrapper (`exec_argv`) under the
    run's deadline and is recorded in its telemetry; scripts are
    controller-built and their output is untrusted."""

    _run: _Run

    def exec(
        self,
        purpose: str,
        script: str,
        *,
        stage: str = "session",
        budget_s: float | None = None,
    ) -> tuple[int | None, str]:
        """The script's exit status (None with no marker) and its output,
        from `parse_exit`. Raises `BoundaryError` (a `StreamTimeoutError`
        when output stopped) and `DeadlineExceededError`."""
        return _exec(self._run, _Exec(stage, purpose, script, budget_s=budget_s))

    def upload(self, data: bytes, path: str, purpose: str) -> None:
        """Writes `data` to the controller-chosen `path` through the same
        exec shape as the source upload; raises unless every byte landed."""
        _upload(self._run, data, path, purpose)


def run_session(
    api: SpritesApi,
    ledger: RunnerLedger,
    body: Callable[[Session], str],
    *,
    name: str,
    deadline_s: float,
    clock: Clock,
    telemetry: Telemetry | None = None,
    first_frame_s: float = FIRST_FRAME_BUDGET_S,
) -> RunnerReport:
    """`body` on a fresh disposable runner with the same lifecycle as a
    review: recorded in the ledger, provisioned deny-all and verified,
    bounded by the deadline and its watchdog, always destroyed. The body's
    return value is the report's note."""
    return _disposable(
        api, ledger, lambda run: body(Session(run)), name=name,
        deadline_s=deadline_s, clock=clock,
        telemetry=telemetry or Telemetry(clock), first_frame_s=first_frame_s,
    )  # fmt: skip


def run_disposable(
    api: SpritesApi,
    ledger: RunnerLedger,
    job: RunnerJob,
    *,
    name: str,
    deadline_s: float,
    clock: Clock,
    telemetry: Telemetry | None = None,
    first_frame_s: float = FIRST_FRAME_BUDGET_S,
) -> RunnerOutcome:
    """The review's exec sequence: tool check, upload, unpack, then each
    available tool. An archive the one-exec upload cannot carry, or one
    that is unreadable or unpacks past `job.unpack`, is refused before
    anything is created or recorded in the ledger."""
    telemetry = telemetry or Telemetry(clock)
    size = len(job.source_tarball)
    refused = refused_archive(job.source_tarball, job.unpack)
    if refused is not None:
        note = f"{refused}; no runner was created"
        telemetry.record(
            "upload", "size check", {"bytes": size, "limit": EXEC_STDIN_MAX_BYTES},
            status=ERROR, error=note,
        )  # fmt: skip
        return RunnerOutcome(
            RunnerReport(RunnerStatus.FAILED, CleanupStatus.NOT_CREATED, name, note),
            (),
        )
    results: list[ToolResult] = []
    pythons: list[TrustedPython | None] = []
    diagnostics: list[Diagnostic] = []

    def body(run: _Run) -> str:
        found = _Found(_probe(run, job.tools), _python_for(run, job))
        pythons.append(found.trusted_python)
        diagnostics.extend(_diagnose(run, diagnostics_before_unpack(), job.diagnose))
        _upload(run, job.source_tarball)
        _unpack(run, job.unpack)
        results.extend(_tool(run, tool, found) for tool in job.tools)
        after = diagnostics_after_unpack(
            found.trusted_python, WORKDIR, DIAGNOSTIC_BOUND_S
        )
        diagnostics.extend(_diagnose(run, after, job.diagnose))
        return f"{len(results)} tool(s) attempted"

    report = _disposable(
        api, ledger, body, name=name, deadline_s=deadline_s, clock=clock,
        telemetry=telemetry, first_frame_s=first_frame_s,
    )  # fmt: skip
    scrub = telemetry.scrub
    return RunnerOutcome(
        report,
        tuple(_scrubbed(result, scrub) for result in results),
        next(iter(pythons), None),
        tuple(replace(d, detail=scrub(d.detail)) for d in diagnostics),
    )


def _scrubbed(result: ToolResult, scrub: Callable[[str], str]) -> ToolResult:
    match result:
        case ToolRan(version=version, output=output):
            return replace(result, version=scrub(version), output=scrub(output))
        case ToolAbsent(detail=detail):
            return replace(result, detail=scrub(detail))
    raise TypeError(f"not a tool result: {result!r}")  # pragma: no cover


def probe_runner(
    api: SpritesApi,
    ledger: RunnerLedger,
    tools: tuple[ToolSpec, ...],
    *,
    name: str,
    deadline_s: float,
    clock: Clock,
    telemetry: Telemetry | None = None,
    first_frame_s: float = FIRST_FRAME_BUDGET_S,
) -> ProbeOutcome:
    """The live-protocol check: provision, probe tools, capture one raw exec
    response for framing, round-trip stdin, try to connect out, destroy.
    Uploads and runs nothing from a PR."""
    found: dict[str, bool] = {}
    sample: list[bytes] = []
    stdin_check: list[str] = []
    egress_check: list[str] = []

    def body(run: _Run) -> str:
        probed = _probe(run, tools)
        sample.append(
            _raw_exec(run, _Exec("probe", "framing check", f"echo {FRAMING_CHECK}"))
        )
        stdin_check.append(_stdin_roundtrip(run))
        egress_check.append(_egress_check(run))
        if isinstance(probed, ExecFailed):
            return probed.detail
        found.update(probed)
        return f"probed {len(found)} binar{'y' if len(found) == 1 else 'ies'}"

    telemetry = telemetry or Telemetry(clock)
    report = _disposable(
        api, ledger, body, name=name, deadline_s=deadline_s, clock=clock,
        telemetry=telemetry, first_frame_s=first_frame_s,
    )  # fmt: skip
    return ProbeOutcome(
        report,
        found,
        _scrub_bytes(b"".join(sample), telemetry.scrub),
        telemetry.scrub(stdin_check[0]) if stdin_check else "not run",
        telemetry.scrub(egress_check[0]) if egress_check else "not run",
    )


def _scrub_bytes(raw: bytes, scrub: Callable[[str], str]) -> bytes:
    text = raw.decode("utf-8", "surrogateescape")
    return scrub(text).encode("utf-8", "surrogateescape")


_EGRESS_CONNECT = """import socket,sys
h,p=sys.argv[1].rsplit(':',1)
try:
 socket.create_connection((h,int(p)),4).close();r='connected'
except socket.gaierror:r='unresolved'
except ConnectionRefusedError:r='refused'
except (TimeoutError,socket.timeout):r='timeout'
except OSError as e:r='oserror-%s'%e.errno
print(r)"""


def egress_script(targets: tuple[str, ...] = EGRESS_TARGETS) -> str:
    """One outbound TCP connect per `host:port` target with the system
    Python, each bounded on its own. Python names its own outcome, so an
    attempt that never started (a missing `timeout`, an interpreter that
    cannot run: exit 126/127 with no outcome) is not read as a refusal.
    Reports `<target>:tried:<outcome>:<exit status>`, or `untested`."""
    attempt = bounded(f'{SYSTEM_PYTHON} -I -c "{_EGRESS_CONNECT}" "$t"', EGRESS_BOUND_S)
    return (
        f"for t in {' '.join(targets)}; do "
        f'if [ ! -x {SYSTEM_PYTHON} ]; then echo "{EGRESS_TAG}:$t:untested"; '
        f"else r=$({attempt} 2>/dev/null); s=$?; "
        f'echo "{EGRESS_TAG}:$t:tried:$r:$s"; fi; done'
    )


@dataclass(frozen=True)
class _EgressResult:
    """One target's line from `egress_script`, read conservatively: a
    `connected` outcome is a connection whatever the exit status, and only
    an outcome Python named after trying, or the bound's own timeout status
    with no outcome, counts as no connection. `outcome` None: not tried."""

    outcome: str | None
    exit_status: int | None

    @property
    def connected(self) -> bool:
        return self.outcome == "connected"

    @property
    def no_connection(self) -> bool:
        if self.exit_status == 0:
            return self.outcome in _NO_CONNECTION or (
                self.outcome is not None and self.outcome.startswith("oserror-")
            )
        return self.outcome == "" and self.exit_status == _EGRESS_TIMED_OUT

    def words(self) -> str:
        if self.outcome is None:
            return "untested (no system Python)"
        if self.connected:
            return "CONNECTED"
        if self.no_connection:
            return _NO_CONNECTION.get(
                self.outcome or "timeout", f"no connection ({self.outcome})"
            ) + (f" (exit {self.exit_status})" if self.exit_status else "")
        return (
            f"did not report an attempt (outcome {self.outcome or 'none'!r}, "
            f"exit {self.exit_status})"
        )


_NO_CONNECTION = {
    "refused": "no connection (refused)",
    "timeout": "no connection (timed out)",
    "unresolved": "name not resolved",
}


def egress_verdict(code: int | None, text: str, targets: tuple[str, ...]) -> str:
    """`OPEN` if any target connected, `no outbound connection` only if
    every target was tried and failed to connect, else `UNVERIFIED`: a
    target that was not reported, not tried, or whose attempt never
    started. A name that did not resolve made no connection, but shows
    nothing about a firewall; the IP-literal target is the one that tests
    the policy without DNS."""
    if code != 0:
        return (
            f"UNVERIFIED: the egress check exited {code}: "
            f"{guest_text(text, GUEST_TAIL_CHARS)}"
        )
    seen = {
        t: _EgressResult(outcome, int(status)) if status else _EgressResult(None, None)
        for t, outcome, status in _EGRESS_RE.findall(text)
    }
    results = [seen.get(t) for t in targets]
    detail = "; ".join(
        f"{t} {r.words() if r else 'not reported'}"
        for t, r in zip(targets, results, strict=True)
    )
    if any(r and r.connected for r in results):
        return f"OPEN: {detail}"
    if all(r and r.no_connection for r in results):
        return f"no outbound connection: {detail}"
    return f"UNVERIFIED: {detail}"


def _egress_check(run: _Run) -> str:
    """Behavioural evidence for deny-all, next to the policy read-back:
    the read-back shows what the control plane stored, this shows whether
    the guest could connect out to an IP literal and a hostname."""
    try:
        code, text = _exec(
            run,
            _Exec("probe", "egress check", egress_script(), budget_s=PROBE_BUDGET_S),
        )
    except BoundaryError as exc:
        return f"UNVERIFIED: the egress check failed: {exc}"
    return egress_verdict(code, text, EGRESS_TARGETS)


def _stdin_roundtrip(run: _Run) -> str:
    """Send the size of a real upload through the upload's own `head -c`
    mechanism and read back how many bytes the runner saw."""
    sent = STDIN_CHECK_BYTES
    try:
        code, text = _exec(
            run,
            _Exec("probe", "stdin round-trip", "wc -c", bytes(sent), UPLOAD_BUDGET_S),
        )
    except BoundaryError as exc:
        return f"FAILED sending {sent} bytes: {exc}"
    got = _last_int(text)
    if code != 0 or got is None:
        return f"FAILED sending {sent} bytes: exit {code}: {guest_text(text, 200)}"
    verdict = "ok" if got == sent else "MISMATCH"
    return f"{verdict}: sent {sent} bytes, runner received {got}"


def _provision(run: _Run) -> None:
    api, name, t = run.api, run.name, run.telemetry
    run.deadline.check("create")
    run.create.outcome = "unknown"
    t.span("create", "create sprite", lambda: api.create(name))
    run.create.outcome = "settled"
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
    if rules != list(DENY_ALL):
        raise PolicyNotEnforcedError(
            f"network policy read-back is not deny-all: {rules!r}"
        )


def _raw_exec(run: _Run, step: _Exec) -> bytes:
    left = run.deadline.check(step.purpose)
    timeout = left if step.budget_s is None else min(left, step.budget_s)
    first = None if step.stdin else min(run.first_frame_s, timeout)
    fields: Fields = {
        "stage": step.stage,
        "purpose": step.purpose,
        "timeout_s": round(timeout, 1),
        "first_frame_s": None if first is None else round(first, 1),
        "bytes_sent": len(step.stdin),
        "env": "sprite default" if step.sprite_env else "minimal",
    }
    return run.telemetry.span(
        "exec",
        step.purpose,
        lambda: _send(run, step, timeout, first),
        fields,
        _exec_fields,
    )


def _send(run: _Run, step: _Exec, timeout: float, first: float | None) -> bytes:
    argv = exec_argv(step.script, len(step.stdin), step.sprite_env)
    try:
        return run.api.exec(run.name, argv, step.stdin, timeout, first)
    except StreamTimeoutError as exc:
        exc.args = (_timeout_text(step, exc),)
        raise


def _timeout_text(step: _Exec, exc: StreamTimeoutError) -> str:
    if exc.first_byte:
        return (
            f"{step.stage} stage, {step.purpose}: silent -- no output frame for "
            f"a command that sends no input, not even the start marker ({exc})"
        )
    got = exc.received
    return (
        f"{step.stage} stage, {step.purpose}: output stopped before the exit "
        f"marker after {len(got)} byte(s) (frames {frames_seen(got)}), last "
        f"output {guest_text(decode_exec_output(got), 120)!r} ({exc})"
    )


def _exec_fields(raw: bytes) -> Fields:
    code, _ = parse_exit(decode_exec_output(raw))
    return {
        "bytes_received": len(raw),
        "frames_seen": frames_seen(raw),
        "exit_status": code,
    }


def _exec(run: _Run, step: _Exec) -> tuple[int | None, str]:
    return parse_exit(strip_start(decode_exec_output(_raw_exec(run, step))))


Availability = dict[str, bool] | ExecFailed
Resolved = TrustedPython | ExecFailed | None


def _probe(run: _Run, tools: tuple[ToolSpec, ...]) -> Availability:
    binaries = tuple(t.binary for t in tools)
    if not binaries:
        return {}
    code, text = _exec(
        run,
        _Exec(
            "tool check", "tool check", probe_script(binaries), budget_s=PROBE_BUDGET_S
        ),
    )
    if code != 0:
        failed = ExecFailed(
            "availability probe", code, guest_text(text, GUEST_TAIL_CHARS)
        )
        run.telemetry.record(
            "tool check", "availability", {"exit_status": code},
            status=ERROR, error=failed.detail,
        )  # fmt: skip
        return failed
    found = parse_probe(text, binaries)
    paths = parse_paths(text)
    run.telemetry.record(
        "tool check",
        "availability",
        {
            **{f"has_{b}": ok for b, ok in found.items()},
            **{f"path_{b}": where for b, where in paths.items()},
        },
    )
    return found


@dataclass(frozen=True)
class _Found:
    available: Availability
    python: Resolved

    @property
    def trusted_python(self) -> TrustedPython | None:
        return self.python if isinstance(self.python, TrustedPython) else None


def _python_for(run: _Run, job: RunnerJob) -> Resolved:
    if not (job.diagnose or any(t.needs_python for t in job.tools)):
        return None
    return run.telemetry.span(
        "interpreter",
        "resolve trusted python",
        lambda: _resolve_python(run),
        after=_python_fields,
    )


def _resolve_python(run: _Run) -> Resolved:
    code, text = _exec(
        run,
        _Exec(
            "interpreter", "resolve python", resolve_script(), budget_s=PROBE_BUDGET_S
        ),
    )
    if code != 0:
        return ExecFailed(
            "interpreter resolution", code, guest_text(text, GUEST_TAIL_CHARS)
        )
    return choose_python(text)


def _python_fields(python: Resolved) -> Fields:
    match python:
        case TrustedPython(path=path, version=version):
            return {"python": path, "python_version": version}
        case ExecFailed(exit_code=code):
            return {"python": "resolution failed", "exit_status": code}
    return {"python": "none found"}


def _diagnose(
    run: _Run, specs: tuple[DiagnosticSpec, ...], enabled: bool
) -> list[Diagnostic]:
    return [_diagnostic(run, spec) for spec in specs] if enabled else []


def _diagnostic(run: _Run, spec: DiagnosticSpec) -> Diagnostic:
    """Never fatal: a diagnostic that fails or hangs is itself the result."""
    budget = PROBE_BUDGET_S if spec.bound_s is None else spec.bound_s + 10.0
    step = _Exec(
        "diagnostic",
        spec.name,
        spec.script,
        budget_s=budget,
        sprite_env=spec.sprite_env,
    )
    try:
        code, text = _exec(run, step)
    except BoundaryError as exc:
        return _recorded(
            run, Diagnostic(spec.name, spec.expectation, None, f"exec failed: {exc}")
        )
    return _recorded(
        run, Diagnostic(spec.name, spec.expectation, code, summarize(text))
    )


def _recorded(run: _Run, result: Diagnostic) -> Diagnostic:
    run.telemetry.record(
        "diagnostic",
        result.name,
        {
            "expectation": result.expectation,
            "exit_status": result.exit_code,
            "detail": result.detail,
        },
    )
    return result


def _upload(
    run: _Run,
    tarball: bytes,
    path: str = SOURCE_ARCHIVE,
    purpose: str = "source upload",
) -> None:
    """`exec_argv` feeds exactly the bytes sent through `head -c`, so the
    upload does not depend on the exec channel delivering a stdin EOF; the
    runner reports back how many bytes it wrote. `path` is controller-chosen
    and inserted as is."""
    size = len(tarball)
    script = f"cat > {path} && wc -c < {path}"
    run.telemetry.span(
        "upload",
        f"{size}-byte tarball",
        lambda: _confirm_upload(
            _exec(run, _Exec("upload", purpose, script, tarball, UPLOAD_BUDGET_S)),
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
            f"(exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
        )
    return got


def _unpack(run: _Run, limits: UnpackLimits) -> None:
    """The runner holds `limits` again by its own tar (`guest_unpack`)."""
    script = (
        f"{unpack_script(SOURCE_ARCHIVE, WORKDIR, '--strip-components=1', limits)}"
        f" && rm -f {SOURCE_ARCHIVE}"
    )
    run.telemetry.span(
        "unpack",
        "tar -xzf",
        lambda: _confirm_unpack(
            _exec(
                run, _Exec("unpack", "source unpack", script, budget_s=UNPACK_BUDGET_S)
            ),
            limits,
        ),
        after=lambda code: {"exit_status": code},
    )


def _confirm_unpack(result: tuple[int | None, str], limits: UnpackLimits) -> int:
    code, text = result
    refused = unpack_refusal(text, limits) if code != 0 else None
    if refused is not None:
        raise BoundaryError(f"source unpack failed (exit {code}): {refused}")
    if code != 0:
        raise BoundaryError(
            f"source unpack failed (exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
        )
    return code


def _tool(run: _Run, tool: ToolSpec, found: _Found) -> ToolResult:
    return run.telemetry.span(
        "tool",
        tool.name,
        lambda: _run_if_available(run, tool, found),
        after=_tool_fields,
    )


def _tool_fields(result: ToolResult) -> Fields:
    match result:
        case ToolRan(version=version, exit_code=code):
            return {"result": "ran", "version": version, "exit_status": code}
        case ToolAbsent():
            return {"result": "not run"}
    raise TypeError(f"not a tool result: {result!r}")  # pragma: no cover


def _run_if_available(run: _Run, tool: ToolSpec, found: _Found) -> ToolResult:
    missing = _missing(tool, found)
    if missing:
        return ToolAbsent(tool, missing)
    return _run_tool(run, tool, found.trusted_python)


def _missing(tool: ToolSpec, found: _Found) -> str:
    if tool.needs_python:
        match found.python:
            case TrustedPython():
                return ""
            case ExecFailed(detail=detail):
                return f"no trusted Python interpreter: {detail}"
        return "no trusted Python interpreter was resolved"
    match found.available:
        case ExecFailed(detail=detail):
            return f"not checked: {detail}"
        case available if available.get(tool.binary, False):
            return ""
    return f"`{tool.binary}` not found by the availability probe"


def _run_tool(run: _Run, tool: ToolSpec, python: TrustedPython | None) -> ToolResult:
    version_cmd, run_cmd = (
        (tool.version_cmd, tool.run_cmd)
        if python is None
        else (with_python(tool.version_cmd, python), with_python(tool.run_cmd, python))
    )
    budget = tool.timeout_s + _EXEC_SLACK_S
    stage = f"tool {tool.name}"
    v_code, v_text = _exec(
        run,
        _Exec(
            stage,
            f"{tool.name} version",
            f"cd {WORKDIR} && {version_cmd}",
            budget_s=budget,
        ),
    )
    if v_code != 0:
        return ToolAbsent(
            tool,
            f"version probe exited {v_code}: {guest_text(v_text, GUEST_TAIL_CHARS)}",
        )
    script = f"cd {WORKDIR} && timeout --kill-after=5 {tool.timeout_s} {run_cmd}"
    code, text = _exec(run, _Exec(stage, f"{tool.name} run", script, budget_s=budget))
    return ToolRan(tool, _first_line(v_text), code, text)


def _first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return (guest_text(lines[0], VERSION_CHARS) if lines else "") or "unknown"


def sweep(
    api: SpritesApi, ledger: RunnerLedger, telemetry: Telemetry | None = None
) -> dict[str, CleanupStatus]:
    """Destroy every runner a previous (possibly crashed) review left behind.

    Precondition: no review is running against this ledger. It records
    names only, not an owner or a deadline, so a sweep cannot tell a
    crashed review's runner from a live one and would destroy a live
    one. The caller holds `ledger.single_review_lock` for the sweep, as
    for a review; that lock, not this function, keeps the two apart."""
    t = telemetry or _quiet()
    return {name: destroy_runner(api, ledger, name, t) for name in ledger.pending()}
