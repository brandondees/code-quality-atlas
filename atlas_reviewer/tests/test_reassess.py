# SPDX-License-Identifier: MIT
"""D73's reuse-path re-assessment: a reused settled lens keeps its
findings, earns one bounded no-tools call when the evidence snapshot
moved, and the reply's additions, revisions and withdrawals compose onto
the prior findings -- a withdrawal or revision always carrying its stated
reason, and nothing ever dropped silently. Offline: the model is the
scripted fake, the ledger is a real file, and no GitHub, Sprite or live
model call is made."""

import json
import re
from dataclasses import replace
from decimal import Decimal

import pytest

from atlas_reviewer.attestation import (
    Attempt,
    AttemptOutcome,
    Attestation,
    Cause,
    LensKey,
    LensState,
)
from atlas_reviewer.coordinator import render_draft
from atlas_reviewer.domain import (
    Conclusion,
    Missing,
    Omission,
    SourceKey,
    SourceKind,
)
from atlas_reviewer.evidence import Remark
from atlas_reviewer.gather import Collected
from atlas_reviewer.lens_contract import ContractError
from atlas_reviewer.lens_loop import FinalReply
from atlas_reviewer.ports import ByokRefusedError
from atlas_reviewer.prompt import UntrustedBlock
from atlas_reviewer.quotes import SourceText
from atlas_reviewer.reassess import (
    REASSESS_TARGET_PREFIX,
    effective_outcome,
    judge,
    parse_reassess_reply,
    snapshot_digest,
)
from atlas_reviewer.redact import Redactor, redact

from .agentic import COST, DIGEST, LENS, READ_ALL, final, finding
from .helpers import HEAD, NOW
from .helpers import item as evidence_item
from .test_coordinator import EVENT, ledger, review

UNCHANGED = "1" * 64
NEWER = "2" * 64
REASON = "the CI check at this head now fails; the totals drift shows in the run"

REASSESS_KEY = LensKey(EVENT.repo, EVENT.pr_number, HEAD, f"{LENS}#reassess", DIGEST)


def reassess_reply(*findings, withdrawn=(), lens=LENS, digest=DIGEST, text=None):
    """A re-assessment reply as the scripted model's final turn: the
    findings it reports (an entry may carry `revises` and `reason`) and
    the prior labels it withdraws, each with its reason."""
    if text is None:
        payload = {
            "lens": lens,
            "body_sha256": digest,
            "findings": [dict(f) for f in findings],
            "withdrawn": [{"id": i, "reason": r} for i, r in withdrawn],
        }
        text = json.dumps(payload)
    return FinalReply(text, COST)


def ci_context(*fragments):
    """A CI-evidence context block like the first turn's, for a test that
    stands in for the CLI's gathered delta."""
    return (
        UntrustedBlock(
            "ci-evidence",
            redact("\n".join(("CI evidence for the reviewed head SHA:", *fragments))),
        ),
    )


def comment_context(body):
    """A conversation context block whose newest remark is `body`, for a
    test that stands in for the CLI's gathered delta."""
    return (
        UntrustedBlock(
            "pull-request",
            redact(
                f"### issue_comment:9100 by example-maintainer at "
                f"{NOW.isoformat()}\n> {body}"
            ),
        ),
    )


def fenced(turn, label):
    return re.search(rf'label="{label}">\n(.*?)\n</untrusted-data', turn, re.DOTALL)


def reassess_request(model):
    (request,) = model.requests
    return request


# ------------------------------------------------------------ the three cases


def test_a_reused_lens_with_no_newer_evidence_makes_no_extra_call(tmp_path):
    """Reuse without new evidence is today's reuse, pinned to zero extra
    calls: the same snapshot digest as the settled result's means no
    re-assessment request reaches the model at all (the mutant that
    re-assesses whenever the digest is wired, or that compares it wrong,
    makes a request here and fails)."""
    first, _, _ = review(
        tmp_path, [READ_ALL, final(finding())], evidence_digest=UNCHANGED
    )
    again, model, sprites = review(tmp_path, [], evidence_digest=UNCHANGED)
    assert model.requests == []
    assert sprites.calls == []
    assert again.lenses[0].outcome == first.lenses[0].outcome
    assert again.lenses[0].reassess_note == ""
    assert again.lenses[0].withdrawn == ()
    assert again.coverage_complete


