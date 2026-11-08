# SPDX-License-Identifier: MIT
"""The runner must be destroyed on every path, and nothing may execute
inside it before deny-all egress is set and read back from outside."""

import os
import socket
import subprocess
import threading

import pytest

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import CleanupStatus, RunnerStatus
from atlas_reviewer.fakes import ExecRule, FakeSprites, MemoryLedger
from atlas_reviewer.interpreter import PYTHON_TAG
from atlas_reviewer.ports import BoundaryError, StreamTimeoutError
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import (
    FIRST_FRAME_BUDGET_S,
    PROBE_BUDGET_S,
    PROBE_TAG,
    START_MARKER,
    STDIN_CHECK_BYTES,
    TRIVIAL_TOOL,
    UNPACK_BUDGET_S,
    UPLOAD_BUDGET_S,
    RunnerJob,
    ToolAbsent,
    ToolRan,
    ToolSpec,
    decode_exec_output,
    destroy_runner,
    egress_script,
    egress_verdict,
    exec_argv,
    frames_seen,
    guest_text,
    parse_exit,
    parse_paths,
    parse_probe,
    probe_runner,
    probe_script,
    run_disposable,
    runner_name,
    strip_start,
    sweep,
)
from atlas_reviewer.telemetry import Telemetry

from .helpers import CallbackRule, FakeClock, fake_token

NAME = "cqa-rev-20261106-230000-abc123"
TOOLS = (
    ToolSpec("ruff", "ruff", "ruff --version", "ruff check ."),
    ToolSpec("shellcheck", "shellcheck", "shellcheck --version", "shellcheck x.sh"),
)
OK_RULES = (
    ExecRule("tar -xzf", "", 0),
    ExecRule("ruff --version", "ruff 0.17.3", 0),
    ExecRule("ruff check", "a.py:1:1: F401 unused import", 1),
)
# Only bounds a wait for an event another thread sets; no assertion
# depends on how long anything took.
_SYNC_WAIT_S = 10.0


def _no_secrets(text):
    return text


def run(api, ledger=None, clock=None, deadline_s=60.0, tools=TOOLS):
    return run_disposable(
        api,
        ledger if ledger is not None else MemoryLedger(),
        RunnerJob(b"tarball-bytes", tools),
        name=NAME,
        deadline_s=deadline_s,
        clock=clock or FakeClock(),
    )


def ops(api):
    return [c[0] for c in api.calls]


def test_success_runs_tools_and_destroys_verified():
    api, ledger = FakeSprites(rules=OK_RULES), MemoryLedger()
    outcome = run(api, ledger)
    assert outcome.report.status is RunnerStatus.COMPLETED
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()
    assert ledger.pending() == ()
    ruff, shellcheck = outcome.results
    assert ruff == ToolRan(TOOLS[0], "ruff 0.17.3", 1, "a.py:1:1: F401 unused import")
    assert isinstance(shellcheck, ToolAbsent)


def test_deny_all_is_set_and_read_back_before_any_exec():
    api = FakeSprites(rules=OK_RULES)
    run(api)
    sequence = ops(api)
    first_exec = sequence.index("exec")
    assert sequence[:3] == ["create", "set_network_policy", "get_network_policy"]
    assert sequence.index("set_memory_limit") < first_exec
    assert sequence[-2:] == ["delete", "exists"]


@pytest.mark.parametrize(
    "read_back",
    [
        {"rules": [{"include": "defaults"}]},
        {"rules": [None]},
        {"rules": [["action", "deny"]]},
        {"rules": "deny"},
        {},
        {
            "rules": [
                {"action": "deny", "domain": "*"},
                {"action": "allow", "domain": "example.com"},
            ]
        },
        {
            "rules": [
                {"action": "allow", "domain": "example.com"},
                {"action": "deny", "domain": "*"},
            ]
        },
        {"rules": [{"action": "deny", "domain": "*", "except": ["example.com"]}]},
        {
            "rules": [
                {"action": "deny", "domain": "*"},
                {"action": "deny", "domain": "*"},
            ]
        },
    ],
)
def test_policy_read_back_that_is_not_deny_all_blocks_execution(read_back):
    """Exact match: deny-all plus anything else, even a duplicate, is not
    the policy that was set."""
    api = FakeSprites(rules=OK_RULES, policy_read_back=read_back)
    outcome = run(api)
    assert outcome.report.status is RunnerStatus.FAILED
    assert "not deny-all" in outcome.report.note
    assert "exec" not in ops(api)
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED


def test_exec_failure_still_destroys():
    api = FakeSprites(rules=OK_RULES, fail_on={"exec": BoundaryError("exec 500")})
    outcome = run(api)
    assert outcome.report.status is RunnerStatus.FAILED
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()


def test_create_failure_still_attempts_destroy_but_cannot_certify_it():
    """A 503 does not show the server never made the Sprite, so a
    momentary 404 is not verified cleanup."""
    api = FakeSprites(fail_on={"create": BoundaryError("create 503")})
    ledger = MemoryLedger()
    outcome = run(api, ledger)
    assert outcome.report.status is RunnerStatus.FAILED
    assert "delete" in ops(api)
    assert outcome.report.cleanup is CleanupStatus.DESTROY_UNVERIFIED
    assert ledger.pending() == (NAME,)


def test_a_run_stopped_before_create_is_verified_and_leaves_no_entry():
    clock = FakeClock()
    ledger = MemoryLedger()
    outcome = run_disposable(
        FakeSprites(rules=OK_RULES), ledger, RunnerJob(b"tarball-bytes", TOOLS),
        name=NAME, deadline_s=0.0, clock=clock,
    )  # fmt: skip
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert ledger.pending() == ()


class _CreateLandsLater(FakeSprites):
    """The client gives up on `create` (its window ran out) while the
    server goes on to finish it; `land` is that server-side completion."""

    def create(self, name):
        self._record("create", name)
        raise StreamTimeoutError("create: no response within 30s")

    def land(self, name):
        FakeSprites.create(self, name)


def test_a_create_whose_outcome_is_unknown_stays_in_the_ledger_for_a_sweep():
    api = _CreateLandsLater(rules=OK_RULES)
    ledger = MemoryLedger()
    outcome = run(api, ledger)
    assert outcome.report.status is RunnerStatus.FAILED
    assert outcome.report.cleanup is CleanupStatus.DESTROY_UNVERIFIED
    assert ledger.pending() == (NAME,)

    api.land(NAME)
    assert sweep(api, ledger) == {NAME: CleanupStatus.DESTROYED_VERIFIED}
    assert api.live_names() == ()
    assert ledger.pending() == ()


def test_unexpected_exception_propagates_but_runner_is_destroyed():
    clock = FakeClock()

    def boom():
        raise RuntimeError("bug in a tool handler")

    api = FakeSprites(
        rules=(ExecRule("tar -xzf", "", 0), CallbackRule("ruff --version", boom))
    )
    with pytest.raises(RuntimeError):
        run(api, clock=clock)
    assert api.live_names() == ()
    assert ops(api)[-2:] == ["delete", "exists"]


