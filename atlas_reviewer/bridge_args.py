# SPDX-License-Identifier: MIT
"""The bridge's closed tool set and its argument rules (D31 gap 2, D39).

The model names a tool and gives typed arguments; `validate` turns them
into a `Call` or raises `RejectedError` before anything runs. Paths and
prefixes are repo-relative, NUL- and control-free, never start with `-`
or `/`, have no empty, `.` or `..` segment and are at most 512 bytes;
patterns are at most 256 bytes on one line; integers are range-checked;
the revision is one of the staged BASE, HEAD and DEFAULT. A rejection
carries a fixed code and never echoes the tool name or a value the model
sent.
"""

from __future__ import annotations

import json
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
    }
)  # fmt: skip


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
    return (
        _read_range(Call(tool, values)) if tool == "read_file" else Call(tool, values)
    )


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