def test_a_reused_lens_reassesses_when_newer_ci_evidence_exists(tmp_path):
    """Reuse with a new CI failure: the snapshot digest moved, so the lens
    earns exactly one bounded call -- no tools, the prior finding labeled
    and the newer CI evidence fenced inside it -- and its added finding
    stands beside the prior one, which is kept (the mutant that drops the
    prior findings not restated, or that offers tools, fails here)."""
    review(tmp_path, [READ_ALL, final(finding())], evidence_digest=UNCHANGED)
    added = finding(
        severity="blocker",
        finding="the head's CI run now fails on the rounding drift this finding names",
    )
    again, model, sprites = review(
        tmp_path,
        [reassess_reply(added)],
        evidence_digest=NEWER,
        context=ci_context("check_run:7003 lint FAIL"),
    )
    assert sprites.calls == []
    request = reassess_request(model)
    assert request.tools == ()
    assert len(request.messages) == 1
    turn = request.messages[0].text
    assert turn.startswith(REASSESS_TARGET_PREFIX)
    prior = fenced(turn, "prior-findings")
    assert prior is not None
    assert "P1" in prior.group(1)
    assert "rounds each item before summing" in prior.group(1)
    ci = fenced(turn, "ci-evidence")
    assert ci is not None
    assert "check_run:7003 lint FAIL" in ci.group(1)
    assert "re-assessing an earlier result of yours for the same head SHA" in " ".join(
        request.system.split()
    )
    assert {f.id for f in again.verified} == {"L1-F1", "L1-F2"}
    assert "rounds each item before summing, so totals drift" in [
        f.finding.finding for f in again.verified
    ]
    assert "CI run now fails" in next(f.finding.finding for f in again.verified)
    assert "re-assessed with newer CI evidence or comments: 1 added" in (
        again.lenses[0].reassess_note
    )


def test_a_reused_lens_reassesses_when_a_newer_comment_arrives(tmp_path):
    """Reuse with a new comment: the same digest move, the delta delivered
    as this review's conversation block inside the one nonce fence, and
    the reply's revision replacing the prior finding with its reason
    stated (the mutant that ships the delta outside the fence fails
    here)."""
    review(tmp_path, [READ_ALL, final(finding())], evidence_digest=UNCHANGED)
    revised = dict(
        finding(
            severity="minor",
            finding="rounds each item before summing; the comment asks for the three-item case",
        ),
        revises="P1",
        reason="the comment narrows the drift to the three-item cart",
    )
    again, model, _ = review(
        tmp_path,
        [reassess_reply(revised)],
        evidence_digest=NEWER,
        context=comment_context("please round the totals, not each line"),
    )
    request = reassess_request(model)
    turn = request.messages[0].text
    conversation = fenced(turn, "pull-request")
    assert conversation is not None
    assert "please round the totals" in conversation.group(1)
    assert turn.count('<untrusted-data id="f00dfeedf00dfeed"') == 2
    assert turn.count('</untrusted-data id="f00dfeedf00dfeed"') == 2
    (standing,) = again.verified
    assert standing.id == "L1-F1"
    assert "three-item case" in standing.finding.finding
    (w,) = again.lenses[0].withdrawn
    assert w.reason == "the comment narrows the drift to the three-item cart"
    assert w.replacement is not None and w.replacement.verified


# --------------------------------------------------- withdrawal and revision


def test_a_withdrawn_finding_keeps_its_stated_reason(tmp_path):
    """A withdrawal removes the prior finding and its reason reaches the
    draft, so a reader can tell it was revised and not lost -- and a
    review whose only finding was withdrawn, on a lens that ran whole and
    clean, approves again."""
    review(tmp_path, [READ_ALL, final(finding())], evidence_digest=UNCHANGED)
    again, _, _ = review(
        tmp_path,
        [reassess_reply(withdrawn=[("P1", REASON)])],
        evidence_digest=NEWER,
        context=ci_context("check_run:7003 lint PASS"),
    )
    assert again.verified == ()
    assert again.lenses[0].state is LensState.CLEAN
    assert again.coverage_complete
    (w,) = again.lenses[0].withdrawn
    assert w.reason == REASON
    assert w.replacement is None
    draft = render_draft(again, Redactor())
    assert "## Withdrawn findings (re-assessed with newer evidence)" in draft
    assert REASON in draft
    assert "rounds each item before summing" in draft


