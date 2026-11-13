# SPDX-License-Identifier: MIT
"""The agentic coordinator: run the selected lens under the attestation
ledger, verify its output and synthesize the draft (D31, D34; phase 3).

Phase 3 runs one lens, pool size 1. The synthesis is mechanical: the
controller mints `L<lens>-F<n>` IDs, ranks the verified findings by
severity and sets the verdict from them by `synthesis.md`'s rule (one
introduced Blocker blocks; anything else that sets the verdict means
approve with changes; only nits or nothing means approve). There is no
model merge call yet.

Coverage is complete only when the ledger shows every selected lens
settled CLEAN on this head with this body, every changed file's diff was
read in full, and, when this review ran a runner, that runner completed.
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

import json
import secrets
from collections.abc import Callable, Mapping, Sequence
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
from atlas_reviewer.domain import Omission, PrEvent, RunnerReport, RunnerStatus
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
from atlas_reviewer.rounds import (
    PRIOR_ROUND_CHARS,
    SOURCE,
    RoundLog,
    RoundRecord,
    fit_record,
    prior_blocks,
    records_for,
)
from atlas_reviewer.runner import event_runner_name
from atlas_reviewer.telemetry import Telemetry
from atlas_reviewer.tool_model import OpenRouterLensModel
from atlas_reviewer.tracing import (
    ReviewTrace,
    acquire_shared,
    current_review,
    limit_label,
    opening_trace,
    release_shared,
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
    context_omissions: tuple[Omission, ...] = ()
    other_pull_requests: int = 0
    trace_id: str = ""
    round_log_note: str = ""

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
        review cannot approve on a partial picture of this head. A
        superseded round, and a line that names another pull request
        or no pull request, are not that gap."""
        if self.context_omissions:
            return False
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
        tuple(context_omissions),
        other_pull_requests,
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
    if trace is None:
        acquire_shared()
    try:
        return _open_review(
            event,
            lens,
            diff,
            trees,
            library=library,
            model=model,
            resolved=resolved,
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
            trace=trace,
        )
    finally:
        if trace is None:
            release_shared()


def _open_review(
    event: PrEvent,
    lens: str,
    diff: str,
    trees: SourceTrees,
    *,
    library: LensLibrary,
    model: LensModel,
    resolved: Limits,
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
    trace: ReviewTrace | None,
) -> AgenticReview:
    active = opening_trace(trace, lambda text: redactor(text).text)
    outer = current_review()
    if outer is None:
        with (
            active.review(event.repo, event.pr_number, event.head_sha) as review_span,
            active.lens(lens) as lens_span,
        ):
            return _with_trace(
                review_span,
                _one_lens(
                    active,
                    lens_span,
                    review_span,
                    event,
                    lens,
                    diff,
                    trees,
                    library=library,
                    model=model,
                    resolved=resolved,
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
                ),
            )
    with active.lens(lens) as lens_span:
        return _with_trace(
            outer,
            _one_lens(
                active,
                lens_span,
                outer,
                event,
                lens,
                diff,
                trees,
                library=library,
                model=model,
                resolved=resolved,
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
            ),
        )


def _with_trace(span: Any, review: AgenticReview) -> AgenticReview:
    trace_id = span.trace_id() if span is not None else ""
    if not trace_id:
        return review
    return replace(review, trace_id=trace_id)


def _one_lens(
    active: ReviewTrace,
    lens_span: Any,
    review_span: Any,
    event: PrEvent,
    lens: str,
    diff: str,
    trees: SourceTrees,
    *,
    library: LensLibrary,
    model: LensModel,
    resolved: Limits,
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
) -> AgenticReview:
    review = _review_lens(
        event, lens, diff, trees, library=library, model=model,
        resolved=resolved, ledger=ledger, sprites=sprites,
        runner_ledger=runner_ledger, redactor=redactor, clock=clock,
        context=context, context_omissions=context_omissions,
        round_log=round_log, prior_chars=prior_chars, telemetry=telemetry,
        nonce=nonce, bridge_root=bridge_root, contract=contract,
        task_socket=task_socket, trace=active,
    )  # fmt: skip
    _annotate(lens_span, review_span, review)
    return review


