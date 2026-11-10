# SPDX-License-Identifier: MIT
"""The trusted controller: one PR event in, one review draft out.

It is the only component holding credentials (inside the GitHub, Sprites
and model adapters it is handed). Untrusted data flows one way: fetched,
redacted, fenced into the prompt, rendered into the draft. Nothing here
writes to GitHub.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from atlas_reviewer.budget import CallLimits, prompt_token_room
from atlas_reviewer.classify import classify
from atlas_reviewer.committed_secrets import DiffSecrets, scan_diff
from atlas_reviewer.diffs import (
    DiffPart,
    DiffSelection,
    FileDiff,
    describe_by_risk,
    diff_paths,
    fit_diff,
    risk_tier,
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
from atlas_reviewer.groups import Link
from atlas_reviewer.instrumented import InstrumentedGitHub
from atlas_reviewer.lenses import LensLibrary, plan_lenses
from atlas_reviewer.notes import ControllerFacts, controller_notes, quote_untrusted
from atlas_reviewer.picker import (
    Depth,
    LensSelection,
    picker_instructions,
    select_lenses,
)
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    GitHubReader,
    Narrative,
    PickRequest,
    ReviewHarness,
    ReviewRequest,
    RunnerLedger,
    SpritesApi,
)
from atlas_reviewer.prompt import RepoText, UntrustedBlock
from atlas_reviewer.redact import RedactedText, Redactor
from atlas_reviewer.runner import (
    DEFAULT_TOOLS,
    FIRST_FRAME_BUDGET_S,
    RunnerJob,
    ToolResult,
    ToolSpec,
    run_disposable,
)
from atlas_reviewer.telemetry import Telemetry
from atlas_reviewer.verdict import (
    FileCoverage,
    ReviewEvent,
    Unreviewed,
    Verdict,
    combine,
    decide,
    proposed_event,
)

MAX_MODEL_CALLS = 3
PROMPT_TOKEN_ROOM = prompt_token_room(CallLimits())
# A part can never hold more than the whole prompt room: the token bound
# counts at least one token per UTF-8 byte. Each review then shrinks parts
# to what fits beside its measured prompt (`_fit`).
DEFAULT_DIFF_CHARS_PER_CALL = PROMPT_TOKEN_ROOM
MIN_DIFF_CHARS_PER_CALL = 1_000
MAX_LISTED_PATHS = 100
MAX_PICKER_PATHS = 500
MAX_TARBALL_BYTES = 9 * 1024 * 1024


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
    depth: Depth = Depth.REVIEW
    prompt_tokens: int = PROMPT_TOKEN_ROOM

    def __post_init__(self) -> None:
        """`model_calls` covers the lens picker's call (unless the depth is
        triage or only one call is allowed) and one call per diff part, and
        retries come out of the same cap (the provider's
        `CallLimits.max_calls`), so a retry can leave a later part unreviewed."""
        if not 1 <= self.model_calls <= MAX_MODEL_CALLS:
            raise ValueError(f"model calls must be 1 to {MAX_MODEL_CALLS}")
        if self.diff_chars_per_call < MIN_DIFF_CHARS_PER_CALL:
            raise ValueError(
                f"diff characters per call must be at least {MIN_DIFF_CHARS_PER_CALL}"
            )
        for label, seconds in (
            ("deadline", self.deadline_s),
            ("first-frame", self.first_frame_s),
        ):
            if not (math.isfinite(seconds) and seconds > 0):
                raise ValueError(f"{label} seconds must be a positive finite number")


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


@dataclass(frozen=True)
class ReviewOutcome:
    draft: str
    verdict: Verdict


def review(event: PrEvent, deps: Deps, config: ReviewConfig) -> str:
    return run_review(event, deps, config).draft


def run_review(event: PrEvent, deps: Deps, config: ReviewConfig) -> ReviewOutcome:
    telemetry = deps.telemetry or Telemetry(
        deps.clock, scrub=lambda text: deps.redactor(text).text
    )
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
    diff = _fetch_diff(event, pull, deps, collected)
    _note_truncation(collected, "pull request body", pull.body, DETAIL_CHARS)
    issues = _issue_blocks(event, pull, deps, config, collected)
    lenses = _select_lenses(event, pull, diff, deps, config, telemetry)
    collected.notes.extend(n for n in (lenses.note,) if n)
    base = _Base(
        event,
        _pull_block(pull, deps),
        tuple(issues),
        evidence,
        ControllerFacts(
            runner,
            tuple(t.name for t in config.tools),
            tool_results,
            tuple(collected.omissions),
            plan_lenses(deps.lenses, lenses.choices, config.depth.limit),
            tuple(collected.notes),
        ),
        tuple(collected.links),
        deps.redactor,
        () if diff is None else diff.paths,
    )
    calls = config.model_calls - int(lenses.used_call)
    selection = None if diff is None else _fit(diff.text, calls, base, deps, config)
    parts = _narrate_parts(base, selection, deps, telemetry)
    secrets = None if diff is None else diff.secrets
    dropped = _dropped(base, selection)
    verdict = decide(_proposed(parts), _file_coverage(selection, parts, dropped))
    draft = render_draft(
        DraftInput(
            event=event,
            mode=config.mode,
            title=pull.title.text,
            evidence=evidence,
            links=base.links,
            controller_notes=(
                *_notes(base, selection),
                *_coverage_lines(selection, parts, dropped),
                *_secret_note(secrets),
            ),
            secrets=None if secrets is None else secrets.findings,
            lenses=base.facts.lenses.uses,
            narratives=parts,
            omissions=(*_omissions(base, selection), *_unreviewed_parts(parts)),
            model_usage=deps.harness.usage_lines(),
            redactions=_redaction_total(
                pull,
                collected.items,
                _shared(base, selection),
            ),
            generated_at=deps.clock.now(),
            telemetry=telemetry.events,
            verdict=verdict,
        )
    )
    # Check names, failure reasons, archive entry names and runner notes are
    # untrusted too, and the model saw the diff unredacted, so a value the
    # secret scan found is scrubbed wherever the narrative repeats it.
    flagged = () if secrets is None else secrets.values
    return ReviewOutcome(replace(deps.redactor, flagged=flagged)(draft).text, verdict)


def _proposed(parts: tuple[PartNarrative, ...]) -> ReviewEvent:
    return combine(
        [
            proposed_event(p.result.text.text)
            if p.model_reviewed and isinstance(p.result, Narrative)
            else None
            for p in parts
        ]
    )


def _file_coverage(
    sel: DiffSelection | None,
    parts: tuple[PartNarrative, ...],
    dropped: tuple[str, ...],
) -> FileCoverage:
    """Every changed file a model call did not review in full (D36). A file
    the selection planned into a part with no recorded narrative counts as
    unreviewed too, so a gap in the bookkeeping cannot read as coverage."""
    if sel is None:
        return FileCoverage(
            None,
            unknown="the diff was not fetched, or could not be tied to the event SHA",
        )
    narrated = [f for p in parts for f in p.files]
    unreviewed = [
        *(
            Unreviewed(f.path, _part_gap(p), f.tier.rank)
            for p in parts
            if not p.model_reviewed
            for f in p.files
        ),
        *(
            Unreviewed(
                f.path, "cut to fit one call, reviewed only in part", f.tier.rank
            )
            for p in parts
            if p.model_reviewed
            for f in p.files
            if f.cut
        ),
        *(
            Unreviewed(f.path, "its diff part was never sent", f.tier.rank)
            for part in sel.parts
            for f in part.files
            if not any(f is n for n in narrated)
        ),
        *(
            Unreviewed(f.path, "never sent to any model call", f.tier.rank)
            for f in sel.unseen
        ),
        *(
            Unreviewed(path, "dropped before any model call", risk_tier(path).rank)
            for path in dropped
        ),
    ]
    return FileCoverage(sel.total_files + len(dropped), tuple(unreviewed))


def _part_gap(p: PartNarrative) -> str:
    if p.simulated:
        return "offline provider, no model call"
    return "its diff part's model call returned no review"


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


@dataclass(frozen=True)
class _Fetched:
    """The diff as GitHub served it (D33: not redacted), every file path its
    headers name, and what the secret scan found in it."""

    text: str
    paths: tuple[str, ...]
    secrets: DiffSecrets


@dataclass(frozen=True)
class _Base:
    """Everything a model call's prompt is built from except the diff
    selection, which adds its own omission row to the evidence block and the
    controller notes. Prompts are rebuilt from this, so the size measured
    while fitting the diff is the size sent."""

    event: PrEvent
    pull: UntrustedBlock
    issues: tuple[UntrustedBlock, ...]
    evidence: tuple[Evidence, ...]
    facts: ControllerFacts
    links: tuple[Link, ...]
    redactor: Redactor
    diff_paths: tuple[str, ...] = ()


def _pull_block(pull: PullInfo, deps: Deps) -> UntrustedBlock:
    return UntrustedBlock(
        "pull-request", deps.redactor(f"Title: {pull.title.text}\n\n{pull.body.text}")
    )


def _omissions(base: _Base, sel: DiffSelection | None) -> tuple[Omission, ...]:
    return (
        *base.facts.omissions,
        *_selection_omission(sel),
        *_dropped_omission(_dropped(base, sel)),
    )


def _dropped(base: _Base, sel: DiffSelection | None) -> tuple[str, ...]:
    """Files the diff's headers name that the selection does not account for
    (sent in full, cut, or listed as unsent). Nothing between the fetch and
    the selection removes files today; this keeps the count honest if
    something ever does, as redaction once did (4 of #601's 23 files)."""
    if sel is None:
        return ()
    seen = {f.path for f in (*sel.full, *sel.cut, *sel.unseen)}
    return tuple(p for p in base.diff_paths if p not in seen)


def _dropped_omission(dropped: tuple[str, ...]) -> tuple[Omission, ...]:
    if not dropped:
        return ()
    detail = (
        f"{len(dropped)} file(s) dropped before any model call, not reviewed: "
        f"{_listed(dropped)}"
    )
    return (Omission("pull request diff", "dropped before the model calls", detail),)


def _notes(base: _Base, sel: DiffSelection | None) -> tuple[str, ...]:
    return controller_notes(replace(base.facts, omissions=_omissions(base, sel)))


def _shared(base: _Base, sel: DiffSelection | None) -> _Shared:
    text = render_evidence(base.evidence, _omissions(base, sel), base.links)
    evidence = UntrustedBlock("ci-and-runner-evidence", base.redactor(text))
    return _Shared(base.pull, evidence, base.issues)


def _part_blocks(
    shared: _Shared, part: DiffPart, notes: tuple[str, ...], redactor: Redactor
) -> tuple[UntrustedBlock, ...]:
    diff = RepoText(part.text or "(no diff content in this call)")
    notes_text = redactor("\n".join(f"- {n}" for n in notes))
    return (
        shared.pull,
        UntrustedBlock("diff", diff),
        shared.evidence,
        UntrustedBlock("controller-notes", notes_text),
        *shared.issues,
    )


def _requests(
    base: _Base, sel: DiffSelection
) -> tuple[tuple[DiffPart, ReviewRequest], ...]:
    """One request per part, in risk order. An empty but fetched diff still
    gets one call."""
    shared, notes = _shared(base, sel), _notes(base, sel)
    parts = sel.parts or (DiffPart(()),)
    plan = base.facts.lenses

    def request(index: int, part: DiffPart) -> ReviewRequest:
        note = _part_note(index, len(parts), part, sel)
        return ReviewRequest(
            base.event.repo,
            base.event.pr_number,
            base.event.head_sha,
            _part_blocks(shared, part, (*notes, note), base.redactor),
            plan.loaded,
            plan.coverage(),
        )

    return tuple((p, request(i, p)) for i, p in enumerate(parts, 1))


def _fetch_diff(
    event: PrEvent, pull: PullInfo, deps: Deps, collected: Collected
) -> _Fetched | None:
    """The redacted diff, or None when it could not be fetched or cannot be
    tied to the event SHA: then no model call is made, because a review of
    an empty diff reads as a clean one. The diff endpoint serves the PR's
    current head, so the head is checked before and after the fetch."""
    if pull.head_sha != event.head_sha:
        _no_diff(collected, "the PR head is no longer the event SHA")
        return None
    try:
        raw = deps.github.get_pull_diff(event.repo, event.pr_number)
        after = parse_pull(
            deps.github.get_pull(event.repo, event.pr_number), deps.redactor
        )
    except BoundaryError as exc:
        collected.notes.append(
            f"The PR diff could not be fetched, so no model call was made "
            f"(error, quoted: {quote_untrusted(str(exc))})."
        )
        collected.omit(
            "pull request diff", "fetch failed", "not fetched; nothing was reviewed"
        )
        return None
    if after.head_sha != event.head_sha:
        _no_diff(collected, "the PR head moved while the diff was fetched")
        return None
    return _Fetched(raw, diff_paths(raw), scan_diff(raw))


def _listed(paths: tuple[str, ...]) -> str:
    more = len(paths) - MAX_LISTED_PATHS
    shown = ", ".join(paths[:MAX_LISTED_PATHS])
    return f"{shown} and {more} more" if more > 0 else shown


def _no_diff(collected: Collected, reason: str) -> None:
    collected.notes.append(
        f"The diff was not reviewed: {reason}, so it may not be the diff at "
        f"that SHA. No model call was made."
    )
    collected.omit(
        "pull request diff",
        "head SHA mismatch",
        "not tied to the event SHA; not reviewed",
    )


def _select_lenses(
    event: PrEvent,
    pull: PullInfo,
    diff: _Fetched | None,
    deps: Deps,
    config: ReviewConfig,
    telemetry: Telemetry,
) -> LensSelection:
    """The picker gets a call only when one is left for at least one diff part,
    and `select_lenses` skips it when no picked lens could fit; an unspent
    call goes to diff review."""
    if diff is None:
        return LensSelection((), "", used_call=False)
    if config.model_calls < 2:
        return select_lenses(config.depth, None, deps.lenses)
    paths = diff_paths(diff.text)
    request = PickRequest(
        event.repo,
        event.pr_number,
        event.head_sha,
        picker_instructions(config.depth),
        (_pull_block(pull, deps), _paths_block(paths)),
    )
    return select_lenses(
        config.depth,
        lambda: telemetry.span(
            "model call",
            "lens picker",
            lambda: deps.harness.pick(request),
            {"paths": len(paths)},
        ),
        deps.lenses,
    )


def _paths_block(paths: tuple[str, ...]) -> UntrustedBlock:
    shown = "\n".join(paths[:MAX_PICKER_PATHS])
    more = len(paths) - MAX_PICKER_PATHS
    tail = f"\n(and {more} more changed paths)" if more > 0 else ""
    return UntrustedBlock(
        "changed-paths", RepoText(shown + tail or "(no changed paths)")
    )


def _fit(
    text: str, calls: int, base: _Base, deps: Deps, config: ReviewConfig
) -> DiffSelection:
    def overflow(sel: DiffSelection) -> int:
        biggest = max(deps.harness.prompt_tokens(r) for _, r in _requests(base, sel))
        return biggest - config.prompt_tokens

    return fit_diff(
        text, calls, config.diff_chars_per_call, overflow, MIN_DIFF_CHARS_PER_CALL
    )


def _selection_omission(sel: DiffSelection | None) -> tuple[Omission, ...]:
    if sel is None or sel.complete:
        return ()
    limit = (
        f"too large for one review pass: {len(sel.parts)} part(s) of at most "
        f"{sel.part_chars} characters, risk-ordered"
    )
    return (Omission("pull request diff", limit, _selection_detail(sel)),)


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
        collected.notes.append(
            f"Issue #{number} could not be fetched (error, quoted: "
            f"{quote_untrusted(str(exc))})."
        )
        return None
    text = f"Title: {issue.get('title', '')}\n\n{issue.get('body') or ''}"
    redacted = deps.redactor(text, DETAIL_CHARS)
    _note_truncation(collected, f"issue #{number}", redacted, DETAIL_CHARS)
    return UntrustedBlock(f"issue-{number}", redacted)


def _narrate_parts(
    base: _Base,
    selection: DiffSelection | None,
    deps: Deps,
    telemetry: Telemetry,
) -> tuple[PartNarrative, ...]:
    """One model call per part, in risk order. A part whose call fails or is
    refused (call cap, cost cap, token bound) still yields a `PartNarrative`,
    so its files are reported as unreviewed rather than dropped. No diff, no
    call."""
    if selection is None:
        return ()
    requests = _requests(base, selection)
    total = len(requests)
    return tuple(
        _narrate_part(i, total, part, request, deps, telemetry)
        for i, (part, request) in enumerate(requests, 1)
    )


def _part_note(index: int, total: int, part: DiffPart, sel: DiffSelection) -> str:
    """File paths are chosen by the PR author, so each is quoted as data."""
    files = ", ".join(
        f"{quote_untrusted(f.path)}{' (cut)' if f.cut else ''}" for f in part.files
    )
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
        f"{part.chars} characters; PR-controlled file paths, quoted: "
        f"{files or 'none'}.{others}{unseen}"
    )


