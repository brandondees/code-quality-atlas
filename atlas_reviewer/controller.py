# SPDX-License-Identifier: MIT
"""The trusted controller: one PR event in, one review draft out.

It is the only component holding credentials (inside the GitHub, Sprites
and model adapters it is handed). Untrusted data flows one way: fetched,
redacted, fenced into the prompt, rendered into the draft. Nothing here
writes to GitHub.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from atlas_reviewer.classify import classify
from atlas_reviewer.diffs import (
    DiffPart,
    DiffSelection,
    FileDiff,
    describe_by_risk,
    diff_paths,
    select_diff,
)
from atlas_reviewer.domain import (
    CleanupStatus,
    Evidence,
    EvidenceItem,
    Missing,
    Omission,
    PrEvent,
    RunnerReport,
    RunnerStatus,
    SourceKey,
    SourceKind,
)
from atlas_reviewer.draft import (
    DraftInput,
    NarrativeFailure,
    PartNarrative,
    render_draft,
    render_evidence,
)
from atlas_reviewer.evidence import DETAIL_CHARS, PullInfo, parse_pull, tool_evidence
from atlas_reviewer.gather import Collected, IngestConfig, gather_ci
from atlas_reviewer.instrumented import InstrumentedGitHub
from atlas_reviewer.lenses import LensLibrary, LensPlan, plan_lenses, rank_lenses
from atlas_reviewer.notes import ControllerFacts, controller_notes
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    GitHubReader,
    ReviewHarness,
    ReviewRequest,
    RunnerLedger,
    SpritesApi,
)
from atlas_reviewer.prompt import UntrustedBlock
from atlas_reviewer.redact import RedactedText, Redactor
from atlas_reviewer.runner import (
    FIRST_FRAME_BUDGET_S,
    RunnerJob,
    ToolResult,
    ToolSpec,
    run_disposable,
)
from atlas_reviewer.telemetry import Telemetry

MAX_MODEL_CALLS = 3
DEFAULT_DIFF_CHARS_PER_CALL = 60_000
MIN_DIFF_CHARS_PER_CALL = 1_000
MAX_LISTED_PATHS = 100
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
    model_calls: int = MAX_MODEL_CALLS
    diff_chars_per_call: int = DEFAULT_DIFF_CHARS_PER_CALL
    first_frame_s: float = FIRST_FRAME_BUDGET_S

    def __post_init__(self) -> None:
        """`model_calls` is also the number of diff parts: each part gets
        one call, and retries come out of the same cap (the provider's
        `CallLimits.max_calls`), so a retry can leave a later part unreviewed."""
        if not 1 <= self.model_calls <= MAX_MODEL_CALLS:
            raise ValueError(f"model calls must be 1 to {MAX_MODEL_CALLS}")
        if self.diff_chars_per_call < MIN_DIFF_CHARS_PER_CALL:
            raise ValueError(
                f"diff characters per call must be at least {MIN_DIFF_CHARS_PER_CALL}"
            )
        if self.first_frame_s <= 0:
            raise ValueError("first-frame seconds must be positive")


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
    telemetry: Telemetry | None = None


def review(event: PrEvent, deps: Deps, config: ReviewConfig) -> str:
    telemetry = deps.telemetry or Telemetry(deps.clock)
    deps = replace(
        deps, github=InstrumentedGitHub(deps.github, telemetry), telemetry=telemetry
    )
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
    selection, paths, diff_redactions = _diff(event, deps, config, collected)
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
    shared = _Shared(
        _pull_block(pull, deps),
        _evidence_block(evidence, deps, collected),
        tuple(issues),
    )
    parts = _narrate_parts(event, selection, shared, notes, plan, deps, telemetry)
    draft = render_draft(
        DraftInput(
            event=event,
            mode=config.mode,
            title=pull.title.text,
            evidence=evidence,
            links=tuple(collected.links),
            controller_notes=(*notes, *_coverage_lines(selection, parts)),
            lenses=plan.uses,
            narratives=parts,
            omissions=(*collected.omissions, *_unreviewed_parts(parts)),
            model_usage=deps.harness.usage_lines(),
            redactions=_redaction_total(pull, collected.items, shared, diff_redactions),
            generated_at=deps.clock.now(),
            telemetry=telemetry.events,
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
        telemetry=deps.telemetry,
        first_frame_s=config.first_frame_s,
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


@dataclass(frozen=True)
class _Shared:
    """The untrusted blocks every model call gets, whichever diff part it reviews."""

    pull: UntrustedBlock
    evidence: UntrustedBlock
    issues: tuple[UntrustedBlock, ...]

    @property
    def blocks(self) -> tuple[UntrustedBlock, ...]:
        return (self.pull, self.evidence, *self.issues)


def _pull_block(pull: PullInfo, deps: Deps) -> UntrustedBlock:
    return UntrustedBlock(
        "pull-request", deps.redactor(f"Title: {pull.title.text}\n\n{pull.body.text}")
    )


def _evidence_block(
    evidence: tuple[Evidence, ...], deps: Deps, collected: Collected
) -> UntrustedBlock:
    text = render_evidence(evidence, tuple(collected.omissions), tuple(collected.links))
    return UntrustedBlock("ci-and-runner-evidence", deps.redactor(text))


def _part_blocks(
    shared: _Shared, part: DiffPart, notes: tuple[str, ...], deps: Deps
) -> tuple[UntrustedBlock, ...]:
    diff = deps.redactor(part.text or "(no diff content in this call)")
    notes_text = deps.redactor("\n".join(f"- {n}" for n in notes))
    return (
        shared.pull,
        UntrustedBlock("diff", diff),
        shared.evidence,
        UntrustedBlock("controller-notes", notes_text),
        *shared.issues,
    )


def _diff(
    event: PrEvent, deps: Deps, config: ReviewConfig, collected: Collected
) -> tuple[DiffSelection, tuple[str, ...], int]:
    """The diff split into risk-ordered parts, every changed path (for lens
    selection), and the redaction count of the whole diff. Anything short
    of complete coverage is recorded as an omission naming the files."""
    try:
        raw = deps.github.get_pull_diff(event.repo, event.pr_number)
    except BoundaryError as exc:
        collected.notes.append(
            f"The PR diff could not be fetched ({exc}); the narrative has no diff."
        )
        return select_diff("", 1, config.diff_chars_per_call), (), 0
    full = deps.redactor(raw)
    selection = select_diff(full.text, config.model_calls, config.diff_chars_per_call)
    _note_selection(collected, selection, config)
    return selection, diff_paths(full.text), full.redaction_count


def _note_selection(
    collected: Collected, sel: DiffSelection, config: ReviewConfig
) -> None:
    if sel.complete:
        return
    limit = (
        f"{config.model_calls} model call(s) x {config.diff_chars_per_call} "
        "characters, risk-ordered"
    )
    collected.omit("pull request diff", limit, _selection_detail(sel))


def _selection_detail(sel: DiffSelection) -> str:
    cut = ", ".join(
        f"{f.path} (kept {f.shown_chars} of {f.full_chars} characters)" for f in sel.cut
    )
    parts = [
        (
            f"kept {sel.kept_chars} of {sel.total_chars} characters in "
            f"{len(sel.parts)} part(s), highest risk first"
        ),
        f"{len(sel.full)} of {sel.total_files} file(s) sent in full",
        f"cut to fit one call: {cut}" if cut else "",
        _unseen_detail(sel.unseen),
    ]
    return "; ".join(p for p in parts if p)


def _unseen_detail(unseen: tuple[FileDiff, ...]) -> str:
    if not unseen:
        return ""
    listed = describe_by_risk(unseen, MAX_LISTED_PATHS)
    return f"never sent to any model call ({len(unseen)}), highest risk first: {listed}"


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


def _narrate_parts(
    event: PrEvent,
    selection: DiffSelection,
    shared: _Shared,
    notes: tuple[str, ...],
    plan: LensPlan,
    deps: Deps,
    telemetry: Telemetry,
) -> tuple[PartNarrative, ...]:
    """One model call per part, in risk order. A part whose call fails or is
    refused (call cap, cost cap) still yields a `PartNarrative`, so its
    files are reported as unreviewed rather than dropped."""
    parts = selection.parts or (DiffPart(()),)
    total = len(parts)

    def blocks(index: int, part: DiffPart) -> tuple[UntrustedBlock, ...]:
        note = _part_note(index, total, part, selection)
        return _part_blocks(shared, part, (*notes, note), deps)

    return tuple(
        _narrate_part(event, i, total, part, blocks(i, part), plan, deps, telemetry)
        for i, part in enumerate(parts, 1)
    )


def _part_note(index: int, total: int, part: DiffPart, sel: DiffSelection) -> str:
    files = ", ".join(f"{f.path} (cut)" if f.cut else f.path for f in part.files)
    others = (
        f" The other {total - 1} part(s) go to separate model calls; this call cannot see them."
        if total > 1
        else ""
    )
    unseen = (
        f" {len(sel.unseen)} file(s) go to no model call (listed in the omissions table)."
        if sel.unseen
        else ""
    )
    return (
        f"Diff part {index} of {total} (this model call): {len(part.files)} file(s), "
        f"{part.chars} characters: {files or 'none'}.{others}{unseen}"
    )


def _narrate_part(
    event: PrEvent,
    index: int,
    total: int,
    part: DiffPart,
    blocks: tuple[UntrustedBlock, ...],
    plan: LensPlan,
    deps: Deps,
    telemetry: Telemetry,
) -> PartNarrative:
    request = ReviewRequest(
        event.repo,
        event.pr_number,
        event.head_sha,
        blocks,
        plan.loaded,
        plan.coverage(),
    )
    try:
        result = telemetry.span(
            "model call",
            f"diff part {index} of {total}",
            lambda: deps.harness.review(request),
            {"files": len(part.files), "diff_chars": part.chars},
        )
    except BoundaryError as exc:
        return PartNarrative(
            index, total, part.files, NarrativeFailure(deps.harness.name, str(exc))
        )
    return PartNarrative(index, total, part.files, result)


def _coverage_lines(
    sel: DiffSelection, parts: tuple[PartNarrative, ...]
) -> tuple[str, ...]:
    reviewed = [p for p in parts if p.reviewed]
    full = sum(1 for p in reviewed for f in p.files if not f.cut)
    cut = sum(1 for p in reviewed for f in p.files if f.cut)
    complete = sel.complete and len(reviewed) == len(parts)
    verdict = "complete" if complete else "PARTIAL"
    line = (
        f"Diff coverage after the model calls: {verdict}. {len(reviewed)} of "
        f"{len(parts)} call(s) returned a review, covering {full} of {sel.total_files} "
        f"file(s) in full and {cut} cut to fit; {len(sel.unseen)} file(s) went to "
        "no call."
    )
    return (line,)


def _unreviewed_parts(parts: tuple[PartNarrative, ...]) -> tuple[Omission, ...]:
    return tuple(
        Omission(
            f"pull request diff, part {p.index} of {p.total}",
            "model call returned no review",
            f"{len(p.files)} file(s) sent but not reviewed: "
            f"{describe_by_risk(p.files, MAX_LISTED_PATHS) or 'none'}",
        )
        for p in parts
        if not p.reviewed
    )


def _redaction_total(
    pull: PullInfo, items: list[EvidenceItem], shared: _Shared, diff_redactions: int
) -> int:
    inner = pull.title.redaction_count + pull.body.redaction_count
    return (
        inner
        + diff_redactions
        + sum(i.detail.redaction_count for i in items)
        + sum(b.content.redaction_count for b in shared.blocks)
    )
