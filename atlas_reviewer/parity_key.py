# SPDX-License-Identifier: MIT
"""The 7-Minor parity key.

A key file is one pull request's verified protocol findings. Adding a
protocol-reviewed pull request is another JSON file in the same directory;
the loader reads every file. Grading a candidate list against the key is a
later step. This module only loads the records and refuses a record that
does not match the schema.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from atlas_reviewer.eval_harness import EvalFinding, EvalFormatError

KEY_DIR = Path(__file__).resolve().parent / "fixtures" / "parity-key"
_MATCHES = frozenset({"place", "markers", "unscored"})
_NEEDS = frozenset({"ci", "read", "run_tests", "mutate"})
_SEVERITIES = frozenset({"blocker", "major", "minor", "nit"})
_FILE_KEYS = frozenset({"pr", "reviewed_commit", "source", "findings"})
_FINDING_KEYS = frozenset(
    {
        "id",
        "severity",
        "path",
        "summary",
        "lenses",
        "markers",
        "needs",
        "match",
        "line",
        "end_line",
    }
)
_COMMIT = re.compile(r"[0-9a-f]{40}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class KeyFinding:
    """One protocol finding the parity gate has to see again."""

    id: str
    pr: int
    reviewed_commit: str
    source: str
    severity: str
    path: str
    summary: str
    match: str
    line_start: int | None = None
    line_end: int | None = None
    lenses: tuple[str, ...] = ()
    markers: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()

    def as_eval(self) -> EvalFinding:
        """The place record as a harness finding. Markers and unscored records raise."""
        if self.match != "place":
            raise EvalFormatError(
                f"{self.id} is a {self.match} record and has no place to grade"
            )
        return EvalFinding(
            self.severity,
            self.path,
            self.summary,
            self.line_start,
            self.line_end,
            self.lenses,
        )


def load_key(path: Path) -> tuple[KeyFinding, ...]:
    """Every ``*.json`` file in ``path``, in file name order.

    A duplicate id, a key the schema does not name, or a place finding
    with no line is refused. An empty directory is refused.
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
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise EvalFormatError(f"{path.name} cannot be read: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvalFormatError(f"{path.name} is not JSON: {exc}") from exc
    body = _object(payload, path.name)
    _unknown(body, _FILE_KEYS, path.name)
    pr = _positive(body.get("pr"), f"{path.name} pr")
    commit = _commit(body.get("reviewed_commit"), path.name)
    source = _text(body.get("source"), f"{path.name} source")
    raw = body.get("findings")
    if not isinstance(raw, list) or not raw:
        raise EvalFormatError(f"{path.name} needs a non-empty findings list")
    return tuple(
        _finding(item, f"{path.name} findings[{index}]", pr, commit, source)
        for index, item in enumerate(raw)
    )


def _finding(value: object, name: str, pr: int, commit: str, source: str) -> KeyFinding:
    body = _object(value, name)
    _unknown(body, _FINDING_KEYS, name)
    match = body.get("match")
    if match not in _MATCHES:
        raise EvalFormatError(f"{name} match must be place, markers or unscored")
    severity = body.get("severity")
    if not isinstance(severity, str) or severity not in _SEVERITIES:
        raise EvalFormatError(f"{name} severity must be blocker, major, minor or nit")
    line = _optional_line(body.get("line"), f"{name} line")
    end = _optional_line(body.get("end_line"), f"{name} end_line")
    if match == "place" and line is None:
        raise EvalFormatError(f"{name} place match needs a line")
    if end is not None and (line is None or end < line):
        raise EvalFormatError(f"{name} end_line must be at or after line")
    markers = _strings(body.get("markers"), f"{name} markers")
    if match == "markers" and not markers:
        raise EvalFormatError(f"{name} marker match needs a marker")
    needs = _strings(body.get("needs"), f"{name} needs")
    if not needs or any(item not in _NEEDS for item in needs):
        raise EvalFormatError(f"{name} needs must list ci, read, run_tests or mutate")
    return KeyFinding(
        id=_ident(body.get("id"), name),
        pr=pr,
        reviewed_commit=commit,
        source=source,
        severity=severity,
        path=_text(body.get("path"), f"{name} path"),
        summary=_text(body.get("summary"), f"{name} summary"),
        match=match,
        line_start=line,
        line_end=end,
        lenses=_strings(body.get("lenses"), f"{name} lenses"),
        markers=markers,
        needs=needs,
    )


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
        raise EvalFormatError(
            f"{name} reviewed_commit must be 40 lowercase hex characters"
        )
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
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise EvalFormatError(f"{name} must be a list of non-empty strings")
    return tuple(value)
