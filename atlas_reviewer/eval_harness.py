# SPDX-License-Identifier: MIT
"""Offline scores of a review against a Claude Code protocol reference.

A reference example is one Phoenix dataset row: ``input`` (which pull
request and round), ``output`` (the reference verdict and findings), and
``metadata``. Phoenix can import that shape. This module does not upload
anything and does not call Phoenix.

The cloud reviewer's round reports on this repo are GitHub review bodies
that start with ``## Round N`` and carry ``<!-- atlas-review round:N ... -->``,
plus inline comments whose first line is ``**Severity · lens**``.
``protocol_review`` reads that shape. The checked-in reference files under
``fixtures/eval-references/`` were built from those reviews. A directory of
reference rows alone is not a scored run: scoring needs a ``candidate``
object next to the reference, which the hand-built fixture has and the
reference set does not.

Matching is severity, path, and overlapping line span. A finding with no
line matches only another finding of the same severity and path that also
has no line. Each candidate finding is used at most once. Major+ is
``blocker`` and ``major``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas_reviewer.redact import redact

MAJOR_OR_ABOVE = frozenset({"blocker", "major"})
_VERDICTS = frozenset({"APPROVE", "COMMENT", "REQUEST_CHANGES"})
_SEVERITIES = frozenset({"blocker", "major", "minor", "nit"})
_ROUND = re.compile(r"^## Round\s+(\d+)\s+[—–-]\s+(.*)\s*$", re.MULTILINE)
_MARKER = re.compile(r"<!--\s*atlas-review round:(\d+)\b")
_HEADING = re.compile(r"^\*\*(Blocker|Major|Minor|Nit)\s*·\s*([^*\n]+?)\*\*")
_LENS = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SUMMARY_CHARS = 240
_CODERABBIT = "coderabbit-ai-generated"


class EvalFormatError(ValueError):
    """A fixture is not a reference row or a scored pair."""


@dataclass(frozen=True)
class EvalFinding:
    severity: str
    path: str
    summary: str
    line_start: int | None = None
    line_end: int | None = None
    lenses: tuple[str, ...] = ()

    def overlaps(self, other: EvalFinding) -> bool:
        if self.severity != other.severity or self.path != other.path:
            return False
        if self.line_start is None or other.line_start is None:
            return self.line_start is None and other.line_start is None
        return self.line_start <= (other.line_end or other.line_start) and (
            other.line_start <= (self.line_end or self.line_start)
        )


@dataclass(frozen=True)
class EvalReview:
    verdict: str
    findings: tuple[EvalFinding, ...]


@dataclass(frozen=True)
class CandidateReview(EvalReview):
    """The fields the parity gate reads off a recorded candidate.

    ``changed_files`` is the diff's path list. ``outside_diff_reads`` is
    every path the candidate read at head that is not in that list.
    """

    coverage_complete: bool | None = None
    unreviewed_files: int | None = None
    changed_files: tuple[str, ...] | None = None
    lenses_run: tuple[str, ...] | None = None
    outside_diff_reads: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Score:
    matched: int
    missed_major_or_above: int
    false_positives: int
    false_positives_major_or_above: int
    verdict_agrees: bool

    def as_json(self) -> dict[str, int | bool]:
        return {
            "matched": self.matched,
            "missed_major_or_above": self.missed_major_or_above,
            "false_positives": self.false_positives,
            "false_positives_major_or_above": self.false_positives_major_or_above,
            "verdict_agrees": self.verdict_agrees,
        }


def score(reference: EvalReview, candidate: EvalReview) -> Score:
    """Match findings one-to-one. Order is the reference's order."""
    used: set[int] = set()
    matched = 0
    missed_major = 0
    for finding in reference.findings:
        slot = next(
            (
                i
                for i, other in enumerate(candidate.findings)
                if i not in used and finding.overlaps(other)
            ),
            None,
        )
        if slot is None:
            if finding.severity in MAJOR_OR_ABOVE:
                missed_major += 1
            continue
        used.add(slot)
        matched += 1
    unmatched = [f for i, f in enumerate(candidate.findings) if i not in used]
    return Score(
        matched,
        missed_major,
        len(unmatched),
        sum(1 for f in unmatched if f.severity in MAJOR_OR_ABOVE),
        reference.verdict == candidate.verdict,
    )


