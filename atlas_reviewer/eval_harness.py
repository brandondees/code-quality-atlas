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
RUNS = frozenset({"lens-fan-out", "coordinator-verified", "unrecorded"})
_VERDICTS = frozenset({"APPROVE", "COMMENT", "REQUEST_CHANGES"})
_SEVERITIES = frozenset({"blocker", "major", "minor", "nit"})
_ROUND = re.compile(r"^## Round\s+(\d+)\s+[—–-]\s+(.*)\s*$", re.MULTILINE)
_MARKER = re.compile(r"<!--\s*atlas-review round:(\d+)\b")
_HEADING = re.compile(r"^\*\*(Blocker|Major|Minor|Nit)\s*·\s*([^*\n]+?)\*\*")
_HEADING_SPLIT = re.compile(
    r"^\*\*(Blocker|Major|Minor|Nit)\*\*\s*·\s*(.*?)\s*·\s*(.*)$"
)
_BODY_ANCHORED = re.compile(
    r"^\*\*(Blocker|Major|Minor|Nit)\s*·\s*`([^`]+)`[^*]*·\s*(.*?)\s*\*+\s*$"
)
_BODY_PATH = re.compile(r"^\*\*`([^`]+)`:\s*(.*?)\*\*\s*$")
_SECTION = re.compile(r"^###\s+(Blocker|Major|Minor|Nit)\b", re.IGNORECASE)
_PATH_LINE = re.compile(r"(.+):(\d+)(?:-(\d+))?$")
_LENS = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_LENS_TICK = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`")
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
    reference: EvalReview,
    candidate: CandidateReview,
    scored: Score,
    *,
    run: str = "lens-fan-out",
) -> tuple[str, ...]:
    """Why this pair does not yet allow APPROVE. Empty means it passes.

    The finding bar is no missed Major+ finding, no unmatched candidate
    finding at Major or above, and the same verdict. The coverage bar is
    the candidate's own record: complete coverage, no unreviewed files,
    every lens the reference named was run, and every reference path
    outside the diff was read at head. A ``coordinator-verified`` reference
    did not finish lens fan-out, so the pair cannot clear that criterion.
    """
    failures: list[str] = []
    if run != "lens-fan-out":
        failures.append(
            f"reference run is {run}; only a recorded lens-fan-out clears that criterion"
        )
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
    body: str,
    comments: Sequence[Mapping[str, Any]],
    *,
    state: str | None = None,
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
    return number, EvalReview(
        verdict_of(title, state), (*findings, *_body_findings(body or ""))
    )


def run_mode(body: str) -> str:
    """How the protocol round says it was run.

    ``coordinator-verified`` is the phrase a round uses when lens fan-out
    did not finish and the coordinator verified the partial result.
    ``lens-fan-out`` is a coverage section that names lenses it ran,
    loaded, or re-ran. Anything else is ``unrecorded``.
    """
    text = body or ""
    lowered = text.lower()
    # A leading "not " is a denial, not a statement that this round stopped
    # after the coordinator. Reviews of this term itself must not flip the row.
    if re.search(r"(?<!not )coordinator-verified", lowered) or re.search(
        r"(?<!not )coordinator verified", lowered
    ):
        return "coordinator-verified"
    if re.search(
        r"did not complete lens fan-out|fan-out did not complete|fan-out didn't complete",
        lowered,
    ):
        return "coordinator-verified"
    coverage = _coverage_section(text)
    named = bool(_LENS_TICK.search(coverage))
    ran = re.search(
        r"lenses?(?::| run| re-ran| re-run| loaded)", coverage, re.IGNORECASE
    )
    if coverage and (named or ran):
        return "lens-fan-out"
    return "unrecorded"


def coverage_lenses(body: str) -> tuple[str, ...]:
    """Lens names in backticks in the coverage section, in order, once each."""
    seen: list[str] = []
    for name in _LENS_TICK.findall(_coverage_section(body or "")):
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def _coverage_section(body: str) -> str:
    match = re.search(r"\*\*Coverage[^*\n]*\*\*(.*)", body, re.IGNORECASE | re.DOTALL)
    if match is None:
        match = re.search(
            r"(?m)^#{1,3} Coverage\b[^\n]*\n(.*)", body, re.IGNORECASE | re.DOTALL
        )
    if match is None:
        match = re.search(r"(?m)^Coverage:?\s*(.*)", body, re.IGNORECASE | re.DOTALL)
    if match is None:
        return ""
    text = match.group(1)
    stop = re.search(r"\n## |\n\*\*[A-Z]", text)
    return text[: stop.start()] if stop else text[:2000]


def verdict_of(title: str, state: str | None = None) -> str:
    """GitHub review state wins. A COMMENTED own-PR review spells APPROVE
    or REQUEST_CHANGES in the heading. The clean-round heading
    ``no new findings at or above this round's floor`` is an approval
    (``commands/atlas-review-pr.md`` step 5) even when the heading does
    not contain the word APPROVE."""
    normalized = (state or "").upper()
    if normalized == "APPROVED":
        return "APPROVE"
    if normalized == "CHANGES_REQUESTED":
        return "REQUEST_CHANGES"
    if re.search(r"\bAPPROVE\b", title):
        return "APPROVE"
    if re.search(r"REQUEST_CHANGES|request changes", title, re.IGNORECASE):
        return "REQUEST_CHANGES"
    if re.search(r"no new findings at or above", title, re.IGNORECASE):
        return "APPROVE"
    return "COMMENT"


def findings_expected(title: str) -> bool:
    """A heading that announces findings must parse at least one."""
    if re.search(r"no new findings", title, re.IGNORECASE):
        return False
    return bool(
        re.search(r"\b(blocker|major|minor)\s+findings?\b", title, re.IGNORECASE)
    )


def _comment_finding(comment: Mapping[str, Any]) -> EvalFinding | None:
    text = comment.get("body")
    if not isinstance(text, str) or _CODERABBIT in text:
        return None
    first, _, rest = text.lstrip().partition("\n")
    parsed = _heading_fields(first)
    if parsed is None:
        return None
    severity, lenses, inline_summary = parsed
    path = comment.get("path")
    if not isinstance(path, str) or not path:
        return None
    start, end = _span(comment)
    summary = redact(
        " ".join(part for part in (inline_summary, rest.strip()) if part)
    ).text
    summary = re.sub(r"\s+", " ", summary)[:_SUMMARY_CHARS]
    return EvalFinding(severity, path, summary, start, end, lenses)


def _heading_fields(first: str) -> tuple[str, tuple[str, ...], str] | None:
    heading = _HEADING.match(first)
    if heading is not None:
        lenses = tuple(
            part
            for part in (
                piece.strip() for piece in heading.group(2).split("(")[0].split("/")
            )
            if _LENS.fullmatch(part)
        )
        return heading.group(1).lower(), lenses, ""
    split = _HEADING_SPLIT.match(first)
    if split is None:
        return None
    lenses = tuple(name for name in _LENS_TICK.findall(split.group(2)))
    return split.group(1).lower(), lenses, split.group(3).strip()


def _span(comment: Mapping[str, Any]) -> tuple[int | None, int | None]:
    end = _pos(comment.get("line")) or _pos(comment.get("original_line"))
    start = (
        _pos(comment.get("start_line"))
        or _pos(comment.get("original_start_line"))
        or end
    )
    return start, end


def _pos(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _body_findings(body: str) -> tuple[EvalFinding, ...]:
    """Findings written in the review summary because they had no inline
    anchor. Two shapes occur: ``**Major · `path:line` · summary**`` and,
    under a ``### Major`` heading, ``**`path:line`: summary**``."""
    section = ""
    found: list[EvalFinding] = []
    for line in body.splitlines():
        opened = _SECTION.match(line)
        if opened is not None:
            section = opened.group(1).lower()
            continue
        if line.startswith(("### ", "## ")):
            section = ""
            continue
        anchored = _BODY_ANCHORED.match(line.strip())
        if anchored is not None:
            located = _path_span(anchored.group(2))
            if located is not None:
                path, start, end = located
                found.append(
                    _made(
                        anchored.group(1).lower(), path, anchored.group(3), start, end
                    )
                )
            continue
        if not section:
            continue
        named = _BODY_PATH.match(line.strip())
        if named is None:
            continue
        located = _path_span(named.group(1))
        if located is None:
            continue
        path, start, end = located
        found.append(_made(section, path, named.group(2), start, end))
    return tuple(found)


def _path_span(text: str) -> tuple[str, int, int] | None:
    match = _PATH_LINE.fullmatch(text.strip())
    if match is None:
        return None
    start = int(match.group(2))
    end = int(match.group(3) or start)
    return match.group(1), start, end


def _made(severity: str, path: str, summary: str, start: int, end: int) -> EvalFinding:
    text = re.sub(r"\s+", " ", redact(summary).text)[:_SUMMARY_CHARS]
    return EvalFinding(severity, path, text, start, end, ())


def reference_row(
    pull: Mapping[str, Any],
    review: Mapping[str, Any],
    comments: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """One dataset row from a recorded pull, review, and its inline comments.

    Returns None when the review is not a protocol round. ``reviewed_commit``
    and ``review_state`` come from the review object. ``parse_gap`` is set
    when the heading announces findings and none were parsed.
    """
    raw_body = review.get("body")
    body = raw_body if isinstance(raw_body, str) else ""
    parsed = protocol_review(
        body,
        comments,
        state=review.get("state") if isinstance(review.get("state"), str) else None,
    )
    if parsed is None:
        return None
    number, built = parsed
    heading = _ROUND.search(body)
    title = heading.group(2) if heading is not None else ""
    head = pull.get("head")
    sha = head.get("sha") if isinstance(head, dict) else ""
    repo = ""
    base = pull.get("base")
    if isinstance(base, dict) and isinstance(base.get("repo"), dict):
        full = base["repo"].get("full_name")
        repo = full if isinstance(full, str) else ""
    number_raw = pull.get("number")
    pr = number_raw if isinstance(number_raw, int) else 0
    commit = review.get("commit_id")
    state = review.get("state")
    url = review.get("html_url")
    return example_json(
        repo=repo,
        pr=pr,
        head_sha=sha if isinstance(sha, str) else "",
        round_number=number,
        review=built,
        review_url=url if isinstance(url, str) else "",
        run=run_mode(body),
        lenses_recorded=coverage_lenses(body),
        reviewed_commit=commit if isinstance(commit, str) else "",
        review_state=state if isinstance(state, str) else "",
        parse_gap=findings_expected(title) and not built.findings,
    )


def example_json(
    *,
    repo: str,
    pr: int,
    head_sha: str,
    round_number: int,
    review: EvalReview,
    review_url: str = "",
    run: str = "unrecorded",
    lenses_recorded: Sequence[str] = (),
    reviewed_commit: str = "",
    review_state: str = "",
    parse_gap: bool = False,
) -> dict[str, Any]:
    """One Phoenix dataset example. ``output`` is the reference review.

    ``run`` is how the round says it was executed. ``lenses_recorded`` are
    the lens names in its coverage section.
    """
    if run not in RUNS:
        raise EvalFormatError(f"run must be one of {sorted(RUNS)}")
    return {
        "input": {
            "repo": repo,
            "pr": pr,
            "head_sha": head_sha,
            "round": round_number,
            "reviewed_commit": reviewed_commit,
        },
        "output": _review_json(review),
        "metadata": {
            "source": "claude-code-protocol",
            "review_url": review_url,
            "run": run,
            "lenses_recorded": list(lenses_recorded),
            "review_state": review_state,
            "parse_gap": parse_gap,
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


def load_directory(path: Path, *, head: str | None = None) -> dict[str, Any]:
    """Score every JSON file in ``path``.

    ``gate_pass`` is true only when every checked-in calibration row
    (``fixtures/eval-references/pr-*.json``, matched on repo, PR, round,
    and ``reviewed_commit``) is present as a passing pair, one passing
    pair is for ``head``, and one passing pair records
    ``metadata.over_context_window``. A directory that holds only the
    pair for ``head`` does not open the gate.
    """
    files = sorted(p for p in path.glob("*.json") if p.is_file())
    if not files:
        raise EvalFormatError(f"no JSON fixtures in {path}")
    results: list[dict[str, Any]] = []
    examples = 0
    run_counts = {name: 0 for name in sorted(RUNS)}
    failures: list[str] = []
    seen: set[tuple[str, int, int, str]] = set()
    for file in files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvalFormatError(f"{file.name} is not JSON: {exc}") from exc
        except (UnicodeDecodeError, OSError) as exc:
            raise EvalFormatError(f"{file.name} cannot be read: {exc}") from exc
        if not isinstance(payload, dict):
            raise EvalFormatError(f"{file.name} is not an object")
        examples += 1
        run_counts[_run_of(payload)] += 1
        seen.add(_identity(payload))
        if "candidate" not in payload:
            failures.append(f"{file.name}: reference row has no candidate")
            if _flag(payload, "parse_gap"):
                failures.append(
                    f"{file.name}: heading announces findings that were not parsed"
                )
            continue
        results.append(_score_file(file.name, payload))
    failures.extend(item for row in results for item in row["gate_failures"])
    if not head:
        failures.append("gate requires --head, the commit being approved")
    elif not any(row["passed"] and _matches_head(row, head) for row in results):
        failures.append(f"no passing pair for head {head}")
    if not any(row["passed"] and row["over_context_window"] for row in results):
        failures.append("no passing pair records over_context_window")
    for repo, pr, round_number, commit in reference_identities():
        if (repo, pr, round_number, commit) not in seen:
            failures.append(
                f"calibration row {repo}#{pr} round {round_number} at {commit} is missing"
            )
    totals = _totals(results)
    return {
        "examples": examples,
        "scored": len(results),
        "gate_pass": not failures,
        "gate_failures": failures,
        "totals": totals,
        "run_counts": run_counts,
        "results": results,
    }


def _score_file(name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    reference = _parse_review(payload.get("reference") or payload.get("output"), name)
    candidate = _parse_candidate(payload.get("candidate"), name)
    run = _run_of(payload)
    scored = score(reference, candidate)
    failures = [
        f"{name}: {item}"
        for item in gate_failures(reference, candidate, scored, run=run)
    ]
    if _flag(payload, "parse_gap"):
        failures.append(f"{name}: heading announces findings that were not parsed")
    entered = payload.get("input")
    return {
        "fixture": name,
        "run": run,
        "score": scored.as_json(),
        "gate_failures": failures,
        "passed": not failures,
        "over_context_window": _flag(payload, "over_context_window"),
        "head_sha": _text(entered, "head_sha"),
        "reviewed_commit": _text(entered, "reviewed_commit"),
    }


_REFERENCES = Path(__file__).resolve().parent / "fixtures" / "eval-references"


def reference_identities() -> tuple[tuple[str, int, int, str], ...]:
    """The checked-in protocol rows, as (repo, pr, round, reviewed_commit)."""
    found: list[tuple[str, int, int, str]] = []
    for path in sorted(_REFERENCES.glob("pr-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            found.append(_identity(payload))
    return tuple(found)


def _identity(payload: Mapping[str, Any]) -> tuple[str, int, int, str]:
    entered = payload.get("input")
    if not isinstance(entered, dict):
        return ("", 0, 0, "")
    repo = entered.get("repo")
    pr = entered.get("pr")
    round_number = entered.get("round")
    commit = entered.get("reviewed_commit")
    return (
        repo if isinstance(repo, str) else "",
        pr if isinstance(pr, int) and not isinstance(pr, bool) else 0,
        round_number
        if isinstance(round_number, int) and not isinstance(round_number, bool)
        else 0,
        commit if isinstance(commit, str) else "",
    )


def _matches_head(row: Mapping[str, Any], head: str) -> bool:
    return head in (row["head_sha"], row["reviewed_commit"])


def _flag(payload: Mapping[str, Any], key: str) -> bool:
    meta = payload.get("metadata")
    return isinstance(meta, dict) and meta.get(key) is True


def _text(value: object, key: str) -> str:
    if isinstance(value, dict) and isinstance(value.get(key), str):
        return str(value[key])
    return ""


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


def _run_of(payload: Mapping[str, Any]) -> str:
    meta = payload.get("metadata")
    if isinstance(meta, dict) and meta.get("run") in RUNS:
        return str(meta["run"])
    return "unrecorded"


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
