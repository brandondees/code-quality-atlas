# SPDX-License-Identifier: MIT
"""Config slice S7 (D88): the #734 execution-tool allow-list's proposals
and the in-run operator approval. The parse (`repo_config`'s
`review_test_commands:` line, read from the default branch), the
run-scoped gate (`approval.RunApprovals`), the bridge's `run_tests`
`command` surface -- run for real through `LocalSprites` where the
machine can run them -- and the lens loop's ledger over the results.
Nothing here contacts GitHub, a live Sprite or a model: the approval
channel is a scripted test double, and the production default
(`NeverApproved`) is exercised as itself."""

import sys
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from atlas_reviewer.approval import (
    MAX_APPROVAL_WAIT_S,
    ApprovalOutcome,
    CommandProposal,
    NeverApproved,
    RunApprovals,
)
from atlas_reviewer.attestation import Cause
from atlas_reviewer.bridge import Status, ToolLimits, render, run_test_script
from atlas_reviewer.bridge_args import MAX_COMMAND_CHARS, RejectedError, validate
from atlas_reviewer.bridge_staging import SourceTrees, Staged
from atlas_reviewer.domain import PrEvent, RunnerStatus
from atlas_reviewer.fakes import ScriptedLensModel
from atlas_reviewer.interpreter import TrustedPython
from atlas_reviewer.lens_loop import LensJob, Spend, finding_contract, run_attempt
from atlas_reviewer.ports import BoundaryError, NotFoundError
from atlas_reviewer.repo_config import parse_run_proposals, read_repo_config

from .agentic import (
    BODY,
    CHANGED,
    DIFF,
    DIGEST,
    LENS,
    LIMITS,
    TOP,
    final,
    finding,
    tools,
)
from .helpers import HEAD, OLD, FakeClock, source_tarball

EVENT = PrEvent("example-org/example-app", 42, HEAD)
from .test_bridge_runs import bridge_run
from .test_lens_loop import (
    CALC_ROUND,
    EXEC_TEST,
    EXEC_TOKEN_LINE,
    NONCE,
    read_sources,
)

RUN_SH = b"printf 'declared-command-marker\\n'\n"
CALC = "def total(xs):\n    if not xs:\n        return 0\n    return sum(xs)\n"
TEST_TOTAL = (
    "from calc import total\n\ndef test_two_values():\n    assert total([1, 2]) == 3\n"
)
SUITE = {
    "calc.py": CALC.encode(),
    "test_calc.py": TEST_TOTAL.encode(),
    "run.sh": RUN_SH,
}
LINE = "review_test_commands: {value}"


def trees(source):
    return SourceTrees(source_tarball(source), source_tarball(source), OLD, HEAD)


def proposals(text: str) -> tuple[CommandProposal, ...]:
    return parse_run_proposals(LINE.format(value=text)).proposals


@dataclass
class ScriptedChannel:
    """A test double for the operator-approval channel: one recorded
    request per call, one popped answer, an optional error to raise, and
    an optional side effect to run before answering (the shape the
    wall-ran-out-while-waiting test needs)."""

    outcomes: list[ApprovalOutcome] = field(default_factory=list)
    error: Exception | None = None
    on_request: object = None
    requests: list[tuple[str, float]] = field(default_factory=list)

    def request(self, proposal: CommandProposal, deadline: float) -> ApprovalOutcome:
        self.requests.append((proposal.name, deadline))
        if self.on_request is not None:
            self.on_request()
        if self.error is not None:
            raise self.error
        if self.outcomes:
            return self.outcomes.pop(0)
        return ApprovalOutcome.NO_ANSWER


def gate(text, channel, clock=None, wall_left=None, budget_ok=None):
    """The gate over one proposal line, with the defaults a healthy run
    has: room on the wall and room under the dollar cap."""
    clock = clock or FakeClock()
    return (
        RunApprovals(
            {p.name: p for p in proposals(text)},
            channel,
            clock,
            wall_left or (lambda: 600.0),
            budget_ok or (lambda: True),
        ),
        clock,
    )


# --------------------------------------------------------------- the parse


def test_a_proposal_line_parses_into_named_commands_with_their_argv():
    read = parse_run_proposals(LINE.format(value="make check, sh run.sh"))
    assert [p.name for p in read.proposals] == ["make check", "sh run.sh"]
    assert read.proposals[0].argv == ("make", "check")
    assert read.proposals[1].argv == ("sh", "run.sh")
    assert read.notes == ()