def test_a_revision_replaces_the_prior_finding_and_names_its_replacement(
    tmp_path,
):
    """A revised prior finding is removed and its replacement minted in
    its place, and the withdrawal line names the replacement's id, so the
    reader can follow the revision."""
    review(tmp_path, [READ_ALL, final(finding())], evidence_digest=UNCHANGED)
    replacement = dict(
        finding(
            severity="blocker",
            finding="rounds each item before summing, and the CI run confirms the drift",
        ),
        revises="P1",
        reason="the newer run failed on the exact drift",
    )
    again, _, _ = review(
        tmp_path,
        [reassess_reply(replacement)],
        evidence_digest=NEWER,
        context=ci_context("check_run:7003 lint FAIL"),
    )
    [w] = again.lenses[0].withdrawn
    assert w.replacement is not None and w.replacement.verified
    draft = render_draft(again, Redactor())
    assert "Revised finding: L1-F1" in draft
    assert again.verified[0].id == "L1-F1"


def test_a_revision_whose_replacement_does_not_verify_is_shown_unverified(
    tmp_path,
):
    """A revision whose replacement quote fails the check does not report
    the finding: the withdrawal stands with its reason, the replacement
    shows under Not verified, and nothing is silently lost."""
    review(tmp_path, [READ_ALL, final(finding())], evidence_digest=UNCHANGED)
    again, _, _ = review(
        tmp_path,
        [
            reassess_reply(
                dict(
                    finding(evidence="not in the file"),
                    revises="P1",
                    reason="the run failed",
                )
            )
        ],
        evidence_digest=NEWER,
        context=ci_context("check_run:7003 lint FAIL"),
    )
    assert again.verified == ()
    assert again.unverified
    (w,) = again.lenses[0].withdrawn
    assert w.replacement is not None and not w.replacement.verified
    draft = render_draft(again, Redactor())
    assert "The revised finding did not verify" in draft


# -------------------------------------------------------------- spend, digest


def test_the_reassessment_call_is_charged_to_the_review_s_spend(tmp_path):
    """The re-assessment counts against the run's derived limits and
    dollar ceiling (D68): the reused review's call count and committed
    dollars carry it, and the digest it assessed against is stored with
    the recorded attempt (the mutant that spends outside the shared Spend
    object reports zero calls here)."""
    review(tmp_path, [READ_ALL, final(finding())], evidence_digest=UNCHANGED)
    again, _, _ = review(
        tmp_path,
        [reassess_reply()],
        evidence_digest=NEWER,
        context=ci_context("check_run:7003 lint FAIL"),
    )
    assert again.model_calls == 1
    assert Decimal(again.committed_usd) == Decimal("0.02")
    assert ledger(tmp_path).evidence_digest(REASSESS_KEY) == NEWER


class Overpriced:
    """A model whose re-assessment call cannot fit the reservation: the
    worst case is priced, the reserve refuses, and no turn is ever sent."""

    name = "overpriced"

    def __init__(self) -> None:
        self.priced: list[object] = []
        self.sent: list[object] = []

    def worst_case_usd(self, request):
        self.priced.append(request)
        return Decimal("100.00")

    def turn(self, request):
        self.sent.append(request)
        raise AssertionError("a refused call is not sent")


def test_a_reassessment_over_the_reservation_is_refused_and_retried_later(
    tmp_path,
):
    """A re-assessment the dollar ceiling refuses is recorded as the
    failed attempt it is, the prior findings stand unchanged, and no
    digest is stored -- so the next review of this head earns the call
    again instead of freezing the refusal in."""
    first, _, _ = review(
        tmp_path, [READ_ALL, final(finding())], evidence_digest=UNCHANGED
    )
    again, model, _ = review(tmp_path, [], evidence_digest=NEWER, model=Overpriced())
    assert model.sent == []
    assert len(model.priced) == 1
    assert again.model_calls == 0
    assert again.lenses[0].outcome == first.lenses[0].outcome
    assert "the review's dollar reservation was reached" in (
        again.lenses[0].reassess_note
    )
    assert ledger(tmp_path).evidence_digest(REASSESS_KEY) is None
    (attempt,) = ledger(tmp_path).attempts(REASSESS_KEY)
    assert attempt.outcome.causes == {Cause.BUDGET}
    third, model3, _ = review(
        tmp_path,
        [reassess_reply(withdrawn=[("P1", REASON)])],
        evidence_digest=NEWER,
        context=ci_context("check_run:7003 lint FAIL"),
    )
    assert len(model3.requests) == 1
    assert third.lenses[0].outcome.findings == ()


