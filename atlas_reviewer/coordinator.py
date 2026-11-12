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
settled CLEAN on this head with this body. Anything less fails closed:
the draft opens with the machine-readable status line
(`coverage_complete: false`) and a REVIEW INCOMPLETE warning, and never
approves.

Retries come from the ledger alone (`attestation.next_step`). A lens
already settled for this head and body is reused without a runner, and a
review that stopped mid-attempt resumes its attempt count.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from atlas_reviewer.attestation import (
    Attempt,
    AttemptLedger,
    AttemptOutcome,
    Attestation,
    LensKey,
    LensState,
    RunAttempt,
    Settled,
    body_digest,
    next_step,
)
from atlas_reviewer.bridge import Bridge, BridgeSecret, run_bridge
from atlas_reviewer.bridge_staging import BRIDGE_ROOT, SourceTrees
from atlas_reviewer.committed_secrets import scan_diff
from atlas_reviewer.diffs import by_risk, split_files
from atlas_reviewer.domain import PrEvent, RunnerReport
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
from atlas_reviewer.ports import Clock, RunnerLedger, SpritesApi
from atlas_reviewer.prompt import RepoText, UntrustedBlock, fence
from atlas_reviewer.quotes import read_sources
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import event_runner_name
from atlas_reviewer.telemetry import Telemetry
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

    @property
    def coverage_complete(self) -> bool:
        return bool(self.lenses) and all(
            r.state is LensState.CLEAN for r in self.lenses
        )

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
) -> AgenticReview:
    """Review `event` with one lens. The limits are resolved before any
    model, runner or ledger work, so a run with any of them unset is
    refused outright (`LimitsUnsetError`)."""
    resolved = limits.resolve()
    contract = finding_contract() if contract is None else contract
    body = library.body(lens)
    if body is None:
        missing = LensResult(lens, 1, None, None, reason="no lens body in the bundle")
        return synthesize([missing])
    key = LensKey(event.repo, event.pr_number, event.head_sha, lens, body_digest(body))
    if isinstance(next_step(ledger.attempts(key), resolved.retries), Settled):
        return synthesize([_result(key, ledger.attempts(key), resolved, "")])

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

    spend = Spend(resolved)
    fence_nonce = nonce()
    job = LensJob(
        lens,
        body,
        key.body_sha256,
        contract,
        first_turn(event, diff, context, fence_nonce),
        changed,
        read_sources(trees.head, diff, changed),
        fence_nonce,
    )
    review_deadline = clock.monotonic() + resolved.review_wall_s

    def in_session(bridge: Bridge) -> str:
        session.bridges.append(bridge)
        step = next_step(ledger.attempts(key), resolved.retries)
        while isinstance(step, RunAttempt):
            attempts = ledger.attempts(key)
            ledger.start(key, step.number)
            secrets_seen: list[BridgeSecret] = []
            outcome = run_attempt(
                job, bridge, model, spend, clock,
                review_deadline=review_deadline,
                retry_of=attempts[-1].outcome if step.forced and attempts else None,
                secrets=secrets_seen,
            )  # fmt: skip
            session.secrets.extend(secrets_seen)
            ledger.finish(key, step.number, outcome, scrub=scrub)
            step = next_step(ledger.attempts(key), resolved.retries)
        return f"lens {lens}: {len(ledger.attempts(key))} attempt(s)"

    report = run_bridge(
        sprites, runner_ledger, trees, in_session,
        redactor=scrubber, changed=changed, name=event_runner_name(event),
        deadline_s=resolved.review_wall_s, clock=clock, telemetry=telemetry,
        root=bridge_root,
    )  # fmt: skip
    result = _result(key, ledger.attempts(key), resolved, scrub(report.note))
    return synthesize(
        [result],
        session.secrets,
        report,
        spend,
        (*diff_secrets.values, *session.flagged()),
    )


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


def first_turn(
    event: PrEvent, diff: str, context: Sequence[UntrustedBlock], nonce: str
) -> str:
    """The operator's subject, then fenced: any caller context, the diff
    stat and the changed files in risk order. No diff text: the lens reads
    it through the tools."""
    files = by_risk(split_files(diff))
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
    }
    return f"{STATUS_PREFIX}{json.dumps(fields, sort_keys=True)} -->"


def render_draft(review: AgenticReview, redactor: Redactor) -> str:
    """The draft as the operator reads it. Every model-written value (and
    every PR path) is redacted, with the review's flagged values scrubbed,
    and quoted as data."""
    scrubber = Redactor(
        redactor.known_secrets, redactor.sources, (*redactor.flagged, *review.flagged)
    )

    def scrub(text: str) -> str:
        return scrubber(text).text

    lines = [status_line(review), "", _headline(review), ""]
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
    return "\n".join(lines) + "\n"


def _headline(review: AgenticReview) -> str:
    if review.coverage_complete:
        return (
            f"**Review event: {review.event.value}.** Verdict: {review.verdict.value}. "
            "Every selected lens ran whole, attested, with every quote verified."
        )
    short = [r for r in review.lenses if r.state is not LensState.CLEAN]
    named = "; ".join(f"{r.lens}: {r.state.value}" for r in short) or "no lens selected"
    proposed = (
        f" (the findings alone would be {review.proposed_event.value})"
        if review.proposed_event is not review.event
        else ""
    )
    return (
        "> **REVIEW INCOMPLETE -- not approvable.** "
        f"Review event: {review.event.value}{proposed}. Lens coverage is not "
        f"complete ({named}), so this review cannot approve."
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
