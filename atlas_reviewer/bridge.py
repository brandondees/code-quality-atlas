# SPDX-License-Identifier: MIT
"""The closed, read-only git tool bridge over a staged runner (D31 gap 2,
D34 (2), D39).

`run_bridge` stages the sources on a fresh disposable runner
(`bridge_staging`) and hands a `Bridge` to the caller. Each `Bridge.call`
is validated first (`bridge_args`); an invalid call never runs. A valid
one becomes a fixed git argv, every value shell-quoted, run through the
runner's one exec wrapper under `timeout` and a file-size limit. Output
comes back base64-encoded, so neither the exec framing nor in-band text
can bend it, and is capped at the tool's byte and line bounds with the
cut reported. Every call, rejected or run, is in the bridge's ledger.

Results are repository content and are not redacted (D34's secret rule):
each is scanned with `detect_secrets`, and every hit is reported by path,
line and pattern, never by value; a hit outside HEAD or in a file the PR
did not change is pre-existing. Runtime text (git's stderr) is redacted.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from atlas_reviewer.bridge_args import (
    MAX_READ_LINES,
    Call,
    RejectedError,
    Rev,
    validate,
)
from atlas_reviewer.bridge_staging import (
    BRIDGE_ROOT,
    GIT_ENV,
    GIT_OPTIONS,
    KILL_AFTER_S,
    SourceTrees,
    Staged,
    check_sizes,
    quote,
    stage,
)
from atlas_reviewer.domain import CleanupStatus, RunnerReport, RunnerStatus
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    RunnerLedger,
    SpritesApi,
    StreamTimeoutError,
)
from atlas_reviewer.prompt import RepoText
from atlas_reviewer.redact import RedactedText, Redactor, SecretScan, detect_secrets
from atlas_reviewer.runner import (
    FIRST_FRAME_BUDGET_S,
    GUEST_TAIL_CHARS,
    Session,
    guest_text,
    run_session,
)
from atlas_reviewer.telemetry import ERROR, Telemetry

HEADER = "__ATLAS_BRIDGE__"
STDERR_BYTES = 2_000
STDERR_CHARS = 1_000
# 512-byte blocks under dash (8 MiB); a shell counting 1 KiB blocks allows 16.
RAW_OUTPUT_BLOCKS = 16_384
EXEC_SLACK_S = 15.0
_TIMED_OUT = 124
_KILLED = 137
_FILE_TOO_LARGE = 153
_GREP_NO_MATCH = 1
_B64 = r"[A-Za-z0-9+/=]*"
_REPLY = re.compile(
    rf"{HEADER} (\d+) (\d+) (\d+)(?:\n({_B64}))?(?:\n({_B64}))?", re.ASCII
)
_HUNK = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_PLAIN_PATH = re.compile(r"[\x21-\x7e]+")

_DIFF = ("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--find-renames")


class Status(StrEnum):
    OK = "ok"
    FAILED = "failed"
    TIMED_OUT = "timed out"
    TOO_LARGE = "output over the raw limit"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ToolLimits:
    """`max_bytes` and `max_lines` bound what one call returns;
    `timeout_s` is the in-runner `timeout`, at least 1 (`timeout 0`
    disables it)."""

    max_bytes: int
    timeout_s: int
    max_lines: int | None = None

    def __post_init__(self) -> None:
        sizes = (self.max_bytes, self.timeout_s, self.max_lines or 1)
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in sizes):
            raise ValueError("tool limits must be positive integers")


# D31's proposed bounds, working defaults pending the owner (D34).
DEFAULT_LIMITS: Mapping[str, ToolLimits] = MappingProxyType(
    {
        "diff_stat": ToolLimits(16 * 1024, 10),
        "diff_file": ToolLimits(32 * 1024, 10),
        "list_files": ToolLimits(32 * 1024, 10, 2_000),
        "read_file": ToolLimits(32 * 1024, 10, MAX_READ_LINES),
        "grep": ToolLimits(32 * 1024, 15, 200),
    }
)


# -------------------------------------------------------------------- tools


@dataclass(frozen=True)
class _Plan:
    """The git argv after `git <options>` and the view of its output that
    is returned (`$1` is the raw output file)."""

    argv: tuple[str, ...]
    view: str = 'cat "$1"'


def _plan(call: Call, staged: Staged) -> _Plan:
    commit = staged.commits
    span = f"{commit[Rev.BASE]}...{commit[Rev.HEAD]}"
    rev = commit.get(call.get("rev")) if "rev" in dict(call.args) else None
    pathspec = _pathspec(call.get("prefix")) if "prefix" in dict(call.args) else ()
    match call.tool:
        case "diff_stat":
            return _Plan((*_DIFF, "--stat=200", span))
        case "diff_file":
            view = f'tail -c +{call.get("offset") + 1} "$1"'
            return _Plan((*_DIFF, span, "--", call.get("path")), view)
        case "list_files":
            return _Plan(("ls-tree", "-r", "--name-only", str(rev), *pathspec))
        case "read_file":
            view = f"sed -n '{call.get('start')},{call.get('end')}p' \"$1\""
            return _Plan(("cat-file", "blob", f"{rev}:{call.get('path')}"), view)
    mode = "-E" if call.get("regex") else "-F"
    grep = ("grep", "-z", "-n", "-I", "--no-color", "--max-count=50", mode)
    return _Plan((*grep, "-e", call.get("pattern"), str(rev), *pathspec))


def _pathspec(prefix: str) -> tuple[str, ...]:
    return ("--", prefix) if prefix else ()


def call_script(staged: Staged, call: Call, limits: ToolLimits) -> str:
    """Runs one tool into files under the bridge root, then prints a
    header (exit status, bytes and lines of the view) and the capped view
    and stderr, each base64-encoded on its own line."""
    plan = _plan(call, staged)
    git = " ".join((quote(staged.git), "--git-dir=repo.git", *GIT_OPTIONS))
    argv = " ".join(quote(a) for a in plan.argv)
    lines = f"head -n {limits.max_lines} view | " if limits.max_lines else ""
    return "; ".join(
        (
            f"cd {quote(staged.root)}",
            f"export {' '.join(GIT_ENV)}",
            (
                f"( ulimit -f {RAW_OUTPUT_BLOCKS}; exec timeout -k {KILL_AFTER_S} "
                f"{limits.timeout_s} {git} {argv} ) > out 2> err"
            ),
            "s=$?",
            f"view() {{ {plan.view}; }}",
            "view out > view",
            f'echo "{HEADER} $s $(wc -c < view) $(wc -l < view)"',
            f"{lines}head -c {limits.max_bytes} {'' if lines else 'view'} | base64 -w0; echo",
            f"head -c {STDERR_BYTES} err | base64 -w0; echo",
            "rm -f out err view",
        )
    )


@dataclass(frozen=True)
class BridgeSecret:
    """A possible committed secret in a result: its pattern label and,
    where the result locates it, the path and line (in the revision read,
    or the head side of a diff). Never the value."""

    label: str
    path: str | None
    line: int | None
    preexisting: bool


@dataclass(frozen=True)
class BridgeResult:
    """`content` is repository content, unredacted (D34); `error` is
    runtime text and redacted. `values` are the flagged secret values,
    kept only to scrub published output. Neither is in `repr`."""

    tool: str
    args: str
    status: Status
    content: RepoText = field(repr=False)
    error: RedactedText | None
    shown_bytes: int
    total_bytes: int
    total_lines: int
    truncated: bool
    seconds: float
    secrets: tuple[BridgeSecret, ...] = ()
    next_offset: int | None = None
    values: tuple[str, ...] = field(default=(), repr=False, compare=False)


@dataclass(frozen=True)
class CallRecord:
    """One line of the coverage ledger: what was asked and how much came
    back, never the content."""

    tool: str
    args: str
    status: Status
    shown_bytes: int
    total_bytes: int
    truncated: bool
    seconds: float
    secrets: int


@dataclass(frozen=True)
class _Reply:
    code: int
    total_bytes: int
    total_lines: int
    content: bytes
    stderr: bytes


def parse_reply(text: str) -> _Reply | None:
    """The last header the script printed and the base64 lines after it;
    None when there is none or it does not parse."""
    _, found, rest = text.rpartition(f"{HEADER} ")
    match = _REPLY.fullmatch(f"{HEADER} {rest}") if found else None
    if match is None:
        return None
    code, total, lines = (int(match.group(i)) for i in (1, 2, 3))
    try:
        content, stderr = (
            base64.b64decode(match.group(i) or "", validate=True) for i in (4, 5)
        )
    except ValueError:
        return None
    return _Reply(code, total, lines, content, stderr)


_CODE_STATUS = {
    0: Status.OK,
    _TIMED_OUT: Status.TIMED_OUT,
    _KILLED: Status.TIMED_OUT,
    _FILE_TOO_LARGE: Status.TOO_LARGE,
}


def _status(tool: str, code: int) -> Status:
    no_match = tool == "grep" and code == _GREP_NO_MATCH
    return Status.OK if no_match else _CODE_STATUS.get(code, Status.FAILED)


@dataclass(frozen=True)
class _Where:
    path: str | None
    line: int | None
    preexisting: bool


_NOWHERE = _Where(None, None, False)


@dataclass(frozen=True)
class _View:
    """The shown text, where each of its lines comes from, and whether all
    of the output could be shown (False when some of it did not parse)."""

    text: str
    places: list[_Where]
    complete: bool = True


def _view(
    call: Call, raw: bytes, commit: str, preexisting: Callable[[Rev, str], bool]
) -> _View:
    text = raw.decode("utf-8", errors="replace")
    match call.tool:
        case "read_file":
            rev, path, start = call.get("rev"), call.get("path"), call.get("start")
            return _View(
                text,
                [
                    _Where(path, start + i, preexisting(rev, path))
                    for i in range(text.count("\n") + 1)
                ],
            )
        case "grep":
            return _grep_view(text, commit, call.get("rev"), preexisting)
        case "diff_file":
            return _View(text, _diff_places(text.split("\n"), call.get("path")))
    return _View(text, [])


def _grep_records(text: str, commit: str) -> tuple[list[tuple[str, str, str]], bool]:
    """`<commit>:<path>\\0<line>\\0<text>\\n` per match (`git grep -z -n`).
    The fields are split on NUL first: a path may hold a newline but a
    matched line cannot, so each line's text ends at its first newline and
    the next record's `<commit>:<path>` follows it. A record that is cut
    short or out of step (a NUL inside a matched line) ends the parse;
    the flag says whether every byte was accounted for."""
    fields = text.split("\0")
    prefix = f"{commit}:"
    head = fields[0]
    records: list[tuple[str, str, str]] = []
    for line, rest in zip(fields[1::2], fields[2::2], strict=False):
        match, newline, after = rest.partition("\n")
        if not (head.startswith(prefix) and line.isdigit() and newline):
            return records, False
        records.append((head[len(prefix) :], line, match))
        head = after
    return records, head == "" and len(fields) % 2 == 1


def _grep_view(
    text: str, commit: str, rev: Rev, preexisting: Callable[[Rev, str], bool]
) -> _View:
    records, complete = _grep_records(text, commit)
    return _View(
        "\n".join(f"{_shown_path(p)}:{n}:{t}" for p, n, t in records),
        [_Where(p, int(n), preexisting(rev, p)) for p, n, _ in records],
        complete,
    )


def _shown_path(path: str) -> str:
    return path if _PLAIN_PATH.fullmatch(path) and ":" not in path else json.dumps(path)


def _diff_places(lines: Iterable[str], path: str) -> list[_Where]:
    """Head-side lines of added and context lines, base-side of removed
    ones; added lines are new in the PR, the rest pre-existing. Lines
    before the page's first hunk header are not located."""
    places: list[_Where] = []
    base = head = None
    for line in lines:
        hunk = _HUNK.match(line)
        if hunk:
            base, head = int(hunk.group(1)), int(hunk.group(2))
        place, base, head = _diff_line(line, path, base, head, bool(hunk))
        places.append(place)
    return places