def test_a_reply_that_never_meets_the_contract_keeps_the_prior_findings(
    tmp_path,
):
    """A re-assessment reply outside the contract is recorded, not
    repaired: every prior finding is kept, the note says the reply was not
    accepted, and no digest is stored, so the next review re-runs the
    bounded call (the mutant that drops the prior findings on a failed
    reply fails here)."""
    review(tmp_path, [READ_ALL, final(finding())], evidence_digest=UNCHANGED)
    again, _, _ = review(
        tmp_path, [reassess_reply(text="not json at all")], evidence_digest=NEWER
    )
    assert [f.finding.finding for f in again.verified] == [
        "rounds each item before summing, so totals drift"
    ]
    assert "the latest re-assessment was not accepted" in again.lenses[0].reassess_note
    assert ledger(tmp_path).evidence_digest(REASSESS_KEY) is None
    again2, model2, _ = review(
        tmp_path,
        [reassess_reply(withdrawn=[("P1", REASON)])],
        evidence_digest=NEWER,
        context=ci_context("check_run:7003 lint FAIL"),
    )
    assert len(model2.requests) == 1
    assert again2.verified == ()


def test_a_result_settled_before_the_digest_was_stored_reassesses_once_and_stands(
    tmp_path,
):
    """A settled result with no stored digest -- from before this
    mechanism -- reads as "cannot be shown to be current" and earns the
    one bounded re-assessment; the attested reply records the digest, so
    the next review of unchanged evidence makes no extra call."""
    first, _, _ = review(tmp_path, [READ_ALL, final(finding())])
    again, model, _ = review(tmp_path, [reassess_reply()], evidence_digest=UNCHANGED)
    assert len(model.requests) == 1
    assert again.lenses[0].outcome == first.lenses[0].outcome
    third, model3, _ = review(tmp_path, [], evidence_digest=UNCHANGED)
    assert model3.requests == []
    assert third.lenses[0].outcome == again.lenses[0].outcome
    assert third.lenses[0].reassess_note == (
        "re-assessed with newer CI evidence or comments"
    )


def test_a_settled_result_that_never_attested_earns_no_reassessment(tmp_path):
    """A settled outcome that was not attested -- a lens that never
    produced a usable judgment -- earns no re-assessment: there are no
    prior findings to keep, and a single no-tools call is not a lens run;
    the ordinary retry policy governs it."""

    class Refusing:
        name = "byok"

        def __init__(self) -> None:
            self.requests: list[object] = []

        def worst_case_usd(self, request):
            self.requests.append(request)
            return Decimal("0.01")

        def turn(self, request):
            raise ByokRefusedError("refusing the review: byok")

    first, _, _ = review(tmp_path, [], model=Refusing())
    assert first.lenses[0].state is LensState.FAILED
    again, model, _ = review(tmp_path, [], evidence_digest=NEWER)
    assert model.requests == []
    assert again.lenses[0].state is LensState.FAILED
    assert again.lenses[0].reassess_note == ""


# ------------------------------------------------------------ the composition


