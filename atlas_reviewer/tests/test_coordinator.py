# SPDX-License-Identifier: MIT
"""The agentic coordinator end to end: ledger-driven attempts over the real
bridge (`LocalSprites`), a scripted model, verification and the draft. No
model, Sprite or GitHub call is made."""

import re
import threading
from dataclasses import replace
from decimal import Decimal

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
from atlas_reviewer.bridge_staging import SourceTrees
from atlas_reviewer.coordinator import (
    HALTED_REASON,
    LATE_REASON,
    LensResult,
    Verdict,
    _blocks_coverage,
    _still_unread,
    render_draft,
    review_lens,
    review_lenses,
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
from atlas_reviewer.ports import ByokRefusedError, RefusedError
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
    READ_ALL,
    READ_DIFF,
    TOKEN,
    TOP,
    final,
    finding,
    tools,
    trees,
)
from .helpers import HEAD, OLD, FakeClock, LocalSprites, StubLibrary, source_tarball

EVENT = PrEvent("example-org/example-app", 7, HEAD)
KEY = LensKey(EVENT.repo, EVENT.pr_number, HEAD, LENS, DIGEST)
MISACK = final(digest="0" * 64)


def ledger(tmp_path):
    return AttemptLedger(tmp_path / "state" / "attestations.jsonl", FakeClock())


def review(tmp_path, script, *, sprites=None, limits=LIMITS, library=None,
           hold_fail="", model=None, the_diff=None, the_trees=None, **kw):  # fmt: skip
    from .test_keepalive import TaskServer, socket_path

    sprites = sprites if sprites is not None else LocalSprites()
    model = ScriptedLensModel(list(script)) if model is None else model
    tasks = TaskServer(socket_path(tmp_path))
    tasks.fail = hold_fail
    tasks.start()
    try:
        result = review_lens(
            EVENT, LENS, DIFF if the_diff is None else the_diff,
            trees() if the_trees is None else the_trees,
            library=library or StubLibrary({LENS: BODY}), model=model, limits=limits,
            ledger=ledger(tmp_path), sprites=sprites, runner_ledger=MemoryLedger(),
            redactor=Redactor(), clock=FakeClock(), nonce=lambda: "f00dfeedf00dfeed",
            bridge_root=str(tmp_path / "bridge"), task_socket=str(tasks.path), **kw,
        )  # fmt: skip
    finally:
        review.hold_order = list(tasks.order)
        tasks.close()
        if not hold_fail:
            assert tasks.tasks == {}, tasks.order
    return result, model, sprites


def status(result):
    return parse_status(render_draft(result, Redactor()))


# ------------------------------------------------------------ refusals


def test_a_model_with_other_per_call_limits_is_refused_before_anything_runs(tmp_path):
    sprites = FakeSprites()
    model = ScriptedLensModel([])
    model.per_call = replace(LIMITS.resolve(), max_input_tokens=8)
    with pytest.raises(ValueError, match="per-call limits"):
        review(tmp_path, [], sprites=sprites, model=model)
    assert sprites.calls == []
    assert not (tmp_path / "state").exists()


def test_a_model_that_names_these_limits_still_runs(tmp_path):
    model = ScriptedLensModel([READ_ALL, final(finding())])
    model.per_call = LIMITS.resolve()
    result, seen, _ = review(tmp_path, [], model=model)
    assert result.lenses[0].state is LensState.CLEAN
    assert seen.requests


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
    result, _, _ = review(tmp_path, [READ_ALL, final(finding())])
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
    result, _, _ = review(tmp_path, [READ_ALL, final()])
    assert result.event is ReviewEvent.APPROVE
    parsed = status(result)
    assert parsed["review_event"] == "APPROVE"
    assert parsed["coverage_complete"] is True
    assert (parsed["changed_files"], parsed["unreviewed_files"]) == (2, 0)
    draft = render_draft(result, Redactor())
    assert "Every changed file's diff (2) was read in full." in draft
    assert review.hold_order[0] == "POST"
    assert review.hold_order[-1] == "DELETE"


