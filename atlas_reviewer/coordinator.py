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
import re
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from atlas_reviewer.agentic_config import load_agentic_limits
from atlas_reviewer.approval import (
    ApprovalChannel,
    CommandProposal,
    NeverApproved,
    RunApprovals,
)
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
    _finding_key,
    body_digest,
    next_step,
)
from atlas_reviewer.bridge import Bridge, BridgeSecret, run_bridge
from atlas_reviewer.bridge_staging import BRIDGE_ROOT, SourceTrees
from atlas_reviewer.budget import valid_cost
from atlas_reviewer.cache_stats import CacheSession, by_label, session_lines
from atlas_reviewer.committed_secrets import DiffSecrets, scan_diff
from atlas_reviewer.delta import (
    DELTA_DIFF_CHARS,
    CarryResult,
    DeltaScope,
    LensDecision,
    _cited_path,
    apply_carry,
    capped,
    carry_system,
    carry_turn,
    decision_system,
    decision_turn,
    fallback_decisions,
    judged_carry,
    parse_carry_reply,
    parse_decision_reply,
    parse_prior_line,
)
from atlas_reviewer.diffs import (
    FileDiff,
    PathRanks,
    by_risk,
    rank_files,
    rerank_note,
    risk_tier,
    split_files,
)
from atlas_reviewer.domain import (
    CleanupStatus,
    Omission,
    PrEvent,
    RunnerReport,
    RunnerStatus,
)
from atlas_reviewer.funding import noted_funding_source
from atlas_reviewer.head_change import (
    FIELD_CALLS,
    FIELD_COMMITTED_USD,
    FIELD_HELD_USD,
    FIELD_LENS,
    FIELD_LENSES_DONE,
    FIELD_LENSES_TOTAL,
    FIELD_READING,
    FIELD_RESERVATION_USD,
    FIELD_SETTLED_USD,
    FIELD_SOURCE,
    LENS_SETTLED_STEP,
    PROGRESS_PHASE,
    PROGRESS_REVIEW_STEP,
    cap_reading,
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
    PickerSpend,
    Spend,
    TurnRequest,
    UserText,
    _refusal_cause,
    _reserve_call,
    _Reserved,
    finding_contract,
    retry_reasons,
    run_attempt,
    spend_for_picker,
)
from atlas_reviewer.lenses import LensLibrary
from atlas_reviewer.limit_stop import LimitHit
from atlas_reviewer.notes import quote_untrusted, recovered_note
from atlas_reviewer.openrouter import OpenRouterProvider
from atlas_reviewer.ports import (
    KEY_OUT_OF_CREDIT,
    BoundaryError,
    ByokRefusedError,
    Clock,
    KeyRefusedError,
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
from atlas_reviewer.repo_config import review_md_ceiling
from atlas_reviewer.review_wide import clamp_repo_ceiling, derive_review_wide
from atlas_reviewer.rounds import (
    PRIOR_ROUND_CHARS,
    RECORD_CHARS,
    SOURCE,
    RoundLog,
    RoundRecord,
    UnreadableLine,
    fit_record,
    prior_blocks,
    records_for,
)
from atlas_reviewer.runner import (
    BAKE_WALL_S,
    DEFAULT_CREATE_RETRIES,
    Baked,
    CreateRefusedError,
    RestoreRefusedError,
    SetupSpec,
    bake_setup,
    event_runner_name,
    lens_runner_name,
)
from atlas_reviewer.telemetry import ERROR, Telemetry
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
# The incremental diff's cap lives beside the delta pieces (`delta.py`'s
# DELTA_DIFF_CHARS): the decision turn, the lenses' highlight block and
# the carry-forward turn all carry the range's own per-file patches cut
# to it, with the truncation marker (#702, D83).
# Continuation rounds per review. Each round re-runs the lenses that still
# have unread files; a round that does not shrink the gap ends it earlier.
MAX_CONTINUATIONS = 4
HALTED_REASON = (
    "not started: an earlier call in this review stopped it "
    "(BYOK, a refused key, or a failed lens)"
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
    carried: bool = False
    """True for a prior finding the delta review carried forward (#702):
    `id` is the carry-forward label (`P1`, ...), `lens` is the earlier
    record's lens attribution, and the finding was quote-verified against
    this head like any other."""


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
    rerank_note: str = ""
    """Controller text recording the reviewed repo's path re-ranking
    (config slice S5, D81 Q6), non-empty only when the merge-base
    REVIEW.md carried a ranking line the parse accepted: it names what
    the settings deprioritized and says the ordering never dropped a
    file. Empty when nothing ranked, so an unconfigured review's draft
    reads exactly as it did."""
    settle_overruns: tuple[str, ...] = ()
    """Per-settle notes for calls whose reported cost came in above the
    worst case reserved for them (D82's tripwire, round-1 review of
    #757), carried into the draft's cost line: the observable signal
    that a provider billed past the priced worst case."""
    endpoint_class: str = ""
    """Which endpoint class served the review's calls (config slice S10):
    `operator` for the operator's key, `tenant` for the installation's
    own endpoint, empty when no live model ran (a dry run, an offline
    provider). The draft's cost line names it, and the posted Cost
    section carries the same line."""
    carried_unverified: tuple[tuple[str, Finding, str], ...] = ()
    """Prior findings the delta review carries without a re-anchored,
    verified quote (#702): each with its carry-forward label, the
    finding exactly as the earlier record stored it, and the lens the
    record attributes it to (empty when no record field or id mapping
    can pin it -- the line still travels every surface either way).
    They are not reported as findings (a quote that does not verify at
    this head is not reported), but they are named in the draft and
    carried in the round record, so the next review re-offers them --
    never silently dropped (D73) -- and their severities still count
    for the verdict, because a failed re-anchor is not evidence the
    defect is fixed."""
    carried_raw: tuple[str, ...] = ()
    """Prior finding lines that do not parse (#702, round-1 M3): the
    record's own text, quoted verbatim in the draft's carried section and
    re-recorded, so the chain never loses them. Empty outside a delta
    review."""
    carried_omitted: int = 0
    """Verified findings the earlier record could not store (its
    8,192-character cap), carried forward as a count (#702, round-2
    Major B): the delta review cannot recover their text, but the
    omission is written into this review's own round record, so the next
    hop re-states the gap instead of the chain losing it after one hop.
    Zero outside a delta review."""
    resolved: tuple[tuple[str, str, Finding], ...] = ()
    """Prior findings the delta's new commits fixed (#702), each with its
    carry-forward label and the stated reason the carry-forward call
    gave. A resolution is accepted only for a finding whose file the
    delta touched."""
    delta_note: str = ""
    """Controller text about the delta review's own shape (#702): the
    fallback to the full diff when the delta range could not be fetched,
    or the note that nothing was carried because no earlier findings are
    recorded at the delta base."""
    delta_from: str = ""
    """The head this delta review builds on (#702), empty on a full
    review. The draft cites it; the service post cites it too."""
    delta_paths: frozenset[str] = frozenset()
    """The paths the delta touched that the pull request still changes
    (D83, round-1 review of #760): the coverage accounting's own input.
    A reused settled result read the pull request at the delta base and
    nothing more, so a file the delta added or modified cannot be
    claimed covered on reuse alone -- every path in this set must be
    read by a lens that ran this round, or it is unreviewed and the
    review cannot approve. Empty on a full review, and on a delta whose
    touched paths are unknown or leave the pull request's diff."""
    lens_decisions: tuple[LensDecision, ...] = ()
    """The delta review's per-lens decisions (D83): for every planned
    lens, whether this follow-up re-ran it on the whole pull request or
    reused the earlier review's settled result, each with the reason the
    coordinator gave. The decision is the coordinator's judgment over
    the incoming changes, never a fixed path-intersection rule; it is
    recorded here, in the telemetry and in the round record, and
    summarized in the post. Empty on a full review."""
    billed_usd: str = "0"
    """Known bills: the cost line's settled figure and the daily ledger's
    amount (D93). A served call with no usable cost is included at its
    reservation. $0 when every finished call was a refusal or a hold."""
    held_usd: str = "0"
    """Reservations kept because the request was written and never
    answered (D93). Counted in `committed_usd` for the in-review
    ceiling. Not a bill."""
    funding_source: str = ""
    """The operator funding source this review was pinned to (D94), or
    empty when the service has no source list. A short name the
    controller chose. Never a key."""
    review_error: str = ""
    """The fixed cause a refused key halted the review with (D92):
    `model key out of credit` or `model key refused`, the spend's own
    halt cause. Non-empty means this draft is an error or a partial
    record, not an ordinary review: with no verified finding, no clean
    run and no partial lens before the halt, the draft is the error
    report, with no Findings section to mistake for a clean bill; when a
    lens ran -- clean with its findings, or partial over the files it
    read -- the review is partial and the headline names what did not
    run. Empty on every review that ran on a served key."""

    @property
    def reused_lenses(self) -> frozenset[str]:
        """The planned lenses this delta review reused instead of run
        (D83). They appear in no lens entry, and their reuse covers the
        files their settled results read -- except the files the delta
        touched (`delta_paths`), which only a lens that ran this round
        can have read."""
        return frozenset(
            decision.lens for decision in self.lens_decisions if decision.reuse
        )

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


def decide(
    findings: Sequence[MintedFinding],
    *,
    carried_setting: Sequence[Severity] = (),
) -> Verdict:
    """From the verified verdict-setting findings: only an introduced
    defect sets the verdict. A Blocker requests changes. A Major or a
    Minor means approve with changes (D55).

    `carried_setting` is the delta review's extra (#702): the severities
    of the carried-but-unre-anchored prior findings, which count as
    verdict-setting without being verified at this head -- they were
    verified findings of the earlier review of this pull request's code,
    and a failed re-anchor is not evidence the defect is fixed, so a
    standing prior Blocker can never become an approval."""
    setting = [
        f.finding.severity for f in findings if f.verified and f.finding.sets_verdict
    ]
    setting.extend(carried_setting)
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
    rerank_note: str = "",
    endpoint_class: str = "",
    funding_source: str = "",
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
        rerank_note=rerank_note,
        settle_overruns=tuple(spend.overruns) if spend is not None else (),
        endpoint_class=endpoint_class,
        billed_usd="0" if spend is None else str(spend.billed_usd()),
        held_usd="0" if spend is None else str(spend.held_usd),
        funding_source=funding_source,
        review_error="" if spend is None else spend.halted_cause,
    )


_ENDPOINT_SERVED = {
    "operator": "the operator's model endpoint",
    "tenant": "the installation's own model endpoint",
}


def endpoint_class(model: LensModel) -> str:
    """Which endpoint class the review's model calls run on (config
    slice S10): `tenant` for the installation's own endpoint,
    `operator` for the operator's key, empty when no live provider is
    behind the model (a dry run's scripted model). Read from the
    provider's own name, so a new provider class cannot silently pass
    as either."""
    provider = getattr(model, "provider", None)
    name = getattr(provider, "name", "")
    if not isinstance(name, str):
        return ""
    if name.startswith("tenant-endpoint:"):
        return "tenant"
    if name.startswith("openrouter:"):
        return "operator"
    return ""


def _credit_refusal(model: LensModel, per_lens_usd: Decimal) -> str:
    """The up-front key-credit refusal (D92), or the empty string when
    none applies. The planned review's minimum credit is the smaller of
    the largest reservation one call holds -- the per-call input cap
    priced at the endpoint's rates, the adapter's figure -- and the
    per-lens dollar budget the plan itself prices one lens's work at: a
    key that cannot fund that cannot start the review, whatever the
    refits might shrink later. A model that carries no key-credit seam --
    a dry run's scripted model, the tenant endpoint whose bounds are its
    own caps and the operator's price table -- accepts, as does a key
    that reports no credit limit to compare against."""
    remaining = getattr(model, "remaining_credit_usd", None)
    largest = getattr(model, "largest_call_reservation", None)
    if not callable(remaining) or not callable(largest):
        return ""
    left, one_call = remaining(), largest()
    if left is None or one_call is None or left >= min(one_call, per_lens_usd):
        return ""
    return KEY_OUT_OF_CREDIT


def _rerank_note(
    files: Sequence[FileDiff], path_ranks: PathRanks | None, redactor: Redactor
) -> str:
    """The draft note recording the reviewed repo's path re-ranking (S5):
    empty when the config ranks nothing. The paths in it are quoted as
    data by `diffs.rerank_note` against this redactor; the draft scrubs
    the whole note again with its own, fuller scrubber, the way the
    selection note is scrubbed."""
    if path_ranks is None:
        return ""
    return rerank_note(files, path_ranks, scrub=lambda text: redactor(text).text)


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
    run_proposals: tuple[CommandProposal, ...] = (),
    approval_channel: ApprovalChannel | None = None,
    setup: SetupSpec | None = None,
    restore: str | None = None,
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
    checked for newer evidence and re-assessed when it has some.
    `run_proposals` and `approval_channel` are the S7 allow-list
    proposals (config slice S7, D88) and the approval channel they become
    requests on; the decided channel is pre-approval (D88's update:
    installation admins pre-approve on the S10 settings page, part B --
    no live approval during a review), and the production default
    approves nothing until part B lands."""
    funding = noted_funding_source()
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
            run_proposals=run_proposals,
            approval_channel=approval_channel,
            setup=setup,
            restore=restore,
        )
        single = synthesize(
            [ran.result],
            ran.secrets,
            ran.report,
            ran.spend,
            ran.flagged,
            context_omissions=omissions,
            other_pull_requests=other_pull_requests,
            endpoint_class=endpoint_class(model),
            funding_source=funding,
        )
        # The evidence digest is stored with the record (D73) whether the
        # review ran one lens or the whole plan: a later delta review's
        # trigger reads it.
        return _record_round(round_log, event, single, redactor, evidence_digest)

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
    picker_spend: PickerSpend = (0, Decimal(0)),
    trace: ReviewTrace | None = None,
    evidence_digest: str | None = None,
    delta: DeltaScope | None = None,
    path_ranks: PathRanks | None = None,
    operator_ceiling_max: Decimal | None = None,
    run_proposals: tuple[CommandProposal, ...] = (),
    approval_channel: ApprovalChannel | None = None,
    setup: SetupSpec | None = None,
) -> AgenticReview:
    """Run every named lens, up to `pool_size` at once, then one combined
    verdict. Each lens gets its own runner name. A changed file a lens
    left unread is handed back to that same lens as a continuation, for up
    to `MAX_CONTINUATIONS` rounds, while a call and the review clock remain.
    Partial coverage still cannot approve. `picker_spend` is the calls and
    dollars the lens picker already committed; they count toward this
    review's `max_calls` and `reservation_usd`.

    `path_ranks` is the reviewed repo's path-ranking config (config slice
    S5, D81 Q6), read from the merge-base tree by `repo_config` before
    this entry point is called: it re-orders the changed-file listing
    every lens's first turn presents -- ordering only, never exclusion,
    every changed file still listed and still held to every lens -- and
    the re-ranking is recorded in the draft's note. Q25 (whether anything
    may be excluded from review at all) is untouched.

    Config slice S7 (D88): `run_proposals` are the reviewed repo's
    proposed additions to the #734 execution-tool allow-list, read from
    the default-branch `REVIEW.md` before this entry point is called;
    `approval_channel` is the approval channel they become requests on.
    Issue #819 (D95): `setup` is the reviewed repo's setup spec -- one
    setup pass bakes it with egress allowed, flips to deny-all and
    checkpoints the result, and every lens runner restores that one
    checkpoint instead of re-running the setup; a bake that cannot make
    a checkpoint is named on the telemetry and every lens falls back to
    running the setup phase on its own runner.
    The decided channel is pre-approval (D88's update): installation
    admins pre-approve a repo's extra commands on the S10 settings page
    (part B), the run reads that pre-approved set once at start, and
    there is no live approval during a review -- the production default
    approves nothing until part B lands. A proposal is never
    auto-granted: a blocked `run_tests` command routes to the channel,
    every outcome other than an explicit approval denies, and an
    approved addition lives in run-scoped state that dies with the lens
    run's own runner.

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
    Config slice S9: `operator_ceiling_max` clamps a repo-raised ceiling
    to the operator's max per review, and the clamp is named through
    D68's ceiling note.

    D73: `evidence_digest` is the digest of the evidence snapshot this
    review gathered (the CI block's and the conversation's gathered data,
    `reassess.snapshot_digest`). It is stored with every attempt this
    review finishes, and a reused settled lens whose stored digest differs
    from it -- or that carries none -- earns one bounded re-assessment call
    against this review's shared spend and wall clock.

    D79 and D83: `delta` marks this as a delta review -- the follow-up
    to a review that finished while a push was held back. The subject is
    still the whole pull request at this head: the lenses run on the
    full pull request diff, with the incremental diff
    (`delta_from..head`) highlighted in the first turn as the new
    material, and a re-run lens may report findings anywhere in the pull
    request, unchanged content included. Before any lens runs, the
    coordinator judges each planned lens -- one bounded, tool-less call
    over the incremental diff, the fresh evidence blocks and the lens
    names with their concern summaries -- whether to re-run it or reuse
    the earlier review's settled result; a reused lens does not run, its
    earlier findings stand, and its files count as covered -- except the
    files the delta touched, which only a lens that ran this round can
    have read, so an uncovered one is unreviewed and the review cannot
    approve (round-1 review of #760, Major A). A reused lens whose
    evidence snapshot moved since the earlier review -- or that carries
    no digest -- earns its one bounded D73 re-assessment after the
    carry-forward composes (round-1 review of #760, Major B). After the
    lenses settle, the earlier review's findings (the
    round log's records at the scope's `delta_from`) are carried forward
    through one bounded carry-forward call: re-stated findings
    re-anchored and quote-checked against this head, the new commits'
    fixes marked resolved on evidence the delta removed their cited
    code, everything else carried as it was recorded, never silently
    dropped."""
    funding = noted_funding_source()
    read = review_md_ceiling(trees.base)
    effective, clamp_note = clamp_repo_ceiling(read.value, operator_ceiling_max)
    derived, derivation = derive_review_wide(
        limits,
        len(lenses),
        picker_spend[0],
        picker_spend[1],
        repo_ceiling=effective,
        repo_ceiling_note=(
            f"{read.note} {clamp_note}".strip() if clamp_note else read.note
        ),
    )
    refusal = _credit_refusal(model, derivation.per_lens_usd)
    if refusal:
        # The key's remaining credit cannot fund the review's smallest
        # call (D92): the review stops before any lens fans out, and the
        # draft and the posted comment name the fixed cause instead of
        # running a review that fails call after call into an
        # incomplete-looking stop.
        spend = spend_for_picker(derived, picker_spend, derivation=derivation)
        spend.halt(refusal)
        stopped = tuple(
            LensResult(
                name, index, None, None, reason=f"not started: {refusal}"
            )
            for index, name in enumerate(lenses, start=1)
        )  # fmt: skip
        error = synthesize(
            stopped,
            spend=spend,
            ceiling_note=derivation.ceiling_note,
            endpoint_class=endpoint_class(model),
            funding_source=funding,
        )

        def refused(active: ReviewTrace) -> AgenticReview:
            if delta is not None:
                # A delta review that stops at the credit preflight still
                # carries the earlier review's findings (D92's fix round
                # 4): the carry-forward composes them through its fallback
                # -- the carry call itself is refused on the halted spend,
                # so no model call is made -- and a prior Blocker is never
                # dropped because the lenses never ran. The lenses stay
                # NOT RUN and the credit refusal stays the review error.
                fence_nonce = nonce()
                records, log_note = _records_at(round_log, event, delta.delta_from)
                changed = frozenset(f.path for f in split_files(diff))
                return _with_carryforward(
                    error,
                    event,
                    delta,
                    records,
                    log_note,
                    diff,
                    trees,
                    changed,
                    model,
                    spend,
                    derived,
                    clock,
                    clock.monotonic() + derived.review_wall_s,
                    fence_nonce,
                    contract or finding_contract(),
                    active,
                    redactor,
                )
            return error

        return _traced_review(event, trace, redactor, refused)
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
            delta=delta,
            path_ranks=path_ranks,
            run_proposals=run_proposals,
            approval_channel=approval_channel,
            setup=setup,
        ),
    )


SETUP_LENS = "setup"


def _bake_setup_pass(
    sprites: SpritesApi,
    runner_ledger: RunnerLedger,
    setup: SetupSpec | None,
    event: PrEvent,
    deadline: float,
    clock: Clock,
    telemetry: Telemetry | None,
    gate: threading.Semaphore | None,
    create_retries: int,
    *,
    names: Sequence[str] = (),
    bake_wall_s: float = BAKE_WALL_S,
) -> Baked | None:
    """The setup pass ahead of fan-out (issue #819, D95): with a setup
    spec and at least one lens left to run, one runner bakes the repo's
    declared installs with egress allowed, flips to deny-all, and
    checkpoints the result every lens restores from. The bake gets the
    smaller of the review wall that is left and `bake_wall_s` -- it runs
    serially before any lens starts, so a slow install cannot spend the
    whole wall by itself. None means no spec, no lens left to run, or a
    bake that could not make a checkpoint: a create the API refused (its
    own error is on the telemetry), a deadline, or a failed checkpoint
    call leave every lens the per-lens-setup fallback, named; a
    **deterministic setup-phase failure** (`Baked.setup_failed` -- a
    command that failed, no trusted interpreter) leaves the lenses no
    setup at all, also named, because the same commands would fail
    identically with egress open again."""
    if setup is None or not setup.commands or not names:
        return None
    try:
        baked = bake_setup(
            sprites,
            runner_ledger,
            setup,
            name=lens_runner_name(event, SETUP_LENS),
            deadline_s=min(max(deadline - clock.monotonic(), 0.0), bake_wall_s),
            clock=clock,
            telemetry=telemetry,
            create_gate=gate,
            create_retries=create_retries,
        )
    except CreateRefusedError as exc:
        if telemetry is not None:
            telemetry.record("setup bake", "refused", status=ERROR, error=str(exc))
        return None
    if baked.checkpoint_id is None and telemetry is not None:
        note = baked.report.note if baked.report is not None else "no report"
        telemetry.record(
            "setup bake",
            "failed",
            status=ERROR,
            error=(
                "the setup phase failed deterministically on its own runner, "
                "so the lenses run no setup of their own"
                if baked.setup_failed
                else "no checkpoint was made; every lens runs the setup phase "
                "on its own runner"
            )
            + f" ({note})",
        )
    return baked


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
    picker_spend: PickerSpend,
    evidence_digest: str | None,
    delta: DeltaScope | None = None,
    path_ranks: PathRanks | None = None,
    run_proposals: tuple[CommandProposal, ...] = (),
    approval_channel: ApprovalChannel | None = None,
    setup: SetupSpec | None = None,
    restore: str | None = None,
) -> AgenticReview:
    funding = noted_funding_source()
    files = split_files(diff)
    changed = frozenset(f.path for f in files)
    blocks, omissions, other_pull_requests = _review_context(
        event, context, context_omissions, round_log, prior_chars, redactor
    )
    # One fence nonce per review (D65): the shared diff prefix fences the
    # diff with it, so every lens's prefix is byte-identical and the
    # lenses share one cached block.
    fence_nonce = nonce()
    # `resolved` is D68's derived review-wide limits: the Spend and the
    # review deadline run on them, and a limit stop names their derivation.
    # The picker's calls are finished, so the in-flight backpressure does
    # not wait on them. A reservation held because the request was
    # written and never answered stays out of the billed figure (D93).
    # A served call the picker could not price is a bill.
    spend = spend_for_picker(resolved, picker_spend, derivation=derivation)
    started = clock.monotonic()
    deadline = started + resolved.review_wall_s
    runs: list[_LensRun] = []
    planned = tuple(lenses)
    decisions, prior_records, prior_note, decision_failure = _delta_prelude(
        event,
        planned,
        delta,
        round_log,
        model,
        spend,
        resolved,
        clock,
        deadline,
        fence_nonce,
        trace,
        redactor,
        telemetry,
        library,
        blocks,
    )
    if decisions:
        names = tuple(decision.lens for decision in decisions if not decision.reuse)
    else:
        names = planned

    gate = threading.BoundedSemaphore(resolved.create_concurrency)
    # The shared post-setup checkpoint (issue #819, D95): with a setup
    # spec, one setup pass bakes the repo's declared installs with egress
    # allowed, flips to deny-all and checkpoints the result; every lens
    # runner then restores that one checkpoint instead of re-running the
    # setup. A bake that could not make a checkpoint -- a refusal, a
    # failure, a deadline -- is named on the telemetry and every lens
    # falls back to running the setup phase on its own runner, the
    # slice-1 shape; a restore that is refused later fails that lens's
    # run closed, never re-opens the network mid-runner.
    baked = _bake_setup_pass(
        sprites, runner_ledger, setup, event, deadline, clock, telemetry,
        gate, resolved.create_retries, names=names,
    )  # fmt: skip
    if setup is None or not setup.commands:
        runner_setup = None
        runner_restore = None
    elif baked is not None and baked.checkpoint_id is not None:
        # The restore path, with the spec carried alongside: a restore
        # that is refused at lens time retries once on a fresh runner
        # running the setup phase itself (issue #819, D95).
        runner_setup = setup
        runner_restore = baked.checkpoint_id
    elif baked is not None and baked.setup_failed:
        # The bake's own setup failed deterministically; the same
        # commands would fail identically per lens, so no setup runs.
        runner_setup = None
        runner_restore = None
    else:
        runner_setup = setup
        runner_restore = None

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
            ranks=path_ranks,
            run_proposals=run_proposals,
            approval_channel=approval_channel,
            setup=runner_setup,
            restore=runner_restore,
        )

    with ThreadPoolExecutor(max_workers=resolved.pool_size) as pool:
        futures = [
            submit_with_review_context(pool, run, lens, changed, index)
            for index, lens in enumerate(names, start=1)
        ]
        # Emitted as lenses COMPLETE, not in submission order (round-2
        # review of #747, R2-F7): with a pool past one, blocking on the
        # first-submitted future left no record until the slowest lens
        # settled, and a push in that window read as no progress -- the
        # cancel direction. `runs` itself stays in submission order, so
        # the draft's ordering, mint ids and clean-run supersession are
        # exactly what they were.
        completed: dict[int, _LensRun] = {}
        for future in as_completed(futures):
            ran = future.result()
            completed[ran.result.index] = ran
            runs = [completed[index] for index in sorted(completed)]
            _record_progress(
                telemetry, names, runs, spend, changed, funding_source=funding
            )
    runs = _continuation_rounds(
        runs, run, changed, library, spend, resolved, clock, deadline,
        telemetry, names, funding,
    )  # fmt: skip
    _record_progress(
        telemetry,
        names,
        runs,
        spend,
        changed,
        step=PROGRESS_REVIEW_STEP,
        funding_source=funding,
    )
    secrets = [secret for ran in runs for secret in ran.secrets]
    flagged = tuple(value for ran in runs for value in ran.flagged)
    reports = tuple(ran.report for ran in runs if ran.report is not None)
    if (
        baked is not None
        and baked.report is not None
        and (baked.report.status is RunnerStatus.COMPLETED)
    ):
        # The setup pass's completed report rides the draft's runner
        # records like any lens's, cleanup included -- a bake whose
        # destroy went unverified still holds the Runner line, the way
        # any runner's unverified cleanup does. A FAILED bake does not:
        # its work was re-run on the lens runners (the fallback) or the
        # lenses ran without a setup and their own outcomes carry the
        # gap, so a failed row here would hold `coverage_complete` open
        # on a review whose runners all completed. The failure lives on
        # the telemetry, which `_bake_setup_pass` records at ERROR.
        reports = (baked.report, *reports)
    review = synthesize(
        [ran.result for ran in runs],
        secrets,
        _combined_runner(reports),
        spend,
        flagged,
        context_omissions=omissions,
        other_pull_requests=other_pull_requests,
        ceiling_note=derivation.ceiling_note,
        rerank_note=_rerank_note(files, path_ranks, redactor),
        endpoint_class=endpoint_class(model),
        funding_source=funding,
    )
    if decisions:
        review = replace(review, lens_decisions=decisions)
    if delta is not None:
        review = _with_carryforward(
            review,
            event,
            delta,
            prior_records,
            prior_note,
            diff,
            trees,
            changed,
            model,
            spend,
            resolved,
            clock,
            deadline,
            fence_nonce,
            contract or finding_contract(),
            trace,
            redactor,
        )
        # The reused lenses' D73 re-assessment (round-1 review of #760,
        # Major B) composes after the carry-forward: its priors are the
        # carry-forward's own re-anchored dispositions, so the two
        # judgments of the same prior finding cannot disagree about what
        # stands.
        review, decisions = _with_reused_reassessment(
            review,
            event,
            decisions,
            library,
            ledger,
            evidence_digest,
            _prior_digest(prior_records),
            blocks,
            trees,
            diff,
            changed,
            model,
            spend,
            resolved,
            clock,
            deadline,
            fence_nonce,
            contract or finding_contract(),
            trace,
            redactor,
        )
    _record_decisions(telemetry, decisions, decision_failure)
    return _record_round(
        round_log,
        event,
        replace(
            review,
            changed=changed,
            runners=reports,
            delta_from=delta.delta_from if delta is not None else "",
            delta_paths=frozenset(delta.resolution_paths)
            if delta is not None
            else frozenset(),
            lens_decisions=decisions,
            # The refused-key cause is read from the spend one last time,
            # after every composition step (D92's fix round): a carry or a
            # re-assessment call can be the call the key refused, and both
            # run after `synthesize` captured the halt -- the finalized
            # review carries the cause, or a refused-key review would post
            # as an ordinary one.
            review_error=spend.halted_cause or review.review_error,
        ),
        redactor,
        # The digest is stored with the record (D73, round-2 review of
        # #760): a later delta review's trigger reads it, and a record
        # that stores none reads as evidence that cannot be shown to be
        # current, which re-earns the bounded call every round.
        evidence_digest,
    )


def _prior_digest(records: Sequence[RoundRecord]) -> str:
    """The evidence snapshot's digest (D73) the last review recorded at
    the delta base settled under, or "" when none stored one -- which
    reads as "cannot be shown to be current", D73's own trigger for the
    bounded re-assessment."""
    for record in reversed(records):
        if record.evidence_digest:
            return record.evidence_digest
    return ""


def _continuation_rounds(
    runs: list[_LensRun],
    run: Callable[[str, frozenset[str], int], _LensRun],
    changed: frozenset[str],
    library: LensLibrary,
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    deadline: float,
    telemetry: Telemetry | None,
    names: Sequence[str],
    funding_source: str = "",
) -> list[_LensRun]:
    """The continuation rounds (D44): each round hands every lens with
    unread files its own continuation, for up to `MAX_CONTINUATIONS`
    rounds while a call and the review clock remain; a round that does
    not shrink the gap ends it earlier."""
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
            _record_progress(
                telemetry, names, runs, spend, changed, funding_source=funding_source
            )
        after = {
            lens: paths
            for lens, paths in _pending_by_lens(
                tuple(ran.result for ran in runs), changed
            ).items()
            if library.body(lens) is not None
        }
        if not before - _pending_pairs(after):
            break
    return runs


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


def _record_progress(
    telemetry: Telemetry | None,
    names: Sequence[str],
    runs: Sequence[_LensRun],
    spend: Spend,
    changed: frozenset[str],
    *,
    step: str = LENS_SETTLED_STEP,
    funding_source: str = "",
) -> None:
    """One progress record into the run's events file (#702, D79), after
    a lens settles and once when the lens loop ends.

    The service's keep-or-cancel decision reads these back from the run
    directory while the review is still running: the fraction of planned
    lenses with a settled attempt, the spend so far against the derived
    reservation, and the paths the review is still reading. A record
    made while lenses are in flight counts every planned lens without a
    clean run as still reading -- its scope when it has one, the whole
    changed set when it is still running or not yet started, because a
    lens's first pass is submitted over every changed file. The closing
    record reads the gate's own unread list instead: the lens loop has
    ended, so what is still unread is exactly what no lens read. The
    record is cumulative -- the newest one is the state -- and the
    fields are the decision's own inputs, so a mutant that drops any of
    them is visible to the decision's tests. The reading list is capped
    (`head_change.READING_CHARS`): a truncated list reads as a shorter
    one, which keeps a push rather than cancels, the safe direction."""
    if telemetry is None:
        return
    if step == LENS_SETTLED_STEP:
        clean = {ran.result.lens for ran in runs if ran.result.state is LensState.CLEAN}
        latest: dict[str, LensResult] = {}
        for ran in runs:
            latest[ran.result.lens] = ran.result
        reading: set[str] = set()
        for name in names:
            if name in clean:
                continue
            result = latest.get(name)
            reading.update(
                result.scope
                if result is not None and result.scope is not None
                else changed
            )
    else:
        reading = set(_still_unread([ran.result for ran in runs], changed))
    text = cap_reading(sorted(reading))
    done = {ran.result.lens for ran in runs if ran.result.outcome is not None}
    # One sample. `hold` writes settled and then held; reading them
    # separately can book the hold as a bill in a crash backfill
    # (round-1 review of #799).
    committed, settled, held = spend.snapshot()
    fields: dict[str, str | int] = {
        FIELD_LENS: runs[-1].result.lens if runs else "",
        FIELD_LENSES_DONE: len(done),
        FIELD_LENSES_TOTAL: len(names),
        FIELD_CALLS: spend.calls,
        FIELD_COMMITTED_USD: str(committed),
        FIELD_SETTLED_USD: str(settled),
        FIELD_HELD_USD: str(held),
        FIELD_RESERVATION_USD: str(spend.limits.reservation_usd),
        FIELD_READING: text,
    }
    if funding_source:
        fields[FIELD_SOURCE] = funding_source
    telemetry.record(PROGRESS_PHASE, step, fields)


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
    ranks: PathRanks | None = None,
    run_proposals: tuple[CommandProposal, ...] = (),
    approval_channel: ApprovalChannel | None = None,
    setup: SetupSpec | None = None,
    restore: str | None = None,
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
    # The run-scoped operator-approval gate (config slice S7, D88), built
    # per lens run: the proposals the repo's default-branch config named,
    # the channel they become requests on (the decided channel is
    # pre-approval -- installation admins pre-approve on the S10 settings
    # page, part B; no live approval during a review -- and the production
    # default approves nothing until it lands), and the run's own wall and
    # dollar bounds as the
    # wait's limits. The gate and its approved set live and die with this
    # lens run's runner -- an approval is never carried to another lens's
    # runner, another run, or any state on the volume.
    approvals = (
        RunApprovals(
            {p.name: p for p in run_proposals},
            approval_channel if approval_channel is not None else NeverApproved(),
            clock,
            lambda: deadline - clock.monotonic(),
            lambda: spend.committed_usd < resolved.reservation_usd,
        )
        if run_proposals
        else None
    )
    if approvals is not None and telemetry is not None:
        # The run's allow-list is configured: the proposals count is the
        # operator-facing fact (D88) -- a run that proposed nothing and a
        # run whose proposals never reached the coordinator look the same
        # in the draft, and this record is what tells them apart.
        telemetry.record(
            "run approvals", "configured", {"proposals": len(run_proposals)}
        )
    diff_secrets = scan_diff(diff)
    ledger_lens = lens
    if continuation:
        # A continuation is its own ledger entry. The lens's own attempt
        # stays settled when it left files unread (D42); this entry is the
        # coordinator assigning those files, not a retry of that attempt.
        ledger_lens = f"{lens}#{_scope_digest(scope)}"
    else:
        # The run's scope is part of the entry's identity (round-5
        # review of #748): the ledger is deployment-wide, and a delta
        # run's settled lens at this head shares the key a later full
        # run at the same head would compute -- the reused result's
        # unread list is the delta's, and the full review would claim
        # files no lens ever read. The `@` marker cannot collide with
        # the continuation's `#`-hex suffix or `#reassess`; the same
        # scope at the same head still reuses its settled attempt, so a
        # crash-and-resume of one review bills nothing twice.
        ledger_lens = f"{lens}@{_scope_digest(scope)}"
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
        first_turn(event, diff, context, fence_nonce, only=scope, ranks=ranks),
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

    def run_bridge_call(**overrides: Any) -> RunnerReport:
        return run_bridge(
            sprites, runner_ledger, trees, in_session,
            redactor=scrubber, changed=scope, name=name,
            deadline_s=max(deadline - clock.monotonic(), 0.0), clock=clock,
            telemetry=telemetry,
            root=bridge_root,
            create_gate=create_gate,
            create_retries=create_retries,
            approvals=approvals,
            **overrides,
        )  # fmt: skip

    try:
        report = run_bridge_call(setup=setup, restore=restore)
    except RestoreRefusedError as exc:
        # The shared checkpoint could not be restored into this lens's
        # runner (issue #819, D95): an unknown id -- the shape a restore
        # the API will not perform cross-sprite takes -- a refusal, an
        # incomplete restore. The retry is a **fresh runner** running the
        # setup phase itself, the reviewed slice-1 shape: its own
        # provisioning allows egress again before its own flip, and the
        # denied network is never re-opened on the runner that lost the
        # restore. Once, and only while the wall has room; without a
        # setup spec to fall back to, the lens is NOT RUN with the
        # refusal named.
        if setup is None or clock.monotonic() >= deadline:
            missing = LensResult(lens, index, None, None, reason=str(exc), scope=scope)
            return _LensRun(missing, [], None, spend, ())
        if telemetry is not None:
            telemetry.record(
                "checkpoint restore",
                "refused; retrying on a fresh runner with the setup phase",
                status=ERROR,
                error=str(exc),
            )
        report = run_bridge_call(setup=setup, restore=None)
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
    except KeyRefusedError as exc:
        # A refused key is a review error, not a spend (D92): the review's
        # spend halts with the fixed cause the draft and the post carry,
        # and the refusal is never retried. The settle and the halt land
        # under one lock (`fail_and_halt`).
        spend.fail_and_halt(worst, None, exc.review_error)
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED, frozenset({Cause.MODEL_ERROR}), detail=str(exc)
        )
    except ByokRefusedError as exc:
        spend.settle(worst, None)
        spend.halt()
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED, frozenset({Cause.MODEL_ERROR}), detail=str(exc)
        )
    except TransportError as exc:
        # Written and never answered: a hold, not a bill (D58, D93).
        spend.hold(worst)
        return AttemptOutcome(
            Attestation.UNACKNOWLEDGED,
            frozenset({Cause.TRANSPORT_ERROR}),
            detail=str(exc),
        )
    except BoundaryError as exc:
        # The same three-way settle the decision and carry calls run
        # (D92's fix round 4): a priced 200 the turn rejected settles at
        # the parsed cost, a served response with no usable usage keeps
        # the reservation (D43), and a response that never arrived is a
        # failed call, released at $0. Transport failures keep their
        # reservation on the branch above (D58 item 5).
        reported = exc.reported_cost
        if reported is not None and valid_cost(reported):
            spend.settle(worst, reported)
        elif reported is not None:
            spend.settle(worst, None)
        else:
            spend.settle_failure(worst, None)
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


def _delta_prelude(
    event: PrEvent,
    planned: Sequence[str],
    delta: DeltaScope | None,
    round_log: RoundLog | None,
    model: LensModel,
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    deadline: float,
    fence_nonce: str,
    trace: ReviewTrace,
    redactor: Redactor,
    telemetry: Telemetry | None,
    library: LensLibrary,
    blocks: Sequence[UntrustedBlock],
) -> tuple[tuple[LensDecision, ...], tuple[RoundRecord, ...], str, str]:
    """A delta review's prelude (D83): the earlier review's records at
    the delta base -- read once, shared by the decision call and the
    carry-forward -- and the coordinator's per-lens decisions, with the
    decision call's failure text when it fell back. On a full review the
    decisions are empty and the records unused."""
    if delta is None:
        return (), (), "", ""
    records, note = _records_at(round_log, event, delta.delta_from)
    decisions, failure = _decide_lenses(
        event,
        planned,
        _reuse_eligible(records),
        delta,
        records,
        model,
        spend,
        resolved,
        clock,
        deadline,
        fence_nonce,
        trace,
        redactor,
        library,
        blocks,
    )
    return decisions, records, note, failure


def _prior_attribution(record: RoundRecord, index: int, line: str) -> str:
    """The lens a round record's finding line belongs to, as far as the
    record can pin it: the record's own per-line attribution
    (`attributions`, written from this release on and parallel to the
    finding lines), else the `L<n>` id's entry index resolved against
    the record's lens list -- a review's initial runs are its planned
    lenses in plan order, so the first N ids name their lenses exactly --
    else the record's whole lens list when it names exactly one, else ""
    (unattributed: the line still travels every surface; it just cannot
    be pinned on one lens, and the per-lens re-assessment is not offered
    it)."""
    if index < len(record.attributions) and record.attributions[index]:
        return record.attributions[index]
    identifier = line.split(" ", 1)[0]
    match = re.fullmatch(r"L(\d+)-F\d+", identifier)
    names = [name.strip() for name in record.lens.split(",") if name.strip()]
    if match is not None:
        entry = int(match.group(1))
        if 1 <= entry <= len(names):
            return names[entry - 1]
        return ""
    if len(names) == 1:
        return names[0]
    return ""


def _reuse_eligible(records: Sequence[RoundRecord]) -> frozenset[str]:
    """The lenses a delta review may reuse (D83): the ones the earlier
    review at the delta base recorded with a settled clean run. A record
    that carries the `clean_lenses` field answers exactly (D76's rule:
    some entry of the lens ran clean; a lens the earlier review ran to a
    failure has no settled result to reuse, round-1 review of #760,
    Minor C); a record from before the field falls back to its lens
    list, which names every lens the review ran or reused -- what those
    settled as is the old record's to answer for, and this docstring no
    longer claims they ran clean."""
    names: set[str] = set()
    carrying = []
    for record in records:
        names.update(name.strip() for name in record.lens.split(",") if name.strip())
        if record.clean_lenses is not None:
            carrying.append(record)
    if not carrying:
        return frozenset(names)
    # A lens settled clean in any review recorded at the delta base has
    # a settled result that review stood behind; reuse builds on it.
    eligible: set[str] = set()
    for record in carrying:
        eligible.update(record.clean_lenses or ())
    return frozenset(eligible)


def _decide_lenses(
    event: PrEvent,
    planned: Sequence[str],
    eligible: frozenset[str],
    delta: DeltaScope,
    records: Sequence[RoundRecord],
    model: LensModel,
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    deadline: float,
    fence_nonce: str,
    trace: ReviewTrace,
    redactor: Redactor,
    library: LensLibrary,
    blocks: Sequence[UntrustedBlock],
) -> tuple[tuple[LensDecision, ...], str]:
    """The coordinator's per-lens decision for a delta review (D83).

    The returned tuple holds exactly one decision per planned lens, in
    plan order, plus the decision call's failure text when it fell back
    (the caller records the decisions once the re-assessments have
    composed, so the telemetry event carries the whole disposition). A
    lens the earlier review did not settle clean has no settled result
    at the delta base and re-runs structurally; the rest are the
    judgment call's to decide -- from the incremental diff and the fresh
    evidence, whether the incoming changes could affect the lens's
    concern. The call is skipped, and every lens re-runs (the safe
    direction), when the delta could not be established: with no
    incremental diff there is nothing to judge from, and the follow-up
    is an ordinary full review. It is also skipped when the offer is
    empty (round-1 review of #760, Minor E): nothing is reusable, every
    lens re-runs structurally, and a billed call could not change the
    outcome. An empty established delta -- a merge-only push, or an
    established comparison with no readable patch -- is judged without a
    call: no incoming change can affect any concern, so every eligible
    lens's settled result stands and the carry-forward does the carrying.
    A failed or refused judgment call falls back to re-running every
    eligible lens, with the failure named; a reuse is never silently
    invented, and never silently kept on a broken reply."""
    eligible_in_order = tuple(lens for lens in planned if lens in eligible)
    touched = frozenset(delta.resolution_paths)
    offered = tuple(
        (lens, library.concern(lens), _cites_delta(records, lens, touched))
        for lens in eligible_in_order
    )
    failure = ""
    if delta.note:
        decided = fallback_decisions(
            eligible_in_order,
            "the delta could not be established; the review runs on the "
            "whole pull request and no lens is reused",
        )
    elif not eligible_in_order:
        # Nothing is reusable: no billed judgment call, every planned
        # lens re-runs structurally below.
        decided = ()
    elif not delta.range_diff:
        decided = tuple(
            LensDecision(
                lens,
                True,
                "the incremental diff is empty, so no incoming change "
                "could affect any lens's concern",
            )
            for (lens, _concern, _flagged) in offered
        )
    else:
        scrubber = Redactor(redactor.known_secrets, redactor.sources)
        lens_trace = trace.with_scrub(lambda text: scrubber(text).text)
        try:
            decided = _decision_call(
                event,
                offered,
                delta,
                lens_trace.wrap_model(model),
                spend,
                resolved,
                clock,
                deadline,
                fence_nonce,
                blocks,
            )
        except Exception as exc:  # noqa: BLE001 -- a failed decision re-runs every lens
            failure = f"{type(exc).__name__}: {scrubber(str(exc)).text}"
            decided = fallback_decisions(
                eligible_in_order,
                f"the coordinator's decision call failed ({failure}); every "
                "lens re-runs on the whole pull request",
            )
    by_lens = {decision.lens: decision for decision in decided}
    for lens in planned:
        by_lens.setdefault(
            lens,
            LensDecision(
                lens,
                False,
                _NO_PRIOR_RESULT_WHY,
                flagged=_cites_delta(records, lens, touched),
            ),
        )
    # The flag is the offer's, not the reply's: every decision for a lens
    # the turn flagged carries the flag, whatever the reply decided.
    flags = {name: flagged for name, _concern, flagged in offered}
    every = tuple(
        replace(by_lens[lens], flagged=flags[lens]) if lens in flags else by_lens[lens]
        for lens in planned
    )
    return every, failure


def _cites_delta(
    records: Sequence[RoundRecord], lens: str, touched: frozenset[str]
) -> bool:
    """Whether a lens's earlier findings cite files the incremental diff
    touches -- the highest-stakes reuse, flagged to the coordinator's
    decision turn and recorded with the decision (D83, round-1 review of
    #760). The signal is data for the judgment, never a rule: a flagged
    lens may still be reused, when the coordinator judges the delta's
    change to those files outside the findings' concern."""
    if not touched:
        return False
    for record in records:
        for position, line in enumerate(record.findings):
            if _prior_attribution(record, position, line) != lens:
                continue
            found = parse_prior_line(line)
            if found is None:
                continue
            path = _cited_path(found[1].location)
            if path is not None and path in touched:
                return True
    return False


_NO_PRIOR_RESULT_WHY = (
    "the earlier review did not run it, so there is no settled result "
    "at the delta base to reuse"
)


def _record_decisions(
    telemetry: Telemetry | None,
    decisions: Sequence[LensDecision],
    failure: str = "",
) -> None:
    """One telemetry event per lens decision (D83), so the reuse policy's
    judgments are readable next to the review cost events when it is
    tuned. Each event carries the whole disposition: the decision and
    its reason, whether the lens's earlier findings cite the delta's
    files, and -- recorded after the re-assessments composed (D73) --
    whether the reused lens was re-assessed and with what note. A
    decision call that failed records its error event first; every
    decision still lands."""
    if telemetry is None:
        return
    if failure:
        telemetry.record(
            DECISION_PHASE,
            "lens decision",
            {"decision": "rerun"},
            status=ERROR,
            error=failure,
        )
    for decision in decisions:
        fields: dict[str, str | int | float | bool | None] = {
            "lens": decision.lens,
            "decision": "reuse" if decision.reuse else "rerun",
            "reason": decision.reason,
            "cites_delta": decision.flagged,
        }
        if decision.reuse:
            fields["reassessed"] = decision.reassessed
            if decision.reassess_note:
                fields["reassess_note"] = decision.reassess_note
        telemetry.record(DECISION_PHASE, "lens decision", fields)


DECISION_PHASE = "delta review"


class DecisionCallRefused(Exception):
    """A decision call the review's own limits refused before it was
    sent. The caller falls back to re-running every lens, and the
    refusal's text is named in the draft."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


def _decision_call(
    event: PrEvent,
    offered: Sequence[tuple[str, str | None, bool]],
    delta: DeltaScope,
    traced_model: LensModel,
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    deadline: float,
    fence_nonce: str,
    blocks: Sequence[UntrustedBlock],
) -> tuple[LensDecision, ...]:
    """One bounded coordinator-decision call (D83): the incremental diff,
    the fresh evidence around the pull request (the conversation and CI
    blocks the lenses get -- the same data a reused lens's D73
    re-assessment would see) and the reuse-eligible lens names with
    their concern summaries in, one final reply out, validated against
    the offered names. No tools are offered; the call is reserved at its
    worst case against the review's shared spend (D68) and settled like
    any turn; a BYOK refusal halts the review's spend the way one in the
    lens loop does."""
    block = (
        UntrustedBlock(
            "delta-diff", RepoText(capped(delta.range_diff, DELTA_DIFF_CHARS))
        )
        if delta.range_diff
        else None
    )
    # The turn's own delta block is the guaranteed copy; a context block
    # the CLI built for the lenses would duplicate it.
    extra = tuple(block_ for block_ in blocks if block_.label != "delta-diff")
    request = TurnRequest(
        decision_system(fence_nonce),
        (UserText(decision_turn(event, offered, block, extra, fence_nonce)),),
        (),
        None,
    )  # fmt: skip
    if clock.monotonic() >= deadline:
        # The wall check before the reservation (the carry-forward's own
        # rule, round-5 review of #748): a decision call that starts
        # after the lens loop's deadline must not reserve -- let alone
        # send -- a billable request; the fallback re-runs every lens.
        raise DecisionCallRefused(
            "the review's deadline passed before the lens decisions could be made"
        )
    reserved = _reserve_call(traced_model, request, spend, clock, deadline, fit=False)
    if not isinstance(reserved, _Reserved):
        raise DecisionCallRefused(reserved[1])
    worst = reserved.worst
    if clock.monotonic() >= deadline:
        # The reservation is released (D92): the call was never sent, so
        # nothing was held in flight and nothing was billed.
        spend.settle_failure(worst, None)
        raise DecisionCallRefused(
            "the review's deadline passed while the decision call "
            "reserved; the call was not sent"
        )
    try:
        reply = traced_model.turn(request)
    except KeyRefusedError as exc:
        # A refused key is a review error, not a spend (D92): the review's
        # spend halts with the fixed cause, and the decision fallback then
        # re-runs lenses on a halted spend -- every one NOT RUN -- so the
        # review renders and posts as the error the cause names.
        spend.fail_and_halt(worst, None, exc.review_error)
        raise
    except ByokRefusedError:
        spend.settle(worst, None)
        spend.halt()
        raise
    except TransportError:
        # A written request may still have been billed (D58 item 5,
        # restored by D92's fix round): the reservation is kept, and it
        # is a hold, not a bill (D93).
        spend.hold(worst)
        raise
    except BoundaryError as exc:
        # The settle reads what the exception carries (D92's fix round):
        # a priced 200 the turn rejected settles at the parsed cost, a
        # served response with no usable usage keeps the reservation
        # (D43), and anything that never served a response releases at $0.
        reported = exc.reported_cost
        if reported is not None and valid_cost(reported):
            spend.settle(worst, reported)
        elif reported is not None:
            spend.settle(worst, None)
        else:
            spend.settle_failure(worst, None)
        raise
    spend.settle(worst, reply.cost_usd)
    if not isinstance(reply, FinalReply):
        raise ContractError("the decision reply was a tool call, and the turn has none")
    return parse_decision_reply(
        reply.text, [name for name, _concern, _flagged in offered]
    )


def _with_carryforward(
    review: AgenticReview,
    event: PrEvent,
    delta: DeltaScope,
    records: Sequence[RoundRecord],
    log_note: str,
    diff: str,
    trees: SourceTrees,
    changed: frozenset[str],
    model: LensModel,
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    deadline: float,
    fence_nonce: str,
    contract: str,
    trace: ReviewTrace,
    redactor: Redactor,
) -> AgenticReview:
    """The delta review's carry-forward step (#702, D79): the earlier
    review's findings -- the round log's records at `delta_from`, read
    once before the lenses ran and shared with the decision call -- are
    carried forward through one bounded, tool-less call, then composed
    into the review's findings, verdict and draft.

    Every prior finding ends somewhere visible: re-anchored and verified
    in the findings set, resolved with its stated reason and its
    evidence, or carried as the record stored it -- in the draft's
    carried section and back into this review's round record, so the
    next review re-offers it. Nothing is silently dropped (D73): a line
    that does not parse travels as raw text, and a record whose finding
    lines did not fit the record cap is named as the omission it is. The
    resolution gate is `resolution_paths`, empty whenever the delta
    could not actually be established -- a resolution is then refused
    however the assessor proposed it. The turn carries the incremental
    diff when the delta is established -- the new material, never the
    whole pull request's diff re-sent (D68) -- and the full diff only on
    the fallback, where there is no established delta to highlight. A
    carry-forward call that fails -- a contract refusal, a transport
    error, a spent-out review -- falls back to carrying every prior
    finding as recorded, with the failure named; the composition itself
    never raises."""
    review = replace(review, delta_note=delta.note)
    delta_from = delta.delta_from
    prior: list[tuple[str, Finding, str]] = []
    raw_lines: list[str] = []
    for record in records:
        for position, line in enumerate(record.findings):
            attribution = _prior_attribution(record, position, line)
            found = parse_prior_line(line)
            if found is None:
                # Never dropped (D73): the raw line travels to the draft's
                # carried section and back into this review's record.
                raw_lines.append(line)
            else:
                # The carry-forward labels the priors by position (P1,
                # P2, ...), the labels `prior_findings_block` renders and
                # the reply's `revises`/`withdrawn` entries resolve
                # against; the record's own stored id stays in the record,
                # and the lens the line is attributed to travels with it
                # -- the per-lens re-assessment's (D73) input. When no
                # rule can pin the line, the attribution stays empty:
                # a legacy record's whole comma-joined lens list is
                # never stored as if it were one lens (round-2 review of
                # #760, Nit 2).
                prior.append((f"P{len(prior) + 1}", found[1], attribution))
    omitted = sum(record.findings_omitted for record in records)
    if not prior and not raw_lines and not omitted:
        # An unreadable log is not "no findings recorded" -- nothing is
        # known -- so only the read failure is named (round-1 m1).
        note = log_note or (
            f"no findings are recorded for the review at {delta_from[:12]}; "
            "nothing carried forward"
        )
        return replace(review, delta_note=_merge_note(review.delta_note, note))
    scrubber = Redactor(redactor.known_secrets, redactor.sources)
    lens_trace = trace.with_scrub(lambda text: scrubber(text).text)
    try:
        result = _carry_call(
            event,
            [(identifier, finding) for identifier, finding, _lens in prior],
            # The assessor's readable content: the incremental diff when
            # the delta is established, the whole pull request's diff
            # only on the fallback (D83).
            delta.range_diff if not delta.note else diff,
            trees,
            changed,
            delta.resolution_paths,
            delta.gate_reason,
            delta.removed,
            spend,
            resolved,
            clock,
            deadline,
            fence_nonce,
            contract,
            lens_trace.wrap_model(model),
        )
    except Exception as exc:  # noqa: BLE001 -- a failed carry-forward keeps every prior finding
        result = CarryResult(
            (),
            tuple((identifier, finding) for identifier, finding, _lens in prior),
            (),
            (
                (
                    f"the carry-forward call failed ({type(exc).__name__}: "
                    f"{scrubber(str(exc)).text}); "
                    "every prior finding is carried as the earlier review "
                    "recorded it"
                ),
            ),
        )
    return _compose_carry(
        review,
        prior,
        result,
        delta_from,
        spend,
        raw_lines,
        omitted,
        log_note,
    )


def _records_at(
    round_log: RoundLog | None,
    event: PrEvent,
    delta_from: str,
) -> tuple[tuple[RoundRecord, ...], str]:
    """The round log's records for this pull request at the delta base,
    and a controller note when the log itself could not be read --
    "nothing carried" over an unreadable log is a false statement, so
    the read failure is named instead. The records' finding lines are
    the caller's to walk: the same walk collects the parsed findings and
    the raw lines that do not parse, so neither is counted twice."""
    if round_log is None:
        return (), ""
    loaded = round_log.read()
    if loaded.file_unreadable:
        detail = (
            "the round log file could not be read, so no earlier findings "
            "could be carried"
        )
        if loaded.quarantined_to:
            detail += f"; it was moved aside to {loaded.quarantined_to}"
        return (), detail
    mine, _others = records_for(loaded.records, event.repo, event.pr_number)
    return tuple(record for record in mine if record.head_sha == delta_from), ""


def _carry_call(
    event: PrEvent,
    prior: Sequence[tuple[str, Finding]],
    payload: str,
    trees: SourceTrees,
    changed: frozenset[str],
    resolution_paths: frozenset[str],
    gate_reason: str,
    range_removed: Mapping[str, tuple[tuple[int, str], ...]],
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    deadline: float,
    fence_nonce: str,
    contract: str,
    traced_model: LensModel,
) -> CarryResult:
    """One bounded carry-forward call (#702): the prior findings and the
    incremental diff in, one final reply out, quote-checked through the
    re-assessment judge against the head files. No tools are offered; the
    call is reserved at its worst case against the review's shared spend
    (D68) and settled like any turn; a BYOK refusal halts the review's
    spend the way one in the loop does. The resolution gate is the
    caller's: `resolution_paths` when the delta is established, empty
    when it is not. `payload` is the incremental diff when the delta is
    established -- the RANGE's own per-file patches (`delta_from..head`,
    which the pull request's net diff cannot show: a delta commit
    deleting PR-added code is invisible where the line exists at neither
    end), never the whole pull request's diff re-sent (D68, D83) -- and
    the full diff only on the fallback, where no delta was established.
    The removed-line evidence the reply's proposals quote is checked
    against that range's pool, span-bounded to the finding's citation
    (round-2 review of #748, Major A, a2)."""
    # The assessor's readable content and the judge's quote sources are
    # the payload: a re-statement quoting the payload's added lines
    # verifies against the head tree (they are head content), and its
    # removed runs are the range's deletions.
    sources = read_sources(trees.head, payload, changed)
    checked_prior = [
        CheckedFinding(finding, QuoteSource.HEAD) for _id, finding in prior
    ]
    delta_block = (
        UntrustedBlock("delta-diff", RepoText(capped(payload, DELTA_DIFF_CHARS)))
        if payload
        else None
    )
    request = TurnRequest(
        carry_system(contract, fence_nonce),
        (
            UserText(
                carry_turn(event, prior_findings_block(checked_prior), delta_block, fence_nonce)
            ),
        ),
        (),
        None,
    )  # fmt: skip
    if clock.monotonic() >= deadline:
        # The wall check before the reservation (round-5 review of
        # #748): a carry call that starts after the lens loop's deadline
        # must not reserve -- let alone send -- a billable request; the
        # carry fallback carries every prior finding as recorded.
        raise CarryCallRefused(
            "the review's deadline passed before the carry-forward could run"
        )
    reserved = _reserve_call(traced_model, request, spend, clock, deadline, fit=False)
    if not isinstance(reserved, _Reserved):
        raise CarryCallRefused(reserved[1])
    worst = reserved.worst
    if clock.monotonic() >= deadline:
        # The reservation fits immediately and never consults the clock,
        # so the wall check is ours (round-5 review of #748): the lens
        # loop ended at the deadline, and a billable call sent after it
        # spends past the wall the review respects. The reservation is
        # released (D92): the call was never sent, so nothing was held
        # in flight and nothing was billed. The carry fallback carries
        # every prior finding as recorded.
        spend.settle_failure(worst, None)
        raise CarryCallRefused(
            "the review's deadline passed while the carry-forward "
            "reserved; the call was not sent"
        )
    try:
        reply = traced_model.turn(request)
    except KeyRefusedError as exc:
        # A refused key is a review error, not a spend (D92): the review's
        # spend halts with the fixed cause; the carry fallback composes the
        # priors as recorded, and the finalized review carries the cause
        # as its review error -- the posted result is the error or the
        # partial record it names, never an ordinary review.
        spend.fail_and_halt(worst, None, exc.review_error)
        raise
    except ByokRefusedError:
        spend.settle(worst, None)
        spend.halt()
        raise
    except TransportError:
        # A written request may still have been billed (D58 item 5,
        # restored by D92's fix round): the reservation is kept, and it
        # is a hold, not a bill (D93).
        spend.hold(worst)
        raise
    except BoundaryError as exc:
        # The settle reads what the exception carries (D92's fix round):
        # a priced 200 the turn rejected settles at the parsed cost, a
        # served response with no usable usage keeps the reservation
        # (D43), and anything that never served a response releases at $0.
        reported = exc.reported_cost
        if reported is not None and valid_cost(reported):
            spend.settle(worst, reported)
        elif reported is not None:
            spend.settle(worst, None)
        else:
            spend.settle_failure(worst, None)
        raise
    spend.settle(worst, reply.cost_usd)
    if not isinstance(reply, FinalReply):
        raise ContractError(
            "the carry-forward reply was a tool call, and the turn has none"
        )
    parsed = parse_carry_reply(reply.text)
    checked, revises = judged_carry(
        parsed, prior, sources, trees.head, resolved.quote_tolerance
    )
    result = apply_carry(
        prior,
        checked,
        revises,
        parsed.withdrawn,
        resolution_paths,
        range_removed,
        gate_reason,
        resolved.quote_tolerance,
    )
    if parsed.dropped:
        # The parser's dropped entries are named where the draft reads
        # them (round-5 review of #748): a restatement the parser
        # refused -- an unknown severity, say -- leaves the prior
        # finding standing (it falls to the unanchored carries), and the
        # drop's reason travels with the rest of the carry-forward's
        # notes instead of vanishing with the reply (D54's
        # dropped-finding rule).
        result = replace(result, notes=(*result.notes, *parsed.dropped))
    return result


class CarryCallRefused(Exception):
    """A carry-forward call the review's own limits refused before it was
    sent. The caller falls back to carrying every prior finding as
    recorded, and the refusal's text is named in the draft."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


def _compose_carry(
    review: AgenticReview,
    prior: Sequence[tuple[str, Finding, str]],
    result: CarryResult,
    delta_from: str,
    spend: Spend,
    raw_lines: Sequence[str],
    omitted: int,
    log_note: str,
) -> AgenticReview:
    """The delta review with the carry-forward composed in: the carried
    findings join the minted ones (deduplicated -- a carried copy kept
    over a new duplicate, and one carried copy over a second record's
    restatement of the same finding), the verdict is recomputed over the
    combined set WITH the carried-but-unre-anchored priors counted as
    verdict-setting -- a prior Blocker that fails to re-anchor can never
    become an approval -- and the carry's buckets, raw lines and notes
    land on the review for the draft and the round record."""
    lens_labels = {identifier: lens for identifier, _finding, lens in prior}
    # The duplicate pairs' representatives (round-5 review of #748): a
    # verdict-setting finding beats one that does not set the verdict,
    # then the stronger severity, ties keeping the incumbent. The
    # first-match rule this replaces dropped a verified Blocker under a
    # carried Major restating the same text -- and the same loss between
    # two carried copies -- and flipped a BLOCK to an
    # approve-with-changes.
    representatives: dict[tuple[str, str], MintedFinding] = {}
    for identifier, checked in result.carried:
        _keep_stronger(
            representatives,
            MintedFinding(
                identifier,
                lens_labels.get(identifier, ""),
                checked.finding,
                True,
                "" if checked.source is None else checked.source.value,
                "",
                checked.drift,
                True,
            ),
        )
    for minted in review.findings:
        _keep_stronger(representatives, minted)
    combined = rank(tuple(representatives.values()))
    notes = list(result.notes)
    if raw_lines:
        notes.append(
            f"{len(raw_lines)} finding line(s) at {delta_from[:12]} could not "
            "be parsed and are carried as the record's raw text"
        )
    if omitted:
        notes.append(
            f"{omitted} verified finding(s) from the review at "
            f"{delta_from[:12]} were not stored in that round's record (its "
            f"{RECORD_CHARS}-character cap), so they cannot be carried; the "
            "record names the omission"
        )
    if log_note:
        notes.append(log_note)
    note = "; ".join(notes)
    return replace(
        review,
        findings=combined,
        verdict=decide(
            combined,
            carried_setting=tuple(
                finding.severity
                for _identifier, finding in result.unanchored
                if finding.sets_verdict
            ),
        ),
        carried_unverified=tuple(
            (identifier, finding, lens_labels.get(identifier, ""))
            for identifier, finding in result.unanchored
        ),
        carried_raw=tuple(raw_lines),
        carried_omitted=omitted,
        resolved=result.resolved,
        delta_note=_merge_note(review.delta_note, note),
        model_calls=spend.calls,
        committed_usd=str(spend.committed_usd),
        billed_usd=str(spend.billed_usd()),
        held_usd=str(spend.held_usd),
        # The carry call settles after `synthesize` captured the overruns,
        # so the tripwire line is refreshed here with it (round-3 review
        # of #757) -- an overrun on a post-synthesis settle is counted in
        # committed spend and must reach the draft's cost line too.
        settle_overruns=tuple(spend.overruns),
    )


def _reassess_reused_lens(
    event: PrEvent,
    decision: LensDecision,
    findings: list[MintedFinding],
    library: LensLibrary,
    ledger: AttemptLedger,
    evidence_digest: str | None,
    prior_digest: str,
    blocks: Sequence[UntrustedBlock],
    trees: SourceTrees,
    diff: str,
    changed: frozenset[str],
    traced_model: LensModel,
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    deadline: float,
    fence_nonce: str,
    contract: str,
    scrub: Callable[[str], str],
    order: int,
) -> tuple[LensDecision, list[tuple[int, MintedFinding]], list[MintedFinding]]:
    """One reused lens's D73 re-assessment (round-1 review of #760,
    Major B): the trigger check against the digests, the bounded call on
    the delta review's own `#reassess-delta` ledger key, and the
    composition -- the reply's revisions swapped into the review's
    findings in place (returned as `(index, minted)` swaps), its
    additions returned to append, its annotations carried on the
    decision. The composition's input is the `findings` list the caller
    is building, not the review object (round-2 review of #760, Nit 1).
    A reused lens with no attributed, verified standing
    finding, no body in the bundle, or a review that gathered no
    snapshot is left exactly as the carry-forward left it."""
    carried = [f for f in findings if f.carried and f.lens == decision.lens]
    body = library.body(decision.lens)
    if not carried or body is None or evidence_digest is None:
        return decision, [], []
    key = LensKey(
        event.repo,
        event.pr_number,
        event.head_sha,
        f"{decision.lens}{REASSESS_SUFFIX}-delta",
        body_digest(body),
    )
    settled = AttemptOutcome(
        Attestation.ATTESTED,
        frozenset(),
        findings=tuple(CheckedFinding(f.finding, QuoteSource.HEAD) for f in carried),
        turns=0,
    )
    recorded = ledger.attempts(key)
    stored = ledger.evidence_digest(key) if recorded else (prior_digest or None)
    effective, withdrawn, note = effective_outcome(settled, recorded)
    reassessed = bool(recorded)
    if stored is not None and stored == evidence_digest:
        pass
    elif spend.halted or clock.monotonic() >= deadline:
        why = (
            "the review's spend was halted"
            if spend.halted
            else "the review's wall clock had passed"
        )
        note = f"the re-assessment was not run: {why}"
    else:
        number = len(recorded) + 1
        ledger.start(key, number)
        try:
            outcome = _reassess_call(
                event,
                decision.lens,
                body,
                contract,
                fence_nonce,
                blocks,
                [CheckedFinding(f.finding, QuoteSource.HEAD) for f in carried],
                trees,
                diff,
                changed,
                traced_model,
                spend,
                resolved,
                clock,
                deadline,
            )
        except Exception as exc:  # noqa: BLE001 -- a supplementary call's failure must not fail the review
            outcome = AttemptOutcome(
                Attestation.UNACKNOWLEDGED,
                frozenset({Cause.MODEL_ERROR}),
                detail=str(exc),
            )
        ledger.finish(
            key,
            number,
            outcome,
            scrub=scrub,
            evidence_digest=(
                evidence_digest if outcome.attestation is Attestation.ATTESTED else None
            ),
        )
        effective, withdrawn, note = effective_outcome(settled, ledger.attempts(key))
        reassessed = True
    dropped = [
        note_text for note_text in effective.dropped if note_text not in settled.dropped
    ]
    if dropped:
        note = f"{note}; " + "; ".join(dropped) if note else "; ".join(dropped)
    settled_keys = {_finding_key(checked.finding) for checked in settled.findings}
    replacement_keys = {
        _finding_key(w.replacement.finding)
        for w in withdrawn
        if w.replaced and w.replacement is not None
    }
    swaps: list[tuple[int, MintedFinding]] = []
    for w in withdrawn:
        if not (w.replaced and w.replacement is not None):
            continue
        prior_key = _finding_key(w.finding)
        for index, minted in enumerate(findings):
            if minted.carried and _finding_key(minted.finding) == prior_key:
                swaps.append(
                    (
                        index,
                        replace(
                            minted,
                            finding=w.replacement.finding,
                            source=(
                                ""
                                if w.replacement.source is None
                                else w.replacement.source.value
                            ),
                            drift=w.replacement.drift,
                        ),
                    )
                )
                break
    added = 0
    additions: list[MintedFinding] = []
    for checked in effective.findings:
        finding_key = _finding_key(checked.finding)
        if finding_key in settled_keys or finding_key in replacement_keys:
            continue
        added += 1
        additions.append(
            MintedFinding(
                f"R{order}-F{added}",
                decision.lens,
                checked.finding,
                checked.verified,
                "" if checked.source is None else checked.source.value,
                checked.problem,
                checked.drift,
            )
        )
    return (
        replace(
            decision,
            reassessed=reassessed,
            reassess_note=note,
            withdrawn=withdrawn,
            gained_findings=bool(additions),
        ),
        swaps,
        additions,
    )


def _with_reused_reassessment(
    review: AgenticReview,
    event: PrEvent,
    decisions: tuple[LensDecision, ...],
    library: LensLibrary,
    ledger: AttemptLedger,
    evidence_digest: str | None,
    prior_digest: str,
    blocks: Sequence[UntrustedBlock],
    trees: SourceTrees,
    diff: str,
    changed: frozenset[str],
    model: LensModel,
    spend: Spend,
    resolved: Limits,
    clock: Clock,
    deadline: float,
    fence_nonce: str,
    contract: str,
    trace: ReviewTrace,
    redactor: Redactor,
) -> tuple[AgenticReview, tuple[LensDecision, ...]]:
    """The reused lenses' D73 re-assessment (round-1 review of #760,
    Major B). Brandon's D73 is binding on the delta-reuse path exactly as
    on the ledger-reuse path: a reused result keeps its findings, and
    when newer CI evidence or comments exist the lens re-assesses and
    adds, revises or follows up. A reused lens has no ledger entry at
    this head -- the ledger is keyed by head SHA and the earlier head's
    run directory is gone -- so its settled result is the round record's,
    and the mechanism is made reachable rather than reinvented: the same
    bounded, tool-less `_reassess_call` runs, its attempts recorded on
    the delta review's own `#reassess-delta` ledger key at this head
    (distinct from the ledger-reuse path's key, whose composition inputs
    are a settled outcome rather than record lines), composed by the same
    `effective_outcome`.

    The trigger is D73's own digest rule: the record stores the digest
    the earlier review settled under (`RoundRecord.evidence_digest`), and
    this review's snapshot digest is compared against it -- a moved or
    absent digest is newer evidence or evidence that cannot be shown to
    be current, and every reused lens whose findings stand earns its one
    bounded call. A reused lens with no attributed, verified standing
    finding earns none (nothing to re-assess -- the same rule that
    spares an unattested settled result a call), and so does a review
    that gathered no snapshot: D73's check is not wired there, and the
    carry-forward's disposition of every prior finding against the
    incremental diff is the re-assessment that ran.

    The priors are the lens's carried findings -- the carry-forward's
    re-anchored, quote-verified versions of what the record stored; only
    verified priors take part (D73's rule), and the carried-but-
    unanchored ones stand untouched beside them. The reply's additions
    join the review's findings (quote-verified at this head by the
    re-assessment judge, minted `R<n>-F<m>` under the reused lens's
    name), its revisions replace the carried findings they name -- never
    lowering a Blocker's or a Major's severity: annotation-only, the D73
    rule -- its withdrawals are annotations that remove nothing, and a
    reply the contract refused keeps every prior finding and is named.
    The composition lands on the decision (`reassessed`, the note, the
    withdrawals), so it travels the same four surfaces every decision
    travels, and the verdict is recomputed over the composed set."""
    reused = [decision for decision in decisions if decision.reuse]
    if not reused:
        return review, decisions
    scrubber = Redactor(redactor.known_secrets, redactor.sources)

    def scrub(text: str) -> str:
        return scrubber(text).text

    lens_trace = trace.with_scrub(scrub)
    findings = list(review.findings)
    new_decisions: list[LensDecision] = []
    swaps: list[tuple[int, MintedFinding]] = []
    additions: list[MintedFinding] = []
    reassessed_count = 0
    for decision in decisions:
        if not decision.reuse:
            new_decisions.append(decision)
            continue
        reassessed_count += 1
        outcome = _reassess_reused_lens(
            event,
            decision,
            findings,
            library,
            ledger,
            evidence_digest,
            prior_digest,
            blocks,
            trees,
            diff,
            changed,
            lens_trace.wrap_model(model),
            spend,
            resolved,
            clock,
            deadline,
            fence_nonce,
            contract,
            scrub,
            reassessed_count,
        )
        new_decision, lens_swaps, lens_additions = outcome
        swaps.extend(lens_swaps)
        additions.extend(lens_additions)
        new_decisions.append(new_decision)
    for index, minted in swaps:
        findings[index] = minted
    findings.extend(additions)
    ranked = rank(tuple(findings))
    return (
        replace(
            review,
            findings=ranked,
            verdict=decide(
                ranked,
                carried_setting=tuple(
                    finding.severity
                    for _identifier, finding, _lens in review.carried_unverified
                    if finding.sets_verdict
                ),
            ),
            model_calls=spend.calls,
            committed_usd=str(spend.committed_usd),
            billed_usd=str(spend.billed_usd()),
            held_usd=str(spend.held_usd),
            # The re-assessment call settles after `synthesize` captured
            # the overruns, so the tripwire line is refreshed here with it
            # (round-3 review of #757), the way the totals are.
            settle_overruns=tuple(spend.overruns),
        ),
        tuple(new_decisions),
    )


def _merge_note(seeded: str, note: str) -> str:
    """Two controller notes about the delta review in one line, seeded
    first (the CLI's fallback note), the carry-forward's after."""
    if not seeded:
        return note
    return f"{seeded}; {note}" if note else seeded


def _scope_digest(scope: frozenset[str]) -> str:
    """The scope's short digest, the suffix that makes a lens ledger
    entry scope-specific (round-5 review of #748)."""
    return hashlib.sha256("\n".join(sorted(scope)).encode()).hexdigest()[:12]


def _keep_stronger(
    representatives: dict[tuple[str, str], MintedFinding], candidate: MintedFinding
) -> None:
    """Keep the stronger of the candidate and the finding already keyed
    by the same (location, text) pair, in place; the first incumbent
    wins a tie. The composition's dedupe runs through this, so a
    duplicate pair is one finding whose severity and verdict eligibility
    are the pair's strongest (round-5 review of #748)."""
    key = (str(candidate.finding.location), candidate.finding.finding)
    kept = representatives.get(key)
    if kept is None:
        representatives[key] = candidate
        return
    if candidate.finding.sets_verdict != kept.finding.sets_verdict:
        representatives[key] = candidate if candidate.finding.sets_verdict else kept
        return
    if candidate.finding.severity.rank < kept.finding.severity.rank:
        representatives[key] = candidate


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
            # turns, tool calls and executed runs already seen are part
            # of that record.
            session.secrets.extend(secrets_seen)
            ledger.finish(
                key, step.number,
                AttemptOutcome(
                    Attestation.UNACKNOWLEDGED,
                    frozenset({Cause.MODEL_ERROR}),
                    tools=cast("tuple[ToolUse, ...]", tuple(exc.tools)),
                    turns=exc.turns,
                    test_runs=exc.test_runs,
                    mutants_survived=exc.mutants_survived,
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
    evidence_digest: str | None = None,
) -> AgenticReview:
    """Append the one record for this finished review (D52), from the
    synthesized verdict over every lens and continuation. `evidence_digest`
    is the snapshot the review's reuse judgments settled under (D73),
    stored so a later delta review can tell newer evidence from
    unchanged evidence."""
    if round_log is None:
        return review
    scrubber = Redactor(
        redactor.known_secrets, redactor.sources, (*redactor.flagged, *review.flagged)
    )
    names = tuple(
        dict.fromkeys(
            (
                *(result.lens for result in review.lenses),
                # A reused lens (D83) ran no entry, but it belongs on the
                # record's lens list all the same: the list is what a
                # later round reads to know which lenses the earlier
                # reviews of this pull request actually ran or reused,
                # while `clean_lenses` is what gates the offer.
                *(
                    decision.lens
                    for decision in review.lens_decisions
                    if decision.reuse
                ),
            )
        )
    )
    try:
        round_log.append(
            _round_record(
                event,
                ", ".join(names),
                review,
                lambda text: scrubber(text).text,
                evidence_digest,
            )
        )
    except OSError as exc:
        note = f"the round log was not written: {_log_write_cause(exc)}. Detail: {exc}"
        return replace(review, round_log_note=note)
    return review


def _round_record(
    event: PrEvent,
    lens: str,
    review: AgenticReview,
    scrub: Callable[[str], str],
    evidence_digest: str | None = None,
) -> RoundRecord:
    lines = tuple(
        scrub(
            f"{item.id} {item.finding.severity.value} "
            f'"{item.finding.location}" {item.finding.finding}'
        )
        for item in review.verified
    )
    # A delta review's carried-but-unre-anchored findings (#702) ride in
    # the record too, in their original wording, and so do the lines that
    # do not parse -- the raw text verbatim -- so the next review
    # re-offers them: a finding the carry-forward could not re-anchor is
    # never silently dropped from the chain (D73).
    lines += tuple(
        scrub(
            f"{identifier} {finding.severity.value} "
            f'"{finding.location}" {finding.finding}'
        )
        for identifier, finding, _lens in review.carried_unverified
    )
    lines += tuple(scrub(line) for line in review.carried_raw)
    # Each finding line's lens, parallel to the lines: the per-lens
    # re-assessment (D73) and the delta-citation flag read them; a
    # carried line's lens is the one the record's attribution pinned it
    # to, an unparsable line's is unknown.
    attributions = (
        tuple(item.lens for item in review.verified)
        + tuple(
            lens_name for _identifier, _finding, lens_name in review.carried_unverified
        )
        + ("",) * len(review.carried_raw)
    )
    # The lenses of this round that settled clean, in the lens list's own
    # order, so a later delta review offers a reuse only for a settled
    # result. Two rules put a name here: D76's clean-run rule (some entry
    # of the lens ran clean) for the lenses that ran, and -- round-2
    # review of #760 -- the reuse chain's carried-result rule for the
    # lenses that were reused: a reused lens whose composed outcome is
    # still clean (this round's re-assessment added nothing to it) has a
    # settled result this round stood behind, and stays reuse-eligible; a
    # reused lens that GAINED findings is not recorded, because its
    # settled result changed this round and the next one re-runs it.
    clean = {result.lens for result in review.lenses if result.state is LensState.CLEAN}
    clean |= {
        decision.lens
        for decision in review.lens_decisions
        if decision.reuse and not decision.gained_findings
    }
    stop = _first_limit_stop(review)
    record = fit_record(
        RoundRecord(
            event.repo,
            event.pr_number,
            event.head_sha,
            lens,
            review.event.value,
            lines,
            bool(review.context_omissions),
            limit_stop="" if stop is None else scrub(stop.message()),
            decisions=_stored_decisions(review.lens_decisions, scrub),
            attributions=attributions,
            clean_lenses=tuple(name for name in lens.split(", ") if name in clean),
            evidence_digest=evidence_digest or "",
        )
    )
    if review.carried_omitted:
        # The earlier record's unstorable findings ride into this record's
        # own omission count (round-2 review of #748, Major B): the text
        # is unrecoverable, but the gap stays in the durable chain, so the
        # next hop re-states it instead of the omission dying with the
        # draft. `fit_record`'s own drops, if any, are on top.
        record = replace(
            record, findings_omitted=record.findings_omitted + review.carried_omitted
        )
    return record


DECISIONS_CHARS = 4_096
"""The round record's lens-decision cap (D83): the decisions are
metadata -- the draft, the post and the telemetry each carry them whole
-- and the record keeps as many as fit under this bound, naming how many
were left out, so a many-lens plan cannot crowd the record's findings
out of the cap."""


def _stored_decisions(
    decisions: Sequence[LensDecision], scrub: Callable[[str], str]
) -> tuple[str, ...]:
    """The decisions as the round record stores them (D83): one scrubbed
    line per lens -- the decision and its reason, the delta-citation flag
    when it fired on a reuse, and the reused lens's D73 re-assessment as
    its own line (round-1 review of #760) -- kept under `DECISIONS_CHARS`;
    a plan too large for the bound stores the lines that fit and names
    how many were left out, the record's never-silently-cut rule applied
    to its own field."""
    lines: list[str] = []
    used = 0
    omitted = 0
    for decision in decisions:
        base = (
            f"{decision.lens} {'reuse' if decision.reuse else 'rerun'}: "
            f"{decision.reason}"
        )
        if decision.reuse and decision.flagged:
            base += " (its earlier findings cite files the incremental diff touches)"
        candidates = [base]
        if decision.reassess_note:
            candidates.append(
                f"{decision.lens} "
                f"{'re-assessed' if decision.reassessed else 're-assessment not run'}"
                f": {_clipped(decision.reassess_note)}"
            )
        for candidate in candidates:
            line = scrub(candidate)
            if lines and used + len(line) > DECISIONS_CHARS:
                omitted += 1
                continue
            lines.append(line)
            used += len(line)
    if omitted:
        lines.append(f"{omitted} more lens decision line(s) not stored")
    return tuple(lines)


def _clipped(text: str, cap: int = 600) -> str:
    """A record line's note, clipped to the quoting default the draft
    reads it at; the clip is the cap the reason cap already sets, so no
    note outgrows the line the draft shows."""
    if len(text) <= cap:
        return text
    return text[: cap - 3] + "..."


def first_turn(
    event: PrEvent,
    diff: str,
    context: Sequence[UntrustedBlock],
    nonce: str,
    only: frozenset[str] | None = None,
    ranks: PathRanks | None = None,
) -> str:
    """The operator's subject, then fenced: any caller context, the diff
    stat and the changed files in review order. No diff text: the lens
    reads it through the tools. `only` narrows the list to a
    continuation's files. `ranks` is the reviewed repo's path-ranking
    config (S5, D81 Q6) read from the merge-base tree: when it carries a
    setting, the listing follows `rank_files` -- ordering only, never
    exclusion, every file still listed -- and the header says so instead
    of claiming the risk order."""
    files = list(by_risk(split_files(diff)))
    order = "highest risk first"
    if ranks is not None and ranks.applies:
        files = list(rank_files(files, ranks))
        order = (
            "the reviewed repo's REVIEW.md path ranking, risk order within each group"
        )
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
            RepoText(f"{len(files)} changed file(s), {order}:\n{listing}"),
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
        "test_runs": _test_runs(review),
        "mutants_survived": _mutants_survived(review),
        "context_omissions": len(review.context_omissions),
        "other_pull_requests": review.other_pull_requests,
        "withdrawn": _withdrawn_count(review),
        "round_log_note": _status_log_note(review.round_log_note),
        "limit_stop": _limit_stop(review),
    }
    if review.review_error:
        # The refused-key cause (D92), fixed controller text: the service
        # reads it and renders the post as the error it is, never as an
        # incomplete review.
        fields["review_error"] = review.review_error
    if review.delta_from:
        # The delta review's own counts (#702): a pipeline gating on the
        # status line can tell a delta review from a full one and see
        # what the carry-forward decided -- including the carries that
        # did not re-anchor, so an all-clear on `carried` alone cannot
        # hide them.
        fields["carried"] = len(_carried(review))
        fields["carried_unverified"] = len(review.carried_unverified) + len(
            review.carried_raw
        )
        fields["resolved"] = len(review.resolved)
        fields["reused"] = len(review.reused_lenses)
        if review.delta_note:
            fields["delta_note"] = _status_log_note(review.delta_note)
    if review.trace_id:
        fields["trace_id"] = review.trace_id
    return f"{STATUS_PREFIX}{json.dumps(fields, sort_keys=True)} -->"


def _carried(review: AgenticReview) -> tuple[MintedFinding, ...]:
    return tuple(f for f in review.findings if f.carried)


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
    if review.review_error and not _ran_before_the_stop(review):
        # An error report, not a review (D92): the draft carries the
        # ledger and the cost, never a Findings section an empty one
        # could read as a clean bill.
        lines += [
            "",
            (
                "The review stopped before it could review; the cause above is "
                "fixed controller text. Every lens below shows why it did not "
                "run."
            ),
        ]
    else:
        lines += _delta_lines(review, scrub)
        lines += _selection_and_rank_lines(review, scrub)
        lines += _reassess_sections(review, scrub)
        lines += _delta_sections(review, scrub)
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
        (
            f"Model calls: {review.model_calls}; settled: ${review.billed_usd}; "
            f"held at reservation: ${review.held_usd}."
        ),
    ]
    if review.funding_source:
        # The source the review was pinned to (D94). Same line, so the
        # posted Cost section carries it and the cost parser still matches.
        lines[-1] += f" Funding source: {review.funding_source}."
    served = _ENDPOINT_SERVED.get(review.endpoint_class)
    if served:
        # Which endpoint class served the review (config slice S10),
        # recorded on the cost line so the draft and the posted Cost
        # section both carry it. Controller text: no PR data in it.
        lines[-1] += f" Served by {served}."
    if review.settle_overruns:
        # D82's tripwire (round-1 review of #757): a settle that reported
        # above its own worst case. The line stays one `Model calls:` line
        # so the posted Cost section carries it, and the amounts are
        # controller-computed figures, not PR text.
        lines[-1] += (
            f" {len(review.settle_overruns)} settle(s) reported a cost above "
            "their reservation (D82's tripwire): " + "; ".join(review.settle_overruns)
        )
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


def _selection_and_rank_lines(
    review: AgenticReview, scrub: Callable[[str], str]
) -> list[str]:
    """The Lens selection section, then S5's recorded re-ranking note: a
    note carrying quoted PR paths is scrubbed like the selection note,
    never trusted."""
    lines: list[str] = []
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
    if review.rerank_note:
        lines += ["", scrub(review.rerank_note)]
    return lines


def _ran_before_the_stop(review: AgenticReview) -> bool:
    """Whether any lens ran before the refused-key halt (D92's fix round
    3): a clean run stands with its findings, and a partial run read real
    files before the stop -- either makes the review partial rather than
    the error report that says it never ran. The service post reads the
    same set from the draft's ledger (`_AGENTIC_RUN_STATES` is clean and
    partial), so the two layers decide alike."""
    return bool(
        review.verified
        or _clean_runs(review.lenses)
        or any(r.state is LensState.PARTIAL for r in review.lenses)
    )


def _headline(review: AgenticReview, scrub: Callable[[str], str]) -> str:
    if review.review_error:
        # A refused key's draft leads with the cause (D92). Lenses that ran
        # before the halt stand: the review is partial, the verified
        # findings are kept, and the banner names what did not run -- it
        # never claims the review never ran.
        clean = _clean_runs(review.lenses)
        short = [
            r
            for r in review.lenses
            if r.state is not LensState.CLEAN and r.lens not in clean
        ]
        if _ran_before_the_stop(review):
            named = (
                "; ".join(f"{r.lens}: {r.state.value}" for r in short)
                if short
                else "the stop came after the lenses ran"
            )
            return (
                "> **REVIEW PARTIAL -- not a clean review.** "
                f"The review stopped early: {review.review_error}. The "
                "verified findings below are the lenses' own and stand; "
                f"what did not run to its end: {named}. This is not a "
                "clean bill."
            )
        return (
            f"> **REVIEW ERROR -- not a review.** The review stopped before "
            f"it could review: {review.review_error}. Nothing below is a "
            "review finding, and no coverage is claimed."
        )
    if review.coverage_complete:
        count = _changed_file_count(review)
        files = (
            f" Every changed file's diff ({count}) was read in full." if count else ""
        )
        ran = "Every selected lens ran whole, attested, with every quote verified."
        if review.reused_lenses:
            # A delta review's reused lenses (D83) ran no entry: their
            # settled results stand in, so the headline must not claim
            # every lens ran.
            ran = (
                "Every planned lens ran whole, attested, or was reused from "
                f"the earlier review's settled result "
                f"({len(review.reused_lenses)} reused)."
            )
        return (
            f"**Review event: {review.event.value}.** Verdict: {review.verdict.value}. "
            + ran
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
    `_unread_paths`. A reused lens (D83) is no entry here at all: its
    reuse is its coverage for the files its settled result read at the
    delta base -- but a file the delta touched only a lens that ran this
    round can have read, so `_delta_uncovered`'s paths gate first, and
    the per-lens and unread-file gates run over the lenses that ran."""
    if review.context_omissions:
        return "partial context"
    if review.not_picked:
        return "a picked lens did not run"
    if _dropped_notes(review):
        return "a finding was dropped"
    if review.carried_raw or review.carried_omitted:
        # A prior finding the delta could not assess -- a line that
        # parses only as raw text (a legacy unquoted whole-file location
        # among them), or a finding the earlier record's cap never
        # stored -- is not evidence the defect is gone, and its severity
        # is unknown, so it cannot set the verdict the way an unanchored
        # carry does (round-5 review of #748, M-2): the review's
        # coverage stays incomplete instead, and no plain approval rides
        # on it. A complete record with no standing findings still
        # approves.
        return "a prior finding the delta could not assess"
    if not review.lenses and not review.reused_lenses:
        return "no lens selected"
    if _delta_uncovered(review):
        return "a delta-touched file no lens read"
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


def _delta_uncovered(review: AgenticReview) -> frozenset[str]:
    """The delta-touched paths no lens that ran this round read (D83,
    round-1 review of #760, Major A): a reused settled result read the
    pull request at the delta base -- the delta-admission gate's whole
    guarantee -- and nothing more, so a file the delta added or modified
    cannot be claimed covered on reuse alone. The paths are threaded
    onto the review (`delta_paths`, the resolution gate's touched paths
    intersected with the pull request's own changes at `_review_lenses`),
    and a path is covered when at least one lens entry read it -- a lens
    whose entries all left it unread, or that never ran, covers nothing.
    This is an accounting rule, not a lens scope: it never narrows what
    a lens may read or report, it only refuses to claim coverage."""
    if not review.delta_paths:
        return frozenset()
    pending = _pending_by_lens(review.lenses, review.changed)
    names = {result.lens for result in review.lenses}
    if not names:
        unread_by_every_ran_lens = set(review.changed or ())
    else:
        # A lens absent from `pending` read everything its entries were
        # assigned; an absent lens contributes an empty gap, so its read
        # covers a path for the round.
        gaps = [set(pending.get(name, frozenset())) for name in names]
        unread_by_every_ran_lens = set.intersection(*gaps)
    changed = review.changed if review.changed is not None else None
    touched = (
        review.delta_paths & changed if changed is not None else review.delta_paths
    )
    return frozenset(touched & unread_by_every_ran_lens)


def _unread_paths(review: AgenticReview) -> tuple[str, ...]:
    if _scoped(review.lenses):
        seen = list(_still_unread(review.lenses, review.changed))
    else:
        seen = []
        for result in review.lenses:
            if result.outcome is None:
                continue
            for path in result.outcome.unread:
                if path not in seen:
                    seen.append(path)
    extra = _delta_uncovered(review)
    if extra:
        # The delta-touched paths no ran lens read are unreviewed files
        # too (D83, round-1 Major A): they join the list, so the draft
        # and the status line count them.
        seen.extend(path for path in extra if path not in seen)
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


def _executed(review: AgenticReview, pick: Callable[[Any], int]) -> int:
    """The summed execution count D80's status line carries, over every
    lens's best outcome. The field's meaning is recorded executions at
    this head, not executions this review paid for: a lens reused from
    the ledger (D73) contributes its settled outcome's counts, which are
    real executions at this same head, so the line stays the one place a
    pipeline reads the head's execution evidence from. A lens with no
    outcome contributes zero, the way it contributes no file count."""
    return sum(
        pick(result.outcome) for result in review.lenses if result.outcome is not None
    )


def _test_runs(review: AgenticReview) -> int:
    return _executed(review, lambda outcome: outcome.test_runs)


def _mutants_survived(review: AgenticReview) -> int:
    return _executed(review, lambda outcome: outcome.mutants_survived)


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


def _delta_lines(review: AgenticReview, scrub: Callable[[str], str]) -> list[str]:
    """The delta review's citation line and its controller note (#702):
    which review this one builds on, and anything that fell back. Empty
    on a full review."""
    if not review.delta_from:
        return []
    lines = ["", f"Delta review: builds on the review of `{review.delta_from[:12]}`."]
    if review.delta_note:
        # Quoted like every other model-adjacent field (round-3 review
        # of #748, a8): today's notes are controller text, but a future
        # note composer must not become the one field that bypasses the
        # discipline.
        lines.append(quote_untrusted(review.delta_note, QUOTED_CHARS, scrub=scrub))
    return lines


def _decision_line(decision: LensDecision, scrub: Callable[[str], str]) -> str:
    """One decisions-section bullet: the decision and its reason, the
    delta-citation flag when it fired on a reuse, and the reused lens's
    D73 re-assessment outcome (round-1 review of #760) -- recorded on the
    same surfaces the decision travels."""
    line = (
        f"- {quote_untrusted(decision.lens, QUOTED_CHARS, scrub=scrub)}: "
        f"{'reused' if decision.reuse else 're-ran'} -- "
        f"{quote_untrusted(decision.reason, QUOTED_CHARS, scrub=scrub)}"
    )
    if decision.reuse and decision.flagged:
        line += " (its earlier findings cite files the incremental diff touches)"
    if decision.reassess_note:
        line += (
            f"; {'re-assessed' if decision.reassessed else 're-assessment not run'}: "
            f"{quote_untrusted(decision.reassess_note, QUOTED_CHARS, scrub=scrub)}"
        )
    return line


def _delta_sections(review: AgenticReview, scrub: Callable[[str], str]) -> list[str]:
    """The sections a delta review can add, in order: the per-lens
    decisions (D83), then the prior findings the new commits fixed --
    each with its stated reason -- then the prior findings carried
    without a verified re-anchored quote. Each is empty when nothing
    backs it, and the carried findings that DID re-anchor are in the
    findings section above, tagged `carried`."""
    lines: list[str] = []
    if review.lens_decisions:
        lines += [
            "",
            "## Lens decisions (delta review)",
            "",
            *(_decision_line(decision, scrub) for decision in review.lens_decisions),
        ]
    if review.resolved:
        lines += [
            "",
            "## Resolved by the new commits",
            "",
            *(
                f"- **{identifier}** "
                f"{quote_untrusted(str(finding.location), QUOTED_CHARS, scrub=scrub)}: "
                f"{quote_untrusted(finding.finding, QUOTED_CHARS, scrub=scrub)}. "
                f"Reason, quoted: {quote_untrusted(reason, QUOTED_CHARS, scrub=scrub)}"
                for identifier, reason, finding in review.resolved
            ),
        ]
    if review.carried_unverified or review.carried_raw:
        lines += [
            "",
            "## Carried, not re-verified",
            "",
            *(
                f"- **{identifier}** "
                f"{quote_untrusted(str(finding.location), QUOTED_CHARS, scrub=scrub)}: "
                f"{quote_untrusted(finding.finding, QUOTED_CHARS, scrub=scrub)}"
                for identifier, finding, _lens in review.carried_unverified
            ),
            *(
                f"- {quote_untrusted(line, QUOTED_CHARS, scrub=scrub)}"
                for line in review.carried_raw
            ),
        ]
    return lines


def _finding_line(f: MintedFinding, scrub: Callable[[str], str]) -> str:
    x = f.finding
    tags = [
        x.severity.value,
        x.valence.value,
        f"route: {x.route.value}",
        x.attribution.value,
    ]
    if f.carried:
        # A carried finding's route and attribution are the carry-forward's
        # reconstruction, not this review's judgment; the tag says where
        # the finding came from instead (issue #702).
        return (
            f"- **{f.id}** [carried, {x.severity.value}] "
            f"{quote_untrusted(str(x.location), QUOTED_CHARS, scrub=scrub)} "
            f"({quote_untrusted(f.lens, QUOTED_CHARS, scrub=scrub)}): "
            f"{quote_untrusted(x.finding, QUOTED_CHARS, scrub=scrub)}"
        )
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
    annotation count, never a deletion count. A reused lens's D73
    re-assessment (round-1 review of #760) annotates the same way, on the
    decision, so its annotations count here too."""
    return sum(len(result.withdrawn) for result in review.lenses) + sum(
        len(decision.withdrawn) for decision in review.lens_decisions
    )


def _withdrawn_lines(review: AgenticReview, scrub: Callable[[str], str]) -> list[str]:
    """The draft's withdrawn-findings section (D73), or an empty list when
    no re-assessment withdrew or revised anything: what the finding was,
    the stated reason the newer evidence showed it wrong, and, for a
    revision, the finding that replaced it. A reused lens's annotations
    (round-1 review of #760) ride on its decision and join the section."""
    pairs: list[tuple[LensResult | LensDecision, Withdrawn]] = [
        (result, w) for result in review.lenses for w in result.withdrawn
    ]
    pairs += [
        (decision, w) for decision in review.lens_decisions for w in decision.withdrawn
    ]
    if not pairs:
        return []
    return [
        "",
        "## Withdrawn findings (re-assessed with newer evidence)",
        "",
        *(_withdrawn_line(source, w, scrub, review) for source, w in pairs),
    ]


def _withdrawn_line(
    source: LensResult | LensDecision,
    w: Withdrawn,
    scrub: Callable[[str], str],
    review: AgenticReview,
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
            f"- {source.lens} proposes withdrawing "
            f"{quote_untrusted(str(w.finding.location), QUOTED_CHARS, scrub=scrub)}: "
            f"{quote_untrusted(w.finding.finding, QUOTED_CHARS, scrub=scrub)} "
            f"[{w.finding.severity.value}]. Reason, quoted: "
            f"{quote_untrusted(w.reason, QUOTED_CHARS, scrub=scrub)}"
        )
    if w.replaced:
        text = (
            f"- {source.lens} revises "
            f"{quote_untrusted(str(w.finding.location), QUOTED_CHARS, scrub=scrub)}: "
            f"{quote_untrusted(w.finding.finding, QUOTED_CHARS, scrub=scrub)} "
            f"[{w.finding.severity.value}]. Reason, quoted: "
            f"{quote_untrusted(w.reason, QUOTED_CHARS, scrub=scrub)}"
        )
        if w.replacement.verified:
            return (
                text
                + f". Revised finding: {_finding_id(source, w.replacement, review)}"
            )
        return text + ". The revised finding did not verify; see Not verified"
    lowered = w.replacement.finding.severity.rank > w.finding.severity.rank
    head = (
        f"- {source.lens} proposes revising "
        f"{quote_untrusted(str(w.finding.location), QUOTED_CHARS, scrub=scrub)}: "
        f"{quote_untrusted(w.finding.finding, QUOTED_CHARS, scrub=scrub)} "
        f"[{w.finding.severity.value}] down to "
        f"{w.replacement.finding.severity.value}. Reason, quoted: "
        f"{quote_untrusted(w.reason, QUOTED_CHARS, scrub=scrub)}"
        if lowered
        else (
            f"- {source.lens} proposes revising "
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


def _finding_id(
    source: LensResult | LensDecision,
    checked: CheckedFinding,
    review: AgenticReview,
) -> str:
    """The minted id of one of the source's effective findings, found by
    identity: `effective_outcome` puts the replacement's own object in the
    composed outcome, so the same object the withdrawal carries is in the
    list the ids were minted over. A reused lens's decision (round-1
    review of #760) composes its replacements into the review's findings
    directly, keeping the carried label's id, so the id is found there."""
    if isinstance(source, LensResult):
        findings = () if source.outcome is None else source.outcome.findings
        for n, held in enumerate(findings, 1):
            if held is checked:
                return f"L{source.index}-F{n}"
        return "a finding this draft does not list"
    for minted in review.findings:
        if minted.finding is checked.finding:
            return minted.id
    return "a finding this draft does not list"
