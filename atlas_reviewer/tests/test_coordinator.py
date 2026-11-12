# SPDX-License-Identifier: MIT
"""The agentic coordinator end to end: ledger-driven attempts over the real
bridge (`LocalSprites`), a scripted model, verification and the draft. No
model, Sprite or GitHub call is made."""

from dataclasses import replace

import pytest

from atlas_reviewer.attestation import (
    AttemptLedger,
    AttemptOutcome,
    Attestation,
    Cause,
    CheckedFinding,
    LensKey,
    LensState,
    body_digest,
)
from atlas_reviewer.bridge import BridgeSecret
from atlas_reviewer.coordinator import (
    LensResult,
    Verdict,
    render_draft,
    review_lens,
    status_line,
    synthesize,
)
from atlas_reviewer.domain import CleanupStatus, PrEvent, RunnerStatus
from atlas_reviewer.fakes import FakeSprites, MemoryLedger, ScriptedLensModel
from atlas_reviewer.lens_contract import (
    Attribution,
    Finding,
    LineRange,
    Route,
    Severity,
    Valence,
)
from atlas_reviewer.lens_loop import LimitsUnsetError
from atlas_reviewer.ports import RefusedError
from atlas_reviewer.prompt import UntrustedBlock
from atlas_reviewer.quotes import QuoteSource
from atlas_reviewer.redact import Redactor, redact
from atlas_reviewer.runner import CreateRefusedError, DeadlineExceededError
from atlas_reviewer.verdict import ReviewEvent, parse_status

from .agentic import (
    BODY,
    DIFF,
    DIGEST,
    LENS,
    LIMITS,
    READ_DIFF,
    TOKEN,
    final,
    finding,
    trees,
)
from .helpers import HEAD, FakeClock, LocalSprites, StubLibrary

EVENT = PrEvent("example-org/example-app", 7, HEAD)
KEY = LensKey(EVENT.repo, EVENT.pr_number, HEAD, LENS, DIGEST)
MISACK = final(digest="0" * 64)


def ledger(tmp_path):
    return AttemptLedger(tmp_path / "state" / "attestations.jsonl", FakeClock())


def review(tmp_path, script, *, sprites=None, limits=LIMITS, library=None, **kw):
    sprites = sprites if sprites is not None else LocalSprites()
    model = ScriptedLensModel(list(script))
    result = review_lens(
        EVENT, LENS, DIFF, trees(),
        library=library or StubLibrary({LENS: BODY}), model=model, limits=limits,
        ledger=ledger(tmp_path), sprites=sprites, runner_ledger=MemoryLedger(),
        redactor=Redactor(), clock=FakeClock(), nonce=lambda: "f00dfeedf00dfeed",
        bridge_root=str(tmp_path / "bridge"), **kw,
    )  # fmt: skip
    return result, model, sprites


def status(result):
    return parse_status(render_draft(result, Redactor()))


# ------------------------------------------------------------ refusals


def test_a_review_with_any_limit_unset_is_refused_before_anything_runs(tmp_path):
    sprites = FakeSprites()
    with pytest.raises(LimitsUnsetError, match="reservation_usd"):
        review(tmp_path, [READ_DIFF, final()], sprites=sprites,
               limits=replace(LIMITS, reservation_usd=None))  # fmt: skip
    assert sprites.calls == []
    assert not (tmp_path / "state").exists()


def test_a_lens_with_no_body_stops_before_any_model_runner_or_ledger_work(tmp_path):
    sprites = FakeSprites()
    result, model, _ = review(
        tmp_path, [READ_DIFF, final()], sprites=sprites, library=StubLibrary({})
    )
    (lens,) = result.lenses
    assert lens.state is LensState.NOT_RUN
    assert lens.reason == "no lens body in the bundle"
    assert model.requests == []
    assert len(model.script) == 2
    assert sprites.calls == []
    assert not (tmp_path / "state").exists()
    assert not result.coverage_complete