def test_reading_one_of_five_changed_files_cannot_approve(tmp_path):
    """The #623 shape: one diff page of one file, a clean answer, five
    changed files. The review cannot approve, and the draft names the
    unread files with the highest-risk path first."""
    names = (
        "src/app.py",
        "src/util.py",
        "docs/guide.md",
        "tests/test_app.py",
        "auth/session.py",
    )
    base = {name: b"value = 1\n" for name in names}
    head = {name: b"value = 2\n" for name in names}
    diff = "".join(
        f"diff --git a/{name} b/{name}\n"
        f"--- a/{name}\n"
        f"+++ b/{name}\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
        for name in names
    )
    read = tools(("diff_file", {"path": "src/app.py"}))
    result, model, _ = review(
        tmp_path,
        [read, final()],
        the_diff=diff,
        the_trees=SourceTrees(
            source_tarball(base, TOP), source_tarball(head, TOP), OLD, HEAD
        ),
    )
    assert result.event is ReviewEvent.COMMENT
    assert result.proposed_event is ReviewEvent.APPROVE
    assert not result.coverage_complete
    (lens,) = result.lenses
    assert lens.state is LensState.PARTIAL
    assert Cause.FILES_UNREAD in lens.outcome.causes
    assert not lens.outcome.retryable
    assert lens.outcome.unread == (
        "auth/session.py",
        "docs/guide.md",
        "src/util.py",
        "tests/test_app.py",
    )
    parsed = status(result)
    assert parsed["coverage_complete"] is False
    assert (parsed["changed_files"], parsed["unreviewed_files"]) == (5, 4)
    assert "src/app.py" not in status_line(result)
    headline = render_draft(result, Redactor()).splitlines()[2]
    assert "4 changed files not read in full" in headline
    assert headline.index("auth/session.py") < headline.index("src/util.py")
    assert "src/app.py" not in headline
    assert len(model.requests) == 2


def test_a_hold_that_fails_to_create_does_not_run_the_lens(tmp_path):
    result, model, _ = review(tmp_path, [READ_DIFF, final()], hold_fail="POST")
    (lens,) = result.lenses
    assert lens.state is LensState.NOT_RUN
    assert model.requests == []
    assert ledger(tmp_path).attempts(KEY) == ()
    assert result.event is not ReviewEvent.APPROVE
    assert "POST failed" in render_draft(result, Redactor())


def test_a_keepalive_failure_after_a_clean_lens_cannot_approve(tmp_path):
    """The hold client fails its delete after the lens is clean."""
    result, _, _ = review(tmp_path, [READ_ALL, final()], hold_fail="DELETE")
    (lens,) = result.lenses
    assert lens.state is LensState.CLEAN
    assert result.runner.status is RunnerStatus.FAILED
    assert result.verdict is Verdict.APPROVE
    assert result.event is ReviewEvent.COMMENT
    assert not result.coverage_complete
    draft = render_draft(result, Redactor())
    assert "REVIEW INCOMPLETE" in draft
    assert "runner failed" in draft
    assert "DELETE failed" in draft


def test_the_ledger_records_each_attempt_with_its_head_and_body(tmp_path):
    review(tmp_path, [READ_DIFF, final(finding())])
    (attempt,) = ledger(tmp_path).attempts(KEY)
    assert attempt.number == 1
    assert attempt.outcome.attestation is Attestation.ATTESTED


def test_a_failed_attestation_is_retried_once_with_the_body_forced(tmp_path):
    result, model, _ = review(tmp_path, [READ_ALL, MISACK, READ_ALL, final()])
    (lens,) = result.lenses
    assert (lens.state, lens.attempts, lens.escalated) == (LensState.CLEAN, 2, False)
    retry = model.requests[2]
    assert "A previous attempt of this lens was not accepted" in retry.system
    assert BODY in retry.system
    assert len(retry.messages) == 1


def test_a_retry_that_fails_again_escalates_and_never_approves(tmp_path):
    result, _, _ = review(tmp_path, [READ_ALL, MISACK, READ_ALL, MISACK])
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
    script = [READ_ALL, final(finding(), wrong)] * 2
    result, _, _ = review(tmp_path, script)
    (lens,) = result.lenses
    assert (lens.state, lens.escalated) == (LensState.PARTIAL, True)
    assert [f.id for f in result.verified] == ["L1-F1"]
    assert [f.id for f in result.unverified] == ["L1-F2"]
    assert result.verdict is Verdict.APPROVE_WITH_CHANGES
    draft = render_draft(result, Redactor())
    assert "## Not verified (not reported as findings)" in draft


