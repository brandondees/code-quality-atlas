# SPDX-License-Identifier: MIT
"""The runner must be destroyed on every path, and nothing may execute
inside it before deny-all egress is set and read back from outside."""

import time

import pytest

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import CleanupStatus, RunnerStatus
from atlas_reviewer.fakes import ExecRule, FakeSprites, MemoryLedger
from atlas_reviewer.ports import BoundaryError, StreamTimeoutError
from atlas_reviewer.runner import (
    DENY_ALL,
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
    exec_argv,
    frames_seen,
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

from .helpers import CallbackRule, FakeClock

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
    ],
)
def test_policy_read_back_that_is_not_deny_all_blocks_execution(read_back):
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


def test_create_failure_still_attempts_destroy():
    api = FakeSprites(fail_on={"create": BoundaryError("create 503")})
    ledger = MemoryLedger()
    outcome = run(api, ledger)
    assert outcome.report.status is RunnerStatus.FAILED
    assert "delete" in ops(api)
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
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
    api = FakeSprites(rules=OK_RULES, hang_on="ruff check")
    started = time.monotonic()
    outcome = run(api, clock=SystemClock(), deadline_s=0.3)
    assert time.monotonic() - started < 5
    assert outcome.report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()
    assert ops(api).count("delete") == 1


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


def test_nothing_credential_like_is_passed_into_the_runner():
    api = FakeSprites(rules=OK_RULES)
    run(api)
    scripts = [c[2] for c in api.calls if c[0] == "exec"]
    assert all("TOKEN" not in s and "Authorization" not in s for s in scripts)
    assert [s for s in api.stdin_seen if s] == [b"tarball-bytes"]


def test_network_policy_sent_is_deny_all():
    api = FakeSprites(rules=OK_RULES)
    run(api)
    assert list(DENY_ALL) == [{"action": "deny", "domain": "*"}]


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


def test_tool_without_exit_marker_reports_no_exit_code():
    class NoMarker(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            super().exec(name, argv, stdin, timeout_s, first_byte_s)
            return b"truncated output"

    api = NoMarker(rules=OK_RULES)
    outcome = run(api, tools=())
    assert outcome.report.status is RunnerStatus.FAILED
    assert "exit None" in outcome.report.note


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

    outcome = run(BrokenProbe(rules=OK_RULES))
    assert outcome.report.status is RunnerStatus.COMPLETED
    assert all(isinstance(r, ToolAbsent) for r in outcome.results)


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
    assert [len(x) for x in api.stdin_seen[2:]] == [STDIN_CHECK_BYTES]
    assert outcome.stdin_check == (
        f"ok: sent {STDIN_CHECK_BYTES} bytes, runner received {STDIN_CHECK_BYTES}"
    )
    assert ops(api)[:3] == ["create", "set_network_policy", "get_network_policy"]


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
    assert by_step[("verify", "existence check")] == {"present": False}
    assert by_step[("destroy", "outcome")] == {"cleanup": "destroyed (verified absent)"}


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
    assert events[-1].fields == {"cleanup": "destroyed (verified absent)"}


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

    outcome, _ = run_traced(ShortWrite(rules=OK_RULES))
    assert outcome.report.status is RunnerStatus.FAILED
    assert "upload / 13-byte tarball failed after" in outcome.report.note
    assert "runner wrote 5 of 13 bytes (exit 0)" in outcome.report.note
    assert "tar -xzf" not in " ".join(c[-1] for c in ShortWrite().calls)


def test_destroy_attempts_and_verification_are_recorded_when_delete_fails():
    api = FakeSprites(rules=OK_RULES, fail_on={"delete": BoundaryError("HTTP 500")})
    _, events = run_traced(api)
    tail = [(e.phase, e.step, e.status) for e in events[-3:]]
    assert tail == [
        ("destroy", "delete attempt 1", "error"),
        ("destroy", "delete attempt 2", "error"),
        ("destroy", "outcome", "ok"),
    ]
    assert events[-1].fields == {"cleanup": "destroy NOT verified -- run `sweep`"}


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
        "(frames 0x01:1), last output '__ATLAS_START__\\ntar: ' (POST x: "
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
