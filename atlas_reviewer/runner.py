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
   executes unless the read-back is exactly deny-all. A runner given a
   setup spec (issue #819, D95) runs the repo's declared setup commands
   first, while egress is still allowed -- still before any PR content
   is uploaded or unpacked -- and proves the flip held with the
   behavioral egress check after the read-back. A runner given a
4. cap memory; probe which tool binaries exist (tool check); upload the
   head-SHA tarball over exec stdin to a file, confirming the byte count
   the runner received; unpack it in a second exec; run each available tool
5. destroy -- in `finally`, and from a watchdog timer at the deadline.
   Destroy is idempotent and is verified by a follow-up existence check;
   only the final verified destroy clears the ledger entry, never the
   watchdog's, which can run while `create` is still in flight, and not
   after a create whose outcome is unknown or once the cleanup budget is
   spent: those report DESTROY_UNVERIFIED and leave the entry for
   `sweep --force-live`.

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

import hashlib
import random
import re
import secrets
import shlex
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import CleanupStatus, PrEvent, RunnerReport, RunnerStatus
from atlas_reviewer.guest_unpack import unpack_refusal, unpack_script
from atlas_reviewer.interpreter import (
    NEUTRAL_DIR,
    PYTHON_PLACEHOLDER,
    SYSTEM_PYTHON,
    DiagnosticSpec,
    TrustedPython,
    bounded,
    candidates_glob,
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
    RateLimitedError,
    RefusedError,
    RunnerLedger,
    SpritesApi,
    StreamTimeoutError,
)
from atlas_reviewer.source_archive import DEFAULT_UNPACK, UnpackLimits, measure
from atlas_reviewer.sprites_api import EXEC_STDIN_MAX_BYTES
from atlas_reviewer.stops import held
from atlas_reviewer.telemetry import ERROR, OK, Fields, Telemetry

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
# One setup command's own bound and the exec budget that carries it
# (issue #819, D95): a `pip install` against a real index can take
# minutes, and the review's wall deadline bounds the phase as a whole
# besides. The bound is what the command runs under (`timeout -k`), the
# budget is the exec's window around it. The 2026-11-26 environment
# slice (D80's update) raises it from 300s to 900s, because the setup
# spec this repo itself sets now installs the repo's full requirements
# (`pip install -r requirements.txt`, hash-pinned, about fifty
# packages): a cold resolve-and-install can outlive the old bound, and
# the review wall still bounds the phase as a whole.
SETUP_BOUND_S = 900
SETUP_BUDGET_S = SETUP_BOUND_S + 30.0
# From the first destroy of a runner, shared by the watchdog's and the
# final one: no control-plane call starts after it, so cleanup ends
# within this plus one call window (`SpritesClient` timeout_s, 30s).
CLEANUP_BUDGET_S = 60.0
DIAGNOSTIC_BOUND_S = 15
PYTHON_BINARY = "python3"
MINIMAL_ENV = ("PATH=/usr/bin:/bin", "HOME=/tmp", "LANG=C.UTF-8")
STDIN_CHECK_BYTES = 3 * 1024 * 1024
_FRAMING_BYTES = dict.fromkeys(range(0x05))
# How a refused create is retried (#636, #690): Sprites answers 429 when
# several creates arrive together, so the waits double from 2s and are
# capped at 60s -- `DEFAULT_CREATE_RETRIES` waits spend about two minutes
# before the create gives up, against the old three waits of 1, 2 and 4s
# that gave up inside seven. The runner's deadline bounds it sooner. A
# Retry-After the server names is honored up to `CREATE_RETRY_AFTER_CAP_S`,
# so one huge value cannot park a lens's whole deadline in a single wait.
CREATE_BACKOFF_BASE_S = 2.0
CREATE_BACKOFF_MAX_S = 60.0
CREATE_RETRY_AFTER_CAP_S = 120.0
DEFAULT_CREATE_RETRIES = 6
# How many creates one review may have in flight at once. The 2026-11-14
# trials saw about 12 Sprites starting together draw 429s the short backoff
# could not wait out; the coordinator passes a gate of this size
# (`ATLAS_CREATE_CONCURRENCY`), so the burst is spread instead.
DEFAULT_CREATE_CONCURRENCY = 4


class DeadlineExceededError(RuntimeError):
    pass


class PolicyNotEnforcedError(BoundaryError):
    pass


class CreateRefusedError(BoundaryError):
    """Sprites refused to create the runner, so this run made nothing and
    deletes nothing. Not a failed run but a run that cannot start: it
    propagates instead of becoming a FAILED report."""


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


@dataclass(frozen=True)
class SetupSpec:
    """The reviewed repo's declared setup commands (issue #819, D95): the
    dev-dependency installs a runner runs **before** the review phase,
    with egress still allowed, so `pip install` and friends can reach
    their indexes. The commands are the repo's own default-branch
    `REVIEW.md` text (`repo_config.parse_setup_commands`), controller
    tokens -- the model never names one -- and a command may carry the
    `{python}` placeholder, which the controller substitutes with the
    interpreter it resolved by absolute path before the phase ran.
    `files` are the default-branch files the commands read (the spec's
    `review_setup_files:` line): the controller fetched each from the
    same branch the spec was read from -- never the PR head -- and the
    phase uploads them into the runner's setup directory under their own
    names before the first command runs, so a relative
    `-r requirements.txt` resolves. Empty (or absent) is the ordinary
    runner: deny-all from the start, nothing installed."""

    commands: tuple[tuple[str, ...], ...] = ()
    files: Mapping[str, bytes] = MappingProxyType({})


SETUP_FILE_MAX_BYTES = 8 * 1024 * 1024


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


CreateOutcome = Literal["not started", "unknown", "refused", "settled"]


@dataclass
class _Create:
    """Whether this process's `create` made the runner. Only `settled`
    shows it did, so only then may cleanup delete the name: another
    review of the same commit uses the same name. `refused` is a 4xx
    answer (nothing was made, or the name is someone else's). `unknown`
    while it is in flight and after it raised otherwise: a client-side
    failure (a timeout, a 5xx a proxy sent after forwarding) does not show
    the server never made the Sprite, nor that the Sprite is this
    process's."""

    outcome: CreateOutcome = "not started"


@dataclass(frozen=True)
class _Run:
    api: SpritesApi
    name: str
    deadline: Deadline
    telemetry: Telemetry
    first_frame_s: float = FIRST_FRAME_BUDGET_S
    create: _Create = field(default_factory=_Create)
    exec_lock: threading.Lock = field(default_factory=threading.Lock)
    create_retries: int = DEFAULT_CREATE_RETRIES
    create_gate: threading.Semaphore | None = None
    setup: SetupSpec | None = None
    # The interpreters the lifecycle's own resolution probes, when the
    # caller names them (the eval run's staged interpreter, D98); None
    # probes the image's trusted shapes.
    python_candidates: Sequence[str] | None = None
    # The run's own neutral directory. A live Sprite's filesystem is its
    # own, so the shared default is private there; the local runner's
    # concurrent runners share the host's, where a shared directory races
    # the setup files' uploads (two `cat >`s on one path) -- so the run's
    # is derived from its name.
    neutral_dir: str = NEUTRAL_DIR


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


def event_runner_name(event: PrEvent) -> str:
    """One name per PR commit, so a runner that outlived its controller can
    be found and deleted from the event alone. The digest keeps two repos
    with the same PR number and commit apart."""
    key = f"{event.repo}\n{event.pr_number}\n{event.head_sha}".encode()
    digest = hashlib.sha256(key).hexdigest()[:8]
    return f"cqa-rev-pr{event.pr_number}-{event.head_sha[:12]}-{digest}"


def lens_runner_name(event: PrEvent, lens: str) -> str:
    """One Sprite name per lens of a commit. Parallel lenses would collide
    on `event_runner_name` alone, and one lens's cleanup deletes by name,
    so the suffix is 12 hex digits: a collision would delete a sibling's
    Sprite. The whole name stays under a 63-character DNS label."""
    extra = hashlib.sha256(lens.encode()).hexdigest()[:12]
    return f"{event_runner_name(event)}-{extra}"


# A slot wait is only noted in telemetry once it took this long: a gate
# with room records nothing.
_QUEUED_NOTE_S = 0.1


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


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
        self.deleted = False
        self._budget_start: float | None = None

    def _budget_left(self) -> float:
        if self._budget_start is None:
            self._budget_start = self._clock.monotonic()
        return CLEANUP_BUDGET_S - (self._clock.monotonic() - self._budget_start)

    def destroy(self, trigger: Trigger) -> CleanupStatus:
        """Only the watchdog can run while `create` is still in flight.
        Any other trigger destroys again even after the watchdog did,
        because a create in flight when the watchdog fired can settle
        after it; for the same reason the watchdog never clears the ledger
        entry. No trigger deletes unless this process's create settled:
        with the create refused or never started nothing was made here, so
        the result is NOT_CREATED; with its outcome unknown the Sprite may
        be another review's, so the entry stays for a `sweep --force-live`
        the operator runs and the result is DESTROY_UNVERIFIED. A telemetry write
        failure must not stop cleanup, so cleanup is redone untraced and
        the error re-raised, carrying the cleanup result as a note.

        Cleanup has `CLEANUP_BUDGET_S` from the first destroy: a destroy
        waits for another one only that long, and starts no call once it
        is spent. Cut short, it reports DESTROY_UNVERIFIED and leaves the
        ledger entry for `sweep --force-live`."""
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
        if self._create.outcome != "settled":
            return self._without_delete(telemetry, trigger)
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

    def _without_delete(self, telemetry: Telemetry, trigger: Trigger) -> CleanupStatus:
        create = self._create.outcome
        telemetry.record(
            "destroy", "no delete",
            {"runner": self._name, "trigger": trigger, "create": create},
        )  # fmt: skip
        if create == "unknown":
            return self._outcome(telemetry, trigger, CleanupStatus.DESTROY_UNVERIFIED)
        if trigger != "watchdog":
            self._ledger.clear(self._name)
        return self._outcome(telemetry, trigger, CleanupStatus.NOT_CREATED)

    def _verified_status(self, telemetry: Telemetry, trigger: Trigger) -> CleanupStatus:
        if not self._verified_absent(telemetry, trigger):
            return CleanupStatus.DESTROY_UNVERIFIED
        if trigger != "watchdog":
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
        self.deleted = True
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
    return _sweep_one(api, ledger, name, telemetry or _quiet()).cleanup


@dataclass(frozen=True)
class Swept:
    """`deleted` is False when the runner was already absent."""

    cleanup: CleanupStatus
    deleted: bool


def _sweep_one(
    api: SpritesApi, ledger: RunnerLedger, name: str, telemetry: Telemetry
) -> Swept:
    destroyer = _Destroyer(
        api, ledger, name, telemetry, _Create("settled"), SystemClock()
    )
    return Swept(destroyer.destroy("sweep"), destroyer.deleted)


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
    create_retries: int = DEFAULT_CREATE_RETRIES,
    create_gate: threading.Semaphore | None = None,
    setup: SetupSpec | None = None,
    python_candidates: Sequence[str] | None = None,
) -> RunnerReport:
    """Run `body` on a fresh, policy-verified Sprite; always destroy it."""
    deadline = Deadline(clock, deadline_s)
    run = _Run(
        api, name, deadline, telemetry, first_frame_s,
        create_retries=create_retries, create_gate=create_gate,
        setup=setup, python_candidates=python_candidates,
        neutral_dir=f"{NEUTRAL_DIR}-{name}",
    )  # fmt: skip
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
        with held():
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
    except CreateRefusedError:
        raise
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
    create_retries: int = DEFAULT_CREATE_RETRIES,
    create_gate: threading.Semaphore | None = None,
    setup: SetupSpec | None = None,
    python_candidates: Sequence[str] | None = None,
) -> RunnerReport:
    """`body` on a fresh disposable runner with the same lifecycle as a
    review: recorded in the ledger, provisioned deny-all and verified,
    bounded by the deadline and its watchdog, always destroyed. The body's
    return value is the report's note. `create_gate`, when given, is how
    many creates may be in flight at once across the callers sharing it;
    `create_retries` is how many times a 429'd create waits and retries.
    A `setup` spec (issue #819, D95) runs the repo's declared setup
    commands with egress still allowed, before the deny-all flip and
    before anything of the review -- the body included -- executes; every
    exec after the flip runs under verified deny-all."""
    return _disposable(
        api, ledger, lambda run: body(Session(run)), name=name,
        deadline_s=deadline_s, clock=clock,
        telemetry=telemetry or Telemetry(clock), first_frame_s=first_frame_s,
        create_retries=create_retries, create_gate=create_gate,
        setup=setup, python_candidates=python_candidates,
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
    create_retries: int = DEFAULT_CREATE_RETRIES,
    create_gate: threading.Semaphore | None = None,
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
        create_retries=create_retries, create_gate=create_gate,
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


def _create_waits(retries: int) -> tuple[float, ...]:
    """`retries` waits, doubling from `CREATE_BACKOFF_BASE_S` and capped at
    `CREATE_BACKOFF_MAX_S`. The default six spend at most about two minutes
    waiting a 429 out; the runner's deadline bounds the whole loop sooner."""
    return tuple(
        min(CREATE_BACKOFF_BASE_S * 2**i, CREATE_BACKOFF_MAX_S)
        for i in range(max(retries, 0))
    )


def _wait_s(retry_after: float | None, scheduled: float) -> float:
    """The server's Retry-After exactly, clamped to `[0,
    CREATE_RETRY_AFTER_CAP_S]` -- a Retry-After of 0 is what the server
    asked for, so the next create goes out at once -- or, when no header
    came, the scheduled wait, jittered so pooled lenses do not retry in
    step."""
    if retry_after is None:
        return scheduled * random.uniform(0.5, 1.0)
    return min(max(retry_after, 0.0), CREATE_RETRY_AFTER_CAP_S)


def _create_with_backoff(run: _Run) -> None:
    """Sprites answers HTTP 429 when several creates arrive together.
    The #636 live run refused two of ten creates before anything existed,
    and the #690 runs of 2026-11-14 crashed three reviews when about 12
    pooled lenses started at once, so a 429 is waited out and tried again
    on a longer, bounded schedule (`_create_waits`), honoring the server's
    Retry-After when it names one, with jitter so pooled lenses do not
    retry in step, and only while the runner's deadline has time left.
    When the review passes a `create_gate`, this runner waits its turn
    before the first create, so at most that many Sprites start together.
    Any other refusal is final."""
    gate = run.create_gate
    if gate is None:
        _create_attempts(run)
        return
    left = run.deadline.check("create")
    queued_at = run.deadline.clock.monotonic()
    if not gate.acquire(timeout=max(left, 0.0)):
        raise DeadlineExceededError(
            f"deadline of {run.deadline.seconds:g}s reached waiting for a create slot"
        )
    try:
        waited = run.deadline.clock.monotonic() - queued_at
        if waited >= _QUEUED_NOTE_S:
            run.telemetry.record(
                "create", "waited for a create slot", {"waited_s": round(waited, 1)}
            )
        _create_attempts(run)
    finally:
        gate.release()


def _create_attempts(run: _Run) -> None:
    """The create itself, with the 429 waits. `unknown` is set only while a
    create call is actually in flight or its outcome is genuinely unclear:
    the call's own 429 says nothing was made, so the outcome goes back to
    `not started` for the wait, and a deadline that fires during it leaves
    cleanup nothing to guess about."""
    api, name, t = run.api, run.name, run.telemetry
    waits = _create_waits(run.create_retries)
    waits_done = 0
    while True:
        try:
            run.create.outcome = "unknown"
            t.span("create", "create sprite", lambda: api.create(name))
            return
        except RateLimitedError as exc:
            # A 429 is definitive: the server did not act, so nothing
            # exists to clean up however long the wait runs.
            run.create.outcome = "not started"
            if waits_done >= len(waits):
                t.record(
                    "create", "gave up",
                    {"attempts": waits_done + 1},
                    status=ERROR, error=str(exc),
                )  # fmt: skip
                raise
            delay = _wait_s(exc.retry_after, waits[waits_done])
            t.record(
                "create", "rate limited",
                {
                    "attempt": waits_done + 1,
                    "wait_s": round(delay, 1),
                    "retry_after_s": (
                        None if exc.retry_after is None else round(exc.retry_after, 1)
                    ),
                },
            )  # fmt: skip
            run.deadline.check("create retry")
            _sleep(min(delay, max(run.deadline.remaining(), 0.0)))
            run.deadline.check("create retry")
            waits_done += 1


def _provision(run: _Run) -> None:
    api, name, t = run.api, run.name, run.telemetry
    run.deadline.check("create")
    try:
        _create_with_backoff(run)
    except (RefusedError, NotFoundError) as exc:
        run.create.outcome = "refused"
        raise CreateRefusedError(
            f"Sprites refused to create runner {name} ({exc}); this review "
            "created and deletes nothing. If a Sprite by that name exists, "
            "another review of this commit may be using it."
        ) from exc
    run.create.outcome = "settled"
    spec = run.setup if run.setup is not None and run.setup.commands else None
    if spec is not None:
        # The setup phase (issue #819, D95) runs while egress is still
        # whatever the fresh image's default is, so `pip install` can
        # reach its indexes; every setup exec is still before any PR
        # content is uploaded or unpacked. The deny-all flip below is
        # what ends the phase, and nothing of the review runs before it.
        _setup_phase(run)
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
    if spec is not None:
        _egress_proof(run)


def _require_deny_all(policy: Json) -> None:
    rules = policy.get("rules")
    if rules != list(DENY_ALL):
        raise PolicyNotEnforcedError(
            f"network policy read-back is not deny-all: {rules!r}"
        )


def setup_command_script(
    command: Sequence[str], python: TrustedPython, neutral_dir: str = NEUTRAL_DIR
) -> str:
    """One setup command as the runner runs it (issue #819, D95): from the
    neutral directory -- empty of the PR, which is not uploaded yet, and
    otherwise holding only the setup spec's own declared default-branch
    files, uploaded there under their names before the first command --
    each token quoted, the `{python}` placeholder already substituted
    with the resolved interpreter's quoted absolute path, the whole argv
    under its own `timeout -k` bound. The tokens are the repo's
    default-branch `REVIEW.md` grammar's output, so quoting is
    belt-and-braces, not the containment guarantee."""
    argv = [
        python.quoted if token == PYTHON_PLACEHOLDER else shlex.quote(token)
        for token in command
    ]
    return (
        f"mkdir -p {shlex.quote(neutral_dir)} && cd {shlex.quote(neutral_dir)} && "
        + bounded(" ".join(argv), SETUP_BOUND_S)
    )


def _setup_phase(run: _Run) -> None:
    """The repo's declared setup commands, one exec each, while egress is
    still allowed (issue #819, D95). The interpreter is resolved first --
    before any PR content exists, the same pre-unpack resolution every
    tool path uses -- and a command that fails, times out, or outlives
    its budget fails the run closed: a setup the repo declared and did
    not get is not a review to continue, it is the broken state named in
    the issue. The phase ends at the deny-all flip `_provision` performs
    right after; nothing of the review runs before it."""
    spec = run.setup
    assert spec is not None and spec.commands
    python = run.telemetry.span(
        "interpreter",
        "resolve trusted python",
        lambda: _resolve_python(run),
        after=_python_fields,
    )
    if isinstance(python, ExecFailed):
        # The resolution exec itself failed -- a machinery failure this
        # run cannot distinguish from a transient one, not a property of
        # the image: a fresh runner may resolve fine. The run still fails
        # closed.
        raise BoundaryError(
            f"the setup phase's interpreter resolution failed: {python.detail}"
        )
    if python is None:
        # The resolution ran and established that no trusted interpreter
        # exists on this image -- deterministic across the fresh runners
        # every lens gets, so re-running the same resolution per lens
        # would fail identically.
        raise BoundaryError(
            "the setup phase found no trusted interpreter to run the "
            "repo's setup commands with"
        )
    for name, data in spec.files.items():
        # The spec's declared default-branch files, into the neutral
        # directory under their own names before the first command: a
        # relative `-r requirements.txt` has to resolve there. The names
        # are grammar-validated (plain repo-root-relative paths), and
        # the content is the default branch's -- the same read source
        # the spec itself came from, never the PR head. A nested name
        # gets its parent directory created in the upload's own script.
        purpose = f"setup file {name}"
        run.deadline.check(purpose)
        parents = name.rsplit("/", 1)[0] if "/" in name else None
        _upload(
            run,
            data,
            f"{run.neutral_dir}/{name}",
            purpose,
            parents=f"{run.neutral_dir}/{parents}" if parents else None,
        )
    for n, command in enumerate(spec.commands, start=1):
        purpose = f"setup command {n}"
        run.deadline.check(purpose)
        code, text = _exec(
            run,
            _Exec(
                "setup",
                purpose,
                setup_command_script(command, python, run.neutral_dir),
                budget_s=SETUP_BUDGET_S,
            ),
        )  # fmt: skip
        run.telemetry.record(
            "setup", purpose,
            {"command_index": n, "exit_status": code},
            status=ERROR if code != 0 else OK,
            error=(
                "" if code == 0
                else f"exit {code}: {guest_text(text, GUEST_TAIL_CHARS)}"
            ),
        )  # fmt: skip
        if code != 0:
            raise BoundaryError(
                f"setup command {n} failed (exit {code}): "
                f"{guest_text(text, GUEST_TAIL_CHARS)}"
            )


def _egress_proof(run: _Run) -> None:
    """Behavioural evidence that the deny-all flip held, on the only
    runners that ever had egress allowed (issue #819, D95): the read-back
    proves what the control plane stored, this shows the guest cannot
    connect out to an IP literal and a hostname. `OPEN` fails the run
    closed -- a policy that read back deny-all but connects is the
    enforcement the whole review phase rests on. An `UNVERIFIED` verdict
    (the check itself could not run or a target went unreported) is
    recorded as an error and does not fail the run: the read-back remains
    the enforced gate, exactly as the probe's own egress check is
    evidence beside it, not the gate."""
    verdict = _egress_check(run)
    clean = verdict.startswith("no outbound connection")
    run.telemetry.record(
        "egress",
        "behavioral check",
        {"verdict": verdict},
        status=OK if clean else ERROR,
        error=(
            ""
            if clean
            else f"the deny-all flip's behavioral check did not pass: {verdict}"
        ),
    )
    if verdict.startswith("OPEN"):
        raise PolicyNotEnforcedError(f"the deny-all flip did not hold: {verdict}")


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
    """One exec at a time on this runner. The lens keepalive refreshes from
    its own thread, and a tool call must not share the stream with it."""
    with run.exec_lock:
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
            "interpreter",
            "resolve python",
            resolve_script(
                neutral_dir=run.neutral_dir,
                candidates=candidates_glob(run.python_candidates),
            ),
            budget_s=PROBE_BUDGET_S,
        ),
    )
    if code != 0:
        return ExecFailed(
            "interpreter resolution", code, guest_text(text, GUEST_TAIL_CHARS)
        )
    return choose_python(text, run.python_candidates or ())


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
    *,
    parents: str | None = None,
) -> None:
    """`exec_argv` feeds exactly the bytes sent through `head -c`, so the
    upload does not depend on the exec channel delivering a stdin EOF; the
    runner reports back how many bytes it wrote. `path` is controller-chosen
    and inserted as is. `parents`, when given, is a directory the script
    creates first -- the setup spec's declared files may name a nested
    path, and `cat >` creates no directories."""
    size = len(tarball)
    script = (
        f"mkdir -p {shlex.quote(parents)} && " if parents is not None else ""
    ) + f"cat > {path} && wc -c < {path}"
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
) -> dict[str, Swept]:
    """Destroy every runner a previous (possibly crashed) review left behind.

    Precondition: no review is running against this ledger. It records
    names only, not an owner or a deadline, so a sweep cannot tell a
    crashed review's runner from a live one and would destroy a live
    one. The caller holds `ledger.single_review_lock` for the sweep, as
    for a review; that lock, not this function, keeps the two apart."""
    t = telemetry or _quiet()
    return {name: _sweep_one(api, ledger, name, t) for name in ledger.pending()}