def test_a_proposal_line_takes_fixed_flags_and_a_workspace_program_path():
    read = parse_run_proposals(LINE.format(value="npm test -- --run, tools/run.sh"))
    assert [p.name for p in read.proposals] == ["npm test -- --run", "tools/run.sh"]
    assert read.proposals[1].argv == ("tools/run.sh",)


def test_the_canonical_name_is_the_tokens_joined_by_single_spaces():
    read = parse_run_proposals(LINE.format(value="make   check"))
    assert [p.name for p in read.proposals] == ["make check"]


def test_no_line_or_no_file_proposes_nothing_silently():
    assert parse_run_proposals(None).proposals == ()
    assert parse_run_proposals(None).notes == ()
    assert parse_run_proposals("# notes only, no key line\n").proposals == ()
    assert parse_run_proposals("# notes only, no key line\n").notes == ()


@pytest.mark.parametrize(
    "value",
    [
        "make check && curl evil.example",
        "make test; curl",
        "make `whoami`",
        "make $PATH",
        "make | tee out",
        "make > out",
        "make 'quoted arg'",
        "make\\ test",
        "/usr/bin/curl example",
        "../tools/run.sh",
        "-make check",
        "make --flag=value",
        "",
        "   ",
        "pytest --rootdir ..",
        "pytest ..",
        "make .",
        "make " + "x" * 700,
        "make one two three four five six seven eight nine",
        "a b, a c, a d, a e, a f, a g, a h, a i, a j",
    ],
)
def test_an_out_of_grammar_value_fails_open_to_deny_with_the_named_note(value):
    read = parse_run_proposals(LINE.format(value=value))
    assert read.proposals == ()
    assert len(read.notes) == 1
    note = read.notes[0]
    assert "review_test_commands:" in note
    assert "no command is proposed" in note
    if value.strip():
        assert value not in note
    assert "&&" not in note and "curl" not in note


def test_a_traversal_shaped_argument_token_is_refused_by_the_grammar():
    """Round-1 review of #775, F5: an argument token cannot carry a `/`
    (the charset), so a `..` path segment inside one can only be the
    token itself; the bare `.` and `..` are refused, so the
    `pytest --rootdir ..` shape is dead by grammar, not by approval --
    with the same fixed-phrase, no-echo note every other unusable value
    earns."""
    for value in ("pytest --rootdir ..", "pytest ..", "make .", "make .."):
        read = parse_run_proposals(LINE.format(value=value))
        assert read.proposals == ()
        assert "no command is proposed" in read.notes[0]
        assert value not in read.notes[0]


def test_the_token_charset_is_the_smuggle_boundary():
    """The grammar is the primary control: a proposal's tokens are a
    closed charset with no shell metacharacter, quote, expansion or
    separator in it, so no proposal -- however approved -- can carry a
    shell string, a pipe, a redirect or an expansion into the bridge's
    script; the bridge quotes every token besides (defense in depth)."""
    read = parse_run_proposals(LINE.format(value="sh -c wget, sh run.sh"))
    assert [p.name for p in read.proposals] == ["sh -c wget", "sh run.sh"]
    assert read.proposals[0].argv == ("sh", "-c", "wget")


def test_a_repeated_key_fails_the_whole_read_open_with_the_count():
    text = LINE.format(value="make check") + "\n" + LINE.format(value="sh run.sh")
    read = parse_run_proposals(text)
    assert read.proposals == ()
    assert len(read.notes) == 1
    assert "2 review_test_commands: lines" in read.notes[0]


def test_a_valid_line_and_an_unusable_one_leave_nothing_proposed():
    text = LINE.format(value="make check") + "\n" + LINE.format(value="make; rm")
    read = parse_run_proposals(text)
    assert read.proposals == ()
    assert "no command is proposed" in read.notes[0]


def test_a_duplicated_command_makes_the_line_unusable():
    read = parse_run_proposals(LINE.format(value="make check, make check"))
    assert read.proposals == ()
    assert "no command is proposed" in read.notes[0]