def _review_lens(
    event: PrEvent,
    lens: str,
    diff: str,
    trees: SourceTrees,
    *,
    library: LensLibrary,
    model: LensModel,
    resolved: Limits,
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
    trace: ReviewTrace,
) -> AgenticReview:
    contract = finding_contract() if contract is None else contract
    blocks, omissions, other_pull_requests = _review_context(
        event, context, context_omissions, round_log, prior_chars, redactor
    )
    body = library.body(lens)
    if body is None:
        missing = LensResult(lens, 1, None, None, reason="no lens body in the bundle")
        return synthesize(
            [missing],
            context_omissions=omissions,
            other_pull_requests=other_pull_requests,
        )
    key = LensKey(event.repo, event.pr_number, event.head_sha, lens, body_digest(body))
    if isinstance(next_step(ledger.attempts(key), resolved.retries), Settled):
        return synthesize(
            [_result(key, ledger.attempts(key), resolved, "")],
            context_omissions=omissions,
            other_pull_requests=other_pull_requests,
        )

    changed = frozenset(f.path for f in split_files(diff))
    diff_secrets = scan_diff(diff)
    session = _Session()
    scrubber = Redactor(
        redactor.known_secrets,
        (*redactor.sources, session.flagged),
        (*redactor.flagged, *diff_secrets.values),
    )

    def scrub(text: str) -> str:
        return scrubber(text).text

    trace.scrub = scrub
    traced_model = trace.wrap_model(model)
    spend = Spend(resolved)
    fence_nonce = nonce()
    job = LensJob(
        lens,
        body,
        key.body_sha256,
        contract,
        # No scope. The first turn lists every file in `diff`. A
        # continuation (#646) may pass `scope`. Prior findings are not one.
        first_turn(event, diff, blocks, fence_nonce),
        changed,
        read_sources(trees.head, diff, changed),
        fence_nonce,
    )
    review_started = clock.monotonic()
    review_deadline = review_started + resolved.review_wall_s

    def in_session(bridge: Bridge) -> str:
        session.bridges.append(bridge)
        digest = event_runner_name(event).rsplit("-", 1)[-1]
        with lens_hold(bridge.session, digest, task_socket):
            return _attempts(
                trace.wrap_bridge(bridge), job, traced_model,
                spend, clock, ledger, key, resolved,
                review_deadline, review_started, session, scrub,
            )  # fmt: skip

    report = run_bridge(
        sprites, runner_ledger, trees, in_session,
        redactor=scrubber, changed=changed, name=event_runner_name(event),
        deadline_s=resolved.review_wall_s, clock=clock, telemetry=telemetry,
        root=bridge_root,
    )  # fmt: skip
    result = _result(key, ledger.attempts(key), resolved, scrub(report.note))
    review = synthesize(
        [result],
        session.secrets,
        report,
        spend,
        (*diff_secrets.values, *session.flagged()),
        omissions,
        other_pull_requests,
    )
    if round_log is not None:
        try:
            round_log.append(_round_record(event, lens, review, scrub))
        except OSError as exc:
            review = replace(
                review,
                round_log_note=f"the round log was not written: {exc}",
            )
    return review


def _annotate(lens_span: Any, review_span: Any, review: AgenticReview) -> None:
    lens = review.lenses[0] if review.lenses else None
    if lens is not None:
        lens_span.set("atlas.lens.state", lens.state.value)
        if lens.outcome is not None:
            label = limit_label(
                [cause.value for cause in lens.outcome.causes], lens.outcome.detail
            )
            if label:
                lens_span.set("atlas.limit_stop", label)
    review_span.set("atlas.review_event", review.event.value)


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
    key: LensKey, attempts: tuple[Attempt, ...], limits: Limits, runner_note: str
) -> LensResult:
    if not attempts:
        return LensResult(
            key.lens, 1, key.body_sha256, None,
            reason=f"no attempt was recorded: {runner_note or 'the runner did not start'}",
        )  # fmt: skip
    step = next_step(attempts, limits.retries)
    if isinstance(step, Settled):
        return LensResult(
            key.lens, 1, key.body_sha256, step.outcome, step.attempts, step.escalated
        )
    return LensResult(
        key.lens, 1, key.body_sha256, attempts[-1].outcome, len(attempts),
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
    event: PrEvent, diff: str, context: Sequence[UntrustedBlock], nonce: str
) -> str:
    """The operator's subject, then fenced: prior reviews and any caller
    context, then the diff stat and every changed file in risk order. No
    diff text: the lens reads the whole current diff through the tools.
    Prior findings do not remove a file from that list. A continuation's
    file subset is not a parameter of this turn."""
    listed = by_risk(split_files(diff))
    listing = "\n".join(
        f"[{f.tier.label}] {f.path} (+{added} -{removed})"
        for f in listed
        for added, removed in (_counts(f.text),)
    )
    blocks = (
        *context,
        UntrustedBlock(
            "changed-files",
            RepoText(f"{len(listed)} changed file(s), highest risk first:\n{listing}"),
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
        "round_log_note": review.round_log_note,
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
        lines.append(review.round_log_note)
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


def _coverage_gap_name(review: AgenticReview) -> str:
    """Why a review of clean lenses is still incomplete, or "" when no
    lens was selected. A clean outcome can still lack coverage: unread
    paths, or no changed-file count from before the per-file gate."""
    if review.context_omissions:
        return "partial context"
    if any(r.outcome is not None and r.outcome.unread for r in review.lenses):
        return "unread files"
    if any(
        r.outcome is not None and r.outcome.changed_files is None for r in review.lenses
    ):
        return "no recorded file coverage"
    return ""


def _unread_paths(review: AgenticReview) -> tuple[str, ...]:
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
