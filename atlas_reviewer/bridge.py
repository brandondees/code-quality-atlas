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
import codecs
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from atlas_reviewer.bridge_args import (
    MAX_READ_LINES,
    TOOLS,
    Call,
    RejectedError,
    Rev,
    path_problem,
    validate,
)
from atlas_reviewer.bridge_staging import (
    BRIDGE_ROOT,
    GIT_ENV,
    GIT_OPTIONS,
    SourceTrees,
    Staged,
    check_sizes,
    quote,
    stage,
)
from atlas_reviewer.domain import CleanupStatus, RunnerReport, RunnerStatus
from atlas_reviewer.guest_unpack import KILL_AFTER_S
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
from atlas_reviewer.source_archive import DEFAULT_UNPACK, UnpackLimits
from atlas_reviewer.telemetry import ERROR, Telemetry

HEADER = "__ATLAS_BRIDGE__"
UNKNOWN_TOOL = "(unknown tool)"
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
    rf"{HEADER} (\d+) (\d+) (\d+) (\d+) (\d+)(?:\n({_B64}))?(?:\n({_B64}))?",
    re.ASCII,
)
_HUNK = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_PLAIN_PATH = re.compile(r"[\x21-\x7e]+")
_CONTINUATION = bytes(range(0x80, 0xC0))

_DIFF = ("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--find-renames")


class Status(StrEnum):
    OK = "ok"
    FAILED = "failed"
    TIMED_OUT = "timed out"
    TOO_LARGE = "output over the raw limit"
    REJECTED = "rejected"
    OVER_SESSION_LIMIT = "session limit reached"
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


@dataclass(frozen=True)
class SessionLimits:
    """Bounds across every call one bridge serves: calls made (rejected
    ones too) and output bytes shown. A call is never shown more than the
    output left; once either is spent, calls are refused without running."""

    max_calls: int = 64
    max_output_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        sizes = (self.max_calls, self.max_output_bytes)
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in sizes):
            raise ValueError("session limits must be positive integers")


# Working defaults pending the owner (D39): D31's 12 turns per lens at a
# few calls each, and its about 10k characters of tool output per turn.
DEFAULT_SESSION = SessionLimits()

# The controller's own listing of the PR's renames, for `diff_file`.
RENAME_LIMITS = ToolLimits(1024 * 1024, 10)

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
    nul_records: bool = False


def _plan(call: Call, staged: Staged, paths: tuple[str, ...]) -> _Plan:
    """`paths` are what `diff_file` diffs: its path, and the other side of
    a rename it is part of."""
    commit = staged.commits
    span = f"{commit[Rev.BASE]}...{commit[Rev.HEAD]}"
    rev = commit.get(call.get("rev")) if "rev" in dict(call.args) else None
    pathspec = _pathspec(call.get("prefix")) if "prefix" in dict(call.args) else ()
    match call.tool:
        case "diff_stat":
            return _Plan((*_DIFF, "--stat=200", span))
        case "renames":
            return _Plan((*_DIFF, "-z", "--name-status", "--diff-filter=R", span))
        case "diff_file":
            view = f'tail -c +{call.get("offset") + 1} "$1"'
            return _Plan((*_DIFF, span, "--", *paths), view)
        case "list_files":
            ls_tree = ("ls-tree", "-r", "-z", "--name-only", str(rev), *pathspec)
            return _Plan(ls_tree, nul_records=True)
        case "read_file":
            view = f"sed -n '{call.get('start')},{call.get('end')}p' \"$1\""
            return _Plan(("cat-file", "blob", f"{rev}:{call.get('path')}"), view)
    mode = "-E" if call.get("regex") else "-F"
    grep = ("grep", "-z", "-n", "-I", "--no-color", "--max-count=50", mode)
    return _Plan((*grep, "-e", call.get("pattern"), str(rev), *pathspec))


def _pathspec(prefix: str) -> tuple[str, ...]:
    return ("--", prefix) if prefix else ()


