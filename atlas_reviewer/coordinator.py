# SPDX-License-Identifier: MIT
"""The agentic coordinator: run the selected lenses under the attestation
ledger, verify their output and synthesize one draft (D31, D34, D44).

`review_lens` runs one lens. `review_lenses` runs every selected lens,
up to the configured pool, then gives each lens a continuation of its
own for the files it left unread while a call and the review clock
remain. The synthesis is mechanical: the controller mints
`L<lens>-F<n>` IDs, ranks the verified findings by severity and sets
the verdict from them (D55). An introduced Major or Blocker requests
changes. An introduced Minor means approve with changes. Only nits, or
nothing, means approve. There is no model merge call yet.

Coverage is complete only when every lens read every changed file's
diff in full, through its own attempts or its own continuations (D42:
a read by another lens does not cover a file for this one), no lens
failed for another cause, and, when this review ran a runner, every
runner completed. A single-lens result with no assigned scope keeps the
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
"""

from __future__ import annotations

import hashlib
import json
import secrets
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
from atlas_reviewer.committed_secrets import scan_diff
from atlas_reviewer.diffs import by_risk, risk_tier, split_files
from atlas_reviewer.domain import (
    CleanupStatus,
    Omission,
    PrEvent,
    RunnerReport,
    RunnerStatus,
)
from atlas_reviewer.keepalive import SOCKET_PATH, lens_hold
from atlas_reviewer.lens_contract import Finding, Severity
from atlas_reviewer.lens_loop import (
    AgenticLimits,
    LensJob,
    LensModel,
    Limits,
    Spend,
    finding_contract,
    retry_reasons,
    run_attempt,
)
from atlas_reviewer.lenses import LensLibrary
from atlas_reviewer.notes import quote_untrusted
from atlas_reviewer.openrouter import OpenRouterProvider
from atlas_reviewer.ports import ByokRefusedError, Clock, RunnerLedger, SpritesApi
from atlas_reviewer.prompt import RepoText, UntrustedBlock, fence
from atlas_reviewer.quotes import QuoteSource, read_sources
from atlas_reviewer.redact import Redactor
from atlas_reviewer.rounds import (
    PRIOR_ROUND_CHARS,
    SOURCE,
    RoundLog,
    RoundRecord,
    fit_record,
    prior_blocks,
    records_for,
)
from atlas_reviewer.runner import event_runner_name, lens_runner_name
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
        or no pull request, are not that gap."""
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
    """IDs in each attested lens's reply order, verified or not. An attempt
    that is not attested contributes nothing, whatever it carries."""
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
    defect sets the verdict. A Major or a Blocker requests changes (D55)."""
    setting = [
        f.finding.severity for f in findings if f.verified and f.finding.sets_verdict
    ]
    if any(s.rank <= Severity.MAJOR.rank for s in setting):
        return Verdict.BLOCK
    if any(s is Severity.MINOR for s in setting):
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
    """The live adapter bound to the same resolved limits as the loop."""
    return OpenRouterLensModel(provider, per_call=limits.resolve())


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
    exporter is built. JSONL telemetry is unchanged."""
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
            nonce=nonce,
            bridge_root=bridge_root,
            contract=contract,
            task_socket=task_socket,
            index=1,
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
    `review_lens` describes."""
    resolved = limits.resolve()
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
            resolved=resolved,
            picker_spend=picker_spend,
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
    picker_spend: tuple[int, Decimal],
) -> AgenticReview:
    changed = frozenset(f.path for f in split_files(diff))
    blocks, omissions, other_pull_requests = _review_context(
        event, context, context_omissions, round_log, prior_chars, redactor
    )
    spend = Spend(resolved, *picker_spend)
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
            nonce=nonce,
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
        )

    names = tuple(lenses)
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
    nonce: Callable[[], str],
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
    trace: ReviewTrace,
) -> _LensRun:
    resolved = limits.resolve()
    declared = getattr(model, "per_call", None)
    if declared is not None and declared != resolved:
        raise ValueError("the model's per-call limits differ from this review's limits")
    contract = finding_contract() if contract is None else contract
    changed = frozenset(f.path for f in split_files(diff))
    scope = changed if assigned is None else assigned
    body = library.body(lens)
    if body is None:
        missing = LensResult(
            lens, index, None, None, reason=NO_BODY_REASON, scope=scope
        )
        return _LensRun(missing, [], None, spend or Spend(resolved), ())
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
        return _LensRun(
            replace(settled, lens=lens, scope=scope),
            [],
            None,
            spend or Spend(resolved),
            (),
        )
    diff_secrets = scan_diff(diff)
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
    spend = spend or Spend(resolved)
    fence_nonce = nonce()
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
    )
    started = clock.monotonic() if review_started is None else review_started
    deadline = (
        started + resolved.review_wall_s if review_deadline is None else review_deadline
    )
    name = runner_name or event_runner_name(event)

    def in_session(bridge: Bridge) -> str:
        session.bridges.append(bridge)
        digest = name.rsplit("-", 1)[-1]
        with lens_hold(bridge.session, digest, task_socket):
            return _attempts(
                lens_trace.wrap_bridge(bridge), job, traced_model,
                spend, clock, ledger, key, resolved,
                deadline, started, session, scrub,
            )  # fmt: skip

    report = run_bridge(
        sprites, runner_ledger, trees, in_session,
        redactor=scrubber, changed=scope, name=name,
        deadline_s=max(deadline - clock.monotonic(), 0.0), clock=clock,
        telemetry=telemetry,
        root=bridge_root,
    )  # fmt: skip
    result = replace(
        _result(key, ledger.attempts(key), resolved, scrub(report.note), index),
        lens=lens,
        scope=scope,
    )
    secrets = list(session.secrets)
    flagged = tuple(diff_secrets.values) + tuple(session.flagged())
    return _LensRun(result, secrets, report, spend, flagged)


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
) -> str:
    step = next_step(ledger.attempts(key), limits.retries)
    while isinstance(step, RunAttempt):
        attempts = ledger.attempts(key)
        ledger.start(key, step.number)
        secrets_seen: list[BridgeSecret] = []
        try:
            outcome = run_attempt(
                job, bridge, model, spend, clock,
                review_deadline=review_deadline,
                review_started=review_started,
                retry_of=attempts[-1].outcome if step.forced and attempts else None,
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
            )  # fmt: skip
            raise
        else:
            session.secrets.extend(secrets_seen)
            ledger.finish(key, step.number, outcome, scrub=scrub)
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
        # names no pull request is not charged here.
        mine, dropped_other = records_for(loaded.records, event.repo, event.pr_number)
        if loaded.file_unreadable:
            unreadable = 0
            omissions.append(
                Omission(
                    SOURCE,
                    "round log file",
                    "the round log file could not be read",
                )
            )
        else:
            key = event.repo.casefold()
            unreadable = sum(
                1
                for repo, number in loaded.unreadable
                if repo == key and number == event.pr_number
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
    return fit_record(
        RoundRecord(
            event.repo,
            event.pr_number,
            event.head_sha,
            lens,
            review.event.value,
            lines,
            bool(review.context_omissions),
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


def _limit_stop(review: AgenticReview) -> dict[str, str] | None:
    """The first limit that stopped a lens, or null when none did."""
    for result in review.lenses:
        found = None if result.outcome is None else result.outcome.limit_hit
        if found is not None:
            return found.as_dict()
    return None


def render_draft(review: AgenticReview, redactor: Redactor) -> str:
    """The draft as the operator reads it. Every model-written value (and
    every PR path) is redacted, with the review's flagged values scrubbed,
    and quoted as data."""
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
    missing = _missing_bodies(review)
    if missing:
        lines += ["", "## Lenses NOT RUN (no body in the bundle)", ""]
        lines += [
            "- " + quote_untrusted(r.lens, QUOTED_CHARS, scrub=scrub) for r in missing
        ]
    dropped = _dropped_notes(review)
    if dropped:
        lines += ["", "## Dropped findings (left out of this review)", ""]
        lines += [
            "- " + quote_untrusted(note, QUOTED_CHARS, scrub=scrub) for note in dropped
        ]
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
    lines += [_lens_line(r, scrub) for r in review.lenses]
    lines += [
        "",
        f"Model calls: {review.model_calls}; committed: ${review.committed_usd}.",
    ]
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
    short = [r for r in review.lenses if r.state is not LensState.CLEAN]
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


def _blocks_coverage(result: LensResult) -> bool:
    """A lens that is partial only because it left a file unread does not
    block once that same lens, or its continuation, has read the file."""
    unread_only = (
        result.outcome is not None
        and result.outcome.attestation is Attestation.ATTESTED
        and result.outcome.causes == frozenset({Cause.FILES_UNREAD})
    )
    return result.state is not LensState.CLEAN and not unread_only


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


def _lens_gap(review: AgenticReview) -> str:
    """Why the lenses do not give complete coverage, or "" when they do.
    The one coverage rule: `coverage_complete`, the headline and the
    unread list all read it. A clean outcome can still lack coverage:
    unread paths, or no changed-file count from before the per-file gate."""
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
        if any(_blocks_coverage(result) for result in review.lenses):
            return "a lens did not finish clean"
        return ""
    if any(
        r.outcome is not None and r.outcome.changed_files is None for r in review.lenses
    ):
        return "no recorded file coverage"
    if any(r.state is not LensState.CLEAN for r in review.lenses):
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
    if f.source in (QuoteSource.REMOVED, QuoteSource.HEAD_NEAR):
        tags.append(f.source)
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


def _lens_line(r: LensResult, scrub: Callable[[str], str]) -> str:
    head = f"- L{r.index} {r.lens}: **{r.state.value}**"
    if r.outcome is None:
        return f"{head}; {quote_untrusted(r.reason, QUOTED_CHARS, scrub=scrub)}"
    o = r.outcome
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
    if o.dropped:
        parts.append(f"{len(o.dropped)} finding(s) dropped")
    if o.detail:
        parts.append(f"detail {quote_untrusted(o.detail, QUOTED_CHARS, scrub=scrub)}")
    return f"{head}; " + "; ".join(parts)


def _missing_bodies(review: AgenticReview) -> tuple[LensResult, ...]:
    return tuple(
        result
        for result in review.lenses
        if result.outcome is None and result.reason == NO_BODY_REASON
    )


def _dropped_notes(review: AgenticReview) -> tuple[str, ...]:
    return tuple(
        note
        for result in review.lenses
        if result.outcome is not None
        for note in result.outcome.dropped
    )
