# SPDX-License-Identifier: MIT
"""The agentic coordinator: run the selected lenses under the attestation
ledger, verify their output and synthesize one draft (D31, D34, D44).

`review_lens` runs one lens. `review_lenses` runs every selected lens,
up to the configured pool, then assigns files none of them read to a
continuation while a call and the review clock remain. The synthesis is
mechanical: the
controller mints `L<lens>-F<n>` IDs, ranks the verified findings by
severity and sets the verdict from them by `synthesis.md`'s rule (one
introduced Blocker blocks; anything else that sets the verdict means
approve with changes; only nits or nothing means approve). There is no
model merge call yet.

Coverage is complete only when every changed file's diff was read in
full by some lens (a file left unread by every lens blocks approval),
no lens failed for another cause, and, when this review ran a runner,
every runner completed. A single-lens result with no assigned scope
keeps the older rule: that lens itself must be clean and have read
every file.
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
from atlas_reviewer.domain import PrEvent, RunnerReport, RunnerStatus
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
from atlas_reviewer.quotes import read_sources
from atlas_reviewer.redact import Redactor
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
    trace_id: str = ""

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
        coverage, so it blocks approval too."""
        if _scoped(self.lenses):
            if _still_unread(self.lenses):
                return False
            if not self.lenses or any(_blocks_coverage(r) for r in self.lenses):
                return False
            if self.runner is None:
                return True
            return self.runner.status is RunnerStatus.COMPLETED
        if any(
            r.outcome is not None
            and (r.outcome.unread or r.outcome.changed_files is None)
            for r in self.lenses
        ):
            return False
        lenses_clean = bool(self.lenses) and all(
            r.state is LensState.CLEAN for r in self.lenses
        )
        if not lenses_clean or self.runner is None:
            return lenses_clean
        return self.runner.status is RunnerStatus.COMPLETED

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
    defect sets the verdict."""
    setting = [
        f.finding.severity for f in findings if f.verified and f.finding.sets_verdict
    ]
    if Severity.BLOCKER in setting:
        return Verdict.BLOCK
    if any(s is not Severity.NIT for s in setting):
        return Verdict.APPROVE_WITH_CHANGES
    return Verdict.APPROVE


def synthesize(
    lenses: Sequence[LensResult],
    secrets_found: Sequence[BridgeSecret] = (),
    runner: RunnerReport | None = None,
    spend: Spend | None = None,
    flagged: Sequence[str] = (),
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
            context=context,
            telemetry=telemetry,
            nonce=nonce,
            bridge_root=bridge_root,
            contract=contract,
            task_socket=task_socket,
            index=1,
        )
        return synthesize([ran.result], ran.secrets, ran.report, ran.spend, ran.flagged)

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
    telemetry: Telemetry | None = None,
    nonce: Callable[[], str] = lambda: secrets.token_hex(NONCE_BYTES),
    bridge_root: str = BRIDGE_ROOT,
    contract: str | None = None,
    task_socket: str = SOCKET_PATH,
    model_for: Callable[[], LensModel] | None = None,
    trace: ReviewTrace | None = None,
) -> AgenticReview:
    """Run every named lens, up to `pool_size` at once, then one combined
    verdict. Each lens gets its own runner name. Files no lens read are
    handed to a continuation of the first lens that has a body, while a
    call and the review clock remain. Partial coverage still cannot approve.

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
            telemetry=telemetry,
            nonce=nonce,
            bridge_root=bridge_root,
            contract=contract,
            task_socket=task_socket,
            model_for=model_for,
            resolved=resolved,
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
    telemetry: Telemetry | None,
    nonce: Callable[[], str],
    bridge_root: str,
    contract: str | None,
    task_socket: str,
    model_for: Callable[[], LensModel] | None,
    resolved: Limits,
) -> AgenticReview:
    changed = frozenset(f.path for f in split_files(diff))
    spend = Spend(resolved)
    started = clock.monotonic()
    deadline = started + resolved.review_wall_s
    runs: list[_LensRun] = []

    def run(lens: str, assigned: frozenset[str], index: int) -> _LensRun:
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
            context=context,
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
    for _ in range(4):
        unread = _still_unread(tuple(ran.result for ran in runs))
        if (
            not unread
            or spend.calls >= resolved.max_calls
            or clock.monotonic() >= deadline
        ):
            break
        before = set(unread)
        host = next(
            (ran.result.lens for ran in runs if ran.result.body_sha256), names[0]
        )
        runs.append(run(host, frozenset(unread), len(runs) + 1))
        if not before - set(_still_unread(tuple(ran.result for ran in runs))):
            break
    secrets = [secret for ran in runs for secret in ran.secrets]
    flagged = tuple(value for ran in runs for value in ran.flagged)
    return synthesize(
        [ran.result for ran in runs],
        secrets,
        _combined_runner(tuple(ran.report for ran in runs)),
        spend,
        flagged,
    )