def gate_failures(
    reference: EvalReview, candidate: CandidateReview, scored: Score
) -> tuple[str, ...]:
    """Why this pair does not yet allow APPROVE. Empty means it passes.

    The finding bar is no missed Major+ finding, no unmatched candidate
    finding at Major or above, and the same verdict. The coverage bar is
    the candidate's own record: complete coverage, no unreviewed files,
    every lens the reference named was run, and every reference path
    outside the diff was read at head.
    """
    failures: list[str] = []
    if scored.missed_major_or_above:
        failures.append(
            f"missed {scored.missed_major_or_above} Major+ reference finding(s)"
        )
    if scored.false_positives_major_or_above:
        failures.append(
            f"{scored.false_positives_major_or_above} unmatched Major+ "
            "candidate finding(s)"
        )
    if not scored.verdict_agrees:
        failures.append(
            f"verdict {candidate.verdict} disagrees with {reference.verdict}"
        )
    if candidate.coverage_complete is not True:
        failures.append("coverage_complete is not true")
    if candidate.unreviewed_files not in (0,):
        failures.append("unreviewed_files is not 0")
    if candidate.lenses_run is None or candidate.changed_files is None:
        failures.append("candidate does not record lenses_run and changed_files")
        return tuple(failures)
    if candidate.outside_diff_reads is None:
        failures.append("candidate does not record outside_diff_reads")
        return tuple(failures)
    ran = set(candidate.lenses_run)
    changed = set(candidate.changed_files)
    read_outside = set(candidate.outside_diff_reads)
    for finding in reference.findings:
        missing = [name for name in finding.lenses if name not in ran]
        if missing:
            failures.append(f"lens {missing[0]} named by the reference was not run")
        if (
            finding.path
            and finding.path not in changed
            and (finding.path not in read_outside)
        ):
            failures.append(
                f"reference path {finding.path} is outside the diff and was not read"
            )
    return tuple(dict.fromkeys(failures))


def protocol_review(
    body: str, comments: Sequence[Mapping[str, Any]]
) -> tuple[int, EvalReview] | None:
    """One protocol round, or None when ``body`` is not one.

    Inline comments are findings only when their body opens with the
    severity heading. A CodeRabbit comment is not a protocol finding.
    The summary is redacted and cut to 240 characters.
    """
    heading = _ROUND.search(body or "")
    marker = _MARKER.search(body or "")
    if heading is not None:
        number = int(heading.group(1))
        title = heading.group(2)
    elif marker is not None:
        number = int(marker.group(1))
        title = ""
    else:
        return None
    findings = tuple(
        parsed
        for comment in comments
        if (parsed := _comment_finding(comment)) is not None
    )
    return number, EvalReview(_verdict(title), findings)


def _verdict(title: str) -> str:
    if re.search(r"\bAPPROVE\b", title):
        return "APPROVE"
    if re.search(r"REQUEST_CHANGES|request changes", title, re.IGNORECASE):
        return "REQUEST_CHANGES"
    return "COMMENT"


def _comment_finding(comment: Mapping[str, Any]) -> EvalFinding | None:
    text = comment.get("body")
    if not isinstance(text, str) or _CODERABBIT in text:
        return None
    first, _, rest = text.lstrip().partition("\n")
    heading = _HEADING.match(first)
    if heading is None:
        return None
    path = comment.get("path")
    if not isinstance(path, str) or not path:
        return None
    line = _line(comment)
    lenses = tuple(
        part
        for part in (
            piece.strip() for piece in heading.group(2).split("(")[0].split("/")
        )
        if _LENS.fullmatch(part)
    )
    summary = redact(rest.strip()).text
    summary = re.sub(r"\s+", " ", summary)[:_SUMMARY_CHARS]
    return EvalFinding(
        heading.group(1).lower(),
        path,
        summary,
        line,
        line,
        lenses,
    )


def _line(comment: Mapping[str, Any]) -> int | None:
    for key in ("line", "original_line"):
        value = comment.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def example_json(
    *,
    repo: str,
    pr: int,
    head_sha: str,
    round_number: int,
    review: EvalReview,
    review_url: str = "",
) -> dict[str, Any]:
    """One Phoenix dataset example. ``output`` is the reference review."""
    return {
        "input": {
            "repo": repo,
            "pr": pr,
            "head_sha": head_sha,
            "round": round_number,
        },
        "output": _review_json(review),
        "metadata": {
            "source": "claude-code-protocol",
            "review_url": review_url,
        },
    }


def _review_json(review: EvalReview) -> dict[str, Any]:
    return {
        "verdict": review.verdict,
        "findings": [_finding_json(f) for f in review.findings],
    }