def call_script(
    staged: Staged, call: Call, limits: ToolLimits, paths: tuple[str, ...] = ()
) -> str:
    """Runs one tool into files under the bridge root, then prints a
    header (git's exit status, the view's, the bytes and lines of the
    view, and the bytes of its capped part) and that capped part and
    stderr, each base64-encoded on its own line. The controller checks
    the decoded part against its byte count, so a failed encoding is an
    error, not an empty result."""
    plan = _plan(call, staged, paths)
    git = " ".join((quote(staged.git), "--git-dir=repo.git", *GIT_OPTIONS))
    argv = " ".join(quote(a) for a in plan.argv)
    z = " -z" if plan.nul_records else ""
    lines = f"head{z} -n {limits.max_lines} view | " if limits.max_lines else ""
    count = "tr -dc '\\000' < view | wc -c" if plan.nul_records else "wc -l < view"
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
            "v=$?",
            f"{lines}head -c {limits.max_bytes} {'' if lines else 'view'} > shown",
            f'echo "{HEADER} $s $v $(wc -c < view) $({count}) $(wc -c < shown)"',
            "base64 -w0 < shown; echo",
            f"head -c {STDERR_BYTES} err | base64 -w0; echo",
            "rm -f out err view shown",
        )
    )


def _page(call: Call, reply: _Reply) -> tuple[int, bytes]:
    """The shown bytes without a UTF-8 character split by the cut: an
    incomplete one at the end when the output was cut there, and the rest
    of one at the start of a `diff_file` page past offset 0 (it belongs to
    the page before). Returns how many leading bytes were dropped."""
    data = reply.content
    offset = call.get("offset") if call.tool == "diff_file" else 0
    skipped = _continuation_bytes(data) if offset else 0
    cut_end = len(data) < reply.total_bytes
    end = len(data) - (_incomplete_tail(data) if cut_end else 0)
    return skipped, data[skipped : max(end, skipped)]


def _continuation_bytes(data: bytes) -> int:
    head = data[:3]
    return len(head) - len(head.lstrip(_CONTINUATION))


def _incomplete_tail(data: bytes) -> int:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    decoder.decode(data, final=False)
    pending, _ = decoder.getstate()
    return len(pending)


class _LostOutputError(BoundaryError):
    """The tool ran, but its output did not arrive intact."""


def _rename_pairs(reply: _Reply) -> Mapping[str, tuple[str, str]]:
    """`R<score>\0<old>\0<new>\0` per rename (`--name-status -z`), keyed
    by both sides. A listing that failed or was cut raises, since a
    `diff_file` without it could show a rename as an add or a delete."""
    if reply.code != 0 or reply.shown_bytes < reply.total_bytes:
        raise BoundaryError(
            f"the PR's renames could not be listed in full (exit {reply.code})"
        )
    fields = reply.content.decode("utf-8", errors="replace").split("\0")
    pairs = [
        (old, new)
        for status, old, new in zip(
            fields[0::3], fields[1::3], fields[2::3], strict=False
        )
        if status.startswith("R")
    ]
    return MappingProxyType({path: pair for pair in pairs for path in pair})


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
    view_code: int
    total_bytes: int
    total_lines: int
    shown_bytes: int
    content: bytes
    stderr: bytes

    def problem(self) -> str | None:
        """Why the reply cannot be trusted as the tool's output, if it can't."""
        if self.view_code != 0:
            return f"the runner could not cut the output (exit {self.view_code})"
        if len(self.content) != self.shown_bytes:
            return (
                f"the runner's encoded output held {len(self.content)} of "
                f"{self.shown_bytes} bytes"
            )
        return None


def parse_reply(text: str) -> _Reply | None:
    """The last header the script printed and the base64 lines after it;
    None when there is none or it does not parse."""
    _, found, rest = text.rpartition(f"{HEADER} ")
    match = _REPLY.fullmatch(f"{HEADER} {rest}") if found else None
    if match is None:
        return None
    code, view_code, total, lines, shown = (int(match.group(i)) for i in range(1, 6))
    try:
        content, stderr = (
            base64.b64decode(match.group(i) or "", validate=True) for i in (6, 7)
        )
    except ValueError:
        return None
    return _Reply(code, view_code, total, lines, shown, content, stderr)


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
    call: Call,
    raw: bytes,
    commit: str,
    preexisting: Callable[[Rev, str], bool],
    paths: tuple[str, ...] = (),
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
        case "list_files":
            return _list_view(raw)
        case "diff_file":
            return _View(text, _diff_places(text.split("\n"), paths[0], paths[-1]))
    return _View(text, [])


