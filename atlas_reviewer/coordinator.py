# SPDX-License-Identifier: MIT
"""The agentic coordinator: run the selected lenses under the attestation
ledger, verify their output and synthesize one draft (D31, D34, D44).

`review_lens` runs one lens. `review_lenses` runs every selected lens,
up to the configured pool, then gives each lens a continuation of its
own for the files it left unread while a call and the review clock
remain. The synthesis is mechanical: the controller mints
`L<lens>-F<n>` IDs, ranks the verified findings by severity and sets
the verdict from them (D55). An introduced Blocker requests changes.
An introduced Major or Minor means approve with changes. Only nits, or
nothing, means approve. There is no model merge call yet.

Coverage is complete only when every lens read every changed file's
diff in full, through its own attempts or its own continuations (D42:
a read by another lens does not cover a file for this one), no lens
failed for another cause, and, when this review ran a runner, every
runner completed. A lens with any clean run of its own is covered
however its other entries ended (#692): a continuation after a
failed or never-started run supersedes that failure for coverage, a
later failure does not undo an earlier clean run, and the failure
stays in the draft as a recovered note. A single-lens
result with no assigned scope keeps the
older rule: that lens itself must be clean and have read every file.
A runner whose delete was not verified does not block approval, but the
draft names it so it can be swept.
A keepalive failure is a failed runner, so a clean lens cannot approve
it away. A lens that left a changed file unread is partial, so the same
rule applies. Anything less fails closed:
the draft opens with the machine-readable status line
(`coverage_complete: false`) and a REVIEW INCOMPLETE warning, and never
approves. The runner's own note is in the draft when it did not complete.

Retries come from the ledger alone (`attestation.next_step`). A lens
already settled for this head and body is reused without a runner, and a
review that stopped mid-attempt resumes its attempt count. A BYOK refusal
is finished as a model error before it leaves the loop: the attempt keeps
the turns, tool calls and committed secrets already seen, the outcome is
not retried, and the runner fails, so the next review of this head does
not make another billed call.

D73: a reused settled result keeps its findings -- newer CI evidence or
newer comments never discard them -- and, when the evidence snapshot this
review gathered differs from the digest stored with the settled result,
the lens earns one bounded re-assessment call that sees its prior findings
plus this review's context blocks, and may add, revise or withdraw
findings, a withdrawal or revision always with its stated reason. A
withdrawal is an annotation, not a deletion (round-1 review of #731, M2):
the prior finding stays in the set the verdict is computed over, and so
does a revision that lowers a Blocker's or a Major's severity, so an
injected comment can lower a finding's visibility but never flip a Blocker
review to approve; the status line carries the withdrawn count. The
re-assessment's attempts live on the lens's `#reassess` ledger key, so the
lens's own settled state is never overwritten by a supplementary reply,
and the effective result is composed from the ledger alone on every
review. A settled result that was not attested -- a lens that never
produced a usable judgment -- re-runs through the ordinary retry policy
instead, and earns no re-assessment: there are no prior findings to keep,
and a single no-tools call is not a lens run.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from atlas_reviewer.agentic_config import load_agentic_limits
from atlas_reviewer.attestation import (
    Attempt,
    AttemptLedger,
    AttemptOutcome,
    Attestation,
    Cause,
    CheckedFinding,
    LensKey,
    LensState,
    RunAttempt,
    Settled,
    ToolUse,
    body_digest,
    next_step,
)
from atlas_reviewer.bridge import Bridge, BridgeSecret, run_bridge
from atlas_reviewer.bridge_staging import BRIDGE_ROOT, SourceTrees
from atlas_reviewer.cache_stats import CacheSession, by_label, session_lines
from atlas_reviewer.committed_secrets import DiffSecrets, scan_diff
from atlas_reviewer.diffs import by_risk, risk_tier, split_files
from atlas_reviewer.domain import (
    CleanupStatus,
    Omission,
    PrEvent,
    RunnerReport,
    RunnerStatus,
)
from atlas_reviewer.keepalive import SOCKET_PATH, lens_hold
from atlas_reviewer.lens_contract import ContractError, Finding, Severity
from atlas_reviewer.lens_loop import (
    AgenticLimits,
    Derivation,
    FinalReply,
    LensJob,
    LensModel,
    Limits,
    Spend,
    TurnRequest,
    UserText,
    _refusal_cause,
    _reserve_call,
    _Reserved,
    finding_contract,
    retry_reasons,
    run_attempt,
)
from atlas_reviewer.lenses import LensLibrary
from atlas_reviewer.limit_stop import LimitHit
from atlas_reviewer.notes import quote_untrusted, recovered_note
from atlas_reviewer.openrouter import OpenRouterProvider
from atlas_reviewer.ports import (
    BoundaryError,
    ByokRefusedError,
    Clock,
    RunnerLedger,
    SpritesApi,
    TransportError,
)
from atlas_reviewer.prompt import RepoText, UntrustedBlock, fence
from atlas_reviewer.quotes import QuoteSource, drift_label, read_sources
from atlas_reviewer.reassess import (
    REASSESS_SUFFIX,
    Withdrawn,
    effective_outcome,
    judge,
    parse_reassess_reply,
    prior_findings_block,
    reassess_system,
    reassess_turn,
)
from atlas_reviewer.redact import Redactor
from atlas_reviewer.review_wide import derive_review_wide, review_md_ceiling
from atlas_reviewer.rounds import (
    PRIOR_ROUND_CHARS,
    SOURCE,
    RoundLog,
    RoundRecord,
    UnreadableLine,
    fit_record,
    prior_blocks,
    records_for,
)
from atlas_reviewer.runner import (
    DEFAULT_CREATE_RETRIES,
    CreateRefusedError,
    event_runner_name,
    lens_runner_name,
)
from atlas_reviewer.telemetry import Telemetry
from atlas_reviewer.tool_model import OpenRouterLensModel
from atlas_reviewer.tracing import (
    ReviewTrace,
    acquire_shared,
    current_review,
    limit_label,
    opening_trace,
    release_shared,
    submit_with_review_context,
)
from atlas_reviewer.verdict import STATUS_PREFIX, ReviewEvent

QUOTED_CHARS = 600
EVIDENCE_CHARS = 1_200
NONCE_BYTES = 8
# Continuation rounds per review. Each round re-runs the lenses that still
# have unread files; a round that does not shrink the gap ends it earlier.
MAX_CONTINUATIONS = 4
HALTED_REASON = (
    "not started: an earlier call in this review stopped it (BYOK or a failed lens)"
)
LATE_REASON = "not started: the review deadline had passed"
NO_BODY_REASON = "no lens body in the bundle"

# ----------------------------------------------------------------- results


@dataclass(frozen=True)
class LensResult:
    """One selected lens, as the ledger leaves it. `outcome` is None only
    when no attempt was recorded (NOT RUN, with `reason`). `retry_pending`
    means the last attempt was retryable but the review ended before its
    retry ran; a retryable outcome is never clean. The next review of
    this head and body runs that retry."""

    lens: str
    index: int
    body_sha256: str | None
    outcome: AttemptOutcome | None
    attempts: int = 0
    escalated: bool = False
    retry_pending: bool = False
    reason: str = ""
    scope: frozenset[str] | None = None
    """Changed paths this lens was asked to read. None keeps the older
    rule: any unread path on any lens blocks approval."""
    withdrawn: tuple[Withdrawn, ...] = ()
    """Prior findings a recorded re-assessment (D73) removed, each with
    its stated reason and, for a revision, the finding that replaces it.
    Empty on a lens that ran, and on a reuse with no re-assessment."""
    reassess_note: str = ""
    """Controller text about the re-assessments (D73) recorded for this
    reused result, for the lens line; empty when there were none."""

    @property
    def state(self) -> LensState:
        return LensState.NOT_RUN if self.outcome is None else self.outcome.state


@dataclass(frozen=True)
class MintedFinding:
    id: str
    lens: str
    finding: Finding
    verified: bool
    source: str
    problem: str = ""
    # A verified window match's line distance from the citation (D64); 0
    # otherwise. The draft builds the source tag from it.
    drift: int = 0


class Verdict(StrEnum):
    BLOCK = "block"
    APPROVE_WITH_CHANGES = "approve with changes"
    APPROVE = "approve"


_EVENT = {
    Verdict.BLOCK: ReviewEvent.REQUEST_CHANGES,
    Verdict.APPROVE_WITH_CHANGES: ReviewEvent.COMMENT,
    Verdict.APPROVE: ReviewEvent.APPROVE,
}


@dataclass(frozen=True)
class AgenticReview:
    lenses: tuple[LensResult, ...]
    findings: tuple[MintedFinding, ...]
    verdict: Verdict
    secrets: tuple[BridgeSecret, ...] = ()
    runner: RunnerReport | None = None
    committed_usd: str = "0"
    model_calls: int = 0
    flagged: tuple[str, ...] = field(default=(), repr=False)
    changed: frozenset[str] | None = None
    """The PR's changed paths. When set, every lens is held to all of
    them, whatever scope it was assigned."""
    runners: tuple[RunnerReport, ...] = ()
    """Every lens runner's report, so an unverified delete is named."""
    selection_note: str = ""
    not_picked: tuple[tuple[str, str], ...] = ()
    """Picked names that did not run, with why."""
    context_omissions: tuple[Omission, ...] = ()
    other_pull_requests: int = 0
    trace_id: str = ""
    round_log_note: str = ""
    ceiling_note: str = ""
    """Controller text about the review's dollar ceiling (D68), non-empty
    only when the reviewed repo's merge-base REVIEW.md carried a
    `review_ceiling_usd:` line that could not be used (round-1 review of
    #717, m-5), so a meant ceiling that silently fell back to the default
    is visible in the draft."""

    @property
    def unreviewed_paths(self) -> tuple[str, ...]:
        return _unread_paths(self)

    @property
    def coverage_complete(self) -> bool:
        """Clean lenses that read every changed file, and a completed runner
        when this review started one.

        A settled lens reused from the ledger has no runner. A runner that
        failed after a clean lens (a keepalive refresh or delete, for
        example) is not complete coverage, so the review cannot approve.
        Unread paths block approval even when a lens's state was recorded
        clean, so a missing cause cannot approve a partial read. An outcome
        with no changed-file count predates the per-file gate and shows no
        coverage, so it blocks approval too. Context that was left out of
        the first turn, or a prior-round record for this pull request
        and this head that did not fit, is the same kind of gap: the
        review cannot approve on a partial picture of this head. So is a
        finding dropped for an unknown severity, which could have been a
        Blocker. A superseded round, and a line that names another pull request
        or no pull request, are not that gap. A lens is held to its own
        entries only (#692): one clean run of that lens covers it, however
        its other entries -- an earlier NOT RUN, a later NOT RUN -- ended;
        the failures stay in the draft, marked recovered."""
        if _lens_gap(self):
            return False
        return self.runner is None or self.runner.status is RunnerStatus.COMPLETED

    @property
    def proposed_event(self) -> ReviewEvent:
        return _EVENT[self.verdict]

    @property
    def event(self) -> ReviewEvent:
        proposed = self.proposed_event
        if proposed is ReviewEvent.APPROVE and not self.coverage_complete:
            return ReviewEvent.COMMENT
        return proposed

    @property
    def verified(self) -> tuple[MintedFinding, ...]:
        return tuple(f for f in self.findings if f.verified)

    @property
    def unverified(self) -> tuple[MintedFinding, ...]:
        return tuple(f for f in self.findings if not f.verified)