def test_a_refused_runner_create_propagates_and_records_no_attempt(tmp_path):
    sprites = FakeSprites(fail_on={"create": RefusedError("Sprites HTTP 400")})
    with pytest.raises(CreateRefusedError):
        review(tmp_path, [READ_DIFF, final()], sprites=sprites)
    assert ledger(tmp_path).attempts(KEY) == ()


# ------------------------------------------------------------ end to end


def test_a_clean_lens_gives_complete_coverage_and_its_verdict(tmp_path):
    result, _, _ = review(tmp_path, [READ_DIFF, final(finding())])
    (lens,) = result.lenses
    assert (lens.state, lens.attempts, lens.escalated) == (LensState.CLEAN, 1, False)
    assert result.coverage_complete
    assert result.verdict is Verdict.APPROVE_WITH_CHANGES
    assert result.event is ReviewEvent.COMMENT
    assert result.runner.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert [f.id for f in result.verified] == ["L1-F1"]
    assert status(result)["coverage_complete"] is True
    assert result.model_calls == 2


def test_a_clean_lens_with_no_findings_approves(tmp_path):
    result, _, _ = review(tmp_path, [READ_DIFF, final()])
    assert result.event is ReviewEvent.APPROVE
    assert status(result)["review_event"] == "APPROVE"


def test_the_ledger_records_each_attempt_with_its_head_and_body(tmp_path):
    review(tmp_path, [READ_DIFF, final(finding())])
    (attempt,) = ledger(tmp_path).attempts(KEY)
    assert attempt.number == 1
    assert attempt.outcome.attestation is Attestation.ATTESTED


def test_a_failed_attestation_is_retried_once_with_the_body_forced(tmp_path):
    result, model, _ = review(tmp_path, [READ_DIFF, MISACK, READ_DIFF, final()])
    (lens,) = result.lenses
    assert (lens.state, lens.attempts, lens.escalated) == (LensState.CLEAN, 2, False)
    retry = model.requests[2]
    assert "A previous attempt of this lens was not accepted" in retry.system
    assert BODY in retry.system
    assert len(retry.messages) == 1


def test_a_retry_that_fails_again_escalates_and_never_approves(tmp_path):
    result, _, _ = review(tmp_path, [READ_DIFF, MISACK, READ_DIFF, MISACK])
    (lens,) = result.lenses
    assert (lens.state, lens.attempts, lens.escalated) == (LensState.FAILED, 2, True)
    assert not result.coverage_complete
    assert result.event is ReviewEvent.COMMENT
    draft = render_draft(result, Redactor())
    assert draft.splitlines()[2].startswith(
        "> **REVIEW INCOMPLETE -- not approvable.**"
    )
    assert "escalated: the retry also failed" in draft
    assert status(result)["coverage_complete"] is False
    assert status(result)["lenses"] == {
        "clean": 0,
        "partial": 0,
        "failed": 1,
        "not_run": 0,
    }


def test_quotes_that_fail_twice_leave_the_lens_partial_and_report_only_verified(
    tmp_path,
):
    wrong = finding(evidence="return sum(x for x in xs if x)", severity="blocker")
    script = [READ_DIFF, final(finding(), wrong)] * 2
    result, _, _ = review(tmp_path, script)
    (lens,) = result.lenses
    assert (lens.state, lens.escalated) == (LensState.PARTIAL, True)
    assert [f.id for f in result.verified] == ["L1-F1"]
    assert [f.id for f in result.unverified] == ["L1-F2"]
    assert result.verdict is Verdict.APPROVE_WITH_CHANGES
    draft = render_draft(result, Redactor())
    assert "## Not verified (not reported as findings)" in draft


def test_a_cut_short_lens_is_partial_and_not_retried(tmp_path):
    result, model, _ = review(
        tmp_path, [READ_DIFF] * 10, limits=replace(LIMITS, max_turns=2)
    )
    (lens,) = result.lenses
    assert (lens.state, lens.attempts) == (LensState.PARTIAL, 1)
    assert lens.outcome.causes == {Cause.TURN_CAP}
    assert len(model.requests) == 2
    assert not result.coverage_complete