def _finding_json(finding: EvalFinding) -> dict[str, Any]:
    row: dict[str, Any] = {
        "severity": finding.severity,
        "path": finding.path,
        "summary": finding.summary,
        "lenses": list(finding.lenses),
    }
    if finding.line_start is not None:
        row["line"] = finding.line_start
        if finding.line_end != finding.line_start:
            row["end_line"] = finding.line_end
    return row


def load_directory(path: Path) -> dict[str, Any]:
    """Score every JSON file in ``path``.

    A file with ``candidate`` is a pair and is scored. A file with only
    ``output`` is a reference row and is counted, not scored. ``gate_pass``
    is true only when at least one pair was scored and every pair's
    ``gate_failures`` is empty.
    """
    files = sorted(p for p in path.glob("*.json") if p.is_file())
    if not files:
        raise EvalFormatError(f"no JSON fixtures in {path}")
    results: list[dict[str, Any]] = []
    examples = 0
    for file in files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvalFormatError(f"{file.name} is not JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise EvalFormatError(f"{file.name} is not an object")
        examples += 1
        if "candidate" not in payload:
            continue
        results.append(_score_file(file.name, payload))
    failures = [item for row in results for item in row["gate_failures"]]
    totals = _totals(results)
    return {
        "examples": examples,
        "scored": len(results),
        "gate_pass": bool(results) and not failures,
        "gate_failures": failures,
        "totals": totals,
        "results": results,
    }


def _score_file(name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    reference = _parse_review(payload.get("reference") or payload.get("output"), name)
    candidate = _parse_candidate(payload.get("candidate"), name)
    scored = score(reference, candidate)
    failures = [
        f"{name}: {item}" for item in gate_failures(reference, candidate, scored)
    ]
    return {
        "fixture": name,
        "score": scored.as_json(),
        "gate_failures": failures,
    }


def _totals(results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    keys = (
        "matched",
        "missed_major_or_above",
        "false_positives",
        "false_positives_major_or_above",
    )
    totals = {key: 0 for key in keys}
    totals["verdict_agreements"] = 0
    for row in results:
        score_row = row["score"]
        for key in keys:
            totals[key] += int(score_row[key])
        totals["verdict_agreements"] += int(bool(score_row["verdict_agrees"]))
    return totals


def _parse_review(value: object, name: str) -> EvalReview:
    if not isinstance(value, dict):
        raise EvalFormatError(f"{name} has no reference review object")
    verdict = value.get("verdict")
    if verdict not in _VERDICTS:
        raise EvalFormatError(f"{name} verdict must be one of {sorted(_VERDICTS)}")
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise EvalFormatError(f"{name} findings must be a list")
    return EvalReview(verdict, tuple(_parse_finding(item, name) for item in findings))


def _parse_candidate(value: object, name: str) -> CandidateReview:
    review = _parse_review(value, name)
    assert isinstance(value, dict)
    return CandidateReview(
        review.verdict,
        review.findings,
        _opt_bool(value.get("coverage_complete"), name, "coverage_complete"),
        _opt_int(value.get("unreviewed_files"), name, "unreviewed_files"),
        _opt_strs(value.get("changed_files"), name, "changed_files"),
        _opt_strs(value.get("lenses_run"), name, "lenses_run"),
        _opt_strs(value.get("outside_diff_reads"), name, "outside_diff_reads"),
    )


def _parse_finding(value: object, name: str) -> EvalFinding:
    if not isinstance(value, dict):
        raise EvalFormatError(f"{name} has a finding that is not an object")
    severity = value.get("severity")
    path = value.get("path")
    if not isinstance(severity, str) or severity.lower() not in _SEVERITIES:
        raise EvalFormatError(f"{name} finding severity is not blocker|major|minor|nit")
    if not isinstance(path, str) or not path:
        raise EvalFormatError(f"{name} finding needs a path")
    start = _opt_int(value.get("line"), name, "line")
    end = _opt_int(value.get("end_line"), name, "end_line")
    if start is None:
        end = None
    elif end is None:
        end = start
    lenses = value.get("lenses") or []
    if not isinstance(lenses, list) or not all(
        isinstance(item, str) for item in lenses
    ):
        raise EvalFormatError(f"{name} finding lenses must be a list of strings")
    summary = value.get("summary")
    return EvalFinding(
        severity.lower(),
        path,
        summary if isinstance(summary, str) else "",
        start,
        end,
        tuple(lenses),
    )


def _opt_bool(value: object, name: str, field: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise EvalFormatError(f"{name} {field} must be a boolean")


def _opt_int(value: object, name: str, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvalFormatError(f"{name} {field} must be an integer")
    return value


def _opt_strs(value: object, name: str, field: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise EvalFormatError(f"{name} {field} must be a list of strings")