def mint(lenses: Sequence[LensResult]) -> tuple[MintedFinding, ...]:
    """IDs in each attested lens's findings order, verified or not -- the
    last attempt's reply order, with the earlier attempts' carried
    verified findings appended (#691). An attempt that is not attested
    contributes nothing, whatever it carries."""
    minted = []
    for result in lenses:
        if (
            result.outcome is None
            or result.outcome.attestation is not Attestation.ATTESTED
        ):
            continue
        for n, checked in enumerate(result.outcome.findings, start=1):
            minted.append(
                MintedFinding(
                    f"L{result.index}-F{n}",
                    result.lens,
                    checked.finding,
                    checked.verified,
                    "" if checked.source is None else checked.source.value,
                    checked.problem,
                    checked.drift,
                )
            )
    return tuple(minted)


def rank(findings: Sequence[MintedFinding]) -> tuple[MintedFinding, ...]:
    """Severity first (a Blocker floats to the top), then verdict-setting
    before not, then the minted order."""
    order = {f.id: i for i, f in enumerate(findings)}
    return tuple(
        sorted(
            findings,
            key=lambda f: (
                f.finding.severity.rank,
                not f.finding.sets_verdict,
                order[f.id],
            ),
        )
    )


def decide(findings: Sequence[MintedFinding]) -> Verdict:
    """From the verified verdict-setting findings: only an introduced
    defect sets the verdict. A Blocker requests changes. A Major or a
    Minor means approve with changes (D55)."""
    setting = [
        f.finding.severity for f in findings if f.verified and f.finding.sets_verdict
    ]
    if any(s.rank <= Severity.BLOCKER.rank for s in setting):
        return Verdict.BLOCK
    if any(s is Severity.MAJOR or s is Severity.MINOR for s in setting):
        return Verdict.APPROVE_WITH_CHANGES
    return Verdict.APPROVE


def synthesize(
    lenses: Sequence[LensResult],
    secrets_found: Sequence[BridgeSecret] = (),
    runner: RunnerReport | None = None,
    spend: Spend | None = None,
    flagged: Sequence[str] = (),
    context_omissions: Sequence[Omission] = (),
    other_pull_requests: int = 0,
    ceiling_note: str = "",
) -> AgenticReview:
    findings = rank(mint(lenses))
    return AgenticReview(
        tuple(lenses),
        findings,
        decide(findings),
        tuple(dict.fromkeys(secrets_found)),
        runner,
        "0" if spend is None else str(spend.committed_usd),
        0 if spend is None else spend.calls,
        tuple(dict.fromkeys(flagged)),
        context_omissions=tuple(context_omissions),
        other_pull_requests=other_pull_requests,
        ceiling_note=ceiling_note,
    )


# --------------------------------------------------------------- the review


@dataclass
class _Session:
    """What the runner session leaves behind for synthesis."""

    bridges: list[Bridge] = field(default_factory=list)
    secrets: list[BridgeSecret] = field(default_factory=list)

    def flagged(self) -> tuple[str, ...]:
        return tuple(v for b in self.bridges for v in b.flagged())


def limits_for_lens(env: Mapping[str, str], **flags: str | None) -> AgenticLimits:
    """The limits one lens run uses. A flag wins over its `ATLAS_*` variable.

    This is the reader `review_lens` is given. The one-shot `review`
    command does not call it, so those settings cannot refuse that path.
    """
    return load_agentic_limits(env, **flags)


def model_for_lens(
    provider: OpenRouterProvider, limits: AgenticLimits
) -> OpenRouterLensModel:
    """The live adapter bound to the same resolved limits as the loop.
    The cross-limit relations are not the adapter's to check: the review's
    derivation re-checks them against the totals it derives (D68)."""
    return OpenRouterLensModel(provider, per_call=limits.resolve(cross_limits=False))


def review_lens(
    event: PrEvent,
    lens: str,
    diff: str,
    trees: SourceTrees,
    *,
    library: LensLibrary,
    model: LensModel,
    limits: AgenticLimits,
    ledger: AttemptLedger,
    sprites: SpritesApi,
    runner_ledger: RunnerLedger,
    redactor: Redactor,
    clock: Clock,
    context: Sequence[UntrustedBlock] = (),
    context_omissions: Sequence[Omission] = (),
    round_log: RoundLog | None = None,
    prior_chars: int = PRIOR_ROUND_CHARS,
    telemetry: Telemetry | None = None,
    nonce: Callable[[], str] = lambda: secrets.token_hex(NONCE_BYTES),
    bridge_root: str = BRIDGE_ROOT,
    contract: str | None = None,
    task_socket: str = SOCKET_PATH,
    trace: ReviewTrace | None = None,
    evidence_digest: str | None = None,
) -> AgenticReview:
    """Review `event` with one lens. The limits are resolved before any
    model, runner or ledger work. Brandon's provisional defaults are
    accepted. A limit cleared to unset is refused outright
    (`LimitsUnsetError`). A model that names its own `per_call` bounds
    must name these; a different set is refused before any of that work.
    A model that names none is not checked. The runner holds a Sprite
    task for the length of the lens and deletes it on the way out.

    Spans are recorded when `trace` is passed, or when
    `ATLAS_OTEL_ENDPOINT` is set in the environment. With neither, no
    exporter is built. JSONL telemetry is unchanged. `evidence_digest` is
    D73's evidence-snapshot digest: when given, a reused settled lens is
    checked for newer evidence and re-assessed when it has some."""
    resolved = limits.resolve()
    declared = getattr(model, "per_call", None)
    if declared is not None and declared != resolved:
        raise ValueError("the model's per-call limits differ from this review's limits")

    def one(active: ReviewTrace) -> AgenticReview:
        blocks, omissions, other_pull_requests = _review_context(
            event, context, context_omissions, round_log, prior_chars, redactor
        )
        ran = _traced_lens(
            active,
            event,
            lens,
            diff,
            trees,
            library=library,
            model=model,
            limits=limits,
            ledger=ledger,
            sprites=sprites,
            runner_ledger=runner_ledger,
            redactor=redactor,
            clock=clock,
            context=blocks,
            telemetry=telemetry,
            fence_nonce=nonce(),
            bridge_root=bridge_root,
            contract=contract,
            task_socket=task_socket,
            index=1,
            evidence_digest=evidence_digest,
        )
        single = synthesize(
            [ran.result],
            ran.secrets,
            ran.report,
            ran.spend,
            ran.flagged,
            context_omissions=omissions,
            other_pull_requests=other_pull_requests,
        )
        return _record_round(round_log, event, single, redactor)

    return _traced_review(event, trace, redactor, one)


