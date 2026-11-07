# SPDX-License-Identifier: MIT
"""The trusted controller: one PR event in, one review draft out.

It is the only component holding credentials (inside the GitHub, Sprites
and model adapters it is handed). Untrusted data flows one way: fetched,
redacted, fenced into the prompt, rendered into the draft. Nothing here
writes to GitHub.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from atlas_reviewer.classify import classify
from atlas_reviewer.diffs import diff_coverage, diff_paths
from atlas_reviewer.domain import (
    CleanupStatus,
    Evidence,
    EvidenceItem,
    Missing,
    PrEvent,
    RunnerReport,
    RunnerStatus,
    SourceKey,
    SourceKind,
)
from atlas_reviewer.draft import (
    DraftInput,
    NarrativeFailure,
    render_draft,
    render_evidence,
)
from atlas_reviewer.evidence import DETAIL_CHARS, PullInfo, parse_pull, tool_evidence
from atlas_reviewer.gather import Collected, IngestConfig, gather_ci
from atlas_reviewer.lenses import LensLibrary, LensPlan, plan_lenses, rank_lenses
from atlas_reviewer.notes import ControllerFacts, controller_notes
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    GitHubReader,
    Narrative,
    ReviewHarness,
    ReviewRequest,
    RunnerLedger,
    SpritesApi,
)
from atlas_reviewer.prompt import UntrustedBlock
from atlas_reviewer.redact import RedactedText, Redactor
from atlas_reviewer.runner import RunnerJob, ToolResult, ToolSpec, run_disposable

DIFF_CHARS = 60_000
MAX_TARBALL_BYTES = 9 * 1024 * 1024

DEFAULT_TOOLS = (
    ToolSpec(
        "python-compileall",
        "python3",
        "python3 --version",
        "python3 -m compileall -q .",
    ),
)


@dataclass(frozen=True)
class ReviewConfig:
    expected: tuple[SourceKey, ...] = ()
    include_issues: bool = False
    deadline_s: float = 600.0
    tools: tuple[ToolSpec, ...] = DEFAULT_TOOLS
    max_tarball_bytes: int = MAX_TARBALL_BYTES
    ingest: IngestConfig = field(default_factory=IngestConfig)
    mode: str = "live"


@dataclass(frozen=True)
class Deps:
    github: GitHubReader
    sprites: SpritesApi
    ledger: RunnerLedger
    harness: ReviewHarness
    clock: Clock
    redactor: Redactor
    runner_name: Callable[[], str]
    lenses: LensLibrary = field(default_factory=LensLibrary)


def review(event: PrEvent, deps: Deps, config: ReviewConfig) -> str:
    pull = parse_pull(deps.github.get_pull(event.repo, event.pr_number), deps.redactor)
    collected = Collected(notes=_head_notes(event, pull))
    gather_ci(
        event,
        pull.head_ref,
        deps.github,
        deps.clock.now,
        deps.redactor,
        config.ingest,
        collected,
    )
    runner, tool_results = _run_tools(event, deps, config, collected)
    evidence = classify(
        event.head_sha, collected.items, config.expected, collected.failures
    )
    diff, paths = _diff(event, deps, collected)
    _note_truncation(collected, "pull request body", pull.body, DETAIL_CHARS)
    issues = _issue_blocks(event, pull, deps, config, collected)
    plan = plan_lenses(
        deps.lenses, rank_lenses(paths, f"{pull.title.text}\n{pull.body.text}")
    )
    notes = controller_notes(
        ControllerFacts(
            runner,
            tuple(t.name for t in config.tools),
            tool_results,
            tuple(collected.omissions),
            plan,
            tuple(collected.notes),
        )
    )
    blocks = _blocks(pull, diff, issues, evidence, notes, deps, collected)
    narrative = _narrate(event, blocks, plan, deps)
    draft = render_draft(
        DraftInput(
            event=event,
            mode=config.mode,
            title=pull.title.text,
            evidence=evidence,
            links=tuple(collected.links),
            controller_notes=notes,
            lenses=plan.uses,
            narrative=narrative,
            omissions=tuple(collected.omissions),
            model_usage=deps.harness.usage_lines(),
            redactions=_redaction_total(pull, collected.items, blocks),
            generated_at=deps.clock.now(),
        )
    )
    # Check names, failure reasons, archive entry names and runner notes are untrusted too.
    return deps.redactor(draft).text


def _head_notes(event: PrEvent, pull: PullInfo) -> list[str]:
    if pull.head_sha == event.head_sha:
        return []
    note = (
        f"The PR head is now `{pull.head_sha[:12]}`, not the event SHA. This draft covers "
        f"`{event.head_sha[:12]}` only, and only evidence for that SHA counts."
    )
    return [note]


def _tool_keys(config: ReviewConfig) -> list[SourceKey]:
    return [SourceKey(SourceKind.RUNNER_TOOL, t.name) for t in config.tools]


def _skip_runner(
    config: ReviewConfig, collected: Collected, reason: str
) -> tuple[RunnerReport, tuple[ToolResult, ...]]:
    collected.failures.extend(
        Missing(k, f"runner skipped: {reason}") for k in _tool_keys(config)
    )
    report = RunnerReport(RunnerStatus.SKIPPED, CleanupStatus.NOT_CREATED, None, reason)
    return report, ()


def _run_tools(
    event: PrEvent, deps: Deps, config: ReviewConfig, collected: Collected
) -> tuple[RunnerReport, tuple[ToolResult, ...]]:
    try:
        tarball = deps.github.get_tarball(event.repo, event.head_sha)
    except BoundaryError as exc:
        return _skip_runner(
            config, collected, f"could not fetch the head-SHA tarball: {exc}"
        )
    if len(tarball) > config.max_tarball_bytes:
        return _skip_runner(
            config,
            collected,
            f"tarball is {len(tarball)} bytes, over {config.max_tarball_bytes}",
        )
    result = run_disposable(
        deps.sprites,
        deps.ledger,
        RunnerJob(tarball, config.tools),
        name=deps.runner_name(),
        deadline_s=config.deadline_s,
        clock=deps.clock,
    )
    _record_tool_results(event, deps, config, collected, result.results, result.report)
    return result.report, result.results


def _record_tool_results(
    event: PrEvent,
    deps: Deps,
    config: ReviewConfig,
    collected: Collected,
    results: tuple[ToolResult, ...],
    report: RunnerReport,
) -> None:
    now = deps.clock.now()
    mapped = [
        tool_evidence(r, event.head_sha, report.runner_name or "", now, deps.redactor)
        for r in results
    ]
    collected.items.extend(m for m in mapped if isinstance(m, EvidenceItem))
    collected.failures.extend(m for m in mapped if isinstance(m, Missing))
    attempted = {r.tool.name for r in results}
    reason = f"runner {report.status.value} before this tool ran: {report.note}"
    collected.failures.extend(
        Missing(k, reason) for k in _tool_keys(config) if k.name not in attempted
    )


def _blocks(
    pull: PullInfo,
    diff: RedactedText,
    issues: list[UntrustedBlock],
    evidence: tuple[Evidence, ...],
    notes: tuple[str, ...],
    deps: Deps,
    collected: Collected,
) -> tuple[UntrustedBlock, ...]:
    r = deps.redactor
    evidence_text = render_evidence(
        evidence, tuple(collected.omissions), tuple(collected.links)
    )
    return (
        UntrustedBlock(
            "pull-request", r(f"Title: {pull.title.text}\n\n{pull.body.text}")
        ),
        UntrustedBlock("diff", diff),
        UntrustedBlock("ci-and-runner-evidence", r(evidence_text)),
        UntrustedBlock("controller-notes", r("\n".join(f"- {n}" for n in notes))),
        *issues,
    )


def _diff(
    event: PrEvent, deps: Deps, collected: Collected
) -> tuple[RedactedText, tuple[str, ...]]:
    """The diff as the model gets it, plus every changed path (for lens
    selection). A cut is recorded as an omission naming the files the model
    never fully saw."""
    try:
        raw = deps.github.get_pull_diff(event.repo, event.pr_number)
    except BoundaryError as exc:
        collected.notes.append(
            f"The PR diff could not be fetched ({exc}); the narrative has no diff."
        )
        return deps.redactor("(diff unavailable)"), ()
    full = deps.redactor(raw)
    capped = deps.redactor(raw, DIFF_CHARS)
    if capped.truncated_from is not None:
        collected.omit(
            "pull request diff",
            f"{DIFF_CHARS}-character cap",
            _diff_cut_detail(full.text, capped.truncated_from),
        )
    return capped, diff_paths(full.text)


MAX_LISTED_PATHS = 15


def _diff_cut_detail(full_text: str, total_chars: int) -> str:
    cov = diff_coverage(full_text, DIFF_CHARS)
    parts = [
        f"kept {DIFF_CHARS} of {total_chars} characters",
        f"{len(cov.seen)} of {cov.total_files} file(s) seen in full",
    ]
    if cov.partial is not None:
        parts.append(f"cut partway through {cov.partial}")
    if cov.unseen:
        shown = ", ".join(cov.unseen[:MAX_LISTED_PATHS])
        more = len(cov.unseen) - MAX_LISTED_PATHS
        tail = f", and {more} more" if more > 0 else ""
        parts.append(f"never seen ({len(cov.unseen)}): {shown}{tail}")
    return "; ".join(parts)


def _note_truncation(
    collected: Collected, source: str, text: RedactedText, cap: int
) -> None:
    if text.truncated_from is not None:
        collected.omit(
            source,
            f"{cap}-character cap",
            f"kept {cap} of {text.truncated_from} characters",
        )


def _issue_blocks(
    event: PrEvent,
    pull: PullInfo,
    deps: Deps,
    config: ReviewConfig,
    collected: Collected,
) -> list[UntrustedBlock]:
    if not config.include_issues:
        collected.notes.append("Issue context: off (opt in with `--include-issues`).")
        return []
    blocks = [_issue_block(event, n, deps, collected) for n in pull.issue_refs]
    return [b for b in blocks if b is not None]


def _issue_block(
    event: PrEvent, number: int, deps: Deps, collected: Collected
) -> UntrustedBlock | None:
    try:
        issue = deps.github.get_issue(event.repo, number)
    except BoundaryError as exc:
        collected.notes.append(f"Issue #{number} could not be fetched: {exc}")
        return None
    text = f"Title: {issue.get('title', '')}\n\n{issue.get('body') or ''}"
    redacted = deps.redactor(text, DETAIL_CHARS)
    _note_truncation(collected, f"issue #{number}", redacted, DETAIL_CHARS)
    return UntrustedBlock(f"issue-{number}", redacted)


def _narrate(
    event: PrEvent,
    blocks: tuple[UntrustedBlock, ...],
    plan: LensPlan,
    deps: Deps,
) -> Narrative | NarrativeFailure:
    request = ReviewRequest(
        event.repo,
        event.pr_number,
        event.head_sha,
        blocks,
        plan.loaded,
        plan.coverage(),
    )
    try:
        return deps.harness.review(request)
    except BoundaryError as exc:
        return NarrativeFailure(deps.harness.name, str(exc))


def _redaction_total(
    pull: PullInfo, items: list[EvidenceItem], blocks: tuple[UntrustedBlock, ...]
) -> int:
    inner = pull.title.redaction_count + pull.body.redaction_count
    return (
        inner
        + sum(i.detail.redaction_count for i in items)
        + sum(b.content.redaction_count for b in blocks)
    )
