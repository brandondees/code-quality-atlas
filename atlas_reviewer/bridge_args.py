# SPDX-License-Identifier: MIT
"""The bridge's closed tool set and its argument rules (D31 gap 2, D39).

The model names a tool and gives typed arguments; `validate` turns them
into a `Call` or raises `RejectedError` before anything runs. Paths and
prefixes are repo-relative, NUL- and control-free, never start with `-`
or `/`, have no empty, `.` or `..` segment and are at most 512 bytes;
patterns are at most 256 bytes on one line; integers are range-checked;
the revision is one of the staged BASE, HEAD and DEFAULT, plus MUTANT
once a `mutate` call has produced a mutant tree (D80). A rejection
carries a fixed code and never echoes the tool name or a value the model
sent.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from atlas_reviewer.notes import quote_untrusted

MAX_PATH_BYTES = 512
MAX_PATTERN_BYTES = 256
MAX_READ_LINES = 400
MAX_DIFF_OFFSET = 64 * 1024 * 1024


class Rev(StrEnum):
    BASE = "BASE"
    HEAD = "HEAD"
    DEFAULT = "DEFAULT"
    MUTANT = "MUTANT"


class RejectedError(ValueError):
    """An invalid call: never run, and answered with a fixed `code` and a
    controller-written `detail` that quotes nothing the model sent beyond
    argument names, each through `quote_untrusted` and `QUOTED_CHARS`."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


INVALID = "invalid-argument"
QUOTED_CHARS = 64


@dataclass(frozen=True)
class Call:
    """A validated call: every argument present, typed and in range."""

    tool: str
    args: tuple[tuple[str, Any], ...]

    def get(self, name: str) -> Any:
        return dict(self.args)[name]

    @property
    def args_json(self) -> str:
        return json.dumps(dict(self.args), sort_keys=True, ensure_ascii=True)


Check = Callable[[Any, frozenset[Rev]], Any]
_REQUIRED = object()


@dataclass(frozen=True)
class _Arg:
    name: str
    check: Check
    default: Any = _REQUIRED


def _string(value: Any) -> str:
    if not isinstance(value, str):
        raise RejectedError(INVALID, "must be a string")
    return value


def _path(value: Any, _revs: frozenset[Rev]) -> str:
    text = _string(value)
    if len(text.encode("utf-8")) > MAX_PATH_BYTES:
        raise RejectedError(INVALID, f"is over {MAX_PATH_BYTES} bytes")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise RejectedError(INVALID, "contains a control character")
    if text.startswith(("-", "/")):
        raise RejectedError(INVALID, "may not start with '-' or '/'")
    if any(part in ("", ".", "..") for part in text.split("/")):
        raise RejectedError(INVALID, "has an empty, '.' or '..' segment")
    return text


def path_problem(text: str) -> str | None:
    """Why `read_file` would refuse `text` as its path, or None."""
    try:
        _path(text, frozenset())
    except RejectedError as exc:
        return exc.detail
    return None


def _prefix(value: Any, revs: frozenset[Rev]) -> str:
    return "" if value == "" else _path(value, revs)


def _pattern(value: Any, _revs: frozenset[Rev]) -> str:
    text = _string(value)
    if not text or len(text.encode("utf-8")) > MAX_PATTERN_BYTES:
        raise RejectedError(INVALID, f"must be 1 to {MAX_PATTERN_BYTES} bytes")
    if any(c in text for c in "\n\r\0"):
        raise RejectedError(INVALID, "may not contain a newline or NUL")
    return text


def _int_in(low: int, high: int) -> Check:
    def check(value: Any, _revs: frozenset[Rev]) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise RejectedError(INVALID, "must be an integer")
        if not low <= value <= high:
            raise RejectedError(INVALID, f"must be from {low} to {high}")
        return value

    return check


def _flag(value: Any, _revs: frozenset[Rev]) -> bool:
    if not isinstance(value, bool):
        raise RejectedError(INVALID, "must be true or false")
    return value


def _rev(value: Any, revs: frozenset[Rev]) -> Rev:
    if not isinstance(value, str) or value not in {r.value for r in revs}:
        names = ", ".join(sorted(r.value for r in revs))
        raise RejectedError(INVALID, f"must be one of the staged revisions: {names}")
    return Rev(value)


_LINE = _int_in(1, 10_000_000)

# The bound on the `command` name a `run_tests` call may send (S7, D88):
# the exact-match lookup against the run's allow-list needs no longer
# name than the parse can propose; the parse side (`repo_config`) bounds
# a proposal's canonical name by the same value, pinned equal by a test.
# A longer name matches nothing and is refused here, before any lookup.
MAX_COMMAND_CHARS = 600
# The probe file's cap (D80's probe-tool update): a focused probe test is
# a few dozen lines; 16 KiB is generous headroom over that and matches the
# run tools' output cap's order.
MAX_PROBE_CHARS = 16 * 1024
PROBE_ALLOWED_CONTROLS = frozenset("\n\t\r")