def review_lenses(
    event: PrEvent,
    lenses: Sequence[str],
    diff: str,
    trees: SourceTrees,
    *,
    library: LensLibrary,
    model: LensModel,
    limits: AgenticLimits,
    ledger: AttemptLedger,
    sprites: SpritesApi,
    runner_ledger: RunnerLedger,
    redactor: Redactor,
    clock: Clock,
    context: Sequence[UntrustedBlock] = (),
    context_omissions: Sequence[Omission] = (),
    round_log: RoundLog | None = None,
    prior_chars: int = PRIOR_ROUND_CHARS,
    telemetry: Telemetry | None = None,
    nonce: Callable[[], str] = lambda: secrets.token_hex(NONCE_BYTES),
    bridge_root: str = BRIDGE_ROOT,
    contract: str | None = None,
    task_socket: str = SOCKET_PATH,
    model_for: Callable[[], LensModel] | None = None,
    picker_spend: tuple[int, Decimal] = (0, Decimal(0)),
    trace: ReviewTrace | None = None,
    evidence_digest: str | None = None,
) -> AgenticReview:
    """Run every named lens, up to `pool_size` at once, then one combined
    verdict. Each lens gets its own runner name. A changed file a lens
    left unread is handed back to that same lens as a continuation, for up
    to `MAX_CONTINUATIONS` rounds, while a call and the review clock remain.
    Partial coverage still cannot approve. `picker_spend` is the calls and
    dollars the lens picker already committed; they count toward this
    review's `max_calls` and `reservation_usd`.

    One review span covers every lens, and each lens run, pooled or a
    continuation, is a lens span under it. Spans are recorded as
    `review_lens` describes. One fence nonce covers the review (D65):
    every lens's shared diff prefix fences the diff with it, so the
    prefixes are byte-identical and the lenses share one cached block.

    D68: the review-wide limits are derived from the planned lens count
    (`len(lenses)`) and the picker's committed spend, under the absolute
    per-review dollar ceiling -- the reviewed repo's merge-base `REVIEW.md`
    value when it sets one, else the configured ceiling, else the default.
    The derivation happens before any lens runs, so a configuration it
    refuses stops the review before any lens runs; the CLI validates the
    same refusals before its picker spends (round-1 review of #717, m-3).

    D73: `evidence_digest` is the digest of the evidence snapshot this
    review gathered (the CI block's and the conversation's gathered data,
    `reassess.snapshot_digest`). It is stored with every attempt this
    review finishes, and a reused settled lens whose stored digest differs
    from it -- or that carries none -- earns one bounded re-assessment call
    against this review's shared spend and wall clock."""
    read = review_md_ceiling(trees.base)
    derived, derivation = derive_review_wide(
        limits,
        len(lenses),
        picker_spend[0],
        picker_spend[1],
        repo_ceiling=read.value,
        repo_ceiling_note=read.note,
    )
    return _traced_review(
        event,
        trace,
        redactor,
        lambda active: _review_lenses(
            active,
            event,
            lenses,
            diff,
            trees,
            library=library,
            model=model,
            limits=limits,
            ledger=ledger,
            sprites=sprites,
            runner_ledger=runner_ledger,
            redactor=redactor,
            clock=clock,
            context=context,
            context_omissions=context_omissions,
            round_log=round_log,
            prior_chars=prior_chars,
            telemetry=telemetry,
            nonce=nonce,
            bridge_root=bridge_root,
            contract=contract,
            task_socket=task_socket,
            model_for=model_for,
            resolved=derived,
            derivation=derivation,
            picker_spend=picker_spend,
            evidence_digest=evidence_digest,
        ),
    )


def _review_lenses(
    trace: ReviewTrace,
    event: PrEvent,
    lenses: Sequence[str],
    diff: str,
    trees: SourceTrees,
    *,
    library: LensLibrary,
    model: LensModel,
    limits: AgenticLimits,
    ledger: AttemptLedger,
    sprites: SpritesApi,
    runner_ledger: RunnerLedger,
    redactor: Redactor,
    clock: Clock,
    context: Sequence[UntrustedBlock],
    context_omissions: Sequence[Omission],
    round_log: RoundLog | None,
    prior_chars: int,
    telemetry: Telemetry | None,
    nonce: Callable[[], str],
    bridge_root: str,
    contract: str | None,
    task_socket: str,
    model_for: Callable[[], LensModel] | None,
    resolved: Limits,
    derivation: Derivation,
    picker_spend: tuple[int, Decimal],
    evidence_digest: str | None,
) -> AgenticReview:
    changed = frozenset(f.path for f in split_files(diff))
    blocks, omissions, other_pull_requests = _review_context(
        event, context, context_omissions, round_log, prior_chars, redactor
    )
    # One fence nonce per review (D65): the shared diff prefix fences the
    # diff with it, so every lens's prefix is byte-identical and the
    # lenses share one cached block.
    fence_nonce = nonce()
    # `resolved` is D68's derived review-wide limits: the Spend and the
    # review deadline run on them, and a limit stop names their derivation.
    # The picker's committed dollars are settled spend -- real dollars, not
    # a worst case waiting to come down -- so the in-flight backpressure
    # does not wait on them.
    spend = Spend(
        resolved,
        picker_spend[0],
        picker_spend[1],
        derivation=derivation,
        settled_usd=picker_spend[1],
    )
    started = clock.monotonic()
    deadline = started + resolved.review_wall_s
    runs: list[_LensRun] = []

    def run(lens: str, assigned: frozenset[str], index: int) -> _LensRun:
        if spend.halted:
            return _not_run(trace, lens, index, assigned, HALTED_REASON, spend)
        if clock.monotonic() >= deadline:
            return _not_run(trace, lens, index, assigned, LATE_REASON, spend)
        try:
            return _run_lens(lens, assigned, index)
        except CreateRefusedError as exc:
            # A capacity refusal on one lens's runner is that lens's
            # problem (#690): the review keeps every other lens's result,
            # and this one is NOT RUN with why, so the draft cannot approve.
            return _not_run(trace, lens, index, assigned, str(exc), spend)
        except BaseException:
            spend.halt()
            raise

    def _run_lens(lens: str, assigned: frozenset[str], index: int) -> _LensRun:
        return _traced_lens(
            trace,
            event,
            lens,
            diff,
            trees,
            library=library,
            model=model if model_for is None else model_for(),
            limits=limits,
            ledger=ledger,
            sprites=sprites,
            runner_ledger=runner_ledger,
            redactor=redactor,
            clock=clock,
            context=blocks,
            telemetry=telemetry,
            fence_nonce=fence_nonce,
            bridge_root=f"{bridge_root}-{index}",
            contract=contract,
            task_socket=task_socket,
            index=index,
            assigned=assigned,
            spend=spend,
            review_started=started,
            review_deadline=deadline,
            runner_name=lens_runner_name(event, f"{lens}:{index}"),
            continuation=index > len(names),
            create_gate=gate,
            create_retries=resolved.create_retries,
            evidence_digest=evidence_digest,
        )

    names = tuple(lenses)
    gate = threading.BoundedSemaphore(resolved.create_concurrency)
    with ThreadPoolExecutor(max_workers=resolved.pool_size) as pool:
        futures = [
            submit_with_review_context(pool, run, lens, changed, index)
            for index, lens in enumerate(names, start=1)
        ]
        for future in futures:
            runs.append(future.result())
    for _ in range(MAX_CONTINUATIONS):
        if spend.halted:
            break
        results = tuple(ran.result for ran in runs)
        pending = {
            lens: paths
            for lens, paths in _pending_by_lens(results, changed).items()
            if library.body(lens) is not None
        }
        if (
            not pending
            or spend.calls >= resolved.max_calls
            or clock.monotonic() >= deadline
        ):
            break
        before = _pending_pairs(pending)
        for lens, paths in pending.items():
            runs.append(run(lens, paths, len(runs) + 1))
        after = {
            lens: paths
            for lens, paths in _pending_by_lens(
                tuple(ran.result for ran in runs), changed
            ).items()
            if library.body(lens) is not None
        }
        if not before - _pending_pairs(after):
            break
    secrets = [secret for ran in runs for secret in ran.secrets]
    flagged = tuple(value for ran in runs for value in ran.flagged)
    reports = tuple(ran.report for ran in runs if ran.report is not None)
    review = synthesize(
        [ran.result for ran in runs],
        secrets,
        _combined_runner(reports),
        spend,
        flagged,
        context_omissions=omissions,
        other_pull_requests=other_pull_requests,
        ceiling_note=derivation.ceiling_note,
    )
    return _record_round(
        round_log, event, replace(review, changed=changed, runners=reports), redactor
    )


def _traced_review(
    event: PrEvent,
    trace: ReviewTrace | None,
    redactor: Redactor,
    body: Callable[[ReviewTrace], AgenticReview],
) -> AgenticReview:
    """Run `body` under one review span, or under the caller's open one.
    A caller that opened the span sets `atlas.review_event` itself, after
    any change it makes to the event."""
    if trace is None:
        acquire_shared()
    try:
        active = opening_trace(trace, lambda text: redactor(text).text)
        outer = current_review()
        if outer is not None:
            return _with_trace(outer, body(active))
        with active.review(event.repo, event.pr_number, event.head_sha) as span:
            review = body(active)
            span.set("atlas.review_event", review.event.value)
            return _with_trace(span, review)
    finally:
        if trace is None:
            release_shared()


def _with_trace(span: Any, review: AgenticReview) -> AgenticReview:
    trace_id = span.trace_id() if span is not None else ""
    if not trace_id:
        return review
    return replace(review, trace_id=trace_id)


