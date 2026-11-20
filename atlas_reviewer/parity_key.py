# SPDX-License-Identifier: MIT
"""The parity key: seven graded protocol Minors.

A key file is one pull request's verified protocol findings. Adding a
protocol-reviewed pull request is another JSON file in the same directory;
the loader reads every file. A record is a path and a line span, or the
pull request body and the lines a citation has to quote.
``grade_findings`` compares one verified candidate list with those spans.
``score_parity`` counts found, partial, and lost across recorded runs.
The command that reads a directory of runs is a later layer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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


# The candidate may extend this many lines past the defect and still be a
# find. Zero means the citation has to sit inside the defect span. A
# neighboring line, or a citation of the whole function, is partial.
SPAN_SLACK = 0
FOUND = "found"
PARTIAL = "partial"
LOST = "lost"
RUNS_REQUIRED = 3
FOUND_IN_AT_LEAST = 2
PARTIAL_COUNTS_AS_FOUND = False
_RANK = {"nit": 0, "minor": 1, "major": 2, "blocker": 3}


@dataclass(frozen=True)
class CitedFinding:
    """One verified finding, already deduped by the coordinator.

    ``verified`` is required. The grader does not read the file. ``quote``
    has to contain a body citation. A file finding is cited by its line.
    """

    path: str
    quote: str
    severity: str
    verified: bool
    line: int | None = None
    end_line: int | None = None
    lens: str | None = None


@dataclass(frozen=True)
class FindingGrades:
    """Grades aligned with the findings, plus unused candidates.

    ``grades`` is found, partial, or lost. ``extra_majors`` counts unused
    candidates whose severity is major. A blocker is an extra and is not a
    major.
    """

    grades: tuple[str, ...]
    extras: int
    extra_majors: int


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


def grade_findings(
    findings: Sequence[KeyFinding], candidates: Sequence[CitedFinding]
) -> FindingGrades:
    """Found, then partial. Each candidate is used at most once.

    Both pairings are maximum matchings, so two spans that share a line
    are both found when each can take a different candidate. A find is a
    verified citation that sits inside the defect span. A citation of the
    whole function overlaps and is partial. ``extra_majors`` counts unused
    majors only, in any capitalization.
    """
    used: set[int] = set()
    grades = [LOST for _finding in findings]
    _assign(findings, candidates, grades, used, FOUND, _is_found)
    _assign(findings, candidates, grades, used, PARTIAL, _is_partial)
    unused = [
        candidates[index] for index in range(len(candidates)) if index not in used
    ]
    majors = sum(_rank(item) == _RANK["major"] for item in unused)
    return FindingGrades(tuple(grades), len(unused), majors)


def _assign(
    findings: Sequence[KeyFinding],
    candidates: Sequence[CitedFinding],
    grades: list[str],
    used: set[int],
    grade: str,
    holds: Callable[[KeyFinding, CitedFinding], bool],
) -> None:
    edges = [
        [
            index
            for index, candidate in enumerate(candidates)
            if index not in used and holds(finding, candidate)
        ]
        if grades[ref] == LOST
        else []
        for ref, finding in enumerate(findings)
    ]
    for cand_index, ref_index in enumerate(_assignment(edges, len(candidates))):
        if ref_index == -1:
            continue
        grades[ref_index] = grade
        used.add(cand_index)


def _rank(candidate: CitedFinding) -> int:
    return _RANK.get(candidate.severity.casefold(), -1)


def _is_found(finding: KeyFinding, candidate: CitedFinding) -> bool:
    if not candidate.verified or _rank(candidate) < _RANK["minor"]:
        return False
    if _is_body(finding):
        return _cites(finding, candidate)
    return _contained_any(finding.spans, candidate)


def _is_partial(finding: KeyFinding, candidate: CitedFinding) -> bool:
    if not candidate.verified or _rank(candidate) < 0:
        return False
    if _is_body(finding):
        return _rank(candidate) == _RANK["nit"] and _cites(finding, candidate)
    if _overlaps_any(finding.spans, candidate):
        return True
    return _overlaps_any(finding.encloses, candidate)


def _is_body(finding: KeyFinding) -> bool:
    return finding.spans[0].path == BODY


def _cites(finding: KeyFinding, candidate: CitedFinding) -> bool:
    return candidate.path == BODY and any(
        text in candidate.quote for text in finding.citations
    )


def _contained_any(spans: Sequence[Span], candidate: CitedFinding) -> bool:
    return any(_contains(span, candidate) for span in spans)


def _contains(span: Span, candidate: CitedFinding) -> bool:
    if not _overlaps(span, candidate):
        return False
    cand_end = (
        candidate.end_line
        if candidate.end_line is not None
        else cast(int, candidate.line)
    )
    return cast(int, candidate.line) >= cast(int, span.line_start) - SPAN_SLACK and (
        cand_end <= cast(int, span.line_end) + SPAN_SLACK
    )


def _overlaps_any(spans: Sequence[Span], candidate: CitedFinding) -> bool:
    return any(_overlaps(span, candidate) for span in spans)


def _overlaps(span: Span, candidate: CitedFinding) -> bool:
    if span.path != candidate.path or span.line_start is None or candidate.line is None:
        return False
    cand_end = candidate.line if candidate.end_line is None else candidate.end_line
    if cand_end < candidate.line:
        return False
    return span.line_start - SPAN_SLACK <= cand_end and (
        candidate.line <= cast(int, span.line_end) + SPAN_SLACK
    )


def _assignment(edges: Sequence[Sequence[int]], n_candidates: int) -> list[int]:
    """``assigned[candidate]`` is the reference index, or -1."""
    assigned = [-1] * n_candidates

    def visit(ref_index: int, seen: list[bool]) -> bool:
        for cand_index in edges[ref_index]:
            if seen[cand_index]:
                continue
            seen[cand_index] = True
            prior = assigned[cand_index]
            if prior == -1 or visit(prior, seen):
                assigned[cand_index] = ref_index
                return True
        return False

    for ref_index in range(len(edges)):
        visit(ref_index, [False] * n_candidates)
    return assigned


@dataclass(frozen=True)
class ParityRun:
    """One recorded review. Comparison fields stay None when the run omitted them."""

    name: str
    pr: int
    model: str
    repetition: int
    head_sha: str
    findings: tuple[CitedFinding, ...]
    coverage_complete: bool
    lenses_run: tuple[str, ...]
    lenses_not_run: tuple[str, ...]
    lenses_failed: tuple[str, ...]
    limit_stops: tuple[str, ...]
    false_positive_majors: int | None = None
    lenses_clean: int | None = None
    lenses_planned: int | None = None
    cost_usd: float | None = None
    wall_seconds: float | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    previous_turn_misses: int | None = None


def score_parity(
    findings: Sequence[KeyFinding],
    runs: Sequence[ParityRun],
    *,
    runs_required: int = RUNS_REQUIRED,
    found_in_at_least: int = FOUND_IN_AT_LEAST,
    partial_counts_as_found: bool = PARTIAL_COUNTS_AS_FOUND,
) -> dict[str, Any]:
    """The gate. Empty ``failures`` is a pass.

    A finding passes when the sample has ``runs_required`` runs and the
    finding was found in ``found_in_at_least`` of them. Partial counts only
    when ``partial_counts_as_found`` is true. A value that is not a bool is
    refused, as are the other two overrides. An automatic failure is recorded
    on its run and fails the gate on its own; it does not drop that run from
    the sample. A run whose ``head_sha`` is not that pull request's
    ``reviewed_commit`` is one of those failures. A repeated run name, a
    repeated pull request, model, and repetition, or two models in one pull
    request's sample is refused.
    """
    _check_rule(runs_required, found_in_at_least, partial_counts_as_found)
    _check_sample(runs)
    grouped = _group(findings)
    failures: list[str] = []
    run_rows: list[dict[str, Any]] = []
    per_pr: dict[int, list[tuple[str, ...]]] = {pr: [] for pr in grouped}
    for run in runs:
        pr_findings = grouped.get(run.pr, ())
        if run.pr not in grouped:
            failures.append(
                f"{run.name} is for pull request {run.pr}, which is not in the key"
            )
        graded = grade_findings(pr_findings, run.findings)
        if run.pr in per_pr:
            per_pr[run.pr].append(graded.grades)
        reasons = automatic_failures(run, pr_findings)
        failures.extend(f"{run.name}: {reason}" for reason in reasons)
        run_rows.append(_run_row(run, pr_findings, graded, reasons))
    finding_rows: list[dict[str, Any]] = []
    for pr, pr_findings in grouped.items():
        rows = per_pr[pr]
        if len(rows) < runs_required:
            failures.append(
                f"pull request {pr} has {len(rows)} {_runs_word(len(rows))} recorded; "
                f"the sample is {runs_required}"
            )
        for index, finding in enumerate(pr_findings):
            row, missed = _tally(
                finding,
                [grades[index] for grades in rows],
                runs_required,
                found_in_at_least,
                partial_counts_as_found,
            )
            finding_rows.append(row)
            if missed:
                failures.append(missed)
    return {
        "gate_pass": not failures,
        "defaults": {
            "runs_required": runs_required,
            "found_in_at_least": found_in_at_least,
            "partial_counts_as_found": partial_counts_as_found,
        },
        "failures": failures,
        "findings": finding_rows,
        "runs": run_rows,
    }


def automatic_failures(
    run: ParityRun, findings: Sequence[KeyFinding]
) -> tuple[str, ...]:
    """Why this run fails even if it found every key finding. Independent of k-of-3."""
    reasons: list[str] = []
    if run.coverage_complete is not True:
        reasons.append("coverage_complete is not true")
    for name in run.lenses_not_run:
        reasons.append(f"lens {name} was NOT RUN")
    for name in run.lenses_failed:
        reasons.append(f"lens {name} failed")
    for stop in run.limit_stops:
        reasons.append(f"limit stop: {stop}")
    ran = set(run.lenses_run)
    already = set(run.lenses_not_run) | set(run.lenses_failed)
    for finding in findings:
        for name in finding.lenses:
            if name not in ran and name not in already:
                reasons.append(f"lens {name} named by the key was not run")
    for commit in dict.fromkeys(finding.reviewed_commit for finding in findings):
        if run.head_sha != commit:
            reasons.append(
                f"head_sha {run.head_sha} is not the reviewed commit {commit}"
            )
    return tuple(dict.fromkeys(reasons))


def _check_sample(runs: Sequence[ParityRun]) -> None:
    """One name, one (pull request, model, repetition), and one model per pull request."""
    seen_names: set[str] = set()
    seen_slots: set[tuple[int, str, int]] = set()
    models: dict[int, str] = {}
    for run in runs:
        if run.name in seen_names:
            raise EvalFormatError(f"run name {run.name} is recorded more than once")
        seen_names.add(run.name)
        slot = (run.pr, run.model, run.repetition)
        if slot in seen_slots:
            raise EvalFormatError(
                f"pull request {run.pr} records {run.model} "
                f"repetition {run.repetition} more than once"
            )
        seen_slots.add(slot)
        prior = models.get(run.pr)
        if prior is not None and prior != run.model:
            raise EvalFormatError(
                f"pull request {run.pr} mixes models {prior} and {run.model}"
            )
        models[run.pr] = run.model


def _check_rule(
    runs_required: int, found_in_at_least: int, partial_counts_as_found: bool
) -> None:
    if (
        isinstance(runs_required, bool)
        or isinstance(found_in_at_least, bool)
        or not isinstance(runs_required, int)
        or not isinstance(found_in_at_least, int)
        or runs_required < 1
        or found_in_at_least < 1
        or found_in_at_least > runs_required
        or not isinstance(partial_counts_as_found, bool)
    ):
        raise EvalFormatError(
            "runs_required and found_in_at_least must be positive integers, "
            "and found_in_at_least cannot exceed runs_required; "
            "partial_counts_as_found must be true or false"
        )


def _group(findings: Sequence[KeyFinding]) -> dict[int, tuple[KeyFinding, ...]]:
    buckets: dict[int, list[KeyFinding]] = {}
    for finding in findings:
        buckets.setdefault(finding.pr, []).append(finding)
    return {pr: tuple(items) for pr, items in buckets.items()}


def _tally(
    finding: KeyFinding,
    counts: list[str],
    runs_required: int,
    found_in_at_least: int,
    partial_counts_as_found: bool,
) -> tuple[dict[str, Any], str]:
    found = counts.count(FOUND)
    partial = counts.count(PARTIAL)
    lost = counts.count(LOST)
    credit = found + (partial if partial_counts_as_found else 0)
    passed = len(counts) >= runs_required and credit >= found_in_at_least
    missed = ""
    if credit < found_in_at_least:
        label = "credited" if partial_counts_as_found else "found"
        missed = f"{finding.id} {label} in {credit} of {len(counts)} (need {found_in_at_least})"
    return (
        {
            "id": finding.id,
            "pr": finding.pr,
            "found": found,
            "partial": partial,
            "lost": lost,
            "of": len(counts),
            "passed": passed,
        },
        missed,
    )


def _run_row(
    run: ParityRun,
    pr_findings: Sequence[KeyFinding],
    graded: FindingGrades,
    reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "name": run.name,
        "pr": run.pr,
        "model": run.model,
        "repetition": run.repetition,
        "head_sha": run.head_sha,
        "automatic_fail": list(reasons),
        "grades": {
            finding.id: grade
            for finding, grade in zip(pr_findings, graded.grades, strict=True)
        },
        "extras": graded.extras,
        "extra_majors": graded.extra_majors,
        "false_positive_majors": run.false_positive_majors,
        "lenses_clean": run.lenses_clean,
        "lenses_planned": run.lenses_planned,
        "cost_usd": run.cost_usd,
        "wall_seconds": run.wall_seconds,
        "cache_read_tokens": run.cache_read_tokens,
        "cache_write_tokens": run.cache_write_tokens,
        "previous_turn_misses": run.previous_turn_misses,
    }


def _runs_word(count: int) -> str:
    return "run" if count == 1 else "runs"