def test_a_proposal_over_the_command_name_bound_is_unusable():
    value = "make " + "a" * (MAX_COMMAND_CHARS + 1)
    read = parse_run_proposals(LINE.format(value=value))
    assert read.proposals == ()
    assert value not in read.notes[0]


def test_the_merge_base_read_does_not_call_the_proposals_key_unsupported():
    tarball = source_tarball(
        {"REVIEW.md": b"# policy\n\nreview_test_commands: make check\n"}
    )
    config = read_repo_config(tarball)
    assert config.unsupported_notes == ()


# ------------------------------------------------------------- the gate


def test_an_explicit_approval_grants_and_then_never_re_requests():
    channel = ScriptedChannel(outcomes=[ApprovalOutcome.APPROVED])
    approvals, clock = gate("make check, sh run.sh", channel)
    approved, reason = approvals.admit("make check")
    assert approved and reason == ""
    # The wait is bounded by the shorter of the wall that is left (600s
    # here) and the max wait.
    assert channel.requests == [("make check", clock.monotonic() + MAX_APPROVAL_WAIT_S)]
    # The approved addition lives in run-scoped state: a later call in
    # the same run does not ask again.
    approved_again, _ = approvals.admit("make check")
    assert approved_again
    assert len(channel.requests) == 1
    assert approvals.approved_count() == 1


def test_the_wait_is_bounded_by_the_wall_that_is_left():
    channel = ScriptedChannel()
    approvals, clock = gate("make check", channel, wall_left=lambda: 5.0)
    approvals.admit("make check")
    name, deadline = channel.requests[0]
    assert name == "make check"
    assert deadline - clock.monotonic() == pytest.approx(5.0)


def test_a_denial_denies_sticky_and_names_the_counts():
    channel = ScriptedChannel(outcomes=[ApprovalOutcome.DENIED])
    approvals, _ = gate("make check, sh run.sh", channel)
    approved, reason = approvals.admit("sh run.sh")
    assert not approved
    assert "the operator denied the proposed test command" in reason
    assert "holds 2 proposed and 0 approved" in reason
    assert "sh run.sh" not in reason
    # Sticky: a later call in the same run is refused without re-asking.
    approved_again, reason_again = approvals.admit("sh run.sh")
    assert not approved_again
    assert reason_again == reason
    assert len(channel.requests) == 1


def test_a_no_answer_denies_fail_closed():
    approvals, _ = gate("make check", ScriptedChannel())
    approved, reason = approvals.admit("make check")
    assert not approved
    assert "no operator approval arrived within the run's remaining wall" in reason
    assert "holds 1 proposed and 0 approved" in reason


def test_a_channel_error_denies_fail_closed():
    approvals, _ = gate("make check", ScriptedChannel(error=RuntimeError("boom")))
    approved, reason = approvals.admit("make check")
    assert not approved
    assert "no operator approval arrived" in reason
    assert "boom" not in reason


def test_a_spent_wall_denies_without_asking_the_channel():
    channel = ScriptedChannel()
    approvals, _ = gate("make check", channel, wall_left=lambda: 0.0)
    approved, reason = approvals.admit("make check")
    assert not approved
    assert "the run's wall clock has no room left" in reason
    assert channel.requests == []


def test_a_spent_dollar_bound_denies_without_asking_the_channel():
    channel = ScriptedChannel()
    approvals, _ = gate("make check", channel, budget_ok=lambda: False)
    approved, reason = approvals.admit("make check")
    assert not approved
    assert "the run's dollar limit is spent" in reason
    assert channel.requests == []


def test_the_wall_running_out_while_the_request_waits_denies_an_answer():
    class Wall:
        def __init__(self):
            self.left = 100.0

        def __call__(self):
            return self.left

    wall = Wall()
    channel = ScriptedChannel(
        outcomes=[ApprovalOutcome.APPROVED],
        on_request=lambda: setattr(wall, "left", 0.0),
    )
    approvals, _ = gate("make check", channel, wall_left=wall)
    approved, reason = approvals.admit("make check")
    assert not approved
    assert "the run's wall clock ran out while the approval waited" in reason
    assert approvals.approved_count() == 0


def test_the_dollar_limit_reached_while_the_request_waits_denies_an_answer():
    state = {"ok": True}

    def on_request():
        state["ok"] = False

    channel = ScriptedChannel(
        outcomes=[ApprovalOutcome.APPROVED], on_request=on_request
    )
    approvals, _ = gate("make check", channel, budget_ok=lambda: state["ok"])
    approved, reason = approvals.admit("make check")
    assert not approved
    assert "the run's dollar limit was reached while the approval waited" in reason