def _narrate_part(
    index: int,
    total: int,
    part: DiffPart,
    request: ReviewRequest,
    deps: Deps,
    telemetry: Telemetry,
) -> PartNarrative:
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
    sel: DiffSelection | None,
    parts: tuple[PartNarrative, ...],
    dropped: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if sel is None:
        return (
            (
                "Diff coverage: NOT REVIEWED. The diff was not fetched, or could "
                "not be tied to the event SHA, and no model call was made."
            ),
        )
    reviewed = [p for p in parts if p.reviewed]
    full = sum(1 for p in reviewed for f in p.files if not f.cut)
    cut = sum(1 for p in reviewed for f in p.files if f.cut)
    if parts and all(p.simulated for p in reviewed):
        line = (
            "Diff coverage: NOT REVIEWED. The offline provider built the prompt(s) "
            f"for {len(parts)} part(s) without calling a model, so no model "
            "reviewed the diff."
        )
    else:
        complete = sel.complete and not dropped and len(reviewed) == len(parts)
        verdict = "complete" if complete else "PARTIAL"
        line = (
            f"Diff coverage after the model calls: {verdict}. {len(reviewed)} of "
            f"{len(parts)} call(s) returned a review, covering {full} of "
            f"{sel.total_files + len(dropped)} file(s) in full and {cut} cut to fit; "
            f"{len(sel.unseen) + len(dropped)} file(s) went to no call."
        )
    too_large = (
        "The diff is too large for one review pass: the files cut and the files "
        "never sent are listed in the omissions table, highest risk first."
    )
    removed = (
        f"{len(dropped)} file(s) were dropped from the diff before any model "
        "call; they are listed in the omissions table and were not reviewed."
    )
    return (
        line,
        *(() if sel.complete else (too_large,)),
        *((removed,) if dropped else ()),
    )


def _unreviewed_parts(parts: tuple[PartNarrative, ...]) -> tuple[Omission, ...]:
    return tuple(
        Omission(
            f"pull request diff, part {p.index} of {p.total}",
            "offline provider (no model call)"
            if p.simulated
            else "model call returned no review",
            f"{len(p.files)} file(s) sent but not reviewed: "
            f"{describe_by_risk(p.files, MAX_LISTED_PATHS) or 'none'}",
        )
        for p in parts
        if not p.model_reviewed
    )


def _redaction_total(pull: PullInfo, items: list[EvidenceItem], shared: _Shared) -> int:
    inner = pull.title.redaction_count + pull.body.redaction_count
    return (
        inner
        + sum(i.detail.redaction_count for i in items)
        + sum(
            b.content.redaction_count
            for b in shared.blocks
            if isinstance(b.content, RedactedText)
        )
    )


def _secret_note(secrets: DiffSecrets | None) -> tuple[str, ...]:
    if secrets is None:
        return ()
    return (
        (
            "Secret scan of the diff, which is sent to the model unredacted: "
            f"{len(secrets.findings)} possible committed secret(s), listed by file "
            "and line under Possible committed secrets. Values are never shown."
        ),
    )