def _diff_line(
    line: str, path: str, base: int | None, head: int | None, is_hunk: bool
) -> tuple[_Where, int | None, int | None]:
    if is_hunk or base is None or head is None:
        return _Where(path, None, False), base, head
    kind = line[:1]
    if kind == "+":
        return _Where(path, head, False), base, head + 1
    if kind == "-":
        return _Where(path, base, True), base + 1, head
    if kind == " ":
        return _Where(path, head, True), base + 1, head + 1
    return _Where(path, None, False), base, head


def _secrets(scan: SecretScan, places: Sequence[_Where]) -> tuple[BridgeSecret, ...]:
    def where(line: int) -> _Where:
        return places[line - 1] if 0 < line <= len(places) else _NOWHERE

    return tuple(
        BridgeSecret(
            hit.label,
            where(hit.line).path,
            where(hit.line).line,
            where(hit.line).preexisting,
        )
        for hit in scan.hits
    )


@dataclass
class Bridge:
    """The tools over one staged runner. `changed` are the paths the PR
    changes (from its diff): a secret found in any other file, or outside
    HEAD, is pre-existing. Every call, rejected or run, is in `calls`."""

    session: Session
    staged: Staged
    redactor: Redactor
    clock: Clock
    changed: frozenset[str] = frozenset()
    limits: Mapping[str, ToolLimits] = DEFAULT_LIMITS
    calls: list[CallRecord] = field(default_factory=list)
    _flagged: list[str] = field(default_factory=list, repr=False)

    def flagged(self) -> tuple[str, ...]:
        """Every secret value found so far, for `Redactor.sources`."""
        return tuple(self._flagged)

    def call(self, tool: Any, args: Any) -> BridgeResult:
        try:
            checked = validate(tool, args, self.staged.revs)
        except RejectedError as exc:
            return self._logged(self._rejected(tool, args, str(exc)))
        return self._logged(self._run(checked))

    def _rejected(self, tool: Any, args: Any, reason: str) -> BridgeResult:
        given = json.dumps(args, sort_keys=True, ensure_ascii=True, default=str)
        return BridgeResult(
            str(tool), given, Status.REJECTED, RepoText(""),
            self.redactor(reason, STDERR_CHARS), 0, 0, 0, False, 0.0,
        )  # fmt: skip

    def _run(self, call: Call) -> BridgeResult:
        limits = self.limits[call.tool]
        started = self.clock.monotonic()
        try:
            code, text = self.session.exec(
                f"bridge {call.tool}",
                call_script(self.staged, call, limits),
                stage="bridge",
                budget_s=limits.timeout_s + EXEC_SLACK_S,
            )
        except StreamTimeoutError as exc:
            return self._failed(call, Status.TIMED_OUT, str(exc), started)
        except BoundaryError as exc:
            return self._failed(call, Status.UNAVAILABLE, str(exc), started)
        reply = parse_reply(text) if code == 0 else None
        if reply is None:
            detail = (
                f"no bridge reply (exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
            )
            return self._failed(call, Status.UNAVAILABLE, detail, started)
        return self._result(call, reply, self.clock.monotonic() - started)

    def _failed(
        self, call: Call, status: Status, detail: str, started: float
    ) -> BridgeResult:
        return BridgeResult(
            call.tool, call.args_json, status, RepoText(""),
            self.redactor(detail, STDERR_CHARS), 0, 0, 0, False,
            self.clock.monotonic() - started,
        )  # fmt: skip

    def _result(self, call: Call, reply: _Reply, seconds: float) -> BridgeResult:
        limits = self.limits[call.tool]
        status = _status(call.tool, reply.code)
        commit = self.staged.commits[call.get("rev")] if call.tool == "grep" else ""
        view = _view(call, reply.content, commit, self._preexisting)
        scan = detect_secrets(view.text)
        shown = len(reply.content)
        cut = (
            shown < reply.total_bytes
            or (limits.max_lines is not None and reply.total_lines > limits.max_lines)
            or not view.complete
        )
        stderr = reply.stderr.decode("utf-8", errors="replace")
        self._flagged.extend(scan.values)
        return BridgeResult(
            call.tool,
            call.args_json,
            status,
            RepoText(view.text),
            self.redactor(stderr, STDERR_CHARS) if stderr else None,
            shown,
            reply.total_bytes,
            reply.total_lines,
            cut,
            seconds,
            _secrets(scan, view.places),
            call.get("offset") + shown if cut and call.tool == "diff_file" else None,
            scan.values,
        )

    def _preexisting(self, rev: Rev, path: str) -> bool:
        return rev is not Rev.HEAD or path not in self.changed

    def _logged(self, result: BridgeResult) -> BridgeResult:
        self.calls.append(
            CallRecord(
                result.tool,
                result.args,
                result.status,
                result.shown_bytes,
                result.total_bytes,
                result.truncated,
                result.seconds,
                len(result.secrets),
            )
        )
        return result