def test_the_run_scoped_state_dies_with_the_run():
    channel = ScriptedChannel(outcomes=[ApprovalOutcome.APPROVED])
    approvals, _ = gate("make check", channel)
    approvals.admit("make check")
    # A second run's gate -- the same proposals, the same channel shape --
    # starts empty: an approval is never carried across runs.
    channel2 = ScriptedChannel(outcomes=[ApprovalOutcome.APPROVED])
    approvals2, _ = gate("make check", channel2)
    assert approvals2.approved_count() == 0
    approved, _ = approvals2.admit("make check")
    assert approved
    assert len(channel2.requests) == 1


def test_a_never_approving_channel_is_the_production_default():
    approvals, _ = gate("make check", NeverApproved())
    approved, reason = approvals.admit("make check")
    assert not approved
    assert "no operator approval arrived" in reason
    assert "holds 1 proposed and 0 approved" in reason


@dataclass
class BlockingChannel:
    """A channel that never returns: the request parks on an event that
    is never set, so the gate's own bound is the only thing that can end
    the wait. The test must deny without hanging."""

    requests: list = field(default_factory=list)
    _never: threading.Event = field(default_factory=threading.Event)

    def request(self, proposal: CommandProposal, deadline: float) -> ApprovalOutcome:
        self.requests.append((proposal.name, deadline))
        self._never.wait()
        return ApprovalOutcome.APPROVED


@dataclass
class SlowChannel:
    """A channel that answers `APPROVED` only after `delay` real seconds
    -- past the gate's bound when the bound is shorter -- the shape the
    any-later-answer-is-ignored rule pins."""

    delay: float
    requests: list = field(default_factory=list)

    def request(self, proposal: CommandProposal, deadline: float) -> ApprovalOutcome:
        self.requests.append((proposal.name, deadline))
        time.sleep(self.delay)
        return ApprovalOutcome.APPROVED


def test_a_channel_that_never_returns_denies_within_the_bound():
    channel = BlockingChannel()
    approvals, _ = gate("make check", channel, wall_left=lambda: 0.2)
    start = time.monotonic()
    approved, reason = approvals.admit("make check")
    elapsed = time.monotonic() - start
    assert not approved
    assert "no operator approval arrived within the run's remaining wall" in reason
    assert elapsed < 10.0, "the gate's bound must end the wait, not the channel"
    assert channel.requests == [("make check", 0.0 + 0.2)]
    # Sticky: the still-outstanding request is never re-asked.
    approved_again, reason_again = approvals.admit("make check")
    assert not approved_again
    assert reason_again == reason
    assert len(channel.requests) == 1


def test_an_answer_that_arrives_after_the_bound_is_ignored():
    channel = SlowChannel(0.5)
    approvals, _ = gate("make check", channel, wall_left=lambda: 0.2)
    start = time.monotonic()
    approved, _reason = approvals.admit("make check")
    elapsed = time.monotonic() - start
    assert not approved
    assert elapsed < 5.0, "the gate's bound must end the wait, not the channel"
    time.sleep(0.6)  # the channel's answer lands now, after the bound
    approved_again, reason_again = approvals.admit("make check")
    assert not approved_again
    assert "no operator approval arrived" in reason_again
    assert approvals.approved_count() == 0
    assert len(channel.requests) == 1


def test_a_channel_that_answers_within_the_bound_still_grants():
    channel = SlowChannel(0.05)
    approvals, _ = gate("make check", channel, wall_left=lambda: 0.2)
    approved, reason = approvals.admit("make check")
    assert approved and reason == ""
    assert approvals.approved_count() == 1


def test_a_non_enum_channel_answer_denies_fail_closed():
    """The channel port's contract is the enum's three values; anything
    else -- a truthy bare string included -- is not an explicit approval
    and denies sticky, whatever a refactor of the comparison does."""

    class BareString:
        def request(
            self, proposal: CommandProposal, deadline: float
        ) -> ApprovalOutcome:
            return "approved"  # type: ignore[return-value]  (the pin's shape)

    approvals, _ = gate("make check", BareString())
    approved, reason = approvals.admit("make check")
    assert not approved
    assert "no operator approval arrived" in reason
    approved_again, _ = approvals.admit("make check")
    assert not approved_again