def _traced_lens(
    trace: ReviewTrace, event: PrEvent, lens: str, *args: Any, **kwargs: Any
) -> _LensRun:
    with trace.lens(lens) as lens_span:
        ran = _review_one(event, lens, *args, trace=trace, **kwargs)
        lens_span.set("atlas.lens.state", ran.result.state.value)
        if ran.result.outcome is not None:
            label = limit_label(
                [cause.value for cause in ran.result.outcome.causes],
                ran.result.outcome.detail,
            )
            if label:
                lens_span.set("atlas.limit_stop", label)
        return ran


def _not_run(
    trace: ReviewTrace,
    lens: str,
    index: int,
    assigned: frozenset[str],
    reason: str,
    spend: Spend,
) -> _LensRun:
    """A lens that was never started still gets a span, so a trace shows
    why a picked lens has no model calls."""
    with trace.lens(lens) as lens_span:
        result = LensResult(lens, index, None, None, reason=reason, scope=assigned)
        lens_span.set("atlas.lens.state", result.state.value)
        lens_span.set("atlas.lens.reason", reason)
        return _LensRun(result, [], None, spend, ())


@dataclass
class _LensRun:
    result: LensResult
    secrets: list[BridgeSecret]
    report: RunnerReport | None
    spend: Spend
    flagged: tuple[str, ...]


def _combined_runner(reports: Sequence[RunnerReport]) -> RunnerReport | None:
    """The report the draft's Runner line shows: a runner that did not
    complete, else one whose delete was not verified, else the last."""
    if not reports:
        return None
    for report in reports:
        if report.status is not RunnerStatus.COMPLETED:
            return report
    for report in reports:
        if report.cleanup is CleanupStatus.DESTROY_UNVERIFIED:
            return report
    return reports[-1]


def _review_one(
    event: PrEvent,
    lens: str,
    diff: str,
    trees: SourceTrees,
    *,
    library: LensLibrary,
    model: LensModel,
    limits: AgenticLimits,
    ledger: AttemptLedger,
    sprites: SpritesApi,
    runner_ledger: RunnerLedger,
    redactor: Redactor,
    clock: Clock,
    context: Sequence[UntrustedBlock],
    telemetry: Telemetry | None,
    fence_nonce: str,
    bridge_root: str,
    contract: str | None,
    task_socket: str,
    index: int,
    assigned: frozenset[str] | None = None,
    spend: Spend | None = None,
    review_started: float | None = None,
    review_deadline: float | None = None,
    runner_name: str | None = None,
    continuation: bool = False,
    create_gate: threading.Semaphore | None = None,
    create_retries: int = DEFAULT_CREATE_RETRIES,
    evidence_digest: str | None = None,
    trace: ReviewTrace,
) -> _LensRun:
    # The per-call bounds only; the cross-limit relations were checked by
    # the entry point against the totals its review runs on (review_lens
    # on the configured values, the derivation on the derived ones, D68).
    resolved = limits.resolve(cross_limits=False)
    declared = getattr(model, "per_call", None)
    if declared is not None and declared != resolved:
        raise ValueError("the model's per-call limits differ from this review's limits")
    contract = finding_contract() if contract is None else contract
    changed = frozenset(f.path for f in split_files(diff))
    scope = changed if assigned is None else assigned
    body = library.body(lens)
    spend = spend or Spend(resolved)
    if body is None:
        missing = LensResult(
            lens, index, None, None, reason=NO_BODY_REASON, scope=scope
        )
        return _LensRun(missing, [], None, spend, ())
    started = clock.monotonic() if review_started is None else review_started
    deadline = (
        started + resolved.review_wall_s if review_deadline is None else review_deadline
    )
    diff_secrets = scan_diff(diff)
    ledger_lens = lens
    if continuation:
        # A continuation is its own ledger entry. The lens's own attempt
        # stays settled when it left files unread (D42); this entry is the
        # coordinator assigning those files, not a retry of that attempt.
        digest = hashlib.sha256("\n".join(sorted(scope)).encode()).hexdigest()[:12]
        ledger_lens = f"{lens}#{digest}"
    key = LensKey(
        event.repo, event.pr_number, event.head_sha, ledger_lens, body_digest(body)
    )
    if isinstance(next_step(ledger.attempts(key), resolved.retries), Settled):
        settled = _result(key, ledger.attempts(key), resolved, "", index)
        run = _LensRun(
            replace(settled, lens=lens, scope=scope),
            [],
            None,
            spend,
            (),
        )
        if evidence_digest is None:
            # No snapshot was gathered: D73's check is not wired here, and
            # reuse is exactly what it was before it existed.
            return run
        return _reused_with_reassessment(
            run,
            settled,
            key,
            event,
            lens,
            diff,
            trees,
            body,
            contract,
            fence_nonce,
            context,
            evidence_digest,
            model,
            spend,
            resolved,
            clock,
            ledger,
            redactor,
            diff_secrets,
            scope,
            trace,
            deadline,
        )
    session = _Session()
    scrubber = Redactor(
        redactor.known_secrets,
        (*redactor.sources, session.flagged),
        (*redactor.flagged, *diff_secrets.values),
    )

    def scrub(text: str) -> str:
        return scrubber(text).text

    lens_trace = trace.with_scrub(scrub)
    traced_model = lens_trace.wrap_model(model)
    job = LensJob(
        lens,
        body,
        key.body_sha256,
        contract,
        first_turn(event, diff, context, fence_nonce, only=scope),
        scope,
        read_sources(trees.head, diff, scope),
        fence_nonce,
        trees.head,
        diff,
    )
    name = runner_name or event_runner_name(event)

    def in_session(bridge: Bridge) -> str:
        session.bridges.append(bridge)
        digest = name.rsplit("-", 1)[-1]
        with lens_hold(bridge.session, digest, task_socket):
            return _attempts(
                lens_trace.wrap_bridge(bridge), job, traced_model,
                spend, clock, ledger, key, resolved,
                deadline, started, session, scrub, evidence_digest,
            )  # fmt: skip

    report = run_bridge(
        sprites, runner_ledger, trees, in_session,
        redactor=scrubber, changed=scope, name=name,
        deadline_s=max(deadline - clock.monotonic(), 0.0), clock=clock,
        telemetry=telemetry,
        root=bridge_root,
        create_gate=create_gate,
        create_retries=create_retries,
    )  # fmt: skip
    result = replace(
        _result(key, ledger.attempts(key), resolved, scrub(report.note), index),
        lens=lens,
        scope=scope,
    )
    secrets = list(session.secrets)
    flagged = tuple(diff_secrets.values) + tuple(session.flagged())
    return _LensRun(result, secrets, report, spend, flagged)


def _reassess_key(key: LensKey) -> LensKey:
    """The re-assessment ledger key (D73): the lens key with `#reassess`
    appended to the lens name. The lens's own key keeps its settled state
    whatever a re-assessment reply does, and a continuation's scope suffix
    -- twelve hex characters -- cannot collide with one that is not hex."""
    return LensKey(
        key.repo,
        key.pr_number,
        key.head_sha,
        f"{key.lens}{REASSESS_SUFFIX}",
        key.body_sha256,
    )


def _reused(
    run: _LensRun,
    effective: AttemptOutcome,
    withdrawn: Sequence[Withdrawn],
    note: str,
) -> _LensRun:
    """The reused result with its D73 composition applied: the settled
    outcome's other fields stand -- the attestation, causes, turns and
    coverage are the lens's own full run's -- and the findings, the
    withdrawals and the note are the re-assessments'."""
    return _LensRun(
        replace(
            run.result,
            outcome=effective,
            withdrawn=tuple(withdrawn),
            reassess_note=note,
        ),
        run.secrets,
        run.report,
        run.spend,
        run.flagged,
    )