def _command(value: Any, _revs: frozenset[Rev]) -> str:
    text = _string(value)
    if len(text.encode("utf-8")) > MAX_COMMAND_CHARS:
        raise RejectedError(INVALID, f"is over {MAX_COMMAND_CHARS} characters")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise RejectedError(INVALID, "contains a control character")
    return text


# The closed set of single-operator mutants `mutate` applies (D80): one
# named statement, one operator. `negate-condition` wraps the condition of
# the `if`, `while` or conditional expression at the named line in `not
# (...)`; `remove-guard` replaces the body of the `if` at the named line
# with `pass`, so the guarded action no longer happens. The 2026-11-26
# operator slice (D80's update) adds the three the real defects need:
# `drop-operand` keeps one operand of the `and`/`or` at the named line and
# drops the rest -- the shape of an unpinned guard conjunct, which neither
# older operator expresses (negating or removing the whole guard is killed
# by tests the conjunct drop survives) -- so it takes the 1-based
# `operand` argument naming the operand to keep; `break-continue` swaps a
# `break` for a `continue` or the other way round, the shape of a loop
# that stops scanning where it should keep going; `flip-compare` negates
# the first comparison operator of the comparison at the named line
# (`==`/`!=`, `<`/`>=`, `>`/`<=`, `<=`/`>`, `>=`/`<`, `in`/`not in`,
# `is`/`is not`). Anything else is a rejected call, and an operator that
# does not apply to the named line is a refused call at run time (D80's
# update: a mis-aimed mutant is the model's error to re-aim, never an
# inconclusive verdict and never a survived one).
MUTANT_OPERATORS = (
    "negate-condition",
    "remove-guard",
    "drop-operand",
    "break-continue",
    "flip-compare",
)


def _operand_index(value: Any, _revs: frozenset[Rev]) -> int:
    """`drop-operand`'s 1-based operand to keep. Only `drop-operand` takes
    it; `validate` enforces the pairing, so this checks the shape alone."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise RejectedError(INVALID, "must be an integer")
    if not 1 <= value <= 64:
        raise RejectedError(INVALID, "is an operand index out of range")
    return value


def _probe_content(value: Any, _revs: frozenset[Rev]) -> str:
    """The probe file's source, as the model wrote it: UTF-8 text within
    the size cap, no control characters beyond newline, tab and carriage
    return. The content is code the guard runs -- the same trust level as
    the PR's own tests -- and it is never written back: it dies with the
    disposable copy it ran in."""
    text = _string(value)
    if len(text.encode("utf-8")) > MAX_PROBE_CHARS:
        raise RejectedError(INVALID, f"is over {MAX_PROBE_CHARS} bytes")
    if any(
        ord(c) < 0x20 and c not in PROBE_ALLOWED_CONTROLS or ord(c) == 0x7F
        for c in text
    ):
        raise RejectedError(INVALID, "contains a control character")
    return text


_PROBE_SELECTOR = re.compile(r"::[A-Za-z0-9_.:\[\]/-]{1,200}")


def _probe_selector(value: Any, _revs: frozenset[Rev]) -> str:
    """`run_probe`'s optional selection: a `::node-id` suffix appended to
    the probe file's own path -- the model never names the file, whose
    name is the controller's. Empty runs the whole probe file."""
    text = _string(value)
    if text == "":
        return ""
    if not _PROBE_SELECTOR.fullmatch(text):
        raise RejectedError(
            INVALID, "must be a ::node-id suffix (for example ::test_x)"
        )
    return text


def _operator(value: Any, _revs: frozenset[Rev]) -> str:
    if not isinstance(value, str) or value not in MUTANT_OPERATORS:
        names = ", ".join(MUTANT_OPERATORS)
        raise RejectedError(INVALID, f"must be one of the mutant operators: {names}")
    return value