def test_the_composition_replays_recorded_reassessments_in_order():
    """The effective set is the ledger's to reproduce: two recorded
    re-assessments apply in order, each judged against the set its own
    reply was labeled against -- the first revises P1 (the major), the
    second withdraws P1 as the set then labels it (the kept nit) and adds
    a blocker -- and the final set carries the revision and the addition
    (the mutant that drops unnamed priors, or that mislabels the replay,
    fails here)."""
    settled = AttemptOutcome(
        Attestation.ATTESTED,
        findings=(checked(finding()), checked(finding(severity="nit"))),
    )
    first = AttemptOutcome(
        Attestation.ATTESTED,
        findings=(checked(finding(severity="minor")),),
        revises=((1, "P1", "the comment narrows it"),),
    )
    second = AttemptOutcome(
        Attestation.ATTESTED,
        findings=(checked(finding(severity="blocker")),),
        withdrawn=(("P1", REASON),),
    )
    effective, withdrawn, note = effective_outcome(
        settled, (Attempt(1, first), Attempt(2, second))
    )
    assert [
        (c.finding.severity.value, c.finding.finding) for c in effective.findings
    ] == [
        ("minor", "rounds each item before summing, so totals drift"),
        ("blocker", "rounds each item before summing, so totals drift"),
    ]
    assert [(w.reason, w.replacement is not None) for w in withdrawn] == [
        ("the comment narrows it", True),
        (REASON, False),
    ]
    assert note == (
        "re-assessed with newer CI evidence or comments: "
        "1 added, 1 revised, 1 withdrawn"
    )


def checked(raw):
    """One of `raw`'s findings quote-checked against a head file that
    holds the quote, as the reuse path's judge checks a reply's."""
    reply = parse_reassess_reply(
        json.dumps(
            {
                "lens": LENS,
                "body_sha256": DIGEST,
                "findings": [raw],
                "withdrawn": [],
            }
        )
    )
    sources = SourceText(
        {"calc.py": ("def total(xs):", "    return sum(round(x, 2) for x in xs)")}
    )
    (judged,) = judge(reply, (), sources, 3).checked
    return judged


def test_a_composition_note_names_an_unresolvable_reference():
    """A recorded label that resolves against nothing -- possible only on
    a hand-corrupted ledger line -- is skipped and named in the note,
    never applied half-way."""
    settled = AttemptOutcome(Attestation.ATTESTED, findings=(checked(finding()),))
    bogus = AttemptOutcome(
        Attestation.ATTESTED, findings=(), withdrawn=(("P9", REASON),)
    )
    effective, withdrawn, note = effective_outcome(settled, (Attempt(1, bogus),))
    assert [c.finding.finding for c in effective.findings] == [
        "rounds each item before summing, so totals drift"
    ]
    assert withdrawn == ()
    assert "1 recorded re-assessment reference(s) resolved against nothing" in note


# ------------------------------------------------------------------ the reply


def test_the_reassessment_reply_parses_its_shape():
    reply = parse_reassess_reply(
        json.dumps(
            {
                "lens": LENS,
                "body_sha256": DIGEST,
                "findings": [dict(finding(), revises="P1", reason=REASON)],
                "withdrawn": [{"id": "P2", "reason": "the check passes"}],
            }
        )
    )
    assert reply.lens == LENS
    assert reply.findings[0].revises == "P1"
    assert reply.findings[0].reason == REASON
    assert reply.withdrawn == (("P2", "the check passes"),)


def test_a_revision_without_a_reason_is_refused():
    with pytest.raises(ContractError, match="a revision carries the reason"):
        parse_reassess_reply(
            json.dumps(
                {
                    "lens": LENS,
                    "body_sha256": DIGEST,
                    "findings": [dict(finding(), revises="P1")],
                    "withdrawn": [],
                }
            )
        )


def test_a_withdrawal_without_a_reason_is_refused():
    with pytest.raises(ContractError, match="withdrawal carries the reason"):
        parse_reassess_reply(
            json.dumps(
                {
                    "lens": LENS,
                    "body_sha256": DIGEST,
                    "findings": [],
                    "withdrawn": [{"id": "P1", "reason": "   "}],
                }
            )
        )


def test_a_withdrawn_entry_is_exactly_id_and_reason():
    with pytest.raises(ContractError, match="exactly the keys"):
        parse_reassess_reply(
            json.dumps(
                {
                    "lens": LENS,
                    "body_sha256": DIGEST,
                    "findings": [],
                    "withdrawn": [{"id": "P1", "reason": REASON, "extra": "x"}],
                }
            )
        )


def test_a_reason_without_a_revision_is_refused():
    with pytest.raises(ContractError, match="a reason names the prior finding"):
        parse_reassess_reply(
            json.dumps(
                {
                    "lens": LENS,
                    "body_sha256": DIGEST,
                    "findings": [dict(finding(), reason=REASON)],
                    "withdrawn": [],
                }
            )
        )