def _reused_with_reassessment(
    run: _LensRun,
    settled: LensResult,
    key: LensKey,
    event: PrEvent,
    lens: str,
    diff: str,
    trees: SourceTrees,
    body: str,
    contract: str,
    fence_nonce: str,
    context: Sequence[UntrustedBlock],
    evidence_digest: str,
    model: LensModel,
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    ledger: AttemptLedger,
    redactor: Redactor,
    diff_secrets: DiffSecrets,
    scope: frozenset[str],
    trace: ReviewTrace,
    deadline: float,
) -> _LensRun:
    """The reuse path with D73's re-assessment wired: compose the reused
    result's effective findings from the settled outcome and every
    re-assessment already recorded for it, then, when the snapshot digest
    differs from the one stored with the result -- or none was stored --
    earn the one bounded re-assessment call, record it, and compose again.

    A settled outcome that was not attested earns no re-assessment: it has
    no prior findings to keep, and a single no-tools call is not a lens
    run -- the ordinary retry policy governs what happens to it instead.
    So does a review whose spend is halted or whose wall clock has passed:
    the reuse stands as it was, and the note says why no call was made.
    The call itself is wrapped by the lens trace like every other model
    call, so it records its completion span (round-1 review of #731, M1)."""
    # A settled result always carries its outcome; the assert is the
    # type checker's, not a new branch.
    assert settled.outcome is not None
    if settled.outcome.attestation is not Attestation.ATTESTED:
        return run
    reassess_key = _reassess_key(key)
    recorded = ledger.attempts(reassess_key)
    effective, withdrawn, note = effective_outcome(settled.outcome, recorded)
    stored = (
        ledger.evidence_digest(reassess_key)
        if recorded
        else ledger.evidence_digest(key)
    )
    if stored == evidence_digest:
        if not recorded:
            # No newer evidence, and nothing recorded: reuse is exactly
            # what it was before D73, with no extra call.
            return run
        return _reused(run, effective, withdrawn, note)
    if spend.halted or clock.monotonic() >= deadline:
        why = (
            "the review's spend was halted"
            if spend.halted
            else "the review's wall clock had passed"
        )
        return _reused(
            run, effective, withdrawn, f"the re-assessment was not run: {why}"
        )
    scrubber = Redactor(
        redactor.known_secrets,
        redactor.sources,
        (*redactor.flagged, *diff_secrets.values),
    )
    lens_trace = trace.with_scrub(lambda text: scrubber(text).text)
    # The attempt is on the ledger before its first model call, the way
    # the lens path's is (round-2 review of #731, the open Minor): a
    # billed call with nothing recorded, or an exception that fails the
    # whole review over a supplementary call, is what that ordering
    # prevents.
    number = len(recorded) + 1
    ledger.start(reassess_key, number)
    try:
        outcome = _reassess_call(
            event,
            lens,
            body,
            contract,
            fence_nonce,
            context,
            [c for c in effective.findings if c.verified],
            trees,
            diff,
            scope,
            lens_trace.wrap_model(model),
            spend,
            resolved,
            clock,
            deadline,
        )
    except Exception as exc:  # noqa: BLE001 - a supplementary call's failure must not fail the review
        # The last guard: whatever the call or its judging raised beyond
        # the recorded causes, the review goes on -- the attempt is
        # finished as the model error it is, the prior findings stand, and
        # the note says so. No digest is stored, so the next review
        # re-earns the bounded call.
        outcome = AttemptOutcome(
            Attestation.UNACKNOWLEDGED,
            frozenset({Cause.MODEL_ERROR}),
            detail=str(exc),
        )
    ledger.finish(
        reassess_key,
        number,
        outcome,
        scrub=lambda text: scrubber(text).text,
        evidence_digest=(
            evidence_digest if outcome.attestation is Attestation.ATTESTED else None
        ),
    )
    effective, withdrawn, note = effective_outcome(
        settled.outcome, ledger.attempts(reassess_key)
    )
    return _reused(run, effective, withdrawn, note)


def _reassess_call(
    event: PrEvent,
    lens: str,
    body: str,
    contract: str,
    fence_nonce: str,
    context: Sequence[UntrustedBlock],
    prior: Sequence[CheckedFinding],
    trees: SourceTrees,
    diff: str,
    scope: frozenset[str],
    model: LensModel,
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    deadline: float,
) -> AttemptOutcome:
    """One bounded re-assessment call (D73): the prior findings and the
    review's context blocks in, one final reply out, quote-checked like an
    ordinary reply's -- against the head lines of every path the reply's
    and the prior findings' locations cite, not only the changed files,
    so a revision of a verified prior that cites an unchanged file can
    verify the same quote (round-2 review of #731, the open Major). No
    tools are offered -- the head SHA is unchanged, so the code the
    findings cite is the code that is there -- and there is no repair
    turn: a reply outside the contract is the failed attempt it is,
    recorded with no digest stored, so the next review of this head
    re-runs the bounded call. The call is reserved at its worst case
    against the review's shared spend (D68's derived limits and dollar
    ceiling) and settled like any turn; a BYOK refusal halts the review's
    spend the way one in the loop does."""
    sources = read_sources(trees.head, diff, scope)
    request = TurnRequest(
        reassess_system(lens, body, contract, fence_nonce),
        (
            UserText(
                reassess_turn(event, prior_findings_block(prior), context, fence_nonce)
            ),
        ),
        (),
        None,
    )
    reserved = _reserve_call(model, request, spend, clock, deadline, fit=False)
    if not isinstance(reserved, _Reserved):
        found = reserved[2] if len(reserved) > 2 else None
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED,
            frozenset({reserved[0]}),
            detail=reserved[1],
            limit_hit=found,
        )
    worst = reserved.worst
    try:
        reply = model.turn(request)
    except ByokRefusedError as exc:
        spend.settle(worst, None)
        spend.halt()
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED, frozenset({Cause.MODEL_ERROR}), detail=str(exc)
        )
    except TransportError as exc:
        spend.settle(worst, None)
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED,
            frozenset({Cause.TRANSPORT_ERROR}),
            detail=str(exc),
        )
    except BoundaryError as exc:
        spend.settle(worst, None)
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED,
            frozenset({_refusal_cause(exc)}),
            detail=str(exc),
        )
    spend.settle(worst, reply.cost_usd)
    if not isinstance(reply, FinalReply):
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED,
            frozenset({Cause.UNPARSED}),
            detail="the re-assessment reply was a tool call, and the turn has none",
        )
    try:
        parsed = parse_reassess_reply(reply.text)
    except ContractError as exc:
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED, frozenset({Cause.UNPARSED}), detail=str(exc)
        )
    if parsed.lens != lens or parsed.body_sha256 != body_digest(body):
        return AttemptOutcome(
            Attestation.MISACKNOWLEDGED,
            detail="the re-assessment reply named another lens or body",
        )
    try:
        judged = judge(
            parsed,
            prior,
            sources,
            trees.head,
            resolved.quote_tolerance,
        )
    except ContractError as exc:
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED, frozenset({Cause.UNPARSED}), detail=str(exc)
        )
    return AttemptOutcome(
        Attestation.ATTESTED,
        judged.causes,
        findings=judged.checked,
        turns=1,
        changed_files=None,
        dropped=parsed.dropped,
        withdrawn=judged.withdrawn,
        revises=judged.revises,
    )


def _attempts(
    bridge: Bridge,
    job: LensJob,
    model: LensModel,
    spend: Spend,
    clock: Clock,
    ledger: AttemptLedger,
    key: LensKey,
    limits: Limits,
    review_deadline: float,
    review_started: float,
    session: _Session,
    scrub: Callable[[str], str],
    evidence_digest: str | None = None,
) -> str:
    step = next_step(ledger.attempts(key), limits.retries)
    while isinstance(step, RunAttempt):
        attempts = ledger.attempts(key)
        ledger.start(key, step.number)
        # The bridge session budget is per attempt (#693): each attempt,
        # a retry included, begins with the full call and output budget,
        # and its refusals name the attempt that spent them.
        bridge.begin_attempt(job.lens, step.number)
        secrets_seen: list[BridgeSecret] = []
        try:
            outcome = run_attempt(
                job, bridge, model, spend, clock,
                review_deadline=review_deadline,
                review_started=review_started,
                retry_of=attempts[-1].outcome if step.forced and attempts else None,
                attempt=step.number,
                secrets=secrets_seen,
            )  # fmt: skip
        except ByokRefusedError as exc:
            # The refusal still leaves the loop, so the runner fails and
            # its note is quoted. Finish the attempt first: an unfinished
            # one reads as abandoned, and that is retryable, so the next
            # review of this head would bill another call. The secrets,
            # turns and tool calls already seen are part of that record.
            session.secrets.extend(secrets_seen)
            ledger.finish(
                key, step.number,
                AttemptOutcome(
                    Attestation.UNACKNOWLEDGED,
                    frozenset({Cause.MODEL_ERROR}),
                    tools=cast("tuple[ToolUse, ...]", tuple(exc.tools)),
                    turns=exc.turns,
                    detail=str(exc),
                ),
                scrub=scrub,
                evidence_digest=evidence_digest,
            )  # fmt: skip
            raise
        else:
            session.secrets.extend(secrets_seen)
            ledger.finish(
                key, step.number, outcome, scrub=scrub, evidence_digest=evidence_digest
            )
        step = next_step(ledger.attempts(key), limits.retries)
    return f"lens {job.lens}: {len(ledger.attempts(key))} attempt(s)"


def _result(
    key: LensKey,
    attempts: tuple[Attempt, ...],
    limits: Limits,
    runner_note: str,
    index: int = 1,
) -> LensResult:
    if not attempts:
        return LensResult(
            key.lens, index, key.body_sha256, None,
            reason=f"no attempt was recorded: {runner_note or 'the runner did not start'}",
        )  # fmt: skip
    step = next_step(attempts, limits.retries)
    if isinstance(step, Settled):
        return LensResult(
            key.lens,
            index,
            key.body_sha256,
            step.outcome,
            step.attempts,
            step.escalated,
        )
    return LensResult(
        key.lens, index, key.body_sha256, attempts[-1].outcome, len(attempts),
        retry_pending=True,
    )  # fmt: skip