def test_a_runner_that_never_stages_leaves_the_lens_not_run_with_its_reason(tmp_path):
    broken = replace(trees(), head=b"not a tarball")
    model = ScriptedLensModel([READ_DIFF, final()])
    result = review_lens(
        EVENT, LENS, DIFF, broken,
        library=StubLibrary({LENS: BODY}), model=model, limits=LIMITS,
        ledger=ledger(tmp_path), sprites=FakeSprites(), runner_ledger=MemoryLedger(),
        redactor=Redactor(), clock=FakeClock(), bridge_root=str(tmp_path / "bridge"),
    )  # fmt: skip
    (lens,) = result.lenses
    assert lens.state is LensState.NOT_RUN
    assert lens.reason.startswith("no attempt was recorded: ")
    assert "gzip" in lens.reason
    assert model.requests == []
    assert not result.coverage_complete


def test_a_quote_of_removed_code_is_reported_as_removed_lines_with_its_siblings(
    tmp_path,
):
    removed = finding(
        evidence="return sum(xs)",
        attribution="pre-existing",
        route="implementer",
        siblings="none found in src/",
    )
    result, _, _ = review(tmp_path, [READ_DIFF, final(removed)])
    draft = render_draft(result, Redactor())
    assert "pre-existing, removed lines]" in draft
    assert 'Siblings: `"none found in src/"`' in draft


def test_a_secret_hit_without_a_location_is_still_listed():
    hit = BridgeSecret("github-token", None, None, False)
    result = synthesize([lens_result(clean())], [hit, hit])
    draft = render_draft(result, Redactor())
    assert (
        draft.count("possible committed secret (github-token) in an unlocated result")
        == 1
    )


# ------------------------------------------------- restarts and reruns


def test_a_rerun_on_the_same_head_and_body_reuses_the_settled_lens(tmp_path):
    first, _, _ = review(tmp_path, [READ_DIFF, final(finding())])
    sprites = FakeSprites()
    again, model, _ = review(tmp_path, [], sprites=sprites)
    assert sprites.calls == []
    assert model.requests == []
    assert again.lenses[0].outcome == first.lenses[0].outcome
    assert again.coverage_complete


def test_a_changed_body_is_a_new_lens_run(tmp_path):
    review(tmp_path, [READ_DIFF, final()])
    new_body = BODY + "\nAlso check the docs.\n"
    new_digest = body_digest(new_body)
    result, model, _ = review(
        tmp_path, [READ_DIFF, final(digest=new_digest)],
        library=StubLibrary({LENS: new_body}),
    )  # fmt: skip
    assert len(model.requests) == 2
    (lens,) = result.lenses
    assert (lens.state, lens.attempts, lens.body_sha256) == (
        LensState.CLEAN,
        1,
        new_digest,
    )
    assert len(ledger(tmp_path).attempts(KEY)) == 1


def test_a_crash_mid_attempt_counts_the_attempt_and_the_rerun_retries(tmp_path):
    class Crash(Exception):
        pass

    def crash(request):
        raise Crash("controller killed")

    with pytest.raises(Crash):
        review(tmp_path, [READ_DIFF, crash])
    (abandoned,) = ledger(tmp_path).attempts(KEY)
    assert abandoned.outcome.causes == {Cause.ABANDONED}
    result, model, _ = review(tmp_path, [READ_DIFF, final()])
    (lens,) = result.lenses
    assert (lens.state, lens.attempts) == (LensState.CLEAN, 2)
    assert (
        "A previous attempt of this lens was not accepted" in model.requests[0].system
    )


def test_a_review_that_ends_mid_attempt_reports_the_retry_as_pending(tmp_path):
    def deadline(request):
        raise DeadlineExceededError("the review deadline passed")

    result, _, _ = review(tmp_path, [READ_DIFF, deadline])
    (lens,) = result.lenses
    assert result.runner.status is RunnerStatus.DEADLINE_EXCEEDED
    assert (lens.state, lens.retry_pending, lens.attempts) == (
        LensState.FAILED,
        True,
        1,
    )
    assert "its retry did not run before the review ended" in render_draft(
        result, Redactor()
    )


