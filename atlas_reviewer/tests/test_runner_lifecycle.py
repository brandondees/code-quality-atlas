# SPDX-License-Identifier: MIT
"""The runner must be destroyed on every path, and nothing may execute
inside it before deny-all egress is set and read back from outside."""

import time

import pytest

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import CleanupStatus, RunnerStatus
from atlas_reviewer.fakes import ExecRule, FakeSprites, MemoryLedger
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.runner import (
    DENY_ALL,
    RunnerJob,
    ToolAbsent,
    ToolRan,
    ToolSpec,
    decode_exec_output,
    destroy_runner,
    parse_exit,
    run_disposable,
    runner_name,
    sweep,
)

from .helpers import CallbackRule, FakeClock

NAME = "cqa-rev-20261106-230000-abc123"
TOOLS = (
    ToolSpec("ruff", "ruff --version", "ruff check ."),
    ToolSpec("shellcheck", "shellcheck --version", "shellcheck x.sh"),
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


def test_policy_read_back_that_is_not_deny_all_blocks_execution():
    api = FakeSprites(
        rules=OK_RULES, policy_read_back={"rules": [{"include": "defaults"}]}
    )
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
    assert "source upload failed" in outcome.report.note


def test_nothing_credential_like_is_passed_into_the_runner():
    api = FakeSprites(rules=OK_RULES)
    run(api)
    scripts = [c[2] for c in api.calls if c[0] == "exec"]
    assert all("TOKEN" not in s and "Authorization" not in s for s in scripts)
    assert api.stdin_seen[0] == b"tarball-bytes"
    assert set(api.stdin_seen[1:]) == {b""}


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
        def exec(self, name, argv, stdin, timeout_s):
            super().exec(name, argv, stdin, timeout_s)
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


def test_runner_names_are_prefixed_and_unique():
    clock = FakeClock()
    assert runner_name(clock, lambda n: "ab" * n) == "cqa-rev-20261106-230000-ababab"
    assert runner_name(clock) != runner_name(clock)