def _review_context(
    event: PrEvent,
    context: Sequence[UntrustedBlock],
    context_omissions: Sequence[Omission],
    round_log: RoundLog | None,
    prior_chars: int,
    redactor: Redactor,
) -> tuple[tuple[UntrustedBlock, ...], tuple[Omission, ...], int]:
    """Caller context, then prior rounds for this pull request.

    The third value is how many records belonged to another pull
    request. The changed-file list is not built here. `first_turn`
    always appends every file in the current diff after these blocks."""
    blocks = list(context)
    omissions = list(context_omissions)
    dropped_other = 0
    if round_log is not None:
        loaded = round_log.read()
        # Other pull requests in the same file are counted and are not
        # omissions. The repository key is case-insensitive. A line that
        # names no pull request is not charged here, and the
        # head-scoping that decides which unreadable lines charge this
        # review is `prior_blocks`'s.
        mine, dropped_other = records_for(loaded.records, event.repo, event.pr_number)
        if loaded.file_unreadable:
            unreadable: tuple[UnreadableLine, ...] = ()
            detail = "the round log file could not be read"
            if loaded.quarantined_to:
                detail += (
                    f"; it was moved aside to {loaded.quarantined_to} "
                    "and this review starts fresh"
                )
            omissions.append(
                Omission(
                    SOURCE,
                    "round log file",
                    detail,
                )
            )
        else:
            key = event.repo.casefold()
            unreadable = tuple(
                line
                for line in loaded.unreadable
                if line.repo == key and line.pr_number == event.pr_number
            )
        prior, prior_omissions = prior_blocks(
            mine,
            event.head_sha,
            prior_chars,
            unreadable=unreadable,
            scrub=lambda text: redactor(text).text,
        )
        blocks = [*prior, *blocks]
        omissions.extend(prior_omissions)
    return tuple(blocks), tuple(omissions), dropped_other


def _record_round(
    round_log: RoundLog | None,
    event: PrEvent,
    review: AgenticReview,
    redactor: Redactor,
) -> AgenticReview:
    """Append the one record for this finished review (D52), from the
    synthesized verdict over every lens and continuation."""
    if round_log is None:
        return review
    scrubber = Redactor(
        redactor.known_secrets, redactor.sources, (*redactor.flagged, *review.flagged)
    )
    lens = ", ".join(dict.fromkeys(result.lens for result in review.lenses))
    try:
        round_log.append(
            _round_record(event, lens, review, lambda text: scrubber(text).text)
        )
    except OSError as exc:
        note = f"the round log was not written: {_log_write_cause(exc)}. Detail: {exc}"
        return replace(review, round_log_note=note)
    return review


def _round_record(
    event: PrEvent, lens: str, review: AgenticReview, scrub: Callable[[str], str]
) -> RoundRecord:
    lines = tuple(
        scrub(
            f"{item.id} {item.finding.severity.value} "
            f"{item.finding.location} {item.finding.finding}"
        )
        for item in review.verified
    )
    stop = _first_limit_stop(review)
    return fit_record(
        RoundRecord(
            event.repo,
            event.pr_number,
            event.head_sha,
            lens,
            review.event.value,
            lines,
            bool(review.context_omissions),
            limit_stop="" if stop is None else scrub(stop.message()),
        )
    )


def first_turn(
    event: PrEvent,
    diff: str,
    context: Sequence[UntrustedBlock],
    nonce: str,
    only: frozenset[str] | None = None,
) -> str:
    """The operator's subject, then fenced: any caller context, the diff
    stat and the changed files in risk order. No diff text: the lens reads
    it through the tools. `only` narrows the list to a continuation's files."""
    files = list(by_risk(split_files(diff)))
    if only is not None:
        files = [f for f in files if f.path in only]
    listing = "\n".join(
        f"[{f.tier.label}] {f.path} (+{added} -{removed})"
        for f in files
        for added, removed in (_counts(f.text),)
    )
    blocks = (
        *context,
        UntrustedBlock(
            "changed-files",
            RepoText(f"{len(files)} changed file(s), highest risk first:\n{listing}"),
        ),
    )
    subject = f"{event.repo}#{event.pr_number} at {event.head_sha}"
    return "\n\n".join(
        (
            f"Review target (from the operator): {subject}",
            *(fence(b, nonce) for b in blocks),
        )
    )


def _counts(text: str) -> tuple[int, int]:
    added = removed = 0
    in_hunk = False
    for line in text.split("\n"):
        in_hunk = in_hunk or line.startswith("@@")
        if in_hunk and line.startswith("+"):
            added += 1
        elif in_hunk and line.startswith("-"):
            removed += 1
    return added, removed


# ---------------------------------------------------------------- the draft


def status_line(review: AgenticReview) -> str:
    """The first line of the draft, for pipelines to gate on: only
    controller values, so PR text cannot end it early."""
    counts = {s.name.lower(): 0 for s in LensState}
    for r in review.lenses:
        counts[r.state.name.lower()] += 1
    fields = {
        "mode": "agentic",
        "review_event": review.event.value,
        "proposed_event": review.proposed_event.value,
        "coverage_complete": review.coverage_complete,
        "lenses": counts,
        "verified_findings": len(review.verified),
        "unverified_findings": len(review.unverified),
        "changed_files": _changed_file_count(review),
        "unreviewed_files": len(_unread_paths(review)),
        "context_omissions": len(review.context_omissions),
        "other_pull_requests": review.other_pull_requests,
        "withdrawn": _withdrawn_count(review),
        "round_log_note": _status_log_note(review.round_log_note),
        "limit_stop": _limit_stop(review),
    }
    if review.trace_id:
        fields["trace_id"] = review.trace_id
    return f"{STATUS_PREFIX}{json.dumps(fields, sort_keys=True)} -->"


def _log_write_cause(exc: OSError) -> str:
    """The error class and its strerror, with no filename.

    `str(exc)` includes the path. The status line must not."""
    name = type(exc).__name__
    detail = exc.strerror or ""
    if not detail:
        filename = "" if exc.filename is None else str(exc.filename)
        parts = [
            str(arg)
            for arg in exc.args
            if not isinstance(arg, int) and str(arg) != filename
        ]
        detail = "; ".join(parts)
    return f"{name}: {detail}" if detail else name


def _status_log_note(note: str) -> str:
    """The status-line form of a log-write note: the cause, not the path."""
    marker = ". Detail: "
    if marker in note:
        return note.split(marker, 1)[0]
    return note


def _first_limit_stop(review: AgenticReview) -> LimitHit | None:
    """The first limit that stopped a lens, or None when none did."""
    for result in review.lenses:
        found = None if result.outcome is None else result.outcome.limit_hit
        if found is not None:
            return found
    return None


def _limit_stop(review: AgenticReview) -> dict[str, str] | None:
    stop = _first_limit_stop(review)
    return None if stop is None else stop.as_dict()


def render_draft(
    review: AgenticReview,
    redactor: Redactor,
    cache: Sequence[CacheSession] = (),
) -> str:
    """The draft as the operator reads it. Every model-written value (and
    every PR path) is redacted, with the review's flagged values scrubbed,
    and quoted as data. `cache` is the prompt-cache sessions the model
    adapters reported (issue #695); empty when none did."""
    scrubber = Redactor(
        redactor.known_secrets, redactor.sources, (*redactor.flagged, *review.flagged)
    )

    def scrub(text: str) -> str:
        return scrubber(text).text

    lines = [status_line(review), "", _headline(review, scrub)]
    if review.selection_note or review.not_picked:
        lines += ["", "## Lens selection"]
        if review.selection_note:
            lines += ["", scrub(review.selection_note)]
        if review.not_picked:
            lines.append("")
            lines += [
                f"- NOT RUN: {quote_untrusted(name, QUOTED_CHARS, scrub=scrub)} ({why})"
                for name, why in review.not_picked
            ]
    lines += _reassess_sections(review, scrub)
    lines += ["", "## Findings (verified quotes only)", ""]
    lines += [_finding_line(f, scrub) for f in review.verified] or [
        "No verified findings."
    ]
    if review.unverified:
        lines += ["", "## Not verified (not reported as findings)", ""]
        lines += [
            f"- {f.id} {quote_untrusted(str(f.finding.location), QUOTED_CHARS, scrub=scrub)}: "
            f"{quote_untrusted(f.problem, QUOTED_CHARS, scrub=scrub)}"
            for f in review.unverified
        ]
    if review.context_omissions:
        lines += ["", "## Context omissions", ""]
        lines += [
            f"- {quote_untrusted(item.source, scrub=scrub)} "
            f"({quote_untrusted(item.limit, scrub=scrub)}): "
            f"{quote_untrusted(item.detail, scrub=scrub)}"
            for item in review.context_omissions
        ]
    if review.secrets:
        lines += ["", "## Possible committed secrets (controller findings)", ""]
        lines += [_secret_line(s, scrub) for s in review.secrets]
    lines += ["", "## Lens coverage (attestation ledger)", ""]
    clean = _clean_runs(review.lenses)
    lines += [
        _lens_line(
            r,
            scrub,
            recovered_by=(
                clean[r.lens].index
                if r.state is not LensState.CLEAN and r.lens in clean
                else None
            ),
        )
        for r in review.lenses
    ]
    lines += [
        "",
        f"Model calls: {review.model_calls}; committed: ${review.committed_usd}.",
    ]
    if review.ceiling_note:
        # Controller text about the ceiling (D68): no PR data in it, so it
        # needs no quoting.
        lines.append(review.ceiling_note)
    if cache:
        lines += ["", "## Prompt cache", ""]
        lines += _cache_lines(cache, scrub)
        # The lines that follow (the round log and the runner note) are
        # prose, not list items; without the blank line CommonMark folds
        # them into the last cache bullet (review round 1, M1).
        lines.append("")
    if review.round_log_note:
        lines.append(
            "Round log, quoted: "
            + quote_untrusted(review.round_log_note, QUOTED_CHARS, scrub=scrub)
        )
    if review.runner is not None:
        lines.append(
            f"Runner: {review.runner.status.value}; cleanup {review.runner.cleanup.value}."
        )
        if review.runner.status is not RunnerStatus.COMPLETED and review.runner.note:
            lines.append(
                "Runner reported, quoted: "
                + quote_untrusted(review.runner.note, QUOTED_CHARS, scrub=scrub)
            )
    unverified = [
        r.runner_name
        for r in review.runners
        if r.cleanup is CleanupStatus.DESTROY_UNVERIFIED and r.runner_name
    ]
    if unverified:
        lines.append(
            "Runner delete NOT verified for "
            + ", ".join(f"`{name}`" for name in unverified)
            + "; recover each with `sweep --runner NAME --force-live`."
        )
    return "\n".join(lines) + "\n"