def test_a_configured_turn_cap_reaches_the_loop(tmp_path):
    from atlas_reviewer.coordinator import limits_for_lens

    limits = limits_for_lens({"ATLAS_MAX_CALLS": "4"}, max_turns="2")
    result, model, _ = review(tmp_path, [READ_ALL] * 10, limits=limits)
    (lens,) = result.lenses
    assert lens.outcome is not None
    assert lens.outcome.causes == {Cause.TURN_CAP}
    assert lens.outcome.limit_hit is not None
    assert lens.outcome.limit_hit.configured == "2"
    assert len(model.requests) == 2


def test_a_cut_short_lens_is_partial_and_not_retried(tmp_path):
    result, model, _ = review(
        tmp_path, [READ_ALL] * 10, limits=replace(LIMITS, max_turns=2)
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


def test_a_byok_refusal_is_not_retried_on_the_next_review(tmp_path):
    """The refusal leaves this review, and the attempt is a model error.
    A later review of the same head does not bill another call or approve."""

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
    assert first.event is not ReviewEvent.APPROVE
    assert first.runner is not None
    assert first.runner.status is RunnerStatus.FAILED
    assert "Runner reported" in render_draft(first, Redactor())
    (attempt,) = ledger(tmp_path).attempts(KEY)
    assert Cause.MODEL_ERROR in attempt.outcome.causes
    assert not attempt.outcome.retryable
    assert attempt.outcome.turns == 0
    assert attempt.outcome.tools == ()

    sprites = FakeSprites()
    again, model, _ = review(tmp_path, [READ_DIFF, final()], sprites=sprites)
    assert model.requests == []
    assert sprites.calls == []
    assert again.event is not ReviewEvent.APPROVE
    assert again.lenses[0].state is LensState.FAILED


def test_a_byok_refusal_after_a_tool_keeps_the_secret_and_the_progress(tmp_path):
    """A later turn refuses. The tool call already found a committed
    secret, and that secret, the turn and the tool stay in the record.
    Dropping the re-raise would leave the runner completed."""
    read = READ_DIFF.__class__(
        (READ_DIFF.calls[0].__class__("read_file", {"path": "config/keys.py"}),),
        READ_DIFF.cost_usd,
    )
    result, _, _ = review(
        tmp_path, [read, ByokRefusedError("refusing the review: byok")]
    )
    draft = render_draft(result, Redactor())
    assert "## Possible committed secrets (controller findings)" in draft
    assert TOKEN not in draft
    assert result.runner is not None
    assert result.runner.status is RunnerStatus.FAILED
    assert "Runner reported" in draft
    assert result.model_calls == 2
    (attempt,) = ledger(tmp_path).attempts(KEY)
    assert attempt.outcome.turns == 1
    assert [(t.tool, t.status) for t in attempt.outcome.tools] == [("read_file", "OK")]
    assert Cause.MODEL_ERROR in attempt.outcome.causes
    assert not attempt.outcome.retryable

    sprites = FakeSprites()
    again, model, _ = review(tmp_path, [READ_DIFF, final()], sprites=sprites)
    assert model.requests == []
    assert sprites.calls == []
    assert again.event is not ReviewEvent.APPROVE


def test_a_rerun_on_the_same_head_and_body_reuses_the_settled_lens(tmp_path):
    first, _, _ = review(tmp_path, [READ_ALL, final(finding())])
    sprites = FakeSprites()
    again, model, _ = review(tmp_path, [], sprites=sprites)
    assert sprites.calls == []
    assert model.requests == []
    assert again.lenses[0].outcome == first.lenses[0].outcome
    assert again.coverage_complete


def test_a_changed_body_is_a_new_lens_run(tmp_path):
    review(tmp_path, [READ_ALL, final()])
    new_body = BODY + "\nAlso check the docs.\n"
    new_digest = body_digest(new_body)
    result, model, _ = review(
        tmp_path, [READ_ALL, final(digest=new_digest)],
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
    result, model, _ = review(tmp_path, [READ_ALL, final()])
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


def test_a_clean_outcome_without_a_file_count_cannot_approve():
    result = synthesize([lens_result(AttemptOutcome(Attestation.ATTESTED))])
    assert not result.coverage_complete
    assert result.proposed_event is ReviewEvent.APPROVE
    assert result.event is ReviewEvent.COMMENT
    assert status(result)["coverage_complete"] is False
    headline = render_draft(result, Redactor()).splitlines()[2]
    assert "no recorded file coverage" in headline
    assert "no lens selected" not in headline


def test_unread_paths_block_approval_even_when_the_outcome_was_recorded_clean():
    outcome = AttemptOutcome(
        Attestation.ATTESTED,
        unread=("src/a.py", "auth/session.py"),
        changed_files=2,
    )
    result = synthesize([lens_result(outcome)])
    assert not result.coverage_complete
    assert result.proposed_event is ReviewEvent.APPROVE
    assert result.event is ReviewEvent.COMMENT
    headline = render_draft(result, Redactor()).splitlines()[2]
    assert "Every changed file's diff" not in headline
    assert "unread files" in headline


def test_unread_paths_are_named_ahead_of_a_missing_file_count():
    outcome = AttemptOutcome(
        Attestation.ATTESTED, unread=("auth/session.py",), changed_files=None
    )
    result = synthesize([lens_result(outcome)])
    headline = render_draft(result, Redactor()).splitlines()[2]
    assert "unread files" in headline
    assert "no recorded file coverage" not in headline
    assert "no lens selected" not in headline


@pytest.mark.parametrize(
    ("count", "rest"),
    [(20, 0), (21, 1)],
    ids=["exactly-twenty", "one-past-twenty"],
)
def test_the_unread_list_names_twenty_paths_and_counts_the_rest(count, rest):
    paths = tuple(f"src/f{i:02d}.py" for i in range(count))
    outcome = AttemptOutcome(
        Attestation.ATTESTED, unread=paths, changed_files=len(paths)
    )
    result = synthesize([lens_result(outcome)])
    headline = render_draft(result, Redactor()).splitlines()[2]
    assert f"{count} changed files not read in full" in headline
    assert "src/f00.py" in headline
    if rest:
        assert f", and {rest} more" in headline
        assert paths[-1] not in headline
    else:
        assert ", and" not in headline
        assert all(path in headline for path in paths)


def test_the_status_line_is_the_drafts_first_line_and_only_controller_values():
    result = synthesize(
        [lens_result(AttemptOutcome(Attestation.ATTESTED, changed_files=1))]
    )
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
        "changed_files": 1,
        "unreviewed_files": 0,
        "limit_stop": None,
    }


# ------------------------------------------------------ synthesis rules


def lens_result(outcome, **kw):
    return LensResult(LENS, 1, DIGEST, outcome, attempts=1, **kw)


def scoped(lens, paths, *, unread=(), attestation=Attestation.ATTESTED):
    causes = frozenset({Cause.FILES_UNREAD}) if unread else frozenset()
    outcome = AttemptOutcome(
        attestation, causes, unread=tuple(unread), changed_files=len(paths)
    )
    return LensResult(lens, 1, DIGEST, outcome, attempts=1, scope=frozenset(paths))


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
    return AttemptOutcome(
        Attestation.ATTESTED, findings=tuple(findings), changed_files=1
    )


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


def test_a_failed_runner_is_not_complete_coverage_even_when_the_lens_is_clean():
    from atlas_reviewer.domain import RunnerReport

    clean_lens = lens_result(AttemptOutcome(Attestation.ATTESTED, changed_files=1))
    failed = RunnerReport(
        RunnerStatus.FAILED, CleanupStatus.DESTROYED_VERIFIED, "r",
        "sprite task socket DELETE returned HTTP 500",
    )  # fmt: skip
    result = synthesize([clean_lens], runner=failed)
    assert result.verdict is Verdict.APPROVE
    assert result.event is ReviewEvent.COMMENT
    assert not result.coverage_complete
    draft = render_draft(result, Redactor())
    assert "HTTP 500" in draft
    assert "runner failed" in draft


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


OTHER = "sweeping-for-security"
OTHER_BODY = "# Sweeping for security\n\nLook for a secret in a changed file.\n"
_MARKER = re.compile(r"lens body begins: (\S+) \(sha256 ([0-9a-f]{64})\)")


def _acknowledge(request):
    match = _MARKER.search(request.system)
    assert match is not None
    return final(lens=match.group(1), digest=match.group(2))


def _lenses(
    tmp_path, names, model, *, pool=1, models=None, limits=None, sprites=None,
    clock=None, picker_spend=(0, Decimal(0)), trace=None, diff=None,
):  # fmt: skip
    from .test_keepalive import TaskServer, socket_path

    tasks = TaskServer(socket_path(tmp_path))
    tasks.start()
    sprites = sprites or LocalSprites()
    pending = list(models or [])
    lock = threading.Lock()

    def model_for():
        with lock:
            return pending.pop(0)

    try:
        result = review_lenses(
            EVENT,
            names,
            DIFF if diff is None else diff,
            trees(),
            library=StubLibrary({LENS: BODY, OTHER: OTHER_BODY}),
            model=model,
            limits=replace(LIMITS, pool_size=pool) if limits is None else limits,
            ledger=ledger(tmp_path),
            sprites=sprites,
            runner_ledger=MemoryLedger(),
            redactor=Redactor(),
            clock=clock or FakeClock(),
            nonce=lambda: "f00dfeedf00dfeed",
            bridge_root=str(tmp_path / "bridge"),
            task_socket=str(tasks.path),
            model_for=model_for if models is not None else None,
            picker_spend=picker_spend,
            trace=trace,
        )
    finally:
        tasks.close()
        assert tasks.tasks == {}, tasks.order
    return result, sprites


def test_unread_files_go_to_a_continuation_of_the_same_lens_and_can_approve(tmp_path):
    model = ScriptedLensModel(
        [
            tools(("diff_file", {"path": "calc.py"})),
            final(),
            tools(("diff_file", {"path": "config/keys.py"})),
            final(),
        ]
    )
    result, sprites = _lenses(tmp_path, [LENS], model)
    assert result.coverage_complete
    assert [lens.lens for lens in result.lenses] == [LENS, LENS]
    assert result.lenses[0].outcome.causes == {Cause.FILES_UNREAD}
    assert result.lenses[1].state is LensState.CLEAN
    created = [call[1] for call in sprites.calls if call[0] == "create"]
    assert len(created) == 2 and len(set(created)) == 2


def test_a_continuation_that_makes_no_progress_stops(tmp_path):
    result, sprites = _lenses(tmp_path, [LENS], ScriptedLensModel([final(), final()]))
    assert not result.coverage_complete
    assert len(result.lenses) == 2
    created = [call[1] for call in sprites.calls if call[0] == "create"]
    assert len(created) == 2


def test_a_file_one_lens_left_unread_is_not_covered_by_another_lens(tmp_path):
    model = ScriptedLensModel(
        [
            tools(("diff_file", {"path": "calc.py"})),
            final(),
            tools(("diff_file", {"path": "calc.py"})),
            tools(("diff_file", {"path": "config/keys.py"})),
            _acknowledge,
            final(text="not a contract reply"),
            final(text="not a contract reply"),
        ]
    )
    result, _ = _lenses(tmp_path, [LENS, OTHER], model)
    first, other = result.lenses[:2]
    assert first.outcome.unread == ("config/keys.py",)
    assert other.state is LensState.CLEAN
    assert not result.coverage_complete
    assert result.unreviewed_paths == ("config/keys.py",)


def test_a_file_unread_by_one_lens_is_covered_once_that_lens_reads_it():
    skipped = scoped(LENS, ["a.py", "b.py"], unread=["b.py"])
    other = scoped(OTHER, ["a.py", "b.py"])
    assert _still_unread([skipped, other]) == ("b.py",)
    rerun = scoped(LENS, ["b.py"])
    assert _still_unread([skipped, other, rerun]) == ()


def test_a_partial_with_no_cause_still_blocks_coverage():
    unexplained = scoped(LENS, ["a.py"], attestation=Attestation.UNACKNOWLEDGED)
    assert _blocks_coverage(unexplained)
    only_unread = scoped(LENS, ["a.py"], unread=["a.py"])
    assert not _blocks_coverage(only_unread)


def test_a_byok_refusal_stops_the_lenses_that_have_not_started(tmp_path):
    def refuse(request):
        raise ByokRefusedError("refusing the review: byok")

    sprites = LocalSprites()
    result, _ = _lenses(
        tmp_path, [LENS, OTHER], ScriptedLensModel([refuse]), sprites=sprites
    )
    created = [call[1] for call in sprites.calls if call[0] == "create"]
    assert len(created) == 1
    assert result.lenses[0].state is LensState.FAILED
    assert result.lenses[1].outcome is None
    assert result.lenses[1].reason == HALTED_REASON
    assert not result.coverage_complete


def test_a_failed_lens_blocks_approval_after_every_file_was_read(tmp_path):
    bad = final(text="nope")
    result, _ = _lenses(
        tmp_path,
        [LENS],
        ScriptedLensModel([READ_ALL, bad, bad]),
        limits=replace(LIMITS, retries=0),
    )
    assert not result.coverage_complete
    assert result.lenses[0].outcome is not None
    assert Cause.UNPARSED in result.lenses[0].outcome.causes


def test_two_lenses_run_together_under_different_runner_names(tmp_path):
    models = [
        ScriptedLensModel([READ_ALL, _acknowledge]),
        ScriptedLensModel([READ_ALL, _acknowledge]),
    ]
    result, sprites = _lenses(tmp_path, [LENS, OTHER], models[0], pool=2, models=models)
    assert result.coverage_complete
    assert {lens.lens for lens in result.lenses} == {LENS, OTHER}
    created = [call[1] for call in sprites.calls if call[0] == "create"]
    assert len(set(created)) == 2


def test_a_lens_assigned_too_narrow_a_scope_does_not_cover_the_changed_files():
    narrow = scoped(LENS, ["a.py"])
    review = replace(synthesize([narrow]), changed=frozenset({"a.py", "b.py"}))
    assert not review.coverage_complete
    assert review.unreviewed_paths == ("b.py",)
    assert replace(review, changed=frozenset({"a.py"})).coverage_complete


def test_an_attested_reply_that_skipped_files_and_failed_a_quote_still_blocks():
    outcome = AttemptOutcome(
        Attestation.ATTESTED,
        frozenset({Cause.FILES_UNREAD, Cause.QUOTES_FAILED}),
        unread=("a.py",),
        changed_files=1,
    )
    result = LensResult(LENS, 1, DIGEST, outcome, attempts=1, scope=frozenset({"a.py"}))
    assert _blocks_coverage(result)


def test_an_unverified_runner_delete_is_named_in_a_multi_lens_draft():
    from atlas_reviewer.coordinator import _combined_runner
    from atlas_reviewer.domain import RunnerReport

    orphan = RunnerReport(
        RunnerStatus.COMPLETED, CleanupStatus.DESTROY_UNVERIFIED, "cqa-rev-a", ""
    )
    gone = RunnerReport(
        RunnerStatus.COMPLETED, CleanupStatus.DESTROYED_VERIFIED, "cqa-rev-b", ""
    )
    assert _combined_runner((orphan, gone)) is orphan
    lens = scoped(LENS, ["a.py"])
    review = replace(
        synthesize([lens], runner=_combined_runner((orphan, gone))),
        runners=(orphan, gone),
    )
    draft = render_draft(review, Redactor())
    assert "cleanup destroy NOT verified" in draft
    assert "Runner delete NOT verified for `cqa-rev-a`" in draft
    assert "cqa-rev-b" not in draft
    assert "attestation: attested" in draft


def test_a_fatal_error_in_one_lens_stops_the_lenses_that_have_not_started(tmp_path):
    def broken(request):
        raise RuntimeError("an unexpected bug in the lens")

    sprites = LocalSprites()
    with pytest.raises(RuntimeError, match="unexpected bug"):
        _lenses(tmp_path, [LENS, OTHER], ScriptedLensModel([broken]), sprites=sprites)
    created = [call[1] for call in sprites.calls if call[0] == "create"]
    deleted = [call[1] for call in sprites.calls if call[0] == "delete"]
    assert len(created) == 1
    assert set(created) <= set(deleted)


def test_a_sibling_lens_failure_still_deletes_every_runner(tmp_path):
    started = threading.Event()

    def broken(request):
        assert started.wait(5)
        raise RuntimeError("an unexpected bug in the lens")

    def first_turn(request):
        started.set()
        return READ_ALL

    models = [
        ScriptedLensModel([broken]),
        ScriptedLensModel([first_turn, _acknowledge]),
    ]
    sprites = LocalSprites()
    with pytest.raises(RuntimeError, match="unexpected bug"):
        _lenses(tmp_path, [LENS, OTHER], models[0], pool=2, models=models,
                sprites=sprites)  # fmt: skip
    created = [call[1] for call in sprites.calls if call[0] == "create"]
    deleted = [call[1] for call in sprites.calls if call[0] == "delete"]
    assert len(set(created)) == 2
    assert set(created) <= set(deleted)


def _clean_pair():
    return [
        ScriptedLensModel([READ_ALL, _acknowledge]),
        ScriptedLensModel([READ_ALL, _acknowledge]),
    ]


def test_a_picked_lens_that_did_not_run_blocks_approval(tmp_path):
    models = _clean_pair()
    result, _ = _lenses(tmp_path, [LENS, OTHER], models[0], models=models)
    assert result.coverage_complete and result.event is ReviewEvent.APPROVE
    missing = replace(result, not_picked=(("made-up-lens", "no body.md"),))
    assert not missing.coverage_complete
    assert missing.event is ReviewEvent.COMMENT
    assert "a picked lens did not run" in render_draft(missing, Redactor())


def test_a_lens_queued_past_the_review_deadline_does_not_start(tmp_path, monkeypatch):
    from atlas_reviewer import coordinator

    clock = FakeClock()
    real = coordinator.run_bridge

    def then_late(*args, **kwargs):
        report = real(*args, **kwargs)
        clock.advance(LIMITS.review_wall_s + 1)
        return report

    monkeypatch.setattr(coordinator, "run_bridge", then_late)
    models = _clean_pair()
    result, sprites = _lenses(
        tmp_path, [LENS, OTHER], models[0], models=models, clock=clock
    )
    assert [(r.lens, r.reason) for r in result.lenses if r.lens == OTHER] == [
        (OTHER, LATE_REASON)
    ]
    assert models[1].requests == []
    assert len([c for c in sprites.calls if c[0] == "create"]) == 1
    assert not result.coverage_complete


def test_a_queued_lens_runner_gets_only_the_review_time_left(tmp_path, monkeypatch):
    from atlas_reviewer import coordinator

    given = []
    real = coordinator.run_bridge

    def spy(*args, deadline_s, **kwargs):
        given.append(deadline_s)
        return real(*args, deadline_s=deadline_s, **kwargs)

    monkeypatch.setattr(coordinator, "run_bridge", spy)
    clock = FakeClock()

    def slow(request):
        clock.advance(100)
        return READ_ALL

    models = [
        ScriptedLensModel([slow, _acknowledge]),
        ScriptedLensModel([READ_ALL, _acknowledge]),
    ]
    _lenses(tmp_path, [LENS, OTHER], models[0], models=models, clock=clock)
    assert given[:2] == [LIMITS.review_wall_s, LIMITS.review_wall_s - 100]


def test_the_picker_calls_count_toward_the_review_spend(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    models = _clean_pair()
    base, _ = _lenses(tmp_path / "a", [LENS, OTHER], models[0], models=models)
    models = _clean_pair()
    picked, _ = _lenses(
        tmp_path / "b", [LENS, OTHER], models[0], models=models,
        picker_spend=(1, Decimal("0.25")),
    )  # fmt: skip
    assert picked.model_calls == base.model_calls + 1
    assert Decimal(picked.committed_usd) == Decimal(base.committed_usd) + Decimal(
        "0.25"
    )


def test_a_picker_that_used_every_call_leaves_none_for_the_lenses(tmp_path):
    model = ScriptedLensModel([READ_ALL, _acknowledge])
    result, _ = _lenses(
        tmp_path, [LENS], model, picker_spend=(LIMITS.max_calls, Decimal(0))
    )
    assert model.requests == []
    assert result.model_calls == LIMITS.max_calls
    assert not result.coverage_complete


def test_the_continuation_rounds_stop_at_max_continuations(tmp_path, monkeypatch):
    monkeypatch.setattr("atlas_reviewer.coordinator.MAX_CONTINUATIONS", 0)
    model = ScriptedLensModel(
        [
            tools(("diff_file", {"path": "calc.py"})),
            final(),
            tools(("diff_file", {"path": "config/keys.py"})),
            final(),
        ]
    )
    result, _ = _lenses(tmp_path, [LENS], model)
    assert [lens.lens for lens in result.lenses] == [LENS]
    assert not result.coverage_complete


def test_the_draft_names_the_picker_fallback_and_the_names_it_did_not_run():
    review = replace(
        synthesize([scoped(LENS, ["a.py"])]),
        selection_note="Lens selection: the lens picker gave no usable lens list",
        not_picked=(("made-up-lens", "no body.md in the bundle"),),
    )
    draft = render_draft(review, Redactor())
    assert "## Lens selection" in draft
    assert "gave no usable lens list" in draft
    assert '- NOT RUN: `"made-up-lens"` (no body.md in the bundle)' in draft