def test_deadline_between_steps_stops_and_destroys():
    clock = FakeClock()
    api = FakeSprites(
        rules=(CallbackRule("tar -xzf", lambda: clock.advance(120)), *OK_RULES)
    )
    outcome = run(api, clock=clock, deadline_s=60)
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert outcome.results == ()
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED


def test_deadline_before_create_creates_nothing():
    api = FakeSprites()
    outcome = run(api, deadline_s=0)
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert "create" not in ops(api)


def test_watchdog_destroys_a_hung_exec_at_the_deadline():
    """The fake's hung exec ends only when the Sprite is destroyed (or at
    its own hang limit, with a different error), so the note tells which
    one ended it without timing anything."""
    api = FakeSprites(rules=OK_RULES, hang_on="ruff check")
    outcome, events = run_traced(api, deadline_s=0.05)
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert "exec connection closed" in outcome.report.note
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()
    steps = [(e.phase, e.step, e.status) for e in events]
    assert ("watchdog", "fired", "ok") in steps
    assert ("deadline", "exceeded", "error") in steps


def test_watchdog_and_final_destroys_are_told_apart_and_a_404_is_not_an_error():
    api = FakeSprites(rules=OK_RULES, hang_on="ruff check")
    _, events = run_traced(api, deadline_s=0.05)
    destroys = [e for e in events if e.phase in {"destroy", "verify"}]
    by_trigger = {
        trigger: [(e.step, e.status, e.fields.get("result")) for e in destroys
                  if e.fields["trigger"] == trigger]
        for trigger in ("watchdog", "final")
    }  # fmt: skip
    assert by_trigger == {
        "watchdog": [
            ("delete attempt 1", "ok", "deleted"),
            ("existence check", "ok", None),
            ("outcome", "ok", None),
        ],
        "final": [
            ("delete attempt 1", "ok", "already absent"),
            ("existence check", "ok", None),
            ("outcome", "ok", None),
        ],
    }


def test_a_late_create_after_the_watchdog_is_never_reported_completed():
    api, _, outcome, _, events = _run_with_create_held_past_the_watchdog()
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert outcome.results == ()
    assert "exec" not in ops(api)
    assert ("watchdog", "fired") in [(e.phase, e.step) for e in events]