# ------------------------------------------------------- the first turn


def test_the_first_turn_lists_the_change_fenced_and_carries_no_diff_text(tmp_path):
    context = UntrustedBlock("pull-request", redact("Title: round totals"))
    _, model, _ = review(tmp_path, [READ_DIFF, final()], context=(context,))
    first = model.requests[0].messages[0].text
    assert first.startswith(
        f"Review target (from the operator): {EVENT.repo}#7 at {HEAD}"
    )
    assert '<untrusted-data id="f00dfeedf00dfeed" label="pull-request">' in first
    assert "2 changed file(s), highest risk first:" in first
    assert "calc.py (+1 -1)" in first
    assert "config/keys.py (+1 -0)" in first
    assert "return sum(round" not in first


# --------------------------------------------------------- the draft


def test_flagged_values_and_markup_from_the_model_never_reach_the_draft(tmp_path):
    loud = finding(
        location="config/keys.py:1",
        evidence=f'TOKEN = "{TOKEN}"',
        finding=f"token {TOKEN} is committed <!-- end -->",
        severity="blocker",
    )
    result, _, _ = review(tmp_path, [READ_DIFF, final(loud)])
    draft = render_draft(result, Redactor())
    assert TOKEN not in draft
    assert "<!--" not in draft.split("\n", 1)[1]
    assert result.verdict is Verdict.BLOCK
    assert result.event is ReviewEvent.REQUEST_CHANGES
    assert TOKEN not in ledger(tmp_path).path.read_text()


def test_committed_secrets_the_tools_read_are_controller_findings(tmp_path):
    read = READ_DIFF.__class__(
        (READ_DIFF.calls[0].__class__("read_file", {"path": "config/keys.py"}),),
        READ_DIFF.cost_usd,
    )
    result, _, _ = review(tmp_path, [read, final()])
    draft = render_draft(result, Redactor())
    assert "## Possible committed secrets (controller findings)" in draft
    assert "introduced; rotate if real" in draft
    assert TOKEN not in draft


def test_an_unverified_findings_problem_text_is_scrubbed_in_the_draft():
    opaque = "zq-problem-7c1f9a"
    bad = CheckedFinding(
        checked(Severity.MAJOR).finding, problem=f"the quote missed {opaque}"
    )
    result = synthesize([lens_result(clean(bad))], flagged=[opaque])
    draft = render_draft(result, Redactor())
    assert opaque not in draft
    assert "## Not verified" in draft


def test_every_value_the_review_flagged_is_scrubbed_from_the_draft():
    opaque = "zq-internal-7c1f9a"
    leaky = replace(
        checked(Severity.MAJOR).finding, finding=f"the value {opaque} is in the file"
    )
    outcome = clean(CheckedFinding(leaky, QuoteSource.HEAD))
    result = synthesize([lens_result(outcome)], flagged=[opaque])
    draft = render_draft(result, Redactor())
    assert opaque not in draft
    assert "the value" in draft


def test_a_review_carries_the_diffs_flagged_values_to_the_draft(tmp_path):
    result, _, _ = review(tmp_path, [READ_DIFF, final()])
    assert TOKEN in result.flagged
    assert TOKEN not in repr(result)


def test_the_status_line_is_the_drafts_first_line_and_only_controller_values():
    result = synthesize([lens_result(AttemptOutcome(Attestation.ATTESTED))])
    draft = render_draft(result, Redactor())
    assert draft.split("\n", 1)[0] == status_line(result)
    assert parse_status(draft) == {
        "mode": "agentic",
        "review_event": "APPROVE",
        "proposed_event": "APPROVE",
        "coverage_complete": True,
        "lenses": {"clean": 1, "partial": 0, "failed": 0, "not_run": 0},
        "verified_findings": 0,
        "unverified_findings": 0,
    }


# ------------------------------------------------------ synthesis rules


def lens_result(outcome, **kw):
    return LensResult(LENS, 1, DIGEST, outcome, attempts=1, **kw)