def test_a_label_that_names_no_prior_finding_is_refused_at_judge():
    reply = parse_reassess_reply(
        json.dumps(
            {
                "lens": LENS,
                "body_sha256": DIGEST,
                "findings": [dict(finding(), revises="P7", reason=REASON)],
                "withdrawn": [],
            }
        )
    )
    with pytest.raises(ContractError, match="names no prior finding"):
        judge(reply, (checked(finding()),), SourceText({}), 3)


def test_a_reassessed_unknown_severity_is_dropped_and_named():
    reply = parse_reassess_reply(
        json.dumps(
            {
                "lens": LENS,
                "body_sha256": DIGEST,
                "findings": [dict(finding(), severity="urgent")],
                "withdrawn": [],
            }
        )
    )
    assert reply.findings == ()
    assert reply.dropped and "urgent" in reply.dropped[0]


def test_prose_around_the_reassessment_reply_is_fine():
    fenced = (
        "here is my re-assessment:\n```json\n"
        + json.dumps(
            {"lens": LENS, "body_sha256": DIGEST, "findings": [], "withdrawn": []}
        )
        + "\n```"
    )
    reply = parse_reassess_reply(fenced)
    assert reply.findings == ()


# ------------------------------------------------------------------ the digest


def _collected(items=(), omissions=(), failures=(), notes=()):
    collected = Collected()
    collected.items.extend(items)
    collected.omissions.extend(omissions)
    collected.failures.extend(failures)
    collected.notes.extend(notes)
    return collected


def _remark(
    source_id="issue_comment:1",
    at="2026-11-15T20:32:00Z",
    body="please round the totals",
):
    return Remark(source_id, at, "example-maintainer", "conversation comment", body)


def test_the_snapshot_digest_is_stable_over_unchanged_evidence():
    assert snapshot_digest(
        _collected([evidence_item()]), (_remark(),), _collected()
    ) == snapshot_digest(_collected([evidence_item()]), (_remark(),), _collected())


def test_the_snapshot_digest_ignores_the_fetch_time():
    """`fetched_at` is when *we* read; it differs on every review of
    unchanged evidence and must not move the digest (the mutant that
    digests the fetch time re-assesses every review and fails here)."""
    first = snapshot_digest(_collected([evidence_item()]), (), _collected())
    later = replace(evidence_item(), fetched_at=NOW.replace(year=2027))
    assert snapshot_digest(_collected([later]), (), _collected()) == first


def test_the_snapshot_digest_moves_with_new_ci_evidence():
    base = snapshot_digest(_collected([evidence_item()]), (), _collected())
    failed = replace(evidence_item(), conclusion=Conclusion.FAILURE)
    assert snapshot_digest(_collected([failed]), (), _collected()) != base
    fresh = evidence_item(name="gate-2")
    assert (
        snapshot_digest(_collected([evidence_item(), fresh]), (), _collected()) != base
    )


def test_the_snapshot_digest_moves_with_a_new_comment():
    base = snapshot_digest(_collected(), (_remark(),), _collected())
    assert (
        snapshot_digest(_collected(), (_remark(body="edited"),), _collected()) != base
    )
    assert (
        snapshot_digest(
            _collected(), (_remark(), _remark("issue_comment:2")), _collected()
        )
        != base
    )
    assert snapshot_digest(_collected(), (), _collected()) != base


def test_the_snapshot_digest_moves_when_a_fetch_fails_or_recovers():
    """A listing that could not be read is part of what was judged: its
    failure moves the digest, and its recovery moves it back -- the
    fail-safe direction (the mutant that digests only the items hides a
    listing nobody saw)."""
    failed = snapshot_digest(
        _collected(),
        (),
        _collected(omissions=(Omission("CI evidence", "fetch failed", "boom"),)),
    )
    assert failed != snapshot_digest(_collected(), (), _collected())
    assert failed != snapshot_digest(
        _collected(),
        (),
        _collected(omissions=(Omission("CI evidence", "fetch failed", "different"),)),
    )
    keyed = snapshot_digest(
        _collected(),
        (),
        _collected(
            failures=(
                Missing(SourceKey(SourceKind.LISTING, "(all check runs)"), "boom"),
            )
        ),
    )
    assert keyed != snapshot_digest(_collected(), (), _collected())