def _traced_review(
    event: PrEvent,
    trace: ReviewTrace | None,
    redactor: Redactor,
    body: Callable[[ReviewTrace], AgenticReview],
) -> AgenticReview:
    """Run `body` under one review span, or under the caller's open one."""
    if trace is None:
        acquire_shared()
    try:
        active = opening_trace(trace, lambda text: redactor(text).text)
        outer = current_review()
        if outer is not None:
            review = body(active)
            outer.set("atlas.review_event", review.event.value)
            return _with_trace(outer, review)
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


@dataclass
class _LensRun:
    result: LensResult
    secrets: list[BridgeSecret]
    report: RunnerReport | None
    spend: Spend
    flagged: tuple[str, ...]


def _combined_runner(reports: Sequence[RunnerReport | None]) -> RunnerReport | None:
    present = [report for report in reports if report is not None]
    if not present:
        return None
    failed = next(
        (report for report in present if report.status is not RunnerStatus.COMPLETED),
        None,
    )
    return failed if failed is not None else present[-1]


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
            lens, index, None, None, reason="no lens body in the bundle", scope=scope
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
        settled = LensResult(
            lens,
            settled.index,
            settled.body_sha256,
            settled.outcome,
            settled.attempts,
            settled.escalated,
            settled.retry_pending,
            settled.reason,
        )
        return _LensRun(
            replace_scope(settled, scope), [], None, spend or Spend(resolved), ()
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
        deadline_s=resolved.review_wall_s, clock=clock, telemetry=telemetry,
        root=bridge_root,
    )  # fmt: skip
    result = _result(key, ledger.attempts(key), resolved, scrub(report.note), index)
    result = LensResult(
        lens,
        result.index,
        result.body_sha256,
        result.outcome,
        result.attempts,
        result.escalated,
        result.retry_pending,
        result.reason,
    )
    return _LensRun(
        replace_scope(result, scope),
        list(session.secrets),
        report,
        spend,
        tuple(diff_secrets.values) + tuple(session.flagged()),
    )


def replace_scope(result: LensResult, scope: frozenset[str]) -> LensResult:
    return LensResult(
        result.lens,
        result.index,
        result.body_sha256,
        result.outcome,
        result.attempts,
        result.escalated,
        result.retry_pending,
        result.reason,
        scope,
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
        "limit_stop": _limit_stop(review),
    }
    if review.trace_id:
        fields["trace_id"] = review.trace_id
    return f"{STATUS_PREFIX}{json.dumps(fields, sort_keys=True)} -->"


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

    lines = [status_line(review), "", _headline(review, scrub), ""]
    lines += ["## Findings (verified quotes only)", ""]
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
    if review.secrets:
        lines += ["", "## Possible committed secrets (controller findings)", ""]
        lines += [_secret_line(s, scrub) for s in review.secrets]
    lines += ["", "## Lens coverage (attestation ledger)", ""]
    lines += [_lens_line(r, scrub) for r in review.lenses]
    lines += [
        "",
        f"Model calls: {review.model_calls}; committed: ${review.committed_usd}.",
    ]
    if review.runner is not None:
        lines.append(
            f"Runner: {review.runner.status.value}; cleanup {review.runner.cleanup.value}."
        )
        if review.runner.status is not RunnerStatus.COMPLETED and review.runner.note:
            lines.append(
                "Runner reported, quoted: "
                + quote_untrusted(review.runner.note, QUOTED_CHARS, scrub=scrub)
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
        named = _coverage_gap_name(review) or "no lens selected"
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
    block once another lens, or a continuation, has read that file."""
    unread_only = (
        result.outcome is not None
        and result.state is LensState.PARTIAL
        and result.outcome.causes <= frozenset({Cause.FILES_UNREAD})
    )
    return result.state is not LensState.CLEAN and not unread_only


def _still_unread(lenses: Sequence[LensResult]) -> tuple[str, ...]:
    assigned: set[str] = set()
    covered: set[str] = set()
    for result in lenses:
        if result.scope is None:
            continue
        assigned.update(result.scope)
        if result.outcome is None or result.outcome.changed_files is None:
            continue
        covered.update(set(result.scope) - set(result.outcome.unread))
    return tuple(
        sorted(assigned - covered, key=lambda path: (risk_tier(path).rank, path))
    )


def _coverage_gap_name(review: AgenticReview) -> str:
    """Why a review of clean lenses is still incomplete, or "" when no
    lens was selected. A clean outcome can still lack coverage: unread
    paths, or no changed-file count from before the per-file gate."""
    if _scoped(review.lenses):
        if _still_unread(review.lenses):
            return "unread files"
        if any(_blocks_coverage(result) for result in review.lenses):
            return "a lens did not finish clean"
        return ""
    if any(r.outcome is not None and r.outcome.unread for r in review.lenses):
        return "unread files"
    if any(
        r.outcome is not None and r.outcome.changed_files is None for r in review.lenses
    ):
        return "no recorded file coverage"
    return ""


def _unread_paths(review: AgenticReview) -> tuple[str, ...]:
    if _scoped(review.lenses):
        return _still_unread(review.lenses)
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
    if f.source == "removed lines":
        tags.append("removed lines")
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
    if o.detail:
        parts.append(f"detail {quote_untrusted(o.detail, QUOTED_CHARS, scrub=scrub)}")
    return f"{head}; " + "; ".join(parts)