def test_a_diagnostic_that_swallows_the_deadline_does_not_make_the_run_complete():
    """Diagnostics are never fatal, so one that fails at the deadline
    returns normally; the run must still say the deadline was reached."""
    clock = FakeClock()

    class LastDiagnosticOverruns(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if argv[0] == "/bin/sh" and "python3 --version" in argv[-1]:
                clock.advance(1000)
                raise BoundaryError("exec connection closed")
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    telemetry = Telemetry(clock)
    outcome = run_disposable(
        LastDiagnosticOverruns(rules=PY_RULES), MemoryLedger(),
        RunnerJob(b"tarball-bytes", (COMPILEALL,), diagnose=True),
        name=NAME, deadline_s=60.0, clock=clock, telemetry=telemetry,
    )  # fmt: skip
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert ("deadline", "exceeded") in [(e.phase, e.step) for e in telemetry.events]
    (compileall,) = outcome.results
    assert isinstance(compileall, ToolRan)


def test_a_stdin_check_that_swallows_the_deadline_does_not_make_the_probe_complete():
    clock = FakeClock()

    class StdinOverruns(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if stdin:
                clock.advance(timeout_s + 1)
                raise BoundaryError("exec connection closed")
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    outcome = probe_runner(
        StdinOverruns(), MemoryLedger(), TOOLS, name=NAME, deadline_s=60, clock=clock
    )
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert outcome.stdin_check.startswith("FAILED sending")


def _overrun(clock, fails):
    clock.advance(1000)
    if fails:
        raise BoundaryError("exec connection closed")


@pytest.mark.parametrize("fails", [True, False], ids=["swallowed", "returned"])
def test_a_last_diagnostic_past_the_deadline_does_not_make_the_run_complete(fails):
    """Only the very last exec overruns, so no later step's deadline check
    can catch it: the post-body check is the only guard."""
    clock = FakeClock()

    class BareDiagnosticOverruns(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            raw = super().exec(name, argv, stdin, timeout_s, first_byte_s)
            script = argv[-1]
            if "python3 --version" in script and "PYENV_VERSION" not in script:
                _overrun(clock, fails)
            return raw

    api = BareDiagnosticOverruns(rules=PY_RULES)
    outcome = run_disposable(
        api, MemoryLedger(), RunnerJob(b"tarball-bytes", (COMPILEALL,), diagnose=True),
        name=NAME, deadline_s=60.0, clock=clock,
    )  # fmt: skip
    assert outcome.diagnostics[-1].name == "bare python3 in the checkout"
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()


@pytest.mark.parametrize("fails", [True, False], ids=["swallowed", "returned"])
def test_a_last_egress_check_past_the_deadline_does_not_make_the_probe_complete(
    fails,
):
    clock = FakeClock()

    class EgressOverruns(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            raw = super().exec(name, argv, stdin, timeout_s, first_byte_s)
            if "atlas-egress" in argv[-1]:
                _overrun(clock, fails)
            return raw

    api = EgressOverruns()
    outcome = probe_runner(
        api, MemoryLedger(), TOOLS, name=NAME, deadline_s=60, clock=clock
    )
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()


class _WatchdogDone:
    """A sink that signals once the first destroy (the watchdog's) has
    recorded its outcome, so a test can order itself after it without
    sleeping."""

    def __init__(self):
        self.done = threading.Event()

    def emit(self, event):
        if (event.phase, event.step) == ("destroy", "outcome"):
            self.done.set()


def _run_with_create_held_past_the_watchdog(on_created=None):
    """The run's own deadline uses a clock that never moves, so only the
    wall-clock watchdog fires. `create` blocks until the watchdog's destroy
    has finished, then lands -- the late create the watchdog cannot see."""
    signal = _WatchdogDone()
    seen = {}

    class CreateOutlivesWatchdog(FakeSprites):
        def create(self, name):
            assert signal.done.wait(_SYNC_WAIT_S), "the watchdog never finished"
            super().create(name)
            seen["live"] = self.live_names()
            seen["pending"] = ledger.pending()
            if on_created:
                on_created(self)

    api, ledger = CreateOutlivesWatchdog(rules=OK_RULES), MemoryLedger()
    telemetry = Telemetry(SystemClock(), signal, scrub=_no_secrets)
    outcome = run_disposable(
        api, ledger, RunnerJob(b"tarball-bytes", TOOLS), name=NAME,
        deadline_s=0.01, clock=FakeClock(), telemetry=telemetry,
    )  # fmt: skip
    return api, ledger, outcome, seen, telemetry.events


def test_the_ledger_keeps_a_runner_whose_create_lands_after_the_watchdog():
    """A controller killed between the late create and the final destroy
    must still leave the name for `sweep` to find."""
    api, ledger, outcome, seen, _ = _run_with_create_held_past_the_watchdog()
    assert seen == {"live": (NAME,), "pending": (NAME,)}
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()
    assert ledger.pending() == ()


def test_a_telemetry_write_failure_does_not_stop_cleanup():
    class FailingSink:
        def emit(self, event):
            if event.phase == "destroy":
                raise OSError("disk full")

    api, ledger = FakeSprites(rules=OK_RULES), MemoryLedger()
    with pytest.raises(OSError, match="disk full") as caught:
        run_disposable(
            api,
            ledger,
            RunnerJob(b"tarball-bytes", TOOLS),
            name=NAME,
            deadline_s=60.0,
            clock=FakeClock(),
            telemetry=Telemetry(FakeClock(), FailingSink(), scrub=_no_secrets),
        )
    assert api.live_names() == ()
    assert ledger.pending() == ()
    assert caught.value.__notes__ == [
        (
            f"runner {NAME} cleanup after the telemetry write failure: "
            "destroyed (verified absent)"
        )
    ]


def test_destroy_that_does_not_take_effect_is_reported_and_kept_in_ledger():
    api, ledger = FakeSprites(rules=OK_RULES, delete_takes_effect=False), MemoryLedger()
    outcome = run(api, ledger)
    assert outcome.report.cleanup is CleanupStatus.DESTROY_UNVERIFIED
    assert ledger.pending() == (NAME,)


def test_delete_error_is_retried_then_reported_unverified():
    api, ledger = (
        FakeSprites(rules=OK_RULES, fail_on={"delete": BoundaryError("500")}),
        MemoryLedger(),
    )
    outcome = run(api, ledger)
    assert ops(api).count("delete") == 2
    assert outcome.report.cleanup is CleanupStatus.DESTROY_UNVERIFIED
    assert ledger.pending() == (NAME,)


def test_existence_check_error_is_unverified():
    api = FakeSprites(rules=OK_RULES, fail_on={"exists": BoundaryError("500")})
    assert run(api).report.cleanup is CleanupStatus.DESTROY_UNVERIFIED


def test_runner_name_is_in_ledger_before_create():
    seen = []

    class SpyLedger(MemoryLedger):
        def record(self, name):
            seen.append(("record", list(api.calls)))
            super().record(name)

    api = FakeSprites(rules=OK_RULES)
    run(api, SpyLedger())
    assert seen == [("record", [])]


def test_upload_failure_is_a_failed_run():
    api = FakeSprites(rules=(ExecRule("tar -xzf", "tar: invalid", 2),))
    outcome = run(api)
    assert outcome.report.status is RunnerStatus.FAILED
    assert "unpack / tar -xzf failed after" in outcome.report.note
    assert "source unpack failed (exit 2): tar: invalid" in outcome.report.note


def test_guest_text_is_one_printable_bounded_line_from_the_end():
    raw = "\x1b[31mtar: \x1b]0;title\x07bad\r\nentry\x00 caf\u00e9\x1bc\n" + "x" * 50
    assert guest_text(raw, 1000) == "tar: bad entry caf " + "x" * 50
    assert guest_text(raw, 10) == "x" * 10
    assert guest_text("\n\t", 10) == ""
    assert guest_text("abc", 0) == ""


def test_guest_output_in_a_failure_note_is_bounded_and_printable():
    hostile = "\x1b[2J\x1b[Hfake: all checks passed\r\n" + "y" * 2000 + "\x1b[0m"
    api = FakeSprites(rules=(ExecRule("tar -xzf", hostile, 2),))
    note = run(api).report.note
    assert not any(c in note for c in "\x1b\r\n")
    assert note.endswith("y" * 100)
    assert len(note) < 600


def test_a_failure_note_is_scrubbed_like_the_telemetry_it_came_from():
    secret = fake_token("sk-or-v1-")

    class LeakyCreate(FakeSprites):
        def create(self, name):
            raise BoundaryError(f"POST https://api.example failed: echo {secret}")

    outcome = run_disposable(
        LeakyCreate(), MemoryLedger(), RunnerJob(b"tarball-bytes", TOOLS), name=NAME,
        deadline_s=60.0, clock=FakeClock(),
        telemetry=Telemetry(FakeClock(), scrub=lambda text: Redactor((secret,))(text).text),
    )  # fmt: skip
    assert secret not in outcome.report.note
    assert "[REDACTED" in outcome.report.note


def test_a_tool_version_is_printable_guest_text():
    api = FakeSprites(
        rules=(
            ExecRule("tar -xzf", "", 0),
            ExecRule("ruff --version", "\x1b[1mruff\x1b[0m 0.17.3\x07", 0),
            ExecRule("ruff check", "", 0),
        )
    )
    (ruff,) = run(api, tools=TOOLS[:1]).results
    assert isinstance(ruff, ToolRan)
    assert ruff.version == "ruff 0.17.3"


def test_the_only_input_the_runner_gets_is_the_tarball():
    """The credential boundary itself is pinned elsewhere: the token only
    in the control-plane Authorization header
    (test_sprites_api.test_the_token_goes_only_in_the_authorization_header)
    and every exec under `env -i` with the minimal environment
    (test_exec_argv_gives_every_command_exactly_its_stdin_then_eof,
    test_the_wrapper_really_runs_with_only_the_minimal_environment)."""
    api = FakeSprites(rules=OK_RULES)
    run(api)
    assert [s for s in api.stdin_seen if s] == [b"tarball-bytes"]


def test_network_policy_sent_is_deny_all():
    api = FakeSprites(rules=OK_RULES)
    run(api)
    assert api.policies_sent == [(NAME, [{"action": "deny", "domain": "*"}])]


def test_destroy_is_idempotent_and_sweep_clears_leftovers():
    api, ledger = FakeSprites(), MemoryLedger()
    api.create(NAME)
    ledger.record(NAME)
    ledger.record("cqa-rev-already-gone")
    results = sweep(api, ledger)
    assert set(results.values()) == {CleanupStatus.DESTROYED_VERIFIED}
    assert ledger.pending() == ()
    assert destroy_runner(api, ledger, NAME) is CleanupStatus.DESTROYED_VERIFIED


def test_exec_output_decoding_and_exit_marker():
    assert decode_exec_output(b"\x01hello\x02\n") == "hello\n"
    assert parse_exit("out\n__ATLAS_EXIT__=0\nfake\n__ATLAS_EXIT__=3\n") == (
        3,
        "out\n__ATLAS_EXIT__=0\nfake",
    )
    assert parse_exit("no marker") == (None, "no marker")


def test_an_upload_without_exit_marker_is_a_failed_run():
    class NoMarker(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            super().exec(name, argv, stdin, timeout_s, first_byte_s)
            return b"truncated output"

    api = NoMarker(rules=OK_RULES)
    outcome = run(api, tools=())
    assert outcome.report.status is RunnerStatus.FAILED
    assert "exit None" in outcome.report.note


def test_a_tool_run_without_exit_marker_reports_no_exit_code():
    """Only the tool's run exec loses its marker, so a missing marker
    cannot be read as exit 0."""

    class RunLosesMarker(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            raw = super().exec(name, argv, stdin, timeout_s, first_byte_s)
            if "ruff check" in argv[-1]:
                return raw.split(b"__ATLAS_EXIT__=")[0]
            return raw

    outcome = run(RunLosesMarker(rules=OK_RULES), tools=TOOLS[:1])
    assert outcome.report.status is RunnerStatus.COMPLETED
    (ruff,) = outcome.results
    assert isinstance(ruff, ToolRan)
    assert ruff.exit_code is None
    assert ruff.output.strip() == "a.py:1:1: F401 unused import"


def test_empty_version_output_is_unknown_version():
    api = FakeSprites(
        rules=(
            ExecRule("tar -xzf", "", 0),
            ExecRule("ruff --version", "", 0),
            ExecRule("ruff check", "", 0),
        )
    )
    ruff = run(api, tools=TOOLS[:1]).results[0]
    assert isinstance(ruff, ToolRan)
    assert ruff.version == "unknown"


def test_probe_runs_after_deny_all_and_before_the_source_upload():
    api = FakeSprites(rules=OK_RULES)
    run(api)
    scripts = [c[2] for c in api.calls if c[0] == "exec"]
    assert PROBE_TAG in scripts[0]
    assert "head -c 13 | " in scripts[1]
    assert "tar -xzf" in scripts[2]


def test_binary_missing_from_probe_is_absent_and_never_executed():
    api = FakeSprites(rules=OK_RULES, installed=frozenset({"ruff"}))
    outcome = run(api)
    ruff, shellcheck = outcome.results
    assert isinstance(ruff, ToolRan)
    assert shellcheck == ToolAbsent(
        TOOLS[1], "`shellcheck` not found by the availability probe"
    )
    tool_scripts = [c[2] for c in api.calls if c[0] == "exec" and PROBE_TAG not in c[2]]
    assert not any("shellcheck" in s for s in tool_scripts)


def test_failed_probe_marks_every_tool_absent():
    class BrokenProbe(FakeSprites):
        def _answer(self, script, stdin):
            if PROBE_TAG in script:
                return "sh: syntax error", 2
            return super()._answer(script, stdin)

    outcome, events = run_traced(BrokenProbe(rules=OK_RULES))
    assert outcome.report.status is RunnerStatus.COMPLETED
    assert [r.detail for r in outcome.results if isinstance(r, ToolAbsent)] == [
        "not checked: the availability probe failed (exit 2): sh: syntax error",
    ] * 2
    availability = next(e for e in events if e.step == "availability")
    assert (availability.status, availability.fields["exit_status"]) == ("error", 2)


def test_a_failed_interpreter_resolution_is_not_reported_as_no_interpreter():
    class BrokenResolver(FakeSprites):
        def _answer(self, script, stdin):
            if "atlas-python" in script:
                return "mkdir: /tmp/atlas-neutral: Read-only file system", 1
            return super()._answer(script, stdin)

    (result,) = run(BrokenResolver(rules=PY_RULES), tools=(COMPILEALL,)).results
    assert result == ToolAbsent(
        COMPILEALL,
        "no trusted Python interpreter: the interpreter resolution failed (exit 1): "
        "mkdir: /tmp/atlas-neutral: Read-only file system",
    )


def test_a_resolution_that_finds_no_acceptable_interpreter_says_so():
    (result,) = run(
        FakeSprites(rules=PY_RULES, pythons=()), tools=(COMPILEALL,)
    ).results
    assert result == ToolAbsent(
        COMPILEALL, "no trusted Python interpreter was resolved"
    )


def test_a_failed_probe_is_reported_by_the_probe_runner_not_as_absent_tools():
    class BrokenProbe(FakeSprites):
        def _answer(self, script, stdin):
            if PROBE_TAG in script:
                return "sh: syntax error", 2
            return super()._answer(script, stdin)

    outcome = probe_runner(
        BrokenProbe(),
        MemoryLedger(),
        TOOLS,
        name=NAME,
        deadline_s=60,
        clock=FakeClock(),
    )
    assert outcome.available == {}
    assert outcome.report.note.startswith(
        "the availability probe failed (exit 2): sh: syntax error"
    )


def test_probe_parsing_treats_unreported_binaries_as_absent():
    text = "atlas-probe:present:ruff\nnoise atlas-probe:present:evil;rm\n"
    assert parse_probe(text, ("ruff", "shellcheck")) == {
        "ruff": True,
        "shellcheck": False,
    }
    assert "for b in ruff shellcheck;" in probe_script(("ruff", "shellcheck", "ruff"))


def test_tool_binary_must_be_a_bare_command_name():
    with pytest.raises(ValueError, match="bare command"):
        ToolSpec("x", "ruff; curl evil", "v", "r")


def test_probe_runner_reports_tools_and_raw_framing_then_destroys():
    api, ledger = FakeSprites(installed=frozenset({"ruff"})), MemoryLedger()
    outcome = probe_runner(
        api, ledger, TOOLS, name=NAME, deadline_s=60, clock=FakeClock()
    )
    assert outcome.available == {"ruff": True, "shellcheck": False}
    assert outcome.framing_sample.startswith(b"\x01")
    assert outcome.report.status is RunnerStatus.COMPLETED
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert ledger.pending() == ()
    assert api.stdin_seen[:2] == [b"", b""]
    assert len(api.stdin_seen[2]) == STDIN_CHECK_BYTES
    assert outcome.stdin_check == (
        f"ok: sent {STDIN_CHECK_BYTES} bytes, runner received {STDIN_CHECK_BYTES}"
    )
    assert ops(api)[:3] == ["create", "set_network_policy", "get_network_policy"]


def _egress_answer(*lines, exit_code=0):
    return ExecRule("atlas-egress", "\n".join(lines), exit_code)


def _probe_with(*rules, api_cls=FakeSprites):
    api = api_cls(rules=rules)
    return probe_runner(
        api, MemoryLedger(), TOOLS, name=NAME, deadline_s=60, clock=FakeClock()
    )


def test_the_probe_reports_no_outbound_connection_only_when_every_target_failed():
    outcome = _probe_with(
        _egress_answer(
            "atlas-egress:1.1.1.1:443:tried:refused:0",
            "atlas-egress:example.com:443:tried::124",
        )
    )
    assert outcome.egress_check == (
        "no outbound connection: 1.1.1.1:443 no connection (refused); "
        "example.com:443 no connection (timed out) (exit 124)"
    )


@pytest.mark.parametrize(
    "lines,expected",
    [
        (
            ("1.1.1.1:443:tried:timeout:0", "example.com:443:tried:unresolved:0"),
            (
                "no outbound connection: 1.1.1.1:443 no connection (timed out); "
                "example.com:443 name not resolved"
            ),
        ),
        (
            ("1.1.1.1:443:tried:oserror-101:0", "example.com:443:tried:refused:0"),
            (
                "no outbound connection: 1.1.1.1:443 no connection (oserror-101); "
                "example.com:443 no connection (refused)"
            ),
        ),
    ],
)
def test_every_outcome_python_names_after_trying_counts_as_no_connection(
    lines, expected
):
    rule = _egress_answer(*(f"atlas-egress:{line}" for line in lines))
    assert _probe_with(rule).egress_check == expected


@pytest.mark.parametrize(
    "rule,expected",
    [
        (
            _egress_answer(
                "atlas-egress:1.1.1.1:443:tried:connected:0",
                "atlas-egress:example.com:443:tried:refused:0",
            ),
            "OPEN: 1.1.1.1:443 CONNECTED; example.com:443 no connection (refused)",
        ),
        (
            _egress_answer(
                "atlas-egress:1.1.1.1:443:tried:connected:124",
                "atlas-egress:example.com:443:tried:refused:0",
            ),
            "OPEN: 1.1.1.1:443 CONNECTED; example.com:443 no connection (refused)",
        ),
        (
            _egress_answer("atlas-egress:1.1.1.1:443:tried:refused:0"),
            (
                "UNVERIFIED: 1.1.1.1:443 no connection (refused); "
                "example.com:443 not reported"
            ),
        ),
        (
            _egress_answer(
                "atlas-egress:1.1.1.1:443:tried::127",
                "atlas-egress:example.com:443:tried:refused:0",
            ),
            (
                "UNVERIFIED: 1.1.1.1:443 did not report an attempt "
                "(outcome 'none', exit 127); example.com:443 no connection (refused)"
            ),
        ),
        (
            _egress_answer(
                "atlas-egress:1.1.1.1:443:tried:refused:1",
                "atlas-egress:example.com:443:tried:bogus:0",
            ),
            (
                "UNVERIFIED: 1.1.1.1:443 did not report an attempt "
                "(outcome 'refused', exit 1); example.com:443 did not report an "
                "attempt (outcome 'bogus', exit 0)"
            ),
        ),
        (
            _egress_answer(
                "atlas-egress:1.1.1.1:443:refused:1",
                "atlas-egress:example.com:443:connected",
            ),
            "UNVERIFIED: 1.1.1.1:443 not reported; example.com:443 not reported",
        ),
        (
            _egress_answer(
                "atlas-egress:1.1.1.1:443:untested",
                "atlas-egress:example.com:443:untested",
            ),
            (
                "UNVERIFIED: 1.1.1.1:443 untested (no system Python); "
                "example.com:443 untested (no system Python)"
            ),
        ),
        (
            _egress_answer("sh: \x1b[31mbroken", exit_code=2),
            "UNVERIFIED: the egress check exited 2: sh: broken",
        ),
    ],
)
def test_the_probe_never_reports_egress_blocked_without_evidence(rule, expected):
    assert _probe_with(rule).egress_check == expected


def test_an_egress_check_transport_failure_is_unverified_not_fatal():
    class EgressTimesOut(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if "atlas-egress" in argv[-1]:
                raise BoundaryError("exec connection closed")
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    outcome = _probe_with(api_cls=EgressTimesOut)
    assert outcome.egress_check.startswith("UNVERIFIED: the egress check failed: ")
    assert outcome.report.status is RunnerStatus.COMPLETED
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED


@pytest.mark.skipif(
    not (os.path.exists("/usr/bin/python3") and os.path.exists("/usr/bin/timeout"))
    or not os.path.exists("/bin/sh"),
    reason="needs /bin/sh, /usr/bin/python3 and /usr/bin/timeout",
)
def test_the_egress_script_really_tells_a_connection_from_a_refusal():
    """Locally, against 127.0.0.1 only: the script's own shell and Python
    logic, not whether any Sprite blocks egress."""
    with socket.socket() as listening, socket.socket() as unused:
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        unused.bind(("127.0.0.1", 0))
        closed = unused.getsockname()[1]
        unused.close()
        targets = (f"127.0.0.1:{listening.getsockname()[1]}", f"127.0.0.1:{closed}")
        done = subprocess.run(
            list(exec_argv(egress_script(targets), 0)),
            capture_output=True, timeout=30, check=True,
        )  # fmt: skip
    code, text = parse_exit(strip_start(done.stdout.decode()))
    verdict = egress_verdict(code, text, targets)
    assert verdict.startswith(
        f"OPEN: {targets[0]} CONNECTED; {targets[1]} no connection"
    )


def _run_egress_script(targets):
    done = subprocess.run(
        list(exec_argv(egress_script(targets), 0)),
        capture_output=True, timeout=30, check=True,
    )  # fmt: skip
    code, text = parse_exit(strip_start(done.stdout.decode()))
    return egress_verdict(code, text, targets)


def _not_executable(tmp_path):
    path = tmp_path / "python3"
    path.write_text("#!/bin/sh\nexit 126\n")
    path.chmod(0o755)
    return str(path)


@pytest.mark.skipif(
    not (os.path.exists("/usr/bin/python3") and os.path.exists("/usr/bin/timeout"))
    or not os.path.exists("/bin/sh"),
    reason="needs /bin/sh, /usr/bin/python3 and /usr/bin/timeout",
)
@pytest.mark.parametrize("broken", ["no timeout binary", "interpreter cannot run"])
def test_an_attempt_that_never_ran_is_not_reported_as_no_connection(
    broken, tmp_path, monkeypatch
):
    """Locally, against a listening 127.0.0.1 port: when the connect
    attempt itself cannot start, nothing shows the port is unreachable."""
    import atlas_reviewer.runner as runner_module

    if broken == "no timeout binary":
        monkeypatch.setattr(
            runner_module,
            "bounded",
            lambda command, seconds: f"/nonexistent/timeout {seconds} {command}",
        )
    else:
        monkeypatch.setattr(runner_module, "SYSTEM_PYTHON", _not_executable(tmp_path))
    with socket.socket() as listening:
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        target = f"127.0.0.1:{listening.getsockname()[1]}"
        verdict = _run_egress_script((target,))
    assert verdict.startswith("UNVERIFIED: ")
    assert "no connection" not in verdict


def test_probe_runner_still_destroys_when_the_policy_is_wrong():
    api = FakeSprites(policy_read_back={"rules": []})
    outcome = probe_runner(
        api, MemoryLedger(), TOOLS, name=NAME, deadline_s=60, clock=FakeClock()
    )
    assert outcome.report.status is RunnerStatus.FAILED
    assert outcome.available == {}
    assert "exec" not in ops(api)
    assert api.live_names() == ()


def test_runner_names_are_prefixed_and_unique():
    clock = FakeClock()
    assert runner_name(clock, lambda n: "ab" * n) == "cqa-rev-20261106-230000-ababab"
    assert runner_name(clock) != runner_name(clock)


def exec_timeouts(api):
    execs = [c for c in api.calls if c[0] == "exec"]
    return dict(zip((c[2] for c in execs), api.timeouts_seen, strict=True))


def test_upload_exec_gets_the_dedicated_upload_budget_not_the_client_default():
    api = FakeSprites(rules=OK_RULES)
    run(api, deadline_s=600.0)
    (timeout,) = [t for s, t in exec_timeouts(api).items() if "head -c" in s]
    assert timeout == UPLOAD_BUDGET_S
    assert timeout > 30.0


def test_upload_exec_is_capped_by_the_remaining_review_deadline():
    api = FakeSprites(rules=OK_RULES)
    run(api, deadline_s=90.0)
    (timeout,) = [t for s, t in exec_timeouts(api).items() if "head -c" in s]
    assert 60.0 < timeout <= 90.0


def test_an_archive_over_the_exec_stdin_limit_is_refused_before_any_sprite_exists():
    api, ledger = FakeSprites(rules=OK_RULES), MemoryLedger()
    too_big = b"x" * (10 * 1024 * 1024 + 1)
    telemetry = Telemetry(FakeClock())
    outcome = run_disposable(
        api, ledger, RunnerJob(too_big, TOOLS), name=NAME, deadline_s=60.0,
        clock=FakeClock(), telemetry=telemetry,
    )  # fmt: skip
    assert outcome.report.status is RunnerStatus.FAILED
    assert outcome.report.cleanup is CleanupStatus.NOT_CREATED
    assert outcome.report.note == (
        "source archive is 10485761 bytes, over the 10485760-byte limit of the "
        "exec stdin it is uploaded through; no runner was created"
    )
    assert outcome.results == ()
    assert api.calls == []
    assert ledger.pending() == ()
    events = [(e.phase, e.step, e.status) for e in telemetry.events]
    assert events == [("upload", "size check", "error")]


def test_upload_does_not_wait_for_a_stdin_eof():
    api = FakeSprites(rules=OK_RULES)
    run(api)
    (script,) = [s for s in exec_timeouts(api) if "head -c" in s]
    assert f"head -c {len(b'tarball-bytes')} | {{ cat > " in script


def test_upload_transport_failure_names_the_size_and_still_destroys():
    class UploadTimesOut(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if stdin:
                raise BoundaryError("The read operation timed out")
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    api = UploadTimesOut(rules=OK_RULES)
    outcome = run(api)
    assert outcome.report.status is RunnerStatus.FAILED
    assert outcome.report.note.startswith(
        "exec / source upload failed after 0.0s (0.0s into the run): "
    )
    assert "read operation timed out" in outcome.report.note
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED


def test_stdin_roundtrip_reports_a_short_read_as_a_mismatch():
    class ShortReads(FakeSprites):
        def _answer(self, script, stdin):
            if "{ wc -c" in script:
                return "1048576", 0
            return super()._answer(script, stdin)

    outcome = probe_runner(
        ShortReads(), MemoryLedger(), TOOLS, name=NAME, deadline_s=60, clock=FakeClock()
    )
    assert outcome.stdin_check.startswith("MISMATCH: sent 3145728 bytes")
    assert "received 1048576" in outcome.stdin_check
    assert outcome.report.status is RunnerStatus.COMPLETED


def test_stdin_roundtrip_transport_failure_is_reported_not_fatal_to_the_probe():
    class StdinTimesOut(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if stdin:
                raise BoundaryError("The read operation timed out")
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    outcome = probe_runner(
        StdinTimesOut(),
        MemoryLedger(),
        TOOLS,
        name=NAME,
        deadline_s=60,
        clock=FakeClock(),
    )
    assert "FAILED sending 3145728 bytes" in outcome.stdin_check
    assert "read operation timed out" in outcome.stdin_check
    assert outcome.available == {"ruff": True, "shellcheck": True}
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED


def test_default_tools_are_limited_to_what_the_runner_image_is_known_to_have():
    from atlas_reviewer.runner import DEFAULT_TOOLS

    assert [t.binary for t in DEFAULT_TOOLS] == ["python3"]


# --- lifecycle telemetry ----------------------------------------------------


def run_traced(api, clock=None, deadline_s=600.0, tools=TOOLS):
    telemetry = Telemetry(clock or FakeClock())
    outcome = run_disposable(
        api, MemoryLedger(), RunnerJob(b"tarball-bytes", tools), name=NAME,
        deadline_s=deadline_s, clock=clock or FakeClock(), telemetry=telemetry,
    )  # fmt: skip
    return outcome, telemetry.events


def test_every_lifecycle_phase_is_recorded_in_order():
    _, events = run_traced(FakeSprites(rules=OK_RULES))
    assert [(e.phase, e.step) for e in events] == [
        ("ledger", "record runner name"),
        ("create", "create sprite"),
        ("egress", "set deny-all"),
        ("egress", "read back"),
        ("resources", "memory limit"),
        ("exec", "tool check"),
        ("tool check", "availability"),
        ("exec", "source upload"),
        ("upload", "13-byte tarball"),
        ("exec", "source unpack"),
        ("unpack", "tar -xzf"),
        ("exec", "ruff version"),
        ("exec", "ruff run"),
        ("tool", "ruff"),
        ("exec", "shellcheck version"),
        ("tool", "shellcheck"),
        ("destroy", "delete attempt 1"),
        ("verify", "existence check"),
        ("destroy", "outcome"),
    ]
    assert all(e.status == "ok" for e in events)
    by_step = {(e.phase, e.step): e.fields for e in events}
    assert by_step[("egress", "read back")] == {"deny_all": True}
    assert by_step[("upload", "13-byte tarball")] == {
        "bytes": 13,
        "runner_received": 13,
    }
    assert by_step[("tool", "ruff")]["exit_status"] == 1
    assert by_step[("verify", "existence check")] == {
        "trigger": "final",
        "present": False,
    }
    assert by_step[("destroy", "outcome")] == {
        "trigger": "final",
        "cleanup": "destroyed (verified absent)",
    }


def test_each_exec_records_purpose_timeouts_bytes_frames_and_exit():
    _, events = run_traced(FakeSprites(rules=OK_RULES))
    execs = {e.step: e.fields for e in events if e.phase == "exec"}
    upload = execs["source upload"]
    assert upload["purpose"] == "source upload"
    assert upload["timeout_s"] == UPLOAD_BUDGET_S
    assert upload["bytes_sent"] == 13
    assert upload["bytes_received"] > 0
    assert upload["frames_seen"] == "0x01:1"
    assert upload["exit_status"] == 0
    assert execs["tool check"]["timeout_s"] == PROBE_BUDGET_S
    assert execs["source unpack"]["timeout_s"] == UNPACK_BUDGET_S
    assert execs["source unpack"]["bytes_sent"] == 0
    assert execs["ruff run"]["exit_status"] == 1


def test_a_timed_out_tool_check_names_its_step_and_timing_not_a_bare_timeout():
    """The second pilot's unwrapped 'The read operation timed out'."""
    clock = FakeClock()

    class ProbeTimesOut(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if PROBE_TAG in argv[-1]:
                clock.advance(timeout_s)
                raise BoundaryError(
                    f"POST https://api.sprites.dev/v1/sprites/{name}/exec failed: "
                    "The read operation timed out"
                )
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    outcome, events = run_traced(ProbeTimesOut(rules=OK_RULES), clock=clock)
    assert outcome.report.status is RunnerStatus.FAILED
    assert outcome.report.note.startswith(
        "exec / tool check failed after 60.0s (60.0s into the run): POST "
    )
    (failed,) = [e for e in events if e.status == "error"]
    assert (failed.phase, failed.step, failed.duration_s) == (
        "exec",
        "tool check",
        60.0,
    )
    assert failed.fields["timeout_s"] == PROBE_BUDGET_S
    assert "upload" not in {e.phase for e in events}
    assert events[-1].fields["cleanup"] == "destroyed (verified absent)"


def test_every_error_event_carries_its_label_and_elapsed_time():
    api = FakeSprites(rules=OK_RULES, fail_on={"create": BoundaryError("HTTP 503")})
    outcome, events = run_traced(api)
    errors = [e for e in events if e.status == "error"]
    assert errors and all("failed after" in e.error for e in errors)
    assert outcome.report.note == (
        "create / create sprite failed after 0.0s (0.0s into the run): HTTP 503"
    )


def test_a_short_upload_is_a_labelled_failure_naming_the_byte_counts():
    class ShortWrite(FakeSprites):
        def _answer(self, script, stdin):
            if "cat > /tmp" in script:
                return "5", 0
            return super()._answer(script, stdin)

    api = ShortWrite(rules=OK_RULES)
    outcome, _ = run_traced(api)
    assert outcome.report.status is RunnerStatus.FAILED
    assert "upload / 13-byte tarball failed after" in outcome.report.note
    assert "runner wrote 5 of 13 bytes (exit 0)" in outcome.report.note
    assert "tar -xzf" not in " ".join(c[-1] for c in api.calls)


def test_destroy_attempts_and_verification_are_recorded_when_delete_fails():
    api = FakeSprites(rules=OK_RULES, fail_on={"delete": BoundaryError("HTTP 500")})
    _, events = run_traced(api)
    tail = [(e.phase, e.step, e.status) for e in events[-3:]]
    assert tail == [
        ("destroy", "delete attempt 1", "error"),
        ("destroy", "delete attempt 2", "error"),
        ("destroy", "outcome", "ok"),
    ]
    assert events[-1].fields == {
        "trigger": "final",
        "cleanup": "destroy NOT verified -- run `sweep`",
    }


def test_a_deadline_stop_is_recorded():
    clock = FakeClock()
    api = FakeSprites(rules=(CallbackRule("tar -xzf", lambda: clock.advance(100)),))
    outcome, events = run_traced(api, clock=clock, deadline_s=50.0, tools=TOOLS)
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert ("deadline", "exceeded", "error") in [
        (e.phase, e.step, e.status) for e in events
    ]


def test_frames_seen_counts_stream_id_bytes():
    assert frames_seen(b"\x01hello\n\x03\x00") == "0x00:1,0x01:1,0x03:1"
    assert frames_seen(b"plain") == "none"


def test_the_trivial_tool_runs_through_the_review_sequence():
    api = FakeSprites(rules=(ExecRule("tar -xzf", "", 0), ExecRule("echo posix-sh", "posix-sh", 0), ExecRule("find .", "12", 0)))  # fmt: skip
    outcome, events = run_traced(api, tools=(TRIVIAL_TOOL,))
    (result,) = outcome.results
    assert isinstance(result, ToolRan)
    assert (result.version, result.exit_code, result.output) == ("posix-sh", 0, "12")
    assert [e.step for e in events if e.phase == "exec"] == [
        "tool check", "source upload", "source unpack",
        "source-file-count version", "source-file-count run",
    ]  # fmt: skip


def test_stdin_roundtrip_reports_a_nonzero_exit_as_a_failure():
    class WcFails(FakeSprites):
        def _answer(self, script, stdin):
            if "{ wc -c" in script:
                return "wc: broken", 1
            return super()._answer(script, stdin)

    outcome = probe_runner(
        WcFails(), MemoryLedger(), TOOLS, name=NAME, deadline_s=60, clock=FakeClock()
    )
    assert outcome.stdin_check.startswith("FAILED sending 3145728 bytes: exit 1")


# --- one exec shape, and failing fast on silence (D28) ----------------------

COMPILEALL = ToolSpec(
    "python-compileall",
    "python3",
    "{python} -I --version",
    "{python} -I -m compileall -q .",
)
PY_RULES = (
    ExecRule("tar -xzf", "", 0),
    ExecRule("-I --version", "Python 3.13.7", 0),
    ExecRule("compileall", "", 0),
)


def test_exec_argv_gives_every_command_exactly_its_stdin_then_eof():
    env = ("/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "HOME=/tmp", "LANG=C.UTF-8")
    assert exec_argv("tar -xzf a", 0) == (
        *env,
        "/bin/sh",
        "-c",
        f"echo {START_MARKER}; {{ tar -xzf a\n}} </dev/null; echo __ATLAS_EXIT__=$?",
    )
    assert exec_argv("cat > f", 7) == (
        *env,
        "/bin/sh",
        "-c",
        f"echo {START_MARKER}; head -c 7 | {{ cat > f\n}}; echo __ATLAS_EXIT__=$?",
    )
    assert exec_argv("true", 0, sprite_env=True)[:2] == ("/bin/sh", "-c")
    assert strip_start(f"{START_MARKER}\nout\n") == "out\n"
    assert strip_start("no marker") == "no marker"


def test_every_exec_of_a_review_uses_the_one_wrapper():
    api = FakeSprites(
        rules=(
            *PY_RULES,
            ExecRule("echo posix-sh", "posix-sh", 0),
            ExecRule("find .", "3", 0),
        )
    )
    outcome = run(api, tools=(COMPILEALL, TRIVIAL_TOOL))
    assert outcome.report.status is RunnerStatus.COMPLETED
    assert len(api.argv_seen) == 8
    for argv, stdin in zip(api.argv_seen, api.stdin_seen, strict=True):
        assert argv == exec_argv(_inner(argv[-1]), len(stdin))


def _inner(script):
    body = script.split("{ ", 1)[1]
    return body.rsplit("\n}", 1)[0]


def test_only_commands_without_input_get_the_first_frame_window():
    api = FakeSprites(rules=PY_RULES)
    run_disposable(
        api, MemoryLedger(), RunnerJob(b"tarball-bytes", (COMPILEALL,)), name=NAME,
        deadline_s=600.0, clock=FakeClock(), first_frame_s=5.0,
    )  # fmt: skip
    assert api.first_bytes_seen == [5.0, 5.0, None, 5.0, 5.0, 5.0]
    run(api := FakeSprites(rules=PY_RULES), tools=(COMPILEALL,), deadline_s=600.0)
    assert set(api.first_bytes_seen) - {None} == {FIRST_FRAME_BUDGET_S}


def test_the_first_frame_window_never_exceeds_the_exec_budget():
    api = FakeSprites(rules=PY_RULES)
    run(api, tools=(COMPILEALL,), deadline_s=12.0)
    assert api.first_bytes_seen[0] == 12.0


class _SilentVersion(FakeSprites):
    """The failure behind D28: `python3 --version` sends nothing back."""

    def __init__(self, clock, **kwargs):
        super().__init__(rules=PY_RULES, **kwargs)
        self.clock = clock

    def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
        if "-I --version" in argv[-1] and first_byte_s is not None:
            super().exec(name, argv, stdin, timeout_s, first_byte_s)
            self.clock.advance(first_byte_s)
            raise StreamTimeoutError(
                f"POST https://api.sprites.dev/v1/sprites/{name}/exec: "
                f"no response byte within {first_byte_s:g}s",
                first_byte=True,
            )
        return super().exec(name, argv, stdin, timeout_s, first_byte_s)


def test_a_silent_tool_exec_fails_fast_with_a_stage_aware_label():
    clock = FakeClock()
    outcome, events = run_traced(
        _SilentVersion(clock), clock=clock, tools=(COMPILEALL,)
    )
    assert outcome.report.status is RunnerStatus.FAILED
    assert outcome.report.note == (
        "exec / python-compileall version failed after 30.0s (30.0s into the run): "
        "tool python-compileall stage, python-compileall version: silent -- no "
        "output frame for a command that sends no input, not even the start marker "
        f"(POST https://api.sprites.dev/v1/sprites/{NAME}/exec: no response byte "
        "within 30s)"
    )
    failed = next(e for e in events if e.status == "error")
    assert (failed.phase, failed.step) == ("exec", "python-compileall version")
    assert failed.fields["stage"] == "tool python-compileall"
    assert failed.fields["first_frame_s"] == FIRST_FRAME_BUDGET_S
    assert failed.fields["timeout_s"] == 135.0
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED


def test_a_stalled_exec_reports_the_bytes_and_frames_that_did_arrive():
    class Stalls(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if "tar -xzf" in argv[-1]:
                raise StreamTimeoutError(
                    "POST x: response incomplete after 20 byte(s) within 120s",
                    b"\x01__ATLAS_START__\ntar: ",
                )
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    outcome = run(Stalls(rules=PY_RULES), tools=(COMPILEALL,))
    assert outcome.report.note.startswith(
        "exec / source unpack failed after 0.0s (0.0s into the run): unpack stage, "
        "source unpack: output stopped before the exit marker after 22 byte(s) "
        "(frames 0x01:1), last output '__ATLAS_START__ tar:' (POST x: "
    )


def test_the_tool_check_reports_where_each_binary_resolves():
    _, events = run_traced(FakeSprites(rules=PY_RULES), tools=(COMPILEALL,))
    availability = next(e for e in events if e.step == "availability")
    assert availability.fields == {
        "has_python3": True,
        "path_python3": "/usr/bin/python3 -> /usr/bin/python3",
    }
    assert 'p=$(command -v "$b"' in probe_script(("python3",))
    assert 'readlink -f "$p"' in probe_script(("python3",))


def test_resolved_paths_are_parsed_only_from_well_formed_probe_lines():
    text = (
        "atlas-probe:present:python3:/home/sprite/.shims/python3:/usr/bin/mise\n"
        "atlas-probe:present:ruff:/x y:/z\n"
        "atlas-probe:absent:shellcheck\n"
    )
    assert parse_paths(text) == {
        "python3": "/home/sprite/.shims/python3 -> /usr/bin/mise"
    }


_CREDENTIAL = "opaque-credential-" + fake_token("", 24)


def _scrubbers():
    """The default (secret patterns) and a controller-bound redactor whose
    credential matches no pattern; a returned field must pass both."""
    return [
        pytest.param(fake_token("sk-ant-"), None, id="default patterns"),
        pytest.param(
            _CREDENTIAL,
            lambda text: Redactor((_CREDENTIAL,))(text).text,
            id="controller credential",
        ),
    ]


def _leaky_review(secret, scrub, rules=(), failed_checks=()):
    class Leaky(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if "PYENV_VERSION" in argv[-1]:
                raise BoundaryError(f"exec closed after {secret}")
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

        def _answer(self, script, stdin):
            if any(tag in script for tag in failed_checks):
                return f"broken {secret}", 2
            return super()._answer(script, stdin)

    clock = FakeClock()
    return run_disposable(
        Leaky(rules=rules), MemoryLedger(),
        RunnerJob(b"tarball-bytes", (*TOOLS, COMPILEALL), diagnose=True),
        name=NAME, deadline_s=60.0, clock=clock,
        telemetry=None if scrub is None else Telemetry(clock, scrub=scrub),
    )  # fmt: skip


@pytest.mark.parametrize("secret,scrub", _scrubbers())
def test_returned_tool_and_diagnostic_text_is_scrubbed(secret, scrub):
    outcome = _leaky_review(
        secret,
        scrub,
        rules=(
            ExecRule("tar -xzf", "", 0),
            ExecRule("ruff --version", f"ruff 0.17.3 {secret}", 0),
            ExecRule("ruff check", f"a.py:1:1: F401 leaked {secret}\nmore", 1),
            ExecRule("shellcheck --version", f"denied {secret}", 2),
            ExecRule("-I --version", "Python 3.13.7", 0),
            ExecRule("compileall", "", 0),
            ExecRule("ls -1", f"3.13.7 {secret}", 0),
        ),
    )
    ruff, shellcheck, _ = outcome.results
    assert isinstance(ruff, ToolRan) and isinstance(shellcheck, ToolAbsent)
    returned = [
        ruff.version, ruff.output, shellcheck.detail,
        *(d.detail for d in outcome.diagnostics),
    ]  # fmt: skip
    assert all(secret not in text for text in returned), returned
    assert "[REDACTED" in ruff.output and ruff.output.endswith("\nmore")
    assert all("[REDACTED" in text for text in (ruff.version, shellcheck.detail))
    assert any("[REDACTED" in d.detail for d in outcome.diagnostics)


@pytest.mark.parametrize("secret,scrub", _scrubbers())
def test_a_failed_check_detail_returned_on_a_tool_is_scrubbed(secret, scrub):
    outcome = _leaky_review(
        secret,
        scrub,
        rules=(ExecRule("tar -xzf", "", 0),),
        failed_checks=(PROBE_TAG, PYTHON_TAG),
    )
    details = [r.detail for r in outcome.results if isinstance(r, ToolAbsent)]
    assert len(details) == 3
    assert all(secret not in d and "[REDACTED" in d for d in details), details


@pytest.mark.parametrize("secret,scrub", _scrubbers())
def test_returned_probe_checks_are_scrubbed(secret, scrub):
    class Leaky(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if stdin or "atlas-egress" in argv[-1]:
                raise BoundaryError(f"exec closed after {secret}")
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    clock = FakeClock()
    outcome = probe_runner(
        Leaky(), MemoryLedger(), TOOLS, name=NAME, deadline_s=60, clock=clock,
        telemetry=None if scrub is None else Telemetry(clock, scrub=scrub),
    )  # fmt: skip
    for text in (outcome.stdin_check, outcome.egress_check):
        assert secret not in text and "[REDACTED" in text, text


def test_each_failed_delete_attempt_is_labelled_with_its_own_attempt():
    api = FakeSprites(rules=OK_RULES, fail_on={"delete": BoundaryError("HTTP 500")})
    outcome, events = run_traced(api)
    assert outcome.report.cleanup is CleanupStatus.DESTROY_UNVERIFIED
    deletes = [e for e in events if e.step.startswith("delete attempt")]
    assert [e.error.split(" failed")[0] for e in deletes] == [
        f"destroy / {e.step}" for e in deletes
    ]
    assert {e.step for e in deletes} == {"delete attempt 1", "delete attempt 2"}