TOOLS: Mapping[str, tuple[_Arg, ...]] = MappingProxyType(
    {
        "diff_stat": (),
        "diff_file": (_Arg("path", _path), _Arg("offset", _int_in(0, MAX_DIFF_OFFSET), 0)),
        "list_files": (_Arg("rev", _rev, "HEAD"), _Arg("prefix", _prefix, "")),
        "read_file": (
            _Arg("rev", _rev, "HEAD"),
            _Arg("path", _path),
            _Arg("start", _LINE, 1),
            _Arg("end", _LINE, None),
        ),
        "grep": (
            _Arg("pattern", _pattern),
            _Arg("rev", _rev, "HEAD"),
            _Arg("prefix", _prefix, ""),
            _Arg("regex", _flag, False),
        ),
        # D80: the model names a test file or selector and a mutant spec;
        # the bridge builds the argv. `path` is a selector passed to
        # pytest as one positional argument (a file, a directory or a
        # `file.py::node_id`), empty for the whole suite; `mutate`'s
        # `tests` selects what its baseline and mutated runs execute.
        # S7 (D88): `command` names one of the run's allow-list
        # proposals -- the exact string the repo's default-branch
        # `REVIEW.md` proposed -- and is the only thing the model names
        # about a declared command: the argv comes from the proposal's
        # own validated tokens, the model's value is an exact-match
        # lookup and never a shell string. It is optional, it combines
        # with no selector, and `mutate` never takes it (its verdict
        # needs pytest's own summary line).
        "run_tests": (_Arg("path", _prefix, ""), _Arg("command", _command, "")),
        # The probe tool (D80's 2026-11-26 update, Brandon's decision): the
        # model writes one throwaway test file into the disposable copy and
        # the bridge runs it under the same sandbox as run_tests -- the
        # no-root guard, the same clock, output caps and deny-all egress.
        # The file is never written back and dies with the copy; its name
        # is the controller's (a fixed `test_atlas_probe_` prefix the model
        # never needs), so `selector` is only a `::node-id` suffix appended
        # to that path -- `::test_x`, or `::TestX::test_y` -- and empty runs
        # the whole probe file.
        "run_probe": (_Arg("content", _probe_content), _Arg("selector", _probe_selector, "")),
        "mutate": (
            _Arg("path", _path),
            _Arg("line", _LINE),
            _Arg("operator", _operator),
            _Arg("operand", _operand_index, None),
            _Arg("tests", _prefix, ""),
        ),
    }
)  # fmt: skip


def arg_names(tool: str) -> tuple[str, ...]:
    return tuple(a.name for a in TOOLS[tool])


def required_args(tool: str) -> tuple[str, ...]:
    return tuple(a.name for a in TOOLS[tool] if a.default is _REQUIRED)


def validate(tool: Any, args: Any, revs: frozenset[Rev]) -> Call:
    """Raises `RejectedError` with a fixed code for the first problem. The
    tool name and argument values the model sent are never echoed; unknown
    argument names are, quoted and cut to `QUOTED_CHARS`."""
    spec = TOOLS.get(tool) if isinstance(tool, str) else None
    if spec is None:
        raise RejectedError("unknown-tool", f"the tools are {', '.join(TOOLS)}")
    if not isinstance(args, Mapping):
        raise RejectedError("bad-arguments", "arguments must be an object")
    unknown = sorted(str(k) for k in args if k not in {a.name for a in spec})
    if unknown:
        raise RejectedError(
            "unknown-argument",
            quote_untrusted(", ".join(unknown), QUOTED_CHARS, scrub=str),
        )
    values = tuple((a.name, _value(a, args, revs)) for a in spec)
    call = (
        _read_range(Call(tool, values)) if tool == "read_file" else Call(tool, values)
    )
    return _mutate_operand_shape(_run_tools_shape(call))


def _mutate_operand_shape(call: Call) -> Call:
    """`drop-operand` names the operand it keeps; no other operator takes
    one (D80's 2026-11-26 update). A missing index is a rejected call
    before anything runs, and so is an index on an operator that has no
    operands to drop."""
    if call.tool != "mutate":
        return call
    operator = call.get("operator")
    operand = call.get("operand")
    if operator == "drop-operand":
        if operand is None:
            raise RejectedError(INVALID, "drop-operand names the operand it keeps")
        return call
    if operand is not None:
        raise RejectedError(INVALID, "only drop-operand takes an operand index")
    return call


def _run_tools_shape(call: Call) -> Call:
    """The execution tools' cross-argument rule (S7, D88): a declared
    command and a test selector cannot combine -- a proposal runs as it
    was proposed, its argv the bridge's own, and appending a selector
    would be argv the proposal never asked for. `mutate` never carries a
    command: its verdict needs pytest's own summary line, so the argument
    is not in its schema and an unknown-argument refusal already covers
    it."""
    if call.tool == "run_tests" and call.get("command") and call.get("path"):
        raise RejectedError(
            "conflicting-argument",
            "a declared command and a test selector cannot combine; a "
            "command runs as it was proposed",
        )
    return call


def _value(arg: _Arg, args: Mapping[str, Any], revs: frozenset[Rev]) -> Any:
    if arg.name not in args and arg.default is _REQUIRED:
        raise RejectedError("missing-argument", arg.name)
    if arg.name not in args and arg.default is None:
        return None
    try:
        return arg.check(args.get(arg.name, arg.default), revs)
    except RejectedError as exc:
        raise RejectedError(exc.code, f"{arg.name} {exc.detail}") from None


def _read_range(call: Call) -> Call:
    start = call.get("start")
    end = call.get("end") or start + MAX_READ_LINES - 1
    if end < start or end - start >= MAX_READ_LINES:
        raise RejectedError(
            INVALID,
            f"end must be from start to start + {MAX_READ_LINES - 1} "
            f"({MAX_READ_LINES} lines at most)",
        )
    return Call(call.tool, tuple((k, end if k == "end" else v) for k, v in call.args))