def _cache_lines(
    cache: Sequence[CacheSession], scrub: Callable[[str], str]
) -> list[str]:
    """One line per session, then the run total (issue #695). The sessions
    are ordered by lens name, so the pool's scheduling order cannot
    shuffle the summary (round-2 review, Nit 1). The label is the lens a
    session's system prompt named; it is quoted as data, because it is
    still text a reader could mistake for prose. An unlabeled session
    keeps its ordinal."""
    return [
        "- " + line
        for line in session_lines(
            by_label(cache),
            label_of=lambda session, number: (
                (
                    f"session {number} "
                    + quote_untrusted(session.label, QUOTED_CHARS, scrub=scrub)
                )
                if session.label
                else f"session {number}"
            ),
        )
    ]


def _headline(review: AgenticReview, scrub: Callable[[str], str]) -> str:
    if review.coverage_complete:
        count = _changed_file_count(review)
        files = (
            f" Every changed file's diff ({count}) was read in full." if count else ""
        )
        return (
            f"**Review event: {review.event.value}.** Verdict: {review.verdict.value}. "
            "Every selected lens ran whole, attested, with every quote verified."
            + files
        )
    # A lens one of whose own runs came back clean is covered (#692): its
    # earlier NOT RUN or failed entries are recovered, not gaps, so they
    # are not named as reasons the review cannot approve.
    clean = _clean_runs(review.lenses)
    short = [
        r
        for r in review.lenses
        if r.state is not LensState.CLEAN and r.lens not in clean
    ]
    if short:
        named = "; ".join(f"{r.lens}: {r.state.value}" for r in short)
    elif (
        review.runner is not None and review.runner.status is not RunnerStatus.COMPLETED
    ):
        named = f"runner {review.runner.status.value}"
    else:
        named = _lens_gap(review) or "no lens selected"
    proposed = (
        f" (the findings alone would be {review.proposed_event.value})"
        if review.proposed_event is not review.event
        else ""
    )
    return (
        "> **REVIEW INCOMPLETE -- not approvable.** "
        f"Review event: {review.event.value}{proposed}. Lens coverage is not "
        f"complete ({named}), so this review cannot approve."
        + _unread_clause(review, scrub)
    )


def _scoped(lenses: Sequence[LensResult]) -> bool:
    return any(result.scope is not None for result in lenses)


def _pending_by_lens(
    lenses: Sequence[LensResult], changed: frozenset[str] | None = None
) -> dict[str, frozenset[str]]:
    """For each lens, the paths none of its attempts read in full: its
    assigned scope, and every changed path when `changed` is given, so a
    lens assigned too narrow a scope is not covered by it. A file read by
    a different lens does not cover it (D42: the gate is per lens). A lens
    with no body has no attempt, so it stays pending."""
    assigned: dict[str, set[str]] = {}
    covered: dict[str, set[str]] = {}
    for result in lenses:
        if result.scope is None:
            continue
        assigned.setdefault(result.lens, set()).update(result.scope, changed or ())
        if result.outcome is None or result.outcome.changed_files is None:
            continue
        covered.setdefault(result.lens, set()).update(
            set(result.scope) - set(result.outcome.unread)
        )
    pending: dict[str, frozenset[str]] = {}
    for lens in sorted(assigned):
        gap = assigned[lens] - covered.get(lens, set())
        if gap:
            pending[lens] = frozenset(gap)
    return pending


def _pending_pairs(pending: dict[str, frozenset[str]]) -> set[tuple[str, str]]:
    return {(lens, path) for lens, paths in pending.items() for path in paths}


def _still_unread(
    lenses: Sequence[LensResult], changed: frozenset[str] | None = None
) -> tuple[str, ...]:
    paths: set[str] = set()
    for gap in _pending_by_lens(lenses, changed).values():
        paths.update(gap)
    return tuple(sorted(paths, key=lambda path: (risk_tier(path).rank, path)))


def _clean_runs(lenses: Sequence[LensResult]) -> dict[str, LensResult]:
    """Each lens's clean run, the last one in run order when there are
    several (#692). A lens with one is covered however its other entries
    ended: a later clean run supersedes an earlier NOT RUN, and a later
    NOT RUN does not undo an earlier clean run's coverage. Supersession is
    per lens -- one lens's clean run never covers another lens's failure."""
    runs: dict[str, LensResult] = {}
    for result in lenses:
        if result.state is LensState.CLEAN:
            runs[result.lens] = result
    return runs


def _entries_by_lens(lenses: Sequence[LensResult]) -> dict[str, list[LensResult]]:
    grouped: dict[str, list[LensResult]] = {}
    for result in lenses:
        grouped.setdefault(result.lens, []).append(result)
    return grouped


def _uncovered_lens(lenses: Sequence[LensResult]) -> bool:
    """Whether any lens lacks a clean run of its own (#692, D76): a lens
    blocks coverage unless at least one of its entries is clean, however
    its other entries ended. Supersession is by presence, not position --
    a later clean run supersedes an earlier NOT RUN, and a later NOT RUN
    does not undo an earlier clean run -- and per lens, so one lens's
    clean run never covers another lens's failure. The one "is this lens
    covered" predicate: the headline and the draft's recovered notes read
    `_clean_runs`, the same rule from the clean side."""
    return any(
        all(entry.state is not LensState.CLEAN for entry in entries)
        for entries in _entries_by_lens(lenses).values()
    )


def _lens_gap(review: AgenticReview) -> str:
    """Why the lenses do not give complete coverage, or "" when they do.
    The one coverage rule: `coverage_complete`, the headline and the
    unread list all read it. A clean outcome can still lack coverage:
    unread paths, or no changed-file count from before the per-file gate.
    A lens blocks unless at least one of its entries is clean (#692), in
    both the scoped and the no-scope paths -- an unread-only partial is
    not a clean run, so it never excuses a sibling that failed for a real
    cause; the files it left unread gate separately through
    `_unread_paths`."""
    if review.context_omissions:
        return "partial context"
    if review.not_picked:
        return "a picked lens did not run"
    if _dropped_notes(review):
        return "a finding was dropped"
    if not review.lenses:
        return "no lens selected"
    if _unread_paths(review):
        return "unread files"
    if _scoped(review.lenses):
        if _uncovered_lens(review.lenses):
            return "a lens did not finish clean"
        return ""
    if any(
        r.outcome is not None and r.outcome.changed_files is None for r in review.lenses
    ):
        return "no recorded file coverage"
    if _uncovered_lens(review.lenses):
        return "a lens did not finish clean"
    return ""


def _unread_paths(review: AgenticReview) -> tuple[str, ...]:
    if _scoped(review.lenses):
        return _still_unread(review.lenses, review.changed)
    seen: list[str] = []
    for result in review.lenses:
        if result.outcome is None:
            continue
        for path in result.outcome.unread:
            if path not in seen:
                seen.append(path)
    return tuple(sorted(seen, key=lambda path: (risk_tier(path).rank, path)))


def _changed_file_count(review: AgenticReview) -> int | None:
    counts = [
        result.outcome.changed_files
        for result in review.lenses
        if result.outcome is not None and result.outcome.changed_files is not None
    ]
    if not counts:
        return None
    return max(counts)


def _unread_clause(review: AgenticReview, scrub: Callable[[str], str]) -> str:
    unread = _unread_paths(review)
    if not unread:
        return ""
    shown = unread[:20]
    listed = ", ".join(
        quote_untrusted(path, QUOTED_CHARS, scrub=scrub) for path in shown
    )
    more = "" if len(unread) <= 20 else f", and {len(unread) - 20} more"
    noun = "file" if len(unread) == 1 else "files"
    return (
        f" {len(unread)} changed {noun} not read in full, highest risk first: "
        f"{listed}{more}."
    )