# ------------------------------------------------------------- the bridge


def test_a_command_naming_no_proposal_is_rejected_without_an_echo(tmp_path):
    approvals, _ = gate("make check, sh run.sh", ScriptedChannel())
    results = []

    def body(bridge):
        results.extend(
            (
                bridge.call("run_tests", {"command": "make  check"}),
                bridge.call("run_tests", {"command": "totally invented"}),
            )
        )
        return "done"

    bridge_run(tmp_path, body, approvals=approvals)
    for result in results:
        assert result.status is Status.REJECTED
        assert "unknown-command" in result.error.text
        assert result.args == ""


def test_a_command_with_no_proposals_configured_is_rejected(tmp_path):
    results = []

    def body(bridge):
        results.append(bridge.call("run_tests", {"command": "make check"}))
        return "done"

    bridge_run(tmp_path, body)
    result = results[0]
    assert result.status is Status.REJECTED
    assert "proposes no test commands" in result.error.text


def test_a_command_cannot_combine_with_a_test_selector():
    with pytest.raises(RejectedError, match="conflicting-argument"):
        validate(
            "run_tests",
            {"path": "test_calc.py", "command": "make check"},
            frozenset(),
        )


def test_mutate_never_takes_a_command():
    with pytest.raises(RejectedError, match="unknown-argument"):
        validate(
            "mutate",
            {
                "path": "calc.py",
                "line": 2,
                "operator": "remove-guard",
                "command": "make",
            },
            frozenset(),
        )


def test_a_command_value_over_the_bound_is_rejected():
    with pytest.raises(RejectedError, match=f"over {MAX_COMMAND_CHARS} characters"):
        validate("run_tests", {"command": "x" * (MAX_COMMAND_CHARS + 1)}, frozenset())


def test_an_unapproved_proposed_command_is_a_named_unapproved_gap(tmp_path):
    approvals, _ = gate("sh run.sh", NeverApproved())
    results = []

    def body(bridge):
        results.append(bridge.call("run_tests", {"command": "sh run.sh"}))
        return "done"

    bridge_run(tmp_path, body, source=trees(SUITE), approvals=approvals)
    result = results[0]
    assert result.status is Status.UNAVAILABLE
    assert result.error is not None
    assert "unapproved-command:" in result.error.text
    assert "holds 1 proposed and 0 approved" in result.error.text
    # The rejected value is never echoed.
    assert "run.sh" not in result.error.text
    assert result.content.text == ""


def test_an_approved_command_runs_the_proposals_own_argv(tmp_path):
    channel = ScriptedChannel(outcomes=[ApprovalOutcome.APPROVED])
    approvals, _ = gate("sh run.sh", channel)
    results = []

    def body(bridge):
        results.extend(
            (
                bridge.call("run_tests", {"command": "sh run.sh"}),
                bridge.call("run_tests", {"command": "sh run.sh"}),
            )
        )
        return "done"

    bridge_run(tmp_path, body, source=trees(SUITE), approvals=approvals)
    first, second = results
    assert first.status is Status.OK
    assert "declared-command-marker" in first.content.text
    assert first.approved == "sh run.sh"
    # The approval answered one request; the second call ran on the
    # run-scoped approval, not a second one.
    assert len(channel.requests) == 1
    assert second.status is Status.OK
    assert "operator approval for this run" in render(second)
    # A declared command carries no pytest summary to parse.
    assert first.runs[0].summary is None


def test_an_approved_command_runs_without_a_pytest_interpreter(tmp_path):
    channel = ScriptedChannel(outcomes=[ApprovalOutcome.APPROVED])
    approvals, _ = gate("sh run.sh", channel)
    results = []

    def body(bridge):
        results.append(bridge.call("run_tests", {"command": "sh run.sh"}))
        return "done"

    bridge_run(
        tmp_path,
        body,
        source=trees(SUITE),
        approvals=approvals,
        pytest_candidates=(),
    )
    result = results[0]
    assert result.status is Status.OK
    assert "declared-command-marker" in result.content.text


