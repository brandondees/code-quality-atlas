# SPDX-License-Identifier: MIT
"""The parity key: five graded protocol Minors.

A key file is one pull request's verified protocol findings. Adding a
protocol-reviewed pull request is another JSON file in the same directory;
the loader reads every file. A record is a path and a line span, or the
pull request body and the lines a citation has to quote. The grade that
compares a verified finding with those spans is a later layer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from atlas_reviewer.eval_harness import EvalFormatError

KEY_DIR = Path(__file__).resolve().parent / "fixtures" / "parity-key"
BODY = "pull_request.body"
_NEEDS = frozenset({"ci", "read", "run_tests", "mutate"})
_SEVERITIES = frozenset({"blocker", "major", "minor", "nit"})
_FILE_KEYS = frozenset({"pr", "reviewed_commit", "source", "findings"})
_FINDING_KEYS = frozenset(
    {
        "id",
        "severity",
        "summary",
        "source",
        "lenses",
        "needs",
        "spans",
        "encloses",
        "citations",
    }
)
_SPAN_KEYS = frozenset({"path", "line", "end_line"})
_COMMIT = re.compile(r"[0-9a-f]{40}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class Span:
    """One path and, for a file, the inclusive line span."""

    path: str
    line_start: int | None = None
    line_end: int | None = None


@dataclass(frozen=True)
class KeyFinding:
    """One protocol finding the parity gate has to see again."""

    id: str
    pr: int
    reviewed_commit: str
    source: str
    severity: str
    summary: str
    spans: tuple[Span, ...]
    encloses: tuple[Span, ...]
    citations: tuple[str, ...]
    lenses: tuple[str, ...]
    needs: tuple[str, ...]


def load_key(path: Path) -> tuple[KeyFinding, ...]:
    """Every ``*.json`` file in ``path``, in file name order.

    A duplicate id, a key the schema does not name, a code span with no
    line, or a body record with no citation is refused. An empty directory
    is refused.
    """
    if not path.is_dir():
        raise EvalFormatError(f"parity key is not a directory: {path}")
    files = sorted(item for item in path.glob("*.json") if item.is_file())
    if not files:
        raise EvalFormatError(f"parity key has no JSON files: {path}")
    findings: list[KeyFinding] = []
    seen: set[str] = set()
    for file in files:
        for finding in _load_file(file):
            if finding.id in seen:
                raise EvalFormatError(f"{file.name} repeats finding id {finding.id}")
            seen.add(finding.id)
            findings.append(finding)
    return tuple(findings)


def _load_file(path: Path) -> tuple[KeyFinding, ...]:
    body = _object(_read_json(path), path.name)
    _unknown(body, _FILE_KEYS, path.name)
    pr = _positive(body.get("pr"), f"{path.name} pr")
    commit = _commit(body.get("reviewed_commit"), path.name)
    _text(body.get("source"), f"{path.name} source")
    raw = body.get("findings")
    if not isinstance(raw, list) or not raw:
        raise EvalFormatError(f"{path.name} needs a non-empty findings list")
    return tuple(
        _finding(item, f"{path.name} findings[{index}]", pr, commit)
        for index, item in enumerate(raw)
    )


def _finding(value: object, name: str, pr: int, commit: str) -> KeyFinding:
    body = _object(value, name)
    _unknown(body, _FINDING_KEYS, name)
    severity = body.get("severity")
    if not isinstance(severity, str) or severity not in _SEVERITIES:
        raise EvalFormatError(f"{name} severity must be blocker, major, minor or nit")
    spans = _spans(body.get("spans"), f"{name} spans", allow_body=True)
    encloses = _spans(body.get("encloses"), f"{name} encloses", allow_body=False)
    citations = _strings(body.get("citations"), f"{name} citations")
    _spans_cover(name, spans, encloses, citations)
    return KeyFinding(
        id=_ident(body.get("id"), name),
        pr=pr,
        reviewed_commit=commit,
        source=_text(body.get("source"), f"{name} source"),
        severity=severity,
        summary=_text(body.get("summary"), f"{name} summary"),
        spans=spans,
        encloses=encloses,
        citations=citations,
        lenses=_lens_names(body.get("lenses"), name),
        needs=_needs(body.get("needs"), name),
    )


def _spans(value: object, name: str, *, allow_body: bool) -> tuple[Span, ...]:
    if not isinstance(value, list):
        raise EvalFormatError(f"{name} must be a list")
    return tuple(
        _span(item, f"{name}[{index}]", allow_body) for index, item in enumerate(value)
    )


def _span(value: object, name: str, allow_body: bool) -> Span:
    body = _object(value, name)
    _unknown(body, _SPAN_KEYS, name)
    path = _text(body.get("path"), f"{name} path")
    line = _optional_line(body.get("line"), f"{name} line")
    end = _optional_line(body.get("end_line"), f"{name} end_line")
    if path == BODY:
        if not allow_body:
            raise EvalFormatError(f"{name} encloses a file, not the pull request body")
        if line is not None or end is not None:
            raise EvalFormatError(f"{name} body span has no line")
        return Span(path)
    if line is None or end is None or end < line:
        raise EvalFormatError(f"{name} end_line must be at or after line")
    return Span(path, line, end)


def _spans_cover(
    name: str,
    spans: tuple[Span, ...],
    encloses: tuple[Span, ...],
    citations: tuple[str, ...],
) -> None:
    if not spans:
        raise EvalFormatError(f"{name} needs a span")
    body = [span for span in spans if span.path == BODY]
    code = [span for span in spans if span.path != BODY]
    if body and code:
        raise EvalFormatError(f"{name} is a body record or a file record")
    if body:
        if len(body) != 1 or citations == ():
            raise EvalFormatError(f"{name} body record needs one span and a citation")
        if encloses:
            raise EvalFormatError(f"{name} body record has no enclosing span")
        return
    if citations:
        raise EvalFormatError(f"{name} file record has no citation")
    for span in code:
        if not any(_covers(outer, span) for outer in encloses):
            raise EvalFormatError(f"{name} span is outside its enclosing function")
    for outer in encloses:
        if not any(_covers(outer, span) for span in code):
            raise EvalFormatError(f"{name} enclosing span covers no defect")


def _covers(outer: Span, inner: Span) -> bool:
    # A file span always has both lines. A body span never reaches here.
    return outer.path == inner.path and (
        cast(int, outer.line_start) <= cast(int, inner.line_start)
        and cast(int, outer.line_end) >= cast(int, inner.line_end)
    )


def _lens_names(value: object, name: str) -> tuple[str, ...]:
    lenses = _strings(value, f"{name} lenses")
    if not lenses:
        raise EvalFormatError(f"{name} needs a lens")
    return lenses


def _needs(value: object, name: str) -> tuple[str, ...]:
    needs = _strings(value, f"{name} needs")
    if not needs or any(item not in _NEEDS for item in needs):
        raise EvalFormatError(f"{name} needs must list ci, read, run_tests or mutate")
    return needs


def _object(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise EvalFormatError(f"{name} is not an object")
    return value


def _unknown(body: Mapping[str, object], allowed: frozenset[str], name: str) -> None:
    extra = set(body) - allowed
    if extra:
        raise EvalFormatError(f"{name} has an unknown key: {min(extra)}")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvalFormatError(f"{name} must be a non-empty string")
    return value


def _ident(value: object, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise EvalFormatError(
            f"{name} id must be letters, digits, dots, dashes or underscores"
        )
    return value


def _commit(value: object, name: str) -> str:
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise EvalFormatError(f"{name} reviewed_commit must be 40 lowercase hex")
    return value


def _positive(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EvalFormatError(f"{name} must be a positive integer")
    return value


def _optional_line(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _positive(value, name)


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise EvalFormatError(f"{name} must be a list of non-empty strings")
    return tuple(value)


def _read_json(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise EvalFormatError(f"{path.name} cannot be read: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvalFormatError(f"{path.name} is not JSON: {exc}") from exc