def checked(severity, *, attribution=Attribution.INTRODUCED, valence=Valence.DEFECT,
            verified=True, route=None):  # fmt: skip
    route = route or (
        Route.ENG if attribution is Attribution.INTRODUCED else Route.IMPLEMENTER
    )
    f = Finding(
        LineRange("calc.py", 2, 2), severity, valence, route, attribution,
        f"a {severity.value} issue", "fix it", "return sum(round(x, 2) for x in xs)",
    )  # fmt: skip
    if verified:
        return CheckedFinding(f, QuoteSource.HEAD)
    return CheckedFinding(f, problem="the quote is not at that range")


def clean(*findings):
    return AttemptOutcome(Attestation.ATTESTED, findings=tuple(findings))


@pytest.mark.parametrize(
    ("findings", "verdict", "event"),
    [
        ((), Verdict.APPROVE, ReviewEvent.APPROVE),
        ((checked(Severity.NIT),), Verdict.APPROVE, ReviewEvent.APPROVE),
        ((checked(Severity.MINOR),), Verdict.APPROVE_WITH_CHANGES, ReviewEvent.COMMENT),
        ((checked(Severity.MAJOR),), Verdict.APPROVE_WITH_CHANGES, ReviewEvent.COMMENT),
        ((checked(Severity.NIT), checked(Severity.BLOCKER)), Verdict.BLOCK,
         ReviewEvent.REQUEST_CHANGES),
        ((checked(Severity.BLOCKER, route=Route.LEGAL),), Verdict.BLOCK,
         ReviewEvent.REQUEST_CHANGES),
        ((checked(Severity.BLOCKER, attribution=Attribution.PRE_EXISTING),),
         Verdict.APPROVE, ReviewEvent.APPROVE),
        ((checked(Severity.BLOCKER, verified=False),), Verdict.APPROVE, ReviewEvent.APPROVE),
    ],
    ids=["none", "nit", "minor", "major", "blocker", "routed-blocker", "pre-existing",
         "unverified"],
)  # fmt: skip
def test_the_verdict_follows_only_verified_introduced_defects(findings, verdict, event):
    result = synthesize([lens_result(clean(*findings))])
    assert result.verdict is verdict
    assert result.event is event


@pytest.mark.parametrize(
    "outcome",
    [
        AttemptOutcome(Attestation.ATTESTED, frozenset({Cause.NO_SOURCE_READ})),
        AttemptOutcome(Attestation.UNACKNOWLEDGED, frozenset({Cause.TURN_CAP})),
        AttemptOutcome(Attestation.MISACKNOWLEDGED),
        None,
    ],
    ids=["partial", "cut-short", "failed", "not-run"],
)
def test_coverage_short_of_clean_never_approves_even_with_no_findings(outcome):
    result = synthesize([lens_result(outcome)])
    assert not result.coverage_complete
    assert result.proposed_event is ReviewEvent.APPROVE
    assert result.event is ReviewEvent.COMMENT
    assert status_line(result).count('"coverage_complete": false') == 1


def test_no_lens_selected_is_not_complete_coverage():
    assert not synthesize([]).coverage_complete


def test_findings_are_minted_in_reply_order_and_ranked_by_severity():
    outcome = clean(
        checked(Severity.MINOR),
        checked(Severity.BLOCKER, attribution=Attribution.PRE_EXISTING),
        checked(Severity.BLOCKER),
        checked(Severity.MAJOR, verified=False),
    )
    result = synthesize([lens_result(outcome)])
    assert [f.id for f in result.verified] == ["L1-F3", "L1-F2", "L1-F1"]
    assert [f.id for f in result.unverified] == ["L1-F4"]


def test_findings_of_an_unattested_attempt_are_never_reported():
    misack = AttemptOutcome(
        Attestation.MISACKNOWLEDGED, findings=(checked(Severity.BLOCKER),)
    )
    result = synthesize([lens_result(misack)])
    assert result.findings == ()
    assert result.verdict is Verdict.APPROVE