def test_an_unapproved_command_is_refused_before_the_interpreter_matters(tmp_path):
    approvals, _ = gate("sh run.sh", NeverApproved())
    results = []

    def body(bridge):
        results.append(bridge.call("run_tests", {"command": "sh run.sh"}))
        return "done"

    bridge_run(
        tmp_path,
        body,
        source=trees(SUITE),
        approvals=approvals,
        pytest_candidates=(),
    )
    result = results[0]
    assert result.status is Status.UNAVAILABLE
    assert "unapproved-command:" in result.error.text


def test_the_built_in_entry_still_runs_when_a_proposal_is_configured(tmp_path):
    approvals, _ = gate("sh run.sh", NeverApproved())
    results = []

    def body(bridge):
        results.append(bridge.call("run_tests", {}))
        return "done"

    bridge_run(
        tmp_path,
        body,
        source=trees(SUITE),
        approvals=approvals,
        pytest_candidates=(sys.executable,),
    )
    result = results[0]
    assert result.status is Status.OK
    assert "1 passed" in result.content.text
    assert result.approved == ""


def _fake_staged(tmp_path, pytest=None):
    return Staged(
        str(tmp_path / "root"),
        "/usr/bin/git",
        {"BASE": "b" * 40, "HEAD": "c" * 40, "DEFAULT": "d" * 40},
        pytest=pytest,
        head_sha=HEAD,
    )


def test_the_approved_command_script_quotes_the_proposals_tokens(tmp_path):
    call = validate("run_tests", {"command": "sh run.sh"}, frozenset())
    script = run_test_script(
        _fake_staged(tmp_path),
        call,
        ToolLimits(16 * 1024, 60),
        argv="'sh' 'run.sh'",
    )
    assert "exec timeout -k 2 60 'sh' 'run.sh' ) > out 2> err" in script
    assert "-m pytest" not in script
    assert "export PYTHONDONTWRITEBYTECODE=1" in script
    assert "ulimit -f" in script


def test_the_built_in_script_still_names_the_pytest_argv(tmp_path):
    call = validate("run_tests", {}, frozenset())
    staged = _fake_staged(tmp_path, pytest=TrustedPython("/usr/bin/python3", "3.12.3"))
    script = run_test_script(staged, call, ToolLimits(16 * 1024, 60))
    assert "-m pytest -q --color=no -p no:cacheprovider" in script


# ------------------------------------------------- the lens loop's ledger