def render(result: BridgeResult) -> str:
    """The result as the model reads it: one controller-written line, then
    the content. The arguments are the model's own, shown as JSON."""
    head = f"{result.tool} {result.args}: {result.status.value}"
    if result.truncated:
        head += (
            f"; output cut: {result.shown_bytes} of {result.total_bytes} bytes shown"
            f" ({result.total_lines} lines in all)"
        )
    if result.next_offset is not None:
        head += f"; next page at offset {result.next_offset}"
    if result.secrets:
        head += f"; {len(result.secrets)} possible committed secret(s) reported to the controller"
    error = f"\nerror: {result.error.text}" if result.error else ""
    return f"{head}{error}\n{result.content.text}"


def run_bridge(
    api: SpritesApi,
    ledger: RunnerLedger,
    trees: SourceTrees,
    body: Callable[[Bridge], str],
    *,
    redactor: Redactor,
    changed: frozenset[str],
    name: str,
    deadline_s: float,
    clock: Clock,
    telemetry: Telemetry | None = None,
    limits: Mapping[str, ToolLimits] = DEFAULT_LIMITS,
    root: str = BRIDGE_ROOT,
    first_frame_s: float = FIRST_FRAME_BUDGET_S,
) -> RunnerReport:
    """Stage `trees` on a fresh disposable runner and hand `body` the
    bridge; the runner is always destroyed. Trees over the upload cap are
    refused before anything is created."""
    telemetry = telemetry or Telemetry(clock)
    try:
        check_sizes(trees)
    except BoundaryError as exc:
        telemetry.record("upload", "size check", status=ERROR, error=str(exc))
        return RunnerReport(
            RunnerStatus.FAILED, CleanupStatus.NOT_CREATED, name, str(exc)
        )

    def session_body(session: Session) -> str:
        staged = stage(session, trees, root)
        telemetry.record(
            "bridge staging", "staged",
            {"revisions": len(staged.commits), "git": staged.git, "git_version": staged.git_version},
        )  # fmt: skip
        return body(Bridge(session, staged, redactor, clock, changed, limits))

    return run_session(
        api, ledger, session_body, name=name, deadline_s=deadline_s, clock=clock,
        telemetry=telemetry, first_frame_s=first_frame_s,
    )  # fmt: skip