def _finding_line(f: MintedFinding, scrub: Callable[[str], str]) -> str:
    x = f.finding
    tags = [
        x.severity.value,
        x.valence.value,
        f"route: {x.route.value}",
        x.attribution.value,
    ]
    if f.source == QuoteSource.REMOVED.value:
        tags.append(f.source)
    elif f.source == QuoteSource.HEAD_NEAR.value:
        tags.append(drift_label(f.drift))
    text = (
        f"- **{f.id}** [{', '.join(tags)}] "
        f"{quote_untrusted(str(x.location), QUOTED_CHARS, scrub=scrub)} "
        f"({f.lens}): {quote_untrusted(x.finding, QUOTED_CHARS, scrub=scrub)}. "
        f"Fix: {quote_untrusted(x.fix, QUOTED_CHARS, scrub=scrub)}"
    )
    if x.evidence:
        text += (
            f". Evidence: {quote_untrusted(x.evidence, EVIDENCE_CHARS, scrub=scrub)}"
        )
    if x.siblings:
        text += f". Siblings: {quote_untrusted(x.siblings, QUOTED_CHARS, scrub=scrub)}"
    return text


def _secret_line(s: BridgeSecret, scrub: Callable[[str], str]) -> str:
    where = (
        quote_untrusted(f"{s.path}:{s.line}" if s.line else s.path, scrub=scrub)
        if s.path
        else "an unlocated result"
    )
    kind = "pre-existing" if s.preexisting else "introduced"
    return f"- possible committed secret ({s.label}) in {where}, {kind}; rotate if real"


def _lens_line(
    r: LensResult, scrub: Callable[[str], str], recovered_by: int | None = None
) -> str:
    """One coverage-section ledger line. `recovered_by` is the index of the
    same lens's clean run when this entry's failure does not block coverage
    (#692): the note is controller text appended last, outside the quoted
    reason, so a quoted reason cannot carry it (the service report reads
    the marker off the line's end)."""
    head = f"- L{r.index} {r.lens}: **{r.state.value}**"
    if r.outcome is None:
        line = f"{head}; {quote_untrusted(r.reason, QUOTED_CHARS, scrub=scrub)}"
    else:
        line = f"{head}; " + "; ".join(_lens_line_parts(r, scrub))
    if recovered_by is not None:
        line += f"; {recovered_note(recovered_by)}"
    return line


def _lens_line_parts(r: LensResult, scrub: Callable[[str], str]) -> list[str]:
    o = r.outcome
    assert o is not None
    parts = [
        f"body sha256 {r.body_sha256}",
        f"attestation: {o.attestation.value}",
        f"{r.attempts} attempt(s)",
        f"{o.turns} turn(s)",
        f"{len(o.tools)} tool call(s)",
    ]
    reasons = retry_reasons(o)
    if reasons:
        parts.append("; ".join(reasons))
    if r.escalated:
        parts.append("escalated: the retry also failed")
    if r.retry_pending:
        parts.append("its retry did not run before the review ended")
    if r.reassess_note:
        parts.append(f"re-assessment: {r.reassess_note}")
    repairs = o.nudges.count("quote-repair")
    if repairs:
        parts.append(f"{repairs} quote-repair turn(s)")
    corrections = sum(1 for c in o.findings if c.source is QuoteSource.HEAD_NEAR)
    if corrections:
        parts.append(f"{corrections} citation(s) corrected within the window")
    if o.dropped:
        parts.append(f"{len(o.dropped)} finding(s) dropped")
    if o.diff_prefix:
        parts.append(o.diff_prefix)
    if o.detail:
        parts.append(f"detail {quote_untrusted(o.detail, QUOTED_CHARS, scrub=scrub)}")
    return parts


def _reassess_sections(review: AgenticReview, scrub: Callable[[str], str]) -> list[str]:
    """The two sections a re-assessment (D73) can add to the draft, in
    order: the findings dropped for an unknown severity -- the lens's own
    run's and a re-assessment's alike -- and the prior findings a
    re-assessment withdrew or revised. Each section is empty when nothing
    backs it."""
    return [*_dropped_lines(review, scrub), *_withdrawn_lines(review, scrub)]


def _dropped_lines(review: AgenticReview, scrub: Callable[[str], str]) -> list[str]:
    """The draft's dropped-findings section, or an empty list when no
    finding was dropped for an unknown severity."""
    dropped = _dropped_notes(review)
    if not dropped:
        return []
    return [
        "",
        "## Dropped findings (left out of this review)",
        "",
        *("- " + quote_untrusted(note, QUOTED_CHARS, scrub=scrub) for note in dropped),
    ]


def _dropped_notes(review: AgenticReview) -> tuple[str, ...]:
    return tuple(
        note
        for result in review.lenses
        if result.outcome is not None
        for note in result.outcome.dropped
    )


def _withdrawn_count(review: AgenticReview) -> int:
    """The status line's withdrawn count (round-1 review of #731, M2c):
    the prior findings a re-assessment annotated -- proposed withdrawals
    and revisions alike -- since a pipeline gating on the status line must
    see that prior findings were re-judged, not only that new ones were
    added. A withdrawal removes nothing (M2), so the count is an
    annotation count, never a deletion count."""
    return sum(len(result.withdrawn) for result in review.lenses)


def _withdrawn_lines(review: AgenticReview, scrub: Callable[[str], str]) -> list[str]:
    """The draft's withdrawn-findings section (D73), or an empty list when
    no re-assessment withdrew or revised anything: what the finding was,
    the stated reason the newer evidence showed it wrong, and, for a
    revision, the finding that replaced it."""
    pairs = [(result, w) for result in review.lenses for w in result.withdrawn]
    if not pairs:
        return []
    return [
        "",
        "## Withdrawn findings (re-assessed with newer evidence)",
        "",
        *(_withdrawn_line(result, w, scrub) for result, w in pairs),
    ]


def _withdrawn_line(
    result: LensResult, w: Withdrawn, scrub: Callable[[str], str]
) -> str:
    """One annotated prior finding (D73): what it was, the stated reason
    the newer evidence changed its judgment, and, for a revision, what the
    revision proposes -- so a reader can tell a finding was re-judged and
    not lost. A withdrawal removes nothing (round-1 review of #731, M2),
    so the verb is a proposal; a revision that took the prior's place says
    what stands now, and one that only lowers a Blocker's or a Major's
    severity says the higher severity still counts. Every value here is
    model-written or PR-written text, so it is quoted as data."""
    if w.replacement is None:
        return (
            f"- {result.lens} proposes withdrawing "
            f"{quote_untrusted(str(w.finding.location), QUOTED_CHARS, scrub=scrub)}: "
            f"{quote_untrusted(w.finding.finding, QUOTED_CHARS, scrub=scrub)} "
            f"[{w.finding.severity.value}]. Reason, quoted: "
            f"{quote_untrusted(w.reason, QUOTED_CHARS, scrub=scrub)}"
        )
    if w.replaced:
        text = (
            f"- {result.lens} revises "
            f"{quote_untrusted(str(w.finding.location), QUOTED_CHARS, scrub=scrub)}: "
            f"{quote_untrusted(w.finding.finding, QUOTED_CHARS, scrub=scrub)} "
            f"[{w.finding.severity.value}]. Reason, quoted: "
            f"{quote_untrusted(w.reason, QUOTED_CHARS, scrub=scrub)}"
        )
        if w.replacement.verified:
            return text + f". Revised finding: {_finding_id(result, w.replacement)}"
        return text + ". The revised finding did not verify; see Not verified"
    lowered = w.replacement.finding.severity.rank > w.finding.severity.rank
    head = (
        f"- {result.lens} proposes revising "
        f"{quote_untrusted(str(w.finding.location), QUOTED_CHARS, scrub=scrub)}: "
        f"{quote_untrusted(w.finding.finding, QUOTED_CHARS, scrub=scrub)} "
        f"[{w.finding.severity.value}] down to "
        f"{w.replacement.finding.severity.value}. Reason, quoted: "
        f"{quote_untrusted(w.reason, QUOTED_CHARS, scrub=scrub)}"
        if lowered
        else (
            f"- {result.lens} proposes revising "
            f"{quote_untrusted(str(w.finding.location), QUOTED_CHARS, scrub=scrub)}: "
            f"{quote_untrusted(w.finding.finding, QUOTED_CHARS, scrub=scrub)} "
            f"[{w.finding.severity.value}]. Reason, quoted: "
            f"{quote_untrusted(w.reason, QUOTED_CHARS, scrub=scrub)}"
        )
    )
    if lowered and w.replacement.verified:
        return (
            head
            + ". The higher severity still counts; the revised finding, quoted: "
            + quote_untrusted(w.replacement.finding.finding, QUOTED_CHARS, scrub=scrub)
        )
    if lowered:
        return (
            head
            + ". The higher severity still counts; the revised finding did not verify."
        )
    return (
        head
        + ". The revised finding did not verify ("
        + quote_untrusted(w.replacement.problem, QUOTED_CHARS, scrub=scrub)
        + "), so the prior finding stands."
    )


def _finding_id(result: LensResult, checked: CheckedFinding) -> str:
    """The minted id of one of the result's effective findings, found by
    identity: `effective_outcome` puts the replacement's own object in the
    composed outcome, so the same object the withdrawal carries is in the
    list the ids were minted over."""
    findings = () if result.outcome is None else result.outcome.findings
    for n, held in enumerate(findings, 1):
        if held is checked:
            return f"L{result.index}-F{n}"
    return "a finding this draft does not list"