def _attempt(tmp_path, script, approvals, head_extra):
    head = {
        "calc.py": CALC_ROUND,
        "config/keys.py": EXEC_TOKEN_LINE,
        "test_calc.py": EXEC_TEST,
        **head_extra,
    }
    head_tarball = source_tarball(head, TOP)
    the_job = LensJob(
        LENS,
        BODY,
        DIGEST,
        finding_contract(),
        "Review target (from the operator): example-org/example-app#7",
        CHANGED,
        read_sources(head_tarball, DIFF, CHANGED),
        NONCE,
        head_tree=head_tarball,
        diff=DIFF,
    )
    source = SourceTrees(
        source_tarball({"calc.py": b"def total(xs):\n    return sum(xs)\n"}, TOP),
        head_tarball,
        OLD,
        HEAD,
    )
    clock = FakeClock()
    spend = Spend(LIMITS.resolve())
    out = {}

    def body(bridge):
        started = clock.monotonic()
        out["outcome"] = run_attempt(
            the_job,
            bridge,
            ScriptedLensModel(list(script)),
            spend,
            clock,
            review_deadline=started + 600,
            review_started=started,
        )
        return "done"

    report, _sprites, _telemetry = bridge_run(
        tmp_path,
        body,
        source=source,
        approvals=approvals,
        pytest_candidates=(sys.executable,),
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    return out["outcome"]


def test_an_unapproved_command_is_a_tool_gap_the_review_holds(tmp_path):
    approvals, _ = gate("sh run.sh", NeverApproved())
    outcome = _attempt(
        tmp_path,
        [tools(("run_tests", {"command": "sh run.sh"})), final(finding())],
        approvals,
        {"run.sh": RUN_SH},
    )
    assert Cause.TOOL_GAP in outcome.causes
    assert outcome.test_runs == 0


def test_an_approved_command_counts_as_an_executed_run(tmp_path):
    channel = ScriptedChannel(outcomes=[ApprovalOutcome.APPROVED])
    approvals, _ = gate("python3 --version", channel)
    outcome = _attempt(
        tmp_path,
        [tools(("run_tests", {"command": "python3 --version"})), final(finding())],
        approvals,
        {},
    )
    assert Cause.TOOL_GAP not in outcome.causes
    assert outcome.test_runs == 1


# ------------------------------------------------------- the spend wiring


def test_the_gate_reads_the_run_s_dollar_bound_from_the_glue():
    """The budget_ok the service glue wires is the review's own spend: a
    review with room under its reservation cap asks, and one at the cap
    denies without asking."""

    class Limits:
        reservation_usd = Decimal("10.00")

    class Spend:
        committed_usd = Decimal("9.00")
        limits = Limits()

    spend = Spend()
    channel = ScriptedChannel()
    approvals, _ = gate(
        "make check",
        channel,
        budget_ok=lambda: spend.committed_usd < spend.limits.reservation_usd,
    )
    approved, _ = approvals.admit("make check")
    assert not approved
    assert len(channel.requests) == 1
    spend.committed_usd = Decimal("10.00")
    approvals2, _ = gate(
        "sh run.sh",
        channel,
        budget_ok=lambda: spend.committed_usd < spend.limits.reservation_usd,
    )
    approved2, reason2 = approvals2.admit("sh run.sh")
    assert not approved2
    assert "the run's dollar limit is spent" in reason2
    assert len(channel.requests) == 1


# ------------------------------------------------------- the cli glue


@dataclass
class FakeFetchGitHub:
    """The shape `_run_proposals` needs: one repository answer, one file
    answer or error."""

    repository: object = None
    repository_error: Exception | None = None
    file: bytes | None = None
    file_error: Exception | None = None
    calls: list = field(default_factory=list)

    def get_repository(self, repo):
        self.calls.append(("get_repository", repo))
        if self.repository_error is not None:
            raise self.repository_error
        return self.repository

    def get_file(self, repo, ref, path, max_bytes):
        self.calls.append(("get_file", repo, ref, path))
        if self.file_error is not None:
            raise self.file_error
        if self.file is None:
            raise NotFoundError("404")
        return self.file


def test_the_cli_glue_reads_the_default_branch_file():
    from atlas_reviewer.cli import _run_proposals

    github = FakeFetchGitHub(
        repository={"default_branch": "main"},
        file=b"# policy\n\nreview_test_commands: make check\n",
    )
    got, notes = _run_proposals(github, EVENT)
    assert [p.name for p in got] == ["make check"]
    assert notes == ()
    assert github.calls == [
        ("get_repository", EVENT.repo),
        ("get_file", EVENT.repo, "main", "REVIEW.md"),
    ]


def test_no_default_branch_file_is_the_silent_unconfigured_repo():
    from atlas_reviewer.cli import _run_proposals

    github = FakeFetchGitHub(repository={"default_branch": "main"})
    assert _run_proposals(github, EVENT) == ((), ())


def test_a_repo_level_lookup_failure_is_a_named_gap_with_nothing_proposed():
    from atlas_reviewer.cli import _PROPOSAL_LOOKUP_NOTE, _run_proposals

    github = FakeFetchGitHub(repository_error=NotFoundError("404"))
    got, notes = _run_proposals(github, EVENT)
    assert got == () and notes == (_PROPOSAL_LOOKUP_NOTE,)
    github2 = FakeFetchGitHub(repository={"default_branch": ""})
    got2, notes2 = _run_proposals(github2, EVENT)
    assert got2 == () and notes2 == (_PROPOSAL_LOOKUP_NOTE,)


def test_a_failed_fetch_or_an_over_bound_file_names_its_own_gap():
    from atlas_reviewer.cli import (
        _PROPOSAL_FETCH_NOTE,
        _PROPOSAL_OVERBOUND_NOTE,
        _run_proposals,
    )
    from atlas_reviewer.ports import ResponseTooLargeError

    github = FakeFetchGitHub(
        repository={"default_branch": "main"},
        file_error=BoundaryError("boom"),
    )
    got, notes = _run_proposals(github, EVENT)
    assert got == () and notes == (_PROPOSAL_FETCH_NOTE,)
    github2 = FakeFetchGitHub(
        repository={"default_branch": "main"},
        file_error=ResponseTooLargeError("over"),
    )
    got2, notes2 = _run_proposals(github2, EVENT)
    assert got2 == () and notes2 == (_PROPOSAL_OVERBOUND_NOTE,)


def test_the_cli_glue_never_carries_a_failed_reads_error_text():
    from atlas_reviewer.cli import _run_proposals

    github = FakeFetchGitHub(
        repository={"default_branch": "main"},
        file_error=BoundaryError("secret-value leaked into the error"),
    )
    _got, notes = _run_proposals(github, EVENT)
    assert "secret-value" not in notes[0]


# ------------------------------------------------- the coordinator plumb


def test_the_coordinator_builds_the_gate_from_the_glue(tmp_path):
    """The proposals and the channel ride `review_lens` into the lens
    run's gate: an approved proposed command executes, the channel is
    asked once, and the run counts."""
    from .test_coordinator import review

    channel = ScriptedChannel(outcomes=[ApprovalOutcome.APPROVED])
    result, _model, _sprites = review(
        tmp_path,
        [tools(("run_tests", {"command": "python3 --version"})), final(finding())],
        run_proposals=proposals("python3 --version"),
        approval_channel=channel,
    )
    (lens,) = result.lenses
    assert lens.outcome is not None
    assert Cause.TOOL_GAP not in lens.outcome.causes
    assert lens.outcome.test_runs == 1
    assert len(channel.requests) == 1


def test_the_coordinator_holds_the_review_on_an_unapproved_command(tmp_path):
    """The production default approves nothing: the blocked command is a
    tool gap, and a review with the gap open cannot approve."""
    from atlas_reviewer.verdict import ReviewEvent

    from .test_coordinator import review

    result, _model, _sprites = review(
        tmp_path,
        [tools(("run_tests", {"command": "python3 --version"})), final(finding())],
        run_proposals=proposals("python3 --version"),
    )
    (lens,) = result.lenses
    assert lens.outcome is not None
    assert Cause.TOOL_GAP in lens.outcome.causes
    assert lens.outcome.test_runs == 0
    assert result.event is ReviewEvent.COMMENT


# -------------------------------------------------- the shipped dry run


def test_the_dry_run_names_an_unusable_proposal_line(tmp_path):
    """End to end through the shipped sample-pr fixture, whose
    default-branch REVIEW.md carries an out-of-grammar proposals line:
    the run proposes nothing, the built-in pytest entry stands, and the
    named note -- never the rejected text -- rides the draft."""
    import io

    from atlas_reviewer import cli

    from .helpers import FIXTURE

    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "agentic-review",
            "--event",
            str(FIXTURE / "event.json"),
            "--dry-run",
            "--out",
            str(tmp_path / "draft.md"),
        ],
        env={},
        out=out,
        err=err,
    )
    assert code == cli.EXIT_CHANGES_REQUESTED, err.getvalue()
    draft = (tmp_path / "draft.md").read_text(encoding="utf-8")
    assert (
        "a review_test_commands: line it cannot use as the run's proposed "
        "test commands" in draft
    )
    assert "no command is proposed" in draft
    assert "make check && curl" not in draft
    assert "evil.example" not in draft


def test_the_dry_run_records_the_configured_proposals(tmp_path):
    """End to end through the shipped sample-pr-delta fixture, whose
    default-branch REVIEW.md proposes one command: the proposals reach
    the coordinator (the plumb a dropped kwarg would lose), and each lens
    run's gate records the fact on the telemetry."""
    import io
    import json

    from atlas_reviewer import cli

    from .helpers import FIXTURE

    events = tmp_path / "events.jsonl"
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "agentic-review",
            "--event",
            str(FIXTURE.parent / "sample-pr-delta" / "event.json"),
            "--dry-run",
            "--out",
            str(tmp_path / "draft.md"),
            "--events",
            str(events),
        ],
        env={},
        out=out,
        err=err,
    )
    assert code == cli.EXIT_CHANGES_REQUESTED, err.getvalue()
    recorded = [json.loads(line) for line in events.read_text().splitlines()]
    configured = [
        event
        for event in recorded
        if event["phase"] == "run approvals" and event["step"] == "configured"
    ]
    assert configured, "no run-approvals record on the telemetry"
    assert all(event["proposals"] == 1 for event in configured)