def _list_view(raw: bytes) -> _View:
    """One name per line, exactly as `read_file` takes it back. A name it
    would refuse (a control character, a leading `-`, not UTF-8, ...) is
    shown as a JSON string and marked; a name cut short by the cap is
    dropped."""
    *names, last = raw.split(b"\0")
    return _View("\n".join(map(_listed, names)), [], last == b"")


def _listed(name: bytes) -> str:
    text = name.decode("utf-8", errors="replace")
    problem = path_problem(text) if text.encode() == name else "is not valid UTF-8"
    if problem is None:
        return text
    return f"{json.dumps(text)} (not readable by read_file: path {problem})"


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


def _diff_places(lines: Iterable[str], base_path: str, path: str) -> list[_Where]:
    """Head-side lines (in `path`) of added and context lines, base-side
    (in `base_path`, which differs for a rename) of removed ones; added
    lines are new in the PR, the rest pre-existing. Lines before the
    page's first hunk header are not located."""
    places: list[_Where] = []
    base = head = None
    for line in lines:
        hunk = _HUNK.match(line)
        if hunk:
            base, head = int(hunk.group(1)), int(hunk.group(2))
        place, base, head = _diff_line(line, (base_path, path), base, head, bool(hunk))
        places.append(place)
    return places


def _diff_line(
    line: str,
    sides: tuple[str, str],
    base: int | None,
    head: int | None,
    is_hunk: bool,
) -> tuple[_Where, int | None, int | None]:
    base_path, path = sides
    if is_hunk or base is None or head is None:
        return _Where(path, None, False), base, head
    kind = line[:1]
    if kind == "+":
        return _Where(path, head, False), base, head + 1
    if kind == "-":
        return _Where(base_path, base, True), base + 1, head
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
    session_limits: SessionLimits = DEFAULT_SESSION
    calls: list[CallRecord] = field(default_factory=list)
    _flagged: list[str] = field(default_factory=list, repr=False)
    _renames: Mapping[str, tuple[str, str]] | None = field(default=None, repr=False)

    def flagged(self) -> tuple[str, ...]:
        """Every secret value found so far, for `Redactor.sources`."""
        return tuple(self._flagged)

    def call(self, tool: Any, args: Any) -> BridgeResult:
        spent = self._spent()
        if spent is not None:
            return self._logged(self._refused(tool, Status.OVER_SESSION_LIMIT, spent))
        try:
            checked = validate(tool, args, self.staged.revs)
        except RejectedError as exc:
            return self._logged(self._refused(tool, Status.REJECTED, str(exc)))
        return self._logged(self._run(checked))

    def _spent(self) -> str | None:
        limits = self.session_limits
        if len(self.calls) >= limits.max_calls:
            return f"session-limit: all {limits.max_calls} calls of this session made"
        if self._output_left() <= 0:
            return (
                f"session-limit: all {limits.max_output_bytes} output bytes of this "
                "session shown"
            )
        return None

    def _output_left(self) -> int:
        used = sum(c.shown_bytes for c in self.calls)
        return self.session_limits.max_output_bytes - used

    def _refused(self, tool: Any, status: Status, reason: str) -> BridgeResult:
        """Names a known tool, or `UNKNOWN_TOOL`; the arguments are not shown."""
        name = tool if isinstance(tool, str) and tool in TOOLS else UNKNOWN_TOOL
        return BridgeResult(
            name, "", status, RepoText(""),
            self.redactor(reason, STDERR_CHARS), 0, 0, 0, False, 0.0,
        )  # fmt: skip

    def _run(self, call: Call) -> BridgeResult:
        tool_limits = self.limits[call.tool]
        limits = replace(
            tool_limits, max_bytes=min(tool_limits.max_bytes, self._output_left())
        )
        started = self.clock.monotonic()
        try:
            paths = self._diff_paths(call)
            reply = self._exec(call, limits, paths)
        except StreamTimeoutError as exc:
            return self._failed(call, Status.TIMED_OUT, str(exc), started)
        except _LostOutputError as exc:
            return self._failed(call, Status.FAILED, str(exc), started)
        except BoundaryError as exc:
            return self._failed(call, Status.UNAVAILABLE, str(exc), started)
        return self._result(call, reply, paths, self.clock.monotonic() - started)

    def _exec(
        self, call: Call, limits: ToolLimits, paths: tuple[str, ...] = ()
    ) -> _Reply:
        code, text = self.session.exec(
            f"bridge {call.tool}",
            call_script(self.staged, call, limits, paths),
            stage="bridge",
            budget_s=limits.timeout_s + EXEC_SLACK_S,
        )
        reply = parse_reply(text) if code == 0 else None
        if reply is None:
            raise BoundaryError(
                f"no bridge reply (exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
            )
        problem = reply.problem()
        if problem is not None:
            raise _LostOutputError(problem)
        return reply

    def _diff_paths(self, call: Call) -> tuple[str, ...]:
        """What `diff_file` diffs: its path, or both sides of the rename it
        is part of, so git pairs them instead of showing an add or a delete."""
        if call.tool != "diff_file":
            return ()
        path = call.get("path")
        return self._rename_map().get(path, (path,))

    def _rename_map(self) -> Mapping[str, tuple[str, str]]:
        """The PR's renames, listed once per bridge."""
        if self._renames is None:
            self._renames = _rename_pairs(
                self._exec(Call("renames", ()), RENAME_LIMITS)
            )
        return self._renames

    def _failed(
        self, call: Call, status: Status, detail: str, started: float
    ) -> BridgeResult:
        return BridgeResult(
            call.tool, call.args_json, status, RepoText(""),
            self.redactor(detail, STDERR_CHARS), 0, 0, 0, False,
            self.clock.monotonic() - started,
        )  # fmt: skip

    def _result(
        self, call: Call, reply: _Reply, paths: tuple[str, ...], seconds: float
    ) -> BridgeResult:
        limits = self.limits[call.tool]
        status = _status(call.tool, reply.code)
        commit = self.staged.commits[call.get("rev")] if call.tool == "grep" else ""
        skipped, content = _page(call, reply)
        view = _view(call, content, commit, self._preexisting, paths)
        scan = detect_secrets(view.text)
        shown = len(content)
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
            (
                call.get("offset") + skipped + shown
                if cut and call.tool == "diff_file"
                else None
            ),
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
    the content. The arguments are the validated ones, shown as JSON; a
    rejected call shows none, only its code and reason."""
    head = (
        f"{' '.join(filter(None, (result.tool, result.args)))}: {result.status.value}"
    )
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
    session_limits: SessionLimits = DEFAULT_SESSION,
    root: str = BRIDGE_ROOT,
    first_frame_s: float = FIRST_FRAME_BUDGET_S,
    unpack: UnpackLimits = DEFAULT_UNPACK,
) -> RunnerReport:
    """Stage `trees` on a fresh disposable runner and hand `body` the
    bridge; the runner is always destroyed. Trees over the upload cap or
    past `unpack` are refused before anything is created, and the runner
    holds `unpack` again as it extracts them."""
    telemetry = telemetry or Telemetry(clock)
    try:
        check_sizes(trees, unpack=unpack)
    except BoundaryError as exc:
        telemetry.record("upload", "size check", status=ERROR, error=str(exc))
        return RunnerReport(
            RunnerStatus.FAILED, CleanupStatus.NOT_CREATED, name, str(exc)
        )

    def session_body(session: Session) -> str:
        staged = stage(session, trees, root, unpack)
        telemetry.record(
            "bridge staging", "staged",
            {"revisions": len(staged.commits), "git": staged.git, "git_version": staged.git_version},
        )  # fmt: skip
        return body(
            Bridge(session, staged, redactor, clock, changed, limits, session_limits)
        )

    return run_session(
        api, ledger, session_body, name=name, deadline_s=deadline_s, clock=clock,
        telemetry=telemetry, first_frame_s=first_frame_s,
    )  # fmt: skip
