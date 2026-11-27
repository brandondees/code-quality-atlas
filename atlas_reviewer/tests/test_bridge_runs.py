# SPDX-License-Identifier: MIT
"""The execution tools `run_tests` and `mutate` (D80), run for real where
the machine can run them: `LocalSprites` executes every script, so the
staged copy, the mutation edit, the mutant commit and the pytest runs are
exercised against a fixture suite through this machine's own interpreter,
which the tests name as the one extra probe candidate. The framing, the
verdict logic and the probe's trust rules a live runner would answer are
additionally tested against scripted fakes and directly. No Sprite or
GitHub call is made; the fixture suite is built here and executed from a
staged copy."""

import base64
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pytest

from atlas_reviewer.bridge import (
    DEFAULT_LIMITS,
    EXEC_SLACK_S,
    KILL_AFTER_S,
    MUTATION_SCRIPT,
    SWEEP_BUDGET_S,
    SWEEP_RUN_BOUND_S,
    MutantOutcome,
    SessionLimits,
    Status,
    SweepGroup,
    SweepSpec,
    ToolLimits,
    _aim_refusal,
    _imports_module,
    _MutBlock,
    _pytest_argv,
    _run_status,
    _RunBlock,
    _splice,
    added_lines,
    bash_script,
    mutant_outcome,
    mutate_script,
    mutation_refusal,
    parse_mutation,
    parse_run_blocks,
    parse_summary,
    parse_sweep,
    render,
    run_bridge,
    run_probe_script,
    run_test_script,
    run_tool_limits,
    sweep_groups,
    sweep_script,
    sweep_specs,
)
from atlas_reviewer.bridge_args import MAX_BASH_CHARS, Rev, validate
from atlas_reviewer.bridge_staging import (
    DROP_SHIM,
    NOBODY_UID,
    SYSTEM_PYTHON,
    SourceTrees,
    Staged,
    choose_pytest,
    collection_script,
    guarded_env_exports,
    parse_collection,
    parse_history,
    stage_copy_steps,
)
from atlas_reviewer.domain import CleanupStatus, RunnerStatus
from atlas_reviewer.fakes import (
    PYENV_PYTHON,
    ExecRule,
    FakeSprites,
    MemoryLedger,
)
from atlas_reviewer.interpreter import TrustedPython
from atlas_reviewer.local_runner import LocalSprites
from atlas_reviewer.ports import BoundaryError, StreamTimeoutError
from atlas_reviewer.redact import Redactor
from atlas_reviewer.telemetry import Telemetry

from .helpers import HEAD, OLD, FakeClock, source_tarball
from .test_bridge import NEW_TOKEN

PYTEST = sys.executable

CALC = "def total(xs):\n    if not xs:\n        return 0\n    return sum(xs)\n"
TEST_TOTAL = (
    "from calc import total\n\ndef test_two_values():\n    assert total([1, 2]) == 3\n"
)
REQUIRE = (
    "def require(xs):\n"
    "    if xs is None:\n"
    '        raise ValueError("xs is required")\n'
    "    return sum(xs)\n"
)
TEST_REQUIRE = (
    "import pytest\n\n"
    "from require import require\n\n"
    "def test_none_is_refused():\n"
    "    with pytest.raises(ValueError):\n"
    "        require(None)\n"
)
SUITE = {
    "calc.py": CALC.encode(),
    "test_calc.py": TEST_TOTAL.encode(),
    "require.py": REQUIRE.encode(),
    "test_require.py": TEST_REQUIRE.encode(),
}


def trees(head, base=None):
    return SourceTrees(
        source_tarball(base if base is not None else head),
        source_tarball(head),
        OLD,
        HEAD,
    )


def bridge_run(tmp_path, body, source=None, sprites=None, **kw):
    sprites = sprites if sprites is not None else LocalSprites()
    clock = FakeClock()
    telemetry = Telemetry(clock)
    report = run_bridge(
        sprites,
        MemoryLedger(),
        source or trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset({"calc.py"}),
        name="cqa-run-tools-test",
        deadline_s=300,
        clock=clock,
        telemetry=telemetry,
        root=str(tmp_path / "bridge"),
        pytest_candidates=kw.pop("pytest_candidates", (PYTEST,)),
        **kw,
    )
    return report, sprites, telemetry


def calls(tmp_path, *requests, **kw):
    """Each `(tool, args)` in order; returns the results and the bridge."""
    results, bridges = [], []

    def body(bridge):
        bridges.append(bridge)
        results.extend(bridge.call(tool, args) for tool, args in requests)
        return f"{len(results)} call(s)"

    report, *_ = bridge_run(tmp_path, body, **kw)
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    return results, bridges[0]


def one(tmp_path, tool, args=None, **kw):
    (result,), *_ = calls(tmp_path, (tool, args or {}), **kw)
    return result


# ------------------------------------------------------------ the pytest probe


def test_the_probe_records_a_pytest_capable_interpreter_and_the_head_sha(
    tmp_path,
):
    _results, bridge = calls(tmp_path, ("diff_stat", {}))
    assert bridge.staged.pytest is not None
    assert bridge.staged.pytest.path == PYTEST
    assert bridge.staged.pytest.version.startswith("3.")
    assert bridge.staged.head_sha == HEAD


def test_the_staged_telemetry_names_the_pytest_probe_answer(tmp_path):
    def body(bridge):
        return "ok"

    _report, _sprites, telemetry = bridge_run(tmp_path, body)
    (staged,) = [e for e in telemetry.events if e.step == "staged"]
    assert staged.fields["pytest"] == PYTEST
    assert staged.fields["revisions"] == 2


def test_choose_pytest_prefers_the_newest_pyenv_interpreter():
    text = f"atlas-pytest:{SYSTEM_PYTHON}:3.12.1\natlas-pytest:{PYENV_PYTHON}:3.13.7\n"
    chosen = choose_pytest(text)
    assert chosen is not None and chosen.path == PYENV_PYTHON


def test_choose_pytest_takes_the_system_python_when_no_pyenv_has_pytest():
    chosen = choose_pytest(f"atlas-pytest:{SYSTEM_PYTHON}:3.12.3\n")
    assert chosen is not None and chosen.path == SYSTEM_PYTHON


def test_choose_pytest_refuses_a_path_outside_the_trusted_shapes():
    assert choose_pytest("atlas-pytest:/tmp/evil/python3:3.12.3\n") is None


def test_choose_pytest_accepts_exactly_a_literal_candidate_the_caller_named():
    text = f"atlas-pytest:{PYTEST}:3.12.3\n"
    chosen = choose_pytest(text, (PYTEST,))
    assert chosen is not None and chosen.path == PYTEST
    assert choose_pytest(text) is None


def test_choose_pytest_needs_a_three_part_version():
    assert choose_pytest(f"atlas-pytest:{SYSTEM_PYTHON}:3\n") is None


# ------------------------------------------------- the fixed mutation script


def edit(tmp_path, text, line, operator, operand=None):
    path = tmp_path / "m.py"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    extra = [str(operand)] if operand is not None else []
    result = subprocess.run(
        [sys.executable, "-I", "-c", MUTATION_SCRIPT, str(path), str(line), operator, *extra],
        check=False, capture_output=True, text=True,
    )  # fmt: skip
    return result, path


def payload_of(result):
    status, _, rest = result.stdout.strip().partition(" ")
    return status, rest


def test_negate_condition_wraps_the_condition_in_not(tmp_path):
    result, path = edit(tmp_path, CALC, 2, "negate-condition")
    assert result.returncode == 0
    status, rest = payload_of(result)
    assert status == "ok"
    before, after = rest.split(" ")
    assert base64.b64decode(before).decode() == "not xs"
    assert base64.b64decode(after).decode() == "not (not xs)"
    assert "if not (not xs):" in path.read_text()
    # The rest of the file is byte-identical: no whole-module rewrite.
    assert "return sum(xs)" in path.read_text()


def test_remove_guard_replaces_the_body_with_pass(tmp_path):
    result, path = edit(tmp_path, REQUIRE, 2, "remove-guard")
    assert result.returncode == 0
    status, rest = payload_of(result)
    assert status == "ok"
    before, after = rest.split(" ")
    assert base64.b64decode(before).decode() == 'raise ValueError("xs is required")'
    assert base64.b64decode(after).decode() == "pass"
    assert "if xs is None:\n        pass" in path.read_text()
    assert "return sum(xs)" in path.read_text()


def test_negate_condition_applies_to_while_and_the_conditional_expression(tmp_path):
    result, path = edit(
        tmp_path, "def spin(n):\n    while n > 0:\n        n -= 1\n    return n\n",
        2, "negate-condition",
    )  # fmt: skip
    assert result.returncode == 0
    assert "while not (n > 0):" in path.read_text()
    result, path = edit(
        tmp_path, "def pick(n):\n    return 1 if n else 2\n", 2, "negate-condition"
    )
    assert result.returncode == 0
    assert "1 if not (n) else 2" in path.read_text()


def test_a_statement_the_operator_does_not_apply_to_is_refused(tmp_path):
    result, _ = edit(tmp_path, "x = 1\n", 1, "negate-condition")
    assert result.returncode == 0
    status, rest = payload_of(result)
    assert (status, base64.b64decode(rest).decode()) == (
        "no",
        "the operator does not apply to the statement at that line",
    )


def test_a_line_without_a_statement_is_refused(tmp_path):
    result, _ = edit(tmp_path, CALC, 99, "remove-guard")
    status, rest = payload_of(result)
    assert (status, base64.b64decode(rest).decode()) == (
        "no",
        "no statement starts at that line",
    )


def test_a_file_that_does_not_parse_is_refused(tmp_path):
    result, _ = edit(tmp_path, "def broken(:\n", 1, "remove-guard")
    status, rest = payload_of(result)
    assert (status, base64.b64decode(rest).decode()) == (
        "no",
        "the file does not parse",
    )


def test_a_file_that_is_not_utf_8_is_refused(tmp_path):
    path = tmp_path / "m.py"
    path.write_bytes(b"\xff\xfe\x00")
    result = subprocess.run(
        [sys.executable, "-I", "-c", MUTATION_SCRIPT, str(path), "1", "remove-guard"],
        check=False, capture_output=True, text=True,
    )  # fmt: skip
    status, rest = payload_of(result)
    assert (status, base64.b64decode(rest).decode()) == (
        "no",
        "the file could not be read as UTF-8 text",
    )


@pytest.mark.skipif(
    hasattr(os, "getuid") and os.getuid() == 0,
    reason="a chmod-based refusal is a no-op for uid 0",
)
def test_an_unwritable_copy_is_refused_without_a_partial_write(tmp_path):
    path = tmp_path / "m.py"
    path.write_text(CALC, encoding="utf-8")
    tmp_path.chmod(0o555)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                MUTATION_SCRIPT,
                str(path),
                "2",
                "remove-guard",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        tmp_path.chmod(0o755)
    status, rest = payload_of(result)
    assert (status, base64.b64decode(rest).decode()) == (
        "no",
        "the copy could not be written",
    )
    assert path.read_text() == CALC
    assert not (tmp_path / "m.py.atlas-mutant").exists()


def test_a_multi_line_statement_is_cited_whole(tmp_path):
    text = "def pick(n):\n    if (\n        n\n    ):\n        return 1\n    return 2\n"
    result, _ = edit(tmp_path, text, 2, "negate-condition")
    status, rest = payload_of(result)
    assert status == "ok"
    before, _ = rest.split(" ")
    assert base64.b64decode(before).decode() == "n"


# ----------------------------------------------------------------- run_tests


def test_run_tests_runs_the_whole_suite_and_tags_the_head(tmp_path):
    result = one(tmp_path, "run_tests")
    assert result.status is Status.OK
    (run,) = result.runs
    assert run.exit == 0
    assert run.summary is not None and run.summary.count("passed") == 2
    assert result.head_sha == HEAD
    rendered = render(result)
    assert f"head {HEAD}" in rendered
    assert "test run: exit 0, 2 passed" in rendered


def test_run_tests_runs_the_named_file_only(tmp_path):
    result = one(tmp_path, "run_tests", {"path": "test_require.py"})
    assert result.status is Status.OK
    (run,) = result.runs
    assert run.exit == 0 and run.summary.count("passed") == 1


def test_a_selector_that_names_a_node_id_runs_that_test(tmp_path):
    result = one(tmp_path, "run_tests", {"path": "test_calc.py::test_two_values"})
    (run,) = result.runs
    assert run.exit == 0 and run.summary.count("passed") == 1


def test_a_failing_suite_is_a_result_not_a_tool_failure(tmp_path):
    source = trees(
        {
            **SUITE,
            "test_bad.py": b"def test_bad():\n    assert 0\n",
        }
    )
    result = one(tmp_path, "run_tests", source=source)
    assert result.status is Status.OK
    (run,) = result.runs
    assert run.exit == 1
    assert run.summary is not None and run.summary.count("failed") == 1
    assert "test_bad" in result.content.text
    assert not result.truncated


def test_a_selector_that_collects_nothing_reports_no_test_ran(tmp_path):
    result = one(tmp_path, "run_tests", {"path": "no/such/file.py"})
    assert result.status is Status.OK
    (run,) = result.runs
    assert run.exit == 4
    assert run.summary is not None and not run.summary.ran


def test_the_copy_is_the_head_tree_not_the_base(tmp_path):
    source = trees(
        SUITE, base={"calc.py": b"def broken(:\n", "test_calc.py": TEST_TOTAL.encode()}
    )
    result = one(tmp_path, "run_tests", source=source)
    assert result.status is Status.OK
    (run,) = result.runs
    assert run.exit == 0 and run.summary.count("passed") == 2


def test_a_pr_file_named_pytest_cannot_shadow_the_runner(tmp_path):
    source = trees({**SUITE, "pytest.py": b"raise SystemExit('shadowed')\n"})
    result = one(tmp_path, "run_tests", source=source)
    assert result.status is Status.OK
    (run,) = result.runs
    assert run.exit == 0


def test_a_run_past_its_wall_clock_is_a_timeout(tmp_path):
    source = trees(
        {
            "test_slow.py": b"import time\n\ndef test_slow():\n    time.sleep(10)\n",
        }
    )
    limits = {**DEFAULT_LIMITS, "run_tests": ToolLimits(16 * 1024, 1)}
    result = one(tmp_path, "run_tests", source=source, limits=limits)
    assert result.status is Status.TIMED_OUT
    (run,) = result.runs
    assert run.exit == 124


def test_the_shown_output_is_the_runs_tail_and_the_cut_is_named(tmp_path):
    # pytest captures a passing test's stdout, so the loud test fails to
    # make its own output part of the report the run shows.
    lines = "\n".join(f"    print({i})" for i in range(200))
    source = trees(
        {"test_loud.py": f"def test_loud():\n{lines}\n    assert 0\n".encode()}
    )
    limits = {**DEFAULT_LIMITS, "run_tests": ToolLimits(400, 60)}
    result = one(tmp_path, "run_tests", source=source, limits=limits)
    assert result.truncated
    assert result.shown_bytes == 400
    assert "199" in result.content.text
    assert "\n1\n" not in result.content.text
    assert f"; output cut: {result.shown_bytes} of" in render(result)


def test_a_secret_a_test_prints_is_flagged_and_never_located_in_the_tree(tmp_path):
    source = trees(
        {
            "test_leak.py": (
                f"def test_leak():\n    assert False, 'printed {NEW_TOKEN}'\n".encode()
            ),
        }
    )
    result = one(tmp_path, "run_tests", source=source)
    assert result.secrets
    assert all(
        (s.path, s.line, s.preexisting) == (None, None, True) for s in result.secrets
    )
    assert NEW_TOKEN in result.values


def test_a_run_counts_against_its_own_cap(tmp_path):
    (first, second), _ = calls(
        tmp_path, ("run_tests", {}), ("run_tests", {}),
        session_limits=SessionLimits(max_test_runs=1),
    )  # fmt: skip
    assert first.status is Status.OK
    assert second.status is Status.OVER_SESSION_LIMIT
    assert "all 1 run_tests calls of this attempt made" in second.error.text


def test_no_pytest_staged_makes_the_tools_unavailable_not_broken(tmp_path):
    result = one(tmp_path, "run_tests", pytest_candidates=())
    assert result.status is Status.UNAVAILABLE
    assert "no pytest-capable interpreter" in result.error.text


def test_run_tests_rejects_a_selector_that_is_an_option(tmp_path):
    result = one(tmp_path, "run_tests", {"path": "-k"})
    assert result.status is Status.REJECTED
    assert result.content.text == ""


# -------------------------------------------------------------------- mutate


def test_a_mutant_the_tests_catch_is_killed_and_the_tag_names_the_tree(tmp_path):
    reads = []

    def body(bridge):
        result = bridge.call(
            "mutate",
            {"path": "require.py", "line": 2, "operator": "negate-condition"},
        )
        reads.append(result)
        reads.append(bridge.call("read_file", {"rev": "MUTANT", "path": "require.py"}))
        reads.append(bridge.call("read_file", {"rev": "HEAD", "path": "require.py"}))
        reads.append(Rev.MUTANT in bridge.commits)
        return "done"

    report, *_ = bridge_run(tmp_path, body)
    assert report.status is RunnerStatus.COMPLETED, report.note
    result, read, head, tagged = reads
    assert result.status is Status.OK
    assert result.outcome is MutantOutcome.KILLED
    assert result.outcome_reason == "the mutated run failed (exit 1)"
    assert result.mutation is not None
    assert result.mutation.commit
    assert result.mutation.before == "xs is None"
    assert result.mutation.after == "not (xs is None)"
    baseline, mutated = result.runs
    assert (baseline.exit, mutated.exit) == (0, 1)
    assert "baseline run: exit 0, 2 passed" in render(result)
    assert "mutated run: exit 1, 1 passed, 1 failed" in render(result)
    assert f"mutant {result.mutation.commit} killed" in render(result)
    assert f"head {HEAD}" in render(result)
    # The mutated run's output is the shown one (the failing run, not the
    # passing baseline), and the mutated tree is readable at MUTANT while
    # HEAD stays what it was.
    assert result.content.text != ""
    assert "FAILED" in result.content.text
    assert "if not (xs is None):" in read.content.text
    assert head.content.text == REQUIRE
    assert tagged is True


def test_a_mutant_the_tests_do_not_pin_survives(tmp_path):
    result = one(
        tmp_path, "mutate",
        {"path": "calc.py", "line": 2, "operator": "remove-guard"},
    )  # fmt: skip
    assert result.outcome is MutantOutcome.SURVIVED
    assert result.outcome_reason == (
        "the baseline run passed and the mutated run passed too"
    )
    baseline, mutated = result.runs
    assert (baseline.exit, mutated.exit) == (0, 0)
    assert "survived" in render(result)


def test_a_mutation_that_does_not_apply_is_refused_and_commits_nothing(tmp_path):
    (result,), bridge = calls(
        tmp_path,
        ("mutate", {"path": "calc.py", "line": 1, "operator": "negate-condition"}),
    )
    assert result.status is Status.REJECTED
    assert "the mutant was refused" in result.error.text
    assert "the operator does not apply" in result.error.text
    assert result.runs == ()
    assert result.mutation is None or result.mutation.commit == ""
    assert Rev.MUTANT not in bridge.commits


def test_an_already_failing_baseline_is_inconclusive(tmp_path):
    source = trees(
        {
            "calc.py": CALC.encode(),
            "test_bad.py": b"def test_bad():\n    assert 0\n",
        }
    )
    result = one(
        tmp_path, "mutate",
        {"path": "calc.py", "line": 2, "operator": "remove-guard"}, source=source,
    )  # fmt: skip
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "the baseline run already fails (exit 1)"


def test_an_all_skipping_baseline_is_inconclusive(tmp_path):
    source = trees(
        {
            "calc.py": CALC.encode(),
            "test_skip.py": (
                b"import pytest\n\n\n@pytest.mark.skip(reason='not now')\n"
                b"def test_skipped():\n    assert False\n"
            ),
        }
    )
    result = one(
        tmp_path, "mutate",
        {"path": "calc.py", "line": 2, "operator": "remove-guard"}, source=source,
    )  # fmt: skip
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "no test ran in the baseline run"


def test_a_baseline_with_nothing_collected_is_inconclusive(tmp_path):
    result = one(
        tmp_path,
        "mutate",
        {
            "path": "calc.py",
            "line": 2,
            "operator": "remove-guard",
            "tests": "gone.py",
        },
    )
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "the test run stopped before collecting (exit 4)"


def test_a_baseline_past_its_wall_clock_is_inconclusive(tmp_path):
    source = trees(
        {
            "calc.py": CALC.encode(),
            "test_slow.py": b"import time\n\ndef test_slow():\n    time.sleep(10)\n",
        }
    )
    limits = {**DEFAULT_LIMITS, "mutate": ToolLimits(16 * 1024, 1)}
    result = one(
        tmp_path, "mutate",
        {"path": "calc.py", "line": 2, "operator": "remove-guard"},
        source=source, limits=limits,
    )  # fmt: skip
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "the baseline run hit its wall clock"


def test_a_mutated_run_past_its_wall_clock_is_inconclusive(tmp_path):
    source = trees(
        {
            "spin.py": (
                b"def spin(n):\n"
                b"    while True:\n"
                b"        if n > 0:\n"
                b"            n = n - 1\n"
                b"        else:\n"
                b"            return n\n"
            ),
            "test_spin.py": (
                b"from spin import spin\n\ndef test_spin():\n    assert spin(3) == 0\n"
            ),
        }
    )
    limits = {**DEFAULT_LIMITS, "mutate": ToolLimits(16 * 1024, 1)}
    result = one(
        tmp_path, "mutate",
        {"path": "spin.py", "line": 3, "operator": "remove-guard"},
        source=source, limits=limits,
    )  # fmt: skip
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "the mutated run hit its wall clock"


def test_a_second_mutate_moves_the_one_tag(tmp_path):
    results, _bridge = calls(
        tmp_path,
        ("mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}),
        ("mutate", {"path": "require.py", "line": 2, "operator": "negate-condition"}),
        ("read_file", {"rev": "MUTANT", "path": "require.py"}),
    )
    first, second, read = results
    assert first.outcome is MutantOutcome.SURVIVED
    assert second.outcome is MutantOutcome.KILLED
    assert second.mutation.commit != first.mutation.commit
    assert "if not (xs is None):" in read.content.text


def test_the_review_trees_stay_read_only_across_a_mutate(tmp_path):
    source = trees(
        SUITE,
        base={
            "calc.py": b"def total(xs):\n    return sum(xs)\n",
            "test_calc.py": TEST_TOTAL.encode(),
        },
    )
    results, _ = calls(
        tmp_path,
        ("read_file", {"rev": "HEAD", "path": "calc.py"}),
        ("mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}),
        ("read_file", {"rev": "HEAD", "path": "calc.py"}),
        ("diff_stat", {}),
        source=source,
    )
    before, _mutant, after, stat = results
    assert before.content.text == after.content.text == CALC
    assert "calc.py" in stat.content.text


def test_a_mutate_counts_against_its_own_cap_and_leaves_reads_free(tmp_path):
    results, _ = calls(
        tmp_path,
        ("mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}),
        ("mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}),
        ("run_tests", {}),
        session_limits=SessionLimits(max_mutants=1),
    )
    assert results[0].status is Status.OK
    assert results[1].status is Status.OVER_SESSION_LIMIT
    assert "all 1 mutate calls of this attempt made" in results[1].error.text
    assert results[2].status is Status.OK


def test_an_attempt_budget_starts_the_execution_caps_over(tmp_path):
    outcomes = []

    def body(bridge):
        bridge.begin_attempt("lens", 1)
        outcomes.append(
            bridge.call(
                "mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}
            )
        )
        outcomes.append(
            bridge.call(
                "mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}
            )
        )
        bridge.begin_attempt("lens", 2)
        outcomes.append(
            bridge.call(
                "mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}
            )
        )
        return "done"

    report, *_ = bridge_run(tmp_path, body, session_limits=SessionLimits(max_mutants=1))
    assert report.status is RunnerStatus.COMPLETED, report.note
    first, second, again = outcomes
    assert first.status is Status.OK
    assert second.status is Status.OVER_SESSION_LIMIT
    assert "all 1 mutate calls of this attempt made" in second.error.text
    assert again.status is Status.OK


def test_mutate_rejects_an_unknown_operator(tmp_path):
    result = one(
        tmp_path, "mutate",
        {"path": "calc.py", "line": 2, "operator": "rewrite-everything"},
    )  # fmt: skip
    assert result.status is Status.REJECTED
    assert "must be one of the mutant operators" in result.error.text


def test_mutate_needs_its_path_line_and_operator(tmp_path):
    result = one(tmp_path, "mutate", {"path": "calc.py", "operator": "remove-guard"})
    assert result.status is Status.REJECTED
    assert "line" in result.error.text


def test_read_file_at_mutant_before_any_mutate_is_rejected(tmp_path):
    result = one(tmp_path, "read_file", {"rev": "MUTANT", "path": "calc.py"})
    assert result.status is Status.REJECTED
    assert "must be one of the staged revisions" in result.error.text


# ------------------------------------------------------- scripted framing


@dataclass
class ReplyRule:
    """Answers an exec by calling back with the reply that script's own
    markers choose, so one rule can serve the run and mutate scripts."""

    match: str
    answer: object

    def handler(self, script, _stdin):
        return self.answer(script), 0


def framed(code, out, shown=None, err=b""):
    shown = out if shown is None else shown
    return (
        f"__ATLAS_RUN__ {code} {len(out)} {len(out.splitlines())} {len(shown)}\n"
        f"{base64.b64encode(shown).decode()}\n"
        f"{base64.b64encode(err).decode()}\n"
    )


def staged():
    return "__ATLAS_STAGE__ 0\n"


def mutation_block(apply_exit, commit, payload=b"", err=b""):
    return (
        f"__ATLAS_MUT__ {apply_exit} {commit}\n"
        f"{base64.b64encode(payload).decode()}\n"
        f"{base64.b64encode(err).decode()}\n"
    )


def ok_payload(before, after):
    return b"ok " + base64.b64encode(before) + b" " + base64.b64encode(after)


def fake_bridge(tmp_path, answer, requests, source=None, **kw):
    """A FakeSprites whose resolve exec reports the pyenv interpreter (the
    trusted shape the probe accepts) and whose run scripts answer with
    `answer(script)`."""
    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    f"atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
            ReplyRule("__ATLAS_RUN__", answer),
        )
    )
    results, bridges = [], []

    def body(bridge):
        bridges.append(bridge)
        results.extend(bridge.call(tool, args) for tool, args in requests)
        return "done"

    run_bridge(
        sprites,
        MemoryLedger(),
        source or trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-fake-run-test",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
        **kw,
    )
    assert results, "the scripted bridge made no calls"
    return results, bridges[0]


MUTATE_REQUEST = (
    "mutate",
    {"path": "calc.py", "line": 2, "operator": "negate-condition"},
)


def test_a_scripted_reply_frames_the_runs_and_the_mutant(tmp_path):
    out = b"1 passed in 0.01s\n"
    commit = "a" * 40

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return (
                staged()
                + framed(0, out)
                + staged()
                + mutation_block(0, commit, ok_payload(b"not xs", b"not (not xs):"))
                + framed(0, out)
            )
        return staged() + framed(0, out)

    (result,), _ = fake_bridge(tmp_path, answer, (MUTATE_REQUEST,), source=trees(SUITE))
    assert result.status is Status.OK
    assert result.outcome is MutantOutcome.SURVIVED
    assert result.mutation.commit == commit
    assert result.mutation.before == "not xs"
    rendered = render(result)
    assert "baseline run: exit 0, 1 passed" in rendered
    assert "mutated run: exit 0, 1 passed" in rendered
    assert f"head {HEAD}" in rendered
    assert "mutation at calc.py:2 (negate-condition)" in rendered
    assert 'not xs"` -> `"not (not xs):"' in rendered


def test_a_staging_failure_is_not_a_test_result(tmp_path):
    (result,), _ = fake_bridge(
        tmp_path, lambda _script: "__ATLAS_STAGE__ 128\n", (("run_tests", {}),)
    )
    assert result.status is Status.UNAVAILABLE
    assert "the staged copy could not be made (exit 128)" in result.error.text
    assert result.runs == ()


def test_a_mutate_staging_failure_after_the_baseline_is_inconclusive(tmp_path):
    out = b"1 passed in 0.01s\n"

    def answer(script):
        if script.count("__ATLAS_STAGE__") == 2:
            return staged() + framed(0, out) + "__ATLAS_STAGE__ 1\n"
        return staged() + framed(0, out)

    (result,), _ = fake_bridge(tmp_path, answer, (MUTATE_REQUEST,))
    assert result.status is Status.OK
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "the mutated copy could not be staged (exit 1)"
    (baseline,) = result.runs
    assert baseline.exit == 0
    assert "mutated run: not run" in render(result)


def test_a_mutation_step_that_failed_is_inconclusive(tmp_path):
    out = b"1 passed in 0.01s\n"

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return (
                staged()
                + framed(0, out)
                + staged()
                + mutation_block(1, "-", err=b"Traceback: boom\n")
            )
        return staged() + framed(0, out)

    (result,), _ = fake_bridge(
        tmp_path, answer,
        (("mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}),),
    )  # fmt: skip
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == (
        "the mutation did not apply: the mutation step failed (exit 1)"
    )
    # The mutation step's own stderr is surfaced as the runtime error (F6).
    assert "Traceback: boom" in result.error.text
    assert "mutated run: not run" in render(result)


def test_a_refusal_reason_from_the_mutation_script_is_carried(tmp_path):
    """The script's own refusal is a rejected call carrying the reason
    (D80's 2026-11-26 update) -- the model's error to re-aim, not an
    inconclusive verdict."""
    out = b"1 passed in 0.01s\n"
    payload = b"no " + base64.b64encode(b"the file does not parse")

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return (
                staged() + framed(0, out) + staged()
                + mutation_block(0, "-", payload)
            )  # fmt: skip
        return staged() + framed(0, out)

    (result,), _ = fake_bridge(
        tmp_path, answer,
        (("mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}),),
    )  # fmt: skip
    assert result.status is Status.REJECTED
    assert "the file does not parse" in result.error.text


def test_a_mutation_that_applies_but_commits_nothing_is_inconclusive(tmp_path):
    out = b"1 passed in 0.01s\n"

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return (
                staged() + framed(0, out) + staged()
                + mutation_block(0, "-", ok_payload(b"a", b"b"))
            )  # fmt: skip
        return staged() + framed(0, out)

    (result,), _ = fake_bridge(tmp_path, answer, (MUTATE_REQUEST,))
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "the mutated run did not run"


def test_a_killed_verdict_from_a_scripted_pair_of_runs(tmp_path):
    out = b"1 failed in 0.01s\n"

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return (
                staged()
                + framed(0, b"1 passed in 0.01s\n")
                + staged()
                + mutation_block(0, "a" * 40, ok_payload(b"a", b"b"))
                + framed(1, out)
            )
        return staged() + framed(0, b"1 passed in 0.01s\n")

    (result,), _ = fake_bridge(tmp_path, answer, (MUTATE_REQUEST,))
    assert result.outcome is MutantOutcome.KILLED
    assert result.truncated is False


def test_a_malformed_reply_is_unavailable(tmp_path):
    (result,), _ = fake_bridge(
        tmp_path, lambda _script: "not a frame\n", (("run_tests", {}),)
    )
    assert result.status is Status.UNAVAILABLE
    assert "no run reply" in result.error.text


def test_a_run_tests_reply_that_is_a_mutation_block_is_unavailable(tmp_path):
    (result,), _ = fake_bridge(
        tmp_path,
        lambda _script: staged() + mutation_block(0, "-", b"no x"),
        (("run_tests", {}),),
    )
    assert result.status is Status.UNAVAILABLE
    assert "not a staging step and one test run" in result.error.text


def test_a_mutate_reply_with_the_wrong_shape_is_unavailable(tmp_path):
    out = b"1 passed in 0.01s\n"
    (result,), _ = fake_bridge(
        tmp_path,
        lambda _script: staged() + framed(0, out) + mutation_block(0, "a" * 40, b"ok"),
        (MUTATE_REQUEST,),
    )
    assert result.status is Status.UNAVAILABLE
    assert "second staging step is missing" in result.error.text


def test_a_reply_starting_with_a_run_block_is_unavailable(tmp_path):
    out = b"1 passed in 0.01s\n"
    (result,), _ = fake_bridge(
        tmp_path, lambda _script: framed(0, out), (("run_tests", {}),)
    )
    assert result.status is Status.UNAVAILABLE
    assert "not a staging step" in result.error.text


def test_a_run_without_a_summary_line_renders_its_exit_alone(tmp_path):
    (result,), _ = fake_bridge(
        tmp_path,
        lambda _script: staged() + framed(0, b"no summary here\n"),
        (("run_tests", {}),),
    )
    (run,) = result.runs
    assert run.summary is None
    assert "test run: exit 0" in render(result)
    assert "test run: exit 0," not in render(result)


def test_an_exit_zero_run_without_a_summary_is_never_a_verdict(tmp_path):
    """F7: an exit 0 with no summary line does not prove a test ran, so
    the mutated side of the verdict may not rest on it. The baseline here
    has a summary; the mutated run's suppressed reporter is what makes
    this inconclusive."""
    out = b"the terminal reporter was suppressed\n"

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return (
                staged() + framed(0, b"1 passed in 0.01s\n") + staged()
                + mutation_block(0, "a" * 40, ok_payload(b"a", b"b"))
                + framed(0, out)
            )  # fmt: skip
        return staged() + framed(0, out)

    (result,), _ = fake_bridge(tmp_path, answer, (MUTATE_REQUEST,))
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "the mutated run's output carries no summary"


def test_an_exit_zero_baseline_without_a_summary_is_inconclusive(tmp_path):
    out = b"the terminal reporter was suppressed\n"

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return (
                staged() + framed(0, out) + staged()
                + mutation_block(0, "a" * 40, ok_payload(b"a", b"b"))
                + framed(0, b"1 passed in 0.01s\n")
            )  # fmt: skip
        return staged() + framed(0, out)

    (result,), _ = fake_bridge(tmp_path, answer, (MUTATE_REQUEST,))
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "the baseline run's output carries no summary"


def test_a_lost_output_is_a_failure_not_an_empty_result(tmp_path):
    out = b"1 passed in 0.01s\n"
    broken = (
        f"__ATLAS_RUN__ 0 {len(out)} 1 5\n"
        f"{base64.b64encode(out).decode()}\n{base64.b64encode(b'').decode()}\n"
    )
    (result,), _ = fake_bridge(tmp_path, lambda _script: broken, (("run_tests", {}),))
    assert result.status is Status.FAILED
    assert "held 18 of 5 bytes" in result.error.text


def test_a_run_stopped_by_its_exec_budget_is_a_timeout(tmp_path):
    class StuckSprites(FakeSprites):
        """Answers the lifecycle execs but never the run script: the exec
        budget kills it, the same failure a live runner reports."""

        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if "__ATLAS_RUN__" in argv[-1]:
                raise StreamTimeoutError("the run stopped arriving")
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    sprites = StuckSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    f"atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
        )
    )
    results = []

    def body(bridge):
        results.append(bridge.call("run_tests", {}))
        return "done"

    run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-stuck-run",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
    )
    (result,) = results
    assert result.status is Status.TIMED_OUT
    assert "the run stopped arriving" in result.error.text


def test_no_staged_pytest_is_refused_before_any_exec(tmp_path):
    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: "atlas-git:/usr/bin/git\ngit version 2.43.0\n",
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
        )
    )
    results = []

    def body(bridge):
        results.append(bridge.call("run_tests", {}))
        return "done"

    run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-no-pytest",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(),
    )
    (result,) = results
    assert result.status is Status.UNAVAILABLE
    assert "no pytest-capable interpreter" in result.error.text
    assert not any("bridge run_tests" in call for call in sprites.calls)


# ------------------------------------------------------------ pure verdicts


def run_block(code, text=b"1 passed in 0.01s\n"):
    (block,) = parse_run_blocks(framed(code, text))
    return block


class TestParseSummary:
    def test_the_plain_short_summary(self):
        summary = parse_summary("1 failed, 2 passed, 1 skipped in 0.01s")
        assert summary is not None
        assert summary.count("passed") == 2
        assert summary.count("failed") == 1
        assert summary.count("skipped") == 1
        assert summary.ran_any

    def test_the_padded_verbose_summary(self):
        summary = parse_summary("========= 1 failed in 0.03s =========")
        assert summary is not None and summary.count("failed") == 1

    def test_no_tests_ran(self):
        summary = parse_summary("no tests ran in 0.01s")
        assert summary is not None
        assert not summary.ran and not summary.ran_any

    def test_errors_are_singular_or_plural(self):
        assert parse_summary("1 error in 0.01s").count("errors") == 1
        assert parse_summary("2 errors in 0.01s").count("errors") == 2

    def test_the_last_summary_line_wins(self):
        text = "1 passed in 0.01s\n2 passed in 0.02s\n"
        assert parse_summary(text).count("passed") == 2

    def test_no_summary_line_is_none(self):
        assert parse_summary("some traceback\ngoes here\n") is None

    def test_a_summary_with_only_skips_ran_nothing(self):
        summary = parse_summary("3 skipped in 0.01s")
        assert summary is not None and not summary.ran_any

    def test_render_names_the_counts_in_reading_order(self):
        summary = parse_summary("1 failed, 2 passed, 3 skipped, 1 warning in 1s")
        assert summary.render() == "2 passed, 1 failed, 3 skipped, 1 warnings"

    def test_an_empty_summary_renders_as_no_counts(self):
        assert parse_summary("no tests ran in 0.01s").render() == "no test ran"


class TestMutantOutcome:
    @staticmethod
    def judged(
        applied=True,
        reason="r",
        baseline_code=0,
        baseline_text=b"1 passed in 0.01s\n",
        mutated_code=0,
        mutated_text=b"1 passed in 0.01s\n",
        mutated=True,
    ):
        baseline = run_block(baseline_code, baseline_text)
        mutated_block = run_block(mutated_code, mutated_text) if mutated else None
        return mutant_outcome(
            applied, reason, baseline, mutated_block,
            parse_summary(baseline.content.decode()),
            parse_summary(mutated_block.content.decode()) if mutated_block else None,
        )  # fmt: skip

    def test_not_applied(self):
        outcome, reason = self.judged(applied=False, reason="no such line")
        assert (outcome, reason) == (
            MutantOutcome.INCONCLUSIVE,
            "the mutation did not apply: no such line",
        )

    def test_a_baseline_that_times_out(self):
        outcome, reason = self.judged(baseline_code=124)
        assert (outcome, reason) == (
            MutantOutcome.INCONCLUSIVE,
            "the baseline run hit its wall clock",
        )

    def test_a_baseline_that_already_fails(self):
        outcome, reason = self.judged(baseline_code=1)
        assert (outcome, reason) == (
            MutantOutcome.INCONCLUSIVE,
            "the baseline run already fails (exit 1)",
        )

    def test_a_baseline_that_collected_nothing(self):
        outcome, reason = self.judged(baseline_code=5)
        assert (outcome, reason) == (
            MutantOutcome.INCONCLUSIVE,
            "no test was collected for the baseline run (exit 5)",
        )

    def test_a_baseline_where_no_test_ran(self):
        outcome, reason = self.judged(baseline_text=b"1 skipped in 0.01s\n")
        assert (outcome, reason) == (
            MutantOutcome.INCONCLUSIVE,
            "no test ran in the baseline run",
        )

    def test_a_survived_mutant(self):
        outcome, reason = self.judged()
        assert (outcome, reason) == (
            MutantOutcome.SURVIVED,
            "the baseline run passed and the mutated run passed too",
        )

    def test_a_killed_mutant(self):
        outcome, reason = self.judged(mutated_code=1)
        assert (outcome, reason) == (
            MutantOutcome.KILLED,
            "the mutated run failed (exit 1)",
        )

    def test_a_collection_error_kills(self):
        outcome, _ = self.judged(mutated_code=2)
        assert outcome is MutantOutcome.KILLED

    def test_a_mutated_run_that_times_out(self):
        outcome, reason = self.judged(mutated_code=124)
        assert (outcome, reason) == (
            MutantOutcome.INCONCLUSIVE,
            "the mutated run hit its wall clock",
        )

    def test_a_mutated_run_where_no_test_ran(self):
        outcome, reason = self.judged(mutated_text=b"1 skipped in 0.01s\n")
        assert (outcome, reason) == (
            MutantOutcome.INCONCLUSIVE,
            "no test ran in the mutated run",
        )

    def test_a_mutated_run_that_is_not_a_test_result(self):
        outcome, reason = self.judged(mutated_code=139)
        assert (outcome, reason) == (
            MutantOutcome.INCONCLUSIVE,
            "the mutated run ended at exit 139, not a test result",
        )

    def test_a_mutated_run_that_never_happened(self):
        outcome, reason = self.judged(mutated=False)
        assert (outcome, reason) == (
            MutantOutcome.INCONCLUSIVE,
            "the mutated run did not run",
        )


class TestParseMutation:
    @staticmethod
    def ok(before=b"if x:", after=b"if not (x):"):
        return parse_mutation(
            b"ok " + base64.b64encode(before) + b" " + base64.b64encode(after), 0
        )

    def test_an_applied_mutation(self):
        assert self.ok() == (True, "if x:", "if not (x):", "")

    def test_a_refused_mutation_carries_its_reason(self):
        payload = b"no " + base64.b64encode(b"the file does not parse")
        assert parse_mutation(payload, 0) == (False, "", "", "the file does not parse")

    def test_a_failed_step_names_the_exit(self):
        assert parse_mutation(b"", 1) == (
            False,
            "",
            "",
            "the mutation step failed (exit 1)",
        )

    def test_an_unparseable_payload_is_not_applied(self):
        assert parse_mutation(b"junk", 0)[0] is False
        assert parse_mutation(b"junk", 0)[3] == (
            "the mutation step did not report its edit"
        )

    def test_a_broken_field_is_not_applied(self):
        applied, _, _, reason = parse_mutation(b"ok !!! !!!", 0)
        assert (applied, reason) == (False, "the mutation step did not report its edit")

    def test_an_ok_status_with_the_wrong_field_count_is_not_applied(self):
        applied, _, _, reason = parse_mutation(b"ok onlyone", 0)
        assert (applied, reason) == (False, "the mutation step did not report its edit")

    def test_a_refusal_without_a_decodable_reason_is_named(self):
        applied, before, after, reason = parse_mutation(b"no !!!", 0)
        assert (applied, before, after, reason) == (
            False,
            "",
            "",
            "the mutation step refused without a reason",
        )


class TestRunBlocks:
    def test_a_run_block_parses_with_noise_around_it(self):
        (block,) = parse_run_blocks(framed(3, b"abc", b"ab") + "trailing noise\n")
        assert (block.code, block.total_bytes, block.shown_bytes) == (3, 3, 2)
        assert block.content == b"ab"

    def test_a_mut_block_parses_with_and_without_a_commit(self):
        text = f"__ATLAS_MUT__ 0 {'a' * 40}\n{base64.b64encode(b'ok').decode()}\n"
        (block,) = parse_run_blocks(text)
        assert (block.apply_exit, block.commit) == (0, "a" * 40)
        (block,) = parse_run_blocks("__ATLAS_MUT__ 1 -\n\n")
        assert (block.apply_exit, block.commit) == (1, "-")

    def test_a_header_shaped_line_that_does_not_parse_refuses_the_reply(self):
        assert parse_run_blocks("__ATLAS_RUN__ 1 2\nnope\n") is None
        assert parse_run_blocks("__ATLAS_RUN__ x 2 3 4\n\n\n") is None
        assert parse_run_blocks("__ATLAS_MUT__ 1 zz\n\n") is None
        assert parse_run_blocks("__ATLAS_MUT__ 1 -\nno!pe\n") is None
        assert parse_run_blocks("__ATLAS_RUN__ 1 2 3 4\nno!pe\n\n") is None
        assert parse_run_blocks("__ATLAS_RUN__ 1 2 3 4\n\nno!pe\n") is None

    def test_no_block_at_all_is_none(self):
        assert parse_run_blocks("nothing here\n") is None

    def test_the_blocks_come_back_in_order(self):
        text = (
            framed(0, b"a")
            + f"__ATLAS_MUT__ 0 -\n{base64.b64encode(b'no x').decode()}\n"
        )
        baseline, applied = parse_run_blocks(text)
        assert isinstance(baseline, _RunBlock)
        assert isinstance(applied, _MutBlock)
        assert applied.payload == b"no x"


class TestRunStatus:
    def test_pytests_own_outcomes_are_the_tool_working(self):
        for code in (0, 1, 2, 3, 4, 5):
            assert _run_status(code) is Status.OK

    def test_a_killed_run_is_a_timeout(self):
        assert _run_status(124) is Status.TIMED_OUT
        assert _run_status(137) is Status.TIMED_OUT

    def test_anything_else_failed(self):
        assert _run_status(139) is Status.FAILED


# ------------------------------------------------------ session cap shapes


def test_session_limits_reject_non_positive_caps():
    with pytest.raises(ValueError):
        SessionLimits(max_test_runs=0)
    with pytest.raises(ValueError):
        SessionLimits(max_mutants=-1)
    with pytest.raises(ValueError):
        SessionLimits(max_test_runs=True)


def test_the_default_execution_caps_sit_below_the_default_call_cap():
    limits = SessionLimits()
    assert limits.max_test_runs < limits.max_calls
    assert limits.max_mutants < limits.max_calls


# ----------------------------------------------------------- argv building


def test_the_built_argv_is_pytest_module_mode_isolated_and_fixed():
    staged = Staged(
        "/work/bridge",
        "/usr/bin/git",
        MappingProxyType({Rev.HEAD: "h" * 40}),
        pytest=choose_pytest(f"atlas-pytest:{PYTEST}:3.12.3\n", (PYTEST,)),
    )
    argv = _pytest_argv(staged, "test_calc.py::test_two_values")
    assert argv == (
        f"{PYTEST} -I -B -m pytest -q --color=no -p no:cacheprovider "
        "test_calc.py::test_two_values"
    )
    assert _pytest_argv(staged, "").endswith("-p no:cacheprovider")
    assert _pytest_argv(staged, "my tests.py").endswith("'my tests.py'")
    validate("run_tests", {"path": "test_calc.py"}, frozenset(Rev))


# ------------------------------------------------- tamper resistance (round 1)


TAMPER_TEST = """\
import glob
import os
import subprocess
import zlib
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[2]
REPO = str(BRIDGE / "repo.git")


def git(*args, **kwargs):
    return subprocess.run(
        ["git", f"--git-dir={REPO}", *args], capture_output=True, text=True, **kwargs
    )


def test_forges_the_mutant_ref_and_replaces_the_staged_trees():
    work = BRIDGE / "scratch" / "forge"
    work.mkdir(parents=True, exist_ok=True)
    (work / "calc.py").write_text(
        "def total(xs):\\n    return 999  # ATTACKER CONTENT\\n"
    )
    blob = git("hash-object", "-w", str(work / "calc.py")).stdout.strip()
    assert blob, "hash-object failed"
    tree = subprocess.run(
        ["git", f"--git-dir={REPO}", "hash-object", "-w", "-t", "tree", "--stdin"],
        input=b"100644 calc.py\\x00" + bytes.fromhex(blob),
        capture_output=True,
    ).stdout.decode().strip()
    assert tree, "tree hash failed"
    commit = git(
        "-c", "user.name=attacker", "-c", "user.email=attacker@invalid",
        "commit-tree", tree, "-m", "forged",
    ).stdout.strip()
    assert commit, "commit-tree failed"
    moved = git("update-ref", "refs/tags/atlas-mutant", commit)
    assert moved.returncode == 0, moved.stderr
    head = BRIDGE / "trees" / "head"
    subprocess.run(["chmod", "-R", "u+w", str(BRIDGE / "trees")], check=False)
    subprocess.run(["rm", "-rf", str(head)], check=False)
    head.mkdir(parents=True)
    (head / "calc.py").write_text(
        "def total(xs):\\n    if xs:\\n        return 111  # REPLACED TREE\\n    return 0\\n"
    )
    (head / "test_calc.py").write_text(
        "from calc import total\\n\\n"
        "def test_always_passes():\\n    assert total([1]) == 111\\n"
    )


def test_rewrites_a_loose_object_in_place():
    # git does not re-verify a loose object on read, so overwriting the
    # blob file under its original name is the attack that survives every
    # read path that trusts the object store.
    for path in glob.glob(
        str(BRIDGE / "repo.git" / "objects" / "[0-9a-f][0-9a-f]" / "*")
    ):
        with open(path, "rb") as handle:
            raw = handle.read()
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            continue
        if (
            data.endswith(b"    return sum(xs)\\n")
            and b"if not xs:" in data
            and b"def total(xs):" in data
        ):
            forged = data.replace(b"return sum(xs)", b"return 0  # FORGED OBJECT")
            os.unlink(path)
            with open(path, "wb") as handle:
                handle.write(zlib.compress(forged))
            return
"""

DESTRUCTIVE_TEST = (
    "import shutil\n"
    "from pathlib import Path\n\n"
    "BRIDGE = Path(__file__).resolve().parents[2]\n\n\n"
    "def test_deletes_the_staged_repository():\n"
    '    shutil.rmtree(BRIDGE / "repo.git", ignore_errors=True)\n'
)

CARRIER_TEST = (
    "import os\n\n"
    "from calc import total\n\n"
    "marker_predated_the_run = os.path.exists('baseline_marker.txt')\n"
    "open('baseline_marker.txt', 'w').write('the baseline ran here')\n\n\n"
    "def test_marker_did_not_predate_the_run():\n"
    "    assert not marker_predated_the_run\n"
)

TAMPER_TREES = {
    "calc.py": CALC.encode(),
    "test_calc.py": TEST_TOTAL.encode(),
    "test_tamper.py": TAMPER_TEST.encode(),
}
DESTRUCTIVE_TREES = {
    "calc.py": CALC.encode(),
    "test_calc.py": TEST_TOTAL.encode(),
    "test_destructive.py": DESTRUCTIVE_TEST.encode(),
}


def test_executed_code_cannot_tamper_with_what_later_calls_trust(tmp_path):
    """Round 1's F1, from the review's own probe: a test in the executed
    suite forges the `atlas-mutant` ref onto an attacker commit and
    replaces `trees/head` wholesale. What a later call stages and serves
    comes from the bare repository's objects at recorded commit ids, so
    HEAD reads keep their content, MUTANT keeps serving the real mutant,
    the next mutate's record quotes the real head statement, and the next
    run runs the real tree."""
    collected = {}

    def body(bridge):
        out = {}
        out["head0"] = bridge.call("read_file", {"rev": "HEAD", "path": "calc.py"})
        out["m1"] = bridge.call(
            "mutate",
            {"path": "calc.py", "line": 2, "operator": "negate-condition",
             "tests": "test_calc.py"},
        )  # fmt: skip
        out["mutant0"] = bridge.call("read_file", {"rev": "MUTANT", "path": "calc.py"})
        out["run1"] = bridge.call("run_tests", {"path": "test_tamper.py"})
        # A second execution with no read between: it too must stage the
        # real tree, so the tamper cannot live in the object store across
        # a run-to-run handoff.
        out["run1b"] = bridge.call("run_tests", {"path": "test_calc.py"})
        out["head1"] = bridge.call("read_file", {"rev": "HEAD", "path": "calc.py"})
        out["mutant1"] = bridge.call("read_file", {"rev": "MUTANT", "path": "calc.py"})
        out["m2"] = bridge.call(
            "mutate",
            {"path": "calc.py", "line": 2, "operator": "negate-condition",
             "tests": "test_calc.py"},
        )  # fmt: skip
        out["mutant2"] = bridge.call("read_file", {"rev": "MUTANT", "path": "calc.py"})
        # The tamper again, then a read with no execution between: the
        # served content is real even though the object was just
        # rewritten under its recorded name.
        out["run3"] = bridge.call("run_tests", {"path": "test_tamper.py"})
        out["head3"] = bridge.call("read_file", {"rev": "HEAD", "path": "calc.py"})
        collected.update(out)
        return "done"

    report = bridge_run(tmp_path, body, source=trees(TAMPER_TREES))[0]
    assert report.status is RunnerStatus.COMPLETED, report.note
    m1, m2 = collected["m1"], collected["m2"]
    assert m1.outcome is MutantOutcome.KILLED and m1.mutation.commit
    assert m1.mutation.before == "not xs"
    # The tamper run itself ran (the attack executed; it bought nothing).
    (tamper,) = collected["run1"].runs
    assert collected["run1"].status is Status.OK and tamper.exit == 0
    # The very next execution still stages the real tree.
    (run1b,) = collected["run1b"].runs
    assert collected["run1b"].status is Status.OK and run1b.exit == 0
    assert run1b.summary is not None and run1b.summary.count("passed") == 1
    # HEAD keeps its content, and MUTANT keeps serving the real mutant --
    # never the attacker's forged commit.
    assert collected["head1"].content.text == CALC
    assert "ATTACKER CONTENT" not in collected["mutant1"].content.text
    assert "if not (not xs):" in collected["mutant1"].content.text
    # The next mutate ran against the real head tree: its record quotes
    # the real condition, not the replaced tree's, and its verdict is
    # again a real one.
    assert m2.mutation.before == "not xs"
    assert "REPLACED TREE" not in m2.mutation.before
    assert m2.outcome is MutantOutcome.KILLED
    assert "if not (not xs):" in collected["mutant2"].content.text
    # And the tamper's second outing changes nothing a read serves.
    assert collected["head3"].content.text == CALC
    assert "FORGED OBJECT" not in collected["head3"].content.text


def test_executed_code_deleting_the_repository_does_not_take_the_session_hostage(
    tmp_path,
):
    """Round 1's F4 shape, re-run after the round-2 fix: executed code
    deletes the staged repository -- and the next call rebuilds it from
    the controller-held tarballs and runs the real tree, so the DoS buys
    nothing; a staging failure stays a gap (`unavailable`, pinned by the
    scripted staging-failure tests), never a fake test result."""
    collected = {}

    def body(bridge):
        out = {}
        out["run1"] = bridge.call("run_tests", {"path": "test_destructive.py"})
        out["run2"] = bridge.call("run_tests", {})
        out["mutate"] = bridge.call(
            "mutate",
            {
                "path": "calc.py",
                "line": 2,
                "operator": "remove-guard",
                "tests": "test_calc.py",
            },
        )
        collected.update(out)
        return "done"

    report = bridge_run(tmp_path, body, source=trees(DESTRUCTIVE_TREES))[0]
    assert report.status is RunnerStatus.COMPLETED, report.note
    (destructive,) = collected["run1"].runs
    assert collected["run1"].status is Status.OK and destructive.exit == 0
    # The repository was rebuilt from the tarballs: the real tree runs.
    (run2,) = collected["run2"].runs
    assert collected["run2"].status is Status.OK and run2.exit == 0
    assert run2.summary is not None and run2.summary.count("passed") == 2
    # And a mutant runs and is judged against the real head statement.
    # (The mutate's runs select the ordinary test file: a whole-suite run
    # would execute the destructive test again mid-call, and its honest
    # result is the inconclusive shape the staging-failure tests pin.)
    assert collected["mutate"].status is Status.OK
    assert collected["mutate"].outcome is MutantOutcome.SURVIVED
    assert collected["mutate"].mutation.before == "return 0"
    assert "REPLACED TREE" not in collected["mutate"].mutation.before


def test_the_baseline_runs_writes_do_not_carry_into_the_mutant(tmp_path):
    """Round 1's F2, from the carry-over probe: a baseline test's writes
    stay out of the mutant's tree and out of the mutated run -- the copy
    is staged fresh between the baseline and the mutation, so MUTANT is
    the head tree plus one mutation and nothing else."""
    source = trees(
        {
            "calc.py": CALC.encode(),
            "test_calc.py": CARRIER_TEST.encode(),
        }
    )
    collected = {}

    def body(bridge):
        out = {}
        out["mutate"] = bridge.call(
            "mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}
        )
        out["marker"] = bridge.call(
            "read_file", {"rev": "MUTANT", "path": "baseline_marker.txt"}
        )
        collected.update(out)
        return "done"

    report = bridge_run(tmp_path, body, source=source)[0]
    assert report.status is RunnerStatus.COMPLETED, report.note
    # The carrier flips on the fresh copy: its test asserts the marker
    # did NOT exist before the module imported -- true in a copy staged
    # fresh (the fix), false in the baseline's dirty scratch (a dropped
    # second staging, where the marker the baseline run wrote is still
    # lying there and the test fails, turning the verdict KILLED). So the
    # fix's SURVIVED verdict is the pin, and the marker read at MUTANT is
    # the controller-side record of the clean tree.
    assert collected["mutate"].outcome is MutantOutcome.SURVIVED
    assert collected["marker"].status is not Status.OK
    assert "the baseline ran here" not in collected["marker"].content.text


def test_the_mutation_leaves_the_rest_of_the_file_byte_identical(tmp_path):
    """Round 1's F3: the mutation is a span splice, not a whole-module
    rewrite -- the mutated run's source is the head source plus one edit,
    so comments, quoting and formatting outside the mutated span survive,
    and a source-sensitive suite cannot be handed a false `killed` by
    rewritten formatting."""
    formatted = (
        b"# the rounding policy lives here\n"
        b"def total(xs):\n"
        b"    if not xs:      # keep the spacing\n"
        b"        return 0\n"
        b"    return sum(xs)  # trailing comment\n"
    )
    source = trees({"calc.py": formatted, "test_calc.py": TEST_TOTAL.encode()})
    collected = {}

    def body(bridge):
        out = {}
        out["mutate"] = bridge.call(
            "mutate", {"path": "calc.py", "line": 3, "operator": "negate-condition"}
        )
        out["mutant"] = bridge.call("read_file", {"rev": "MUTANT", "path": "calc.py"})
        collected.update(out)
        return "done"

    report = bridge_run(tmp_path, body, source=source)[0]
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert collected["mutate"].mutation.before == "not xs"
    assert collected["mutate"].mutation.after == "not (not xs)"
    mutated = collected["mutant"].content.text
    assert "# the rounding policy lives here" in mutated
    assert "if not (not xs):      # keep the spacing" in mutated
    assert "return sum(xs)  # trailing comment" in mutated


def test_a_rejected_call_does_not_spend_an_execution_slot(tmp_path):
    """Round 1's F8: refused calls -- rejected arguments, an already-spent
    budget -- spent no execution resource and take no execution slot; a
    run that timed out did run, and keeps its slot."""
    results, _ = calls(
        tmp_path,
        ("run_tests", {"path": "-k"}),
        ("mutate", {"path": "calc.py", "operator": "remove-guard"}),
        ("run_tests", {}),
        ("mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}),
        ("run_tests", {}),
        session_limits=SessionLimits(max_test_runs=1, max_mutants=1),
    )
    rejected_run, rejected_mutate, ran, mutated, refused = results
    assert rejected_run.status is Status.REJECTED
    assert rejected_mutate.status is Status.REJECTED
    assert ran.status is Status.OK
    assert mutated.status is Status.OK
    assert refused.status is Status.OVER_SESSION_LIMIT
    assert "all 1 run_tests calls of this attempt made" in refused.error.text


def test_a_tampered_upload_stops_the_restage(tmp_path):
    """Round 2's upload-window shape: a daemon left behind by an executed
    run can rewrite the freshly uploaded tarball before the staging exec
    reads it. The staging verifies each tarball against the digest of the
    bytes the controller holds, so a rewritten one stops the re-staging
    (fail-closed), and the tool answers `unavailable`, never a result
    built from attacker-chosen bytes. The rewrite here is a RECOMPRESSION
    -- the same tree, unpacked identically -- so the digest check is the
    only layer that sees it, and the mutant that drops the check dies on
    this test."""
    import glob as globmod

    class UploadTamperer(LocalSprites):
        armed = False

        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            result = super().exec(name, argv, stdin, timeout_s, first_byte_s)
            script = argv[-1]
            if self.armed and "cat > " in script and ".tar.gz" in script:
                after = script.split("cat > ", 1)[1]
                path = after.split(" &&")[0].split()[0]
                import gzip as gzipmod

                for tarball in globmod.glob(path):
                    # Recompressed, not corrupted: the archive unpacks
                    # exactly as before and yields the same tree, so only
                    # the digest check can see the rewrite.
                    with open(tarball, "rb") as handle:
                        original = handle.read()
                    with open(tarball, "wb") as handle:
                        handle.write(
                            gzipmod.compress(
                                gzipmod.decompress(original), compresslevel=1
                            )
                        )
            return result

    collected = {}
    sprites = UploadTamperer()

    def body(bridge):
        bridge.call("run_tests", {"path": "test_calc.py"})
        # The daemon the executed run left behind starts tampering with
        # whatever is uploaded from here on. The call that follows is one
        # of the tools that still read the runner's repository (the diff
        # trio), so it re-stages first -- and the digest check stops the
        # re-stage: `unavailable`, never a result built from attacker
        # bytes.
        sprites.armed = True
        collected["diff"] = bridge.call("diff_stat", {})
        return "done"

    report = bridge_run(tmp_path, body, sprites=sprites, source=trees(SUITE))[0]
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert collected["diff"].status is Status.UNAVAILABLE
    assert "bridge staging failed" in collected["diff"].error.text


def test_a_daemon_racing_the_edit_cannot_forge_the_recorded_mutant(tmp_path):
    """D80's owned residual, pinned: a test daemon that survives the
    process-group kill could rewrite the scratch between the mutation
    edit and the mutant commit, inside one exec. The re-stage checks the
    re-created mutant commit against the id the record names, so a
    winning daemon's tree is refused -- the tool answers `unavailable`, a
    gap -- instead of serving a mutant the record did not make. The
    daemon here is scripted: the runner writes into the copy between the
    edit and the commit, deterministically, the way a winning race would."""
    from atlas_reviewer.bridge import MUTATION_SCRIPT

    class EditRacer(LocalSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            from atlas_reviewer.runner import exec_argv

            script = argv[-1]
            # The daemon rides only the mutate exec (the one that runs
            # pytest and frames STAGE blocks); the re-stage's re-apply has
            # no staged run in it.
            if "> mut 2> mut_err" in script and "__ATLAS_STAGE__" in script:
                scratch = script.split("( cd ", 1)[1].split(";", 1)[0].strip()
                daemon = f"printf '\\n# daemon wrote here\\n' >> '{scratch}/calc.py'"
                script = script.replace(
                    "> mut 2> mut_err", f"> mut 2> mut_err; {daemon}", 1
                )
                wrapped = exec_argv(script, len(stdin) if stdin else 0)
                return LocalSprites.exec(
                    self, name, wrapped, stdin, timeout_s, first_byte_s
                )
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    collected = {}
    sprites = EditRacer()

    def body(bridge):
        collected["mutate"] = bridge.call(
            "mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}
        )
        # The recorded mutant's id was minted from the tree the daemon's
        # write landed in; the re-stage re-applies the recorded mutation
        # to a clean copy and re-creates the id the splice alone produces,
        # so the mismatch refuses the next runner-side read -- a diff
        # call, one of the tools that still read the repository.
        collected["diff"] = bridge.call("diff_stat", {})
        return "done"

    report = bridge_run(
        tmp_path, body, sprites=sprites,
        source=trees({"calc.py": CALC.encode(), "test_calc.py": TEST_TOTAL.encode()}),
    )[0]  # fmt: skip

    assert report.status is RunnerStatus.COMPLETED, report.note
    assert collected["mutate"].status is Status.OK
    assert collected["diff"].status is Status.UNAVAILABLE
    assert "differs from the recorded one" in collected["diff"].error.text
    assert MUTATION_SCRIPT  # the marker the racer keys on is the fixed script


def test_choose_git_cuts_the_version_at_the_probe_output():
    """The git resolve exec carries the pytest probe's labelled output
    after git's own line, and the live run's telemetry showed it glued
    past git's newline into the version field. The version is the first
    line, cut at the first `atlas-` marker, glued or not."""
    from atlas_reviewer.bridge_staging import choose_git

    path, version = choose_git(
        0,
        "atlas-git:/usr/bin/git\n"
        "git version 2.53.0\n"
        "atlas-pytest:/.sprite/languages/python/pyenv/versions/3.13.17/bin/python3:3.13.17\n",
    )
    assert path == "/usr/bin/git"
    assert version == "git version 2.53.0"
    _path, glued = choose_git(
        0,
        "atlas-git:/usr/bin/git\ngit version 2.53.0atlas-pytest:/x:3.13.17\n",
    )
    assert glued == "git version 2.53.0"


def test_the_content_tools_answer_without_the_runner(tmp_path):
    """The round-2 decision's structural half: `read_file`, the
    fixed-string `grep` and `list_files` are answered from the
    controller's own copy and never exec -- a runner that refuses every
    exec still serves them, and a diff call (which still reads the
    runner) is the `unavailable` gap. The regex `grep` mode is not part
    of this: it stays on the runner (D80 round 3)."""

    class NoExec(LocalSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            script = argv[-1]
            # The lifecycle scripts (resolve, staging, uploads, sweeps,
            # the hold) still run; the read tools' git invocations are
            # what must never be needed for a content answer.
            if any(
                token in script
                for token in ("cat-file", "grep -z", "ls-tree -r", "--find-renames")
            ):
                raise BoundaryError("the runner must not be exec'd for a content read")
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    collected = {}

    def body(bridge):
        out = {}
        out["read"] = bridge.call("read_file", {"rev": "HEAD", "path": "calc.py"})
        out["grep"] = bridge.call("grep", {"pattern": "sum(xs)"})
        out["list"] = bridge.call("list_files", {})
        out["diff"] = bridge.call("diff_stat", {})
        collected.update(out)
        return "done"

    report = bridge_run(
        tmp_path, body, sprites=NoExec(),
        source=trees(SUITE, base={"calc.py": b"def total(xs):\\n    return sum(xs)\\n"}),
    )[0]  # fmt: skip
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert collected["read"].status is Status.OK
    assert collected["read"].content.text == CALC
    assert collected["grep"].status is Status.OK
    assert "sum(xs)" in collected["grep"].content.text
    assert collected["list"].status is Status.OK
    assert "calc.py" in collected["list"].content.text
    # The runner-reading tools fail closed when their exec is refused.
    assert collected["diff"].status is Status.UNAVAILABLE
    assert "must not be exec'd" in collected["diff"].error.text


def test_a_regex_grep_stays_on_the_runner_and_keeps_its_dialect(tmp_path):
    """Round 3's major: only the fixed-string mode moved controller-side
    -- a substring scan is linear, cannot crash and cannot change
    meaning. The regex mode is dispatched to the runner's `git grep -E`,
    where `timeout` still bounds it and a bad pattern is git's exit
    status; its dialect is git's (POSIX extended), the one every regex
    grep before the local path served."""
    seen: list[str] = []

    class Counting(LocalSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            seen.append(argv[-1])
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    results, _ = calls(
        tmp_path,
        ("grep", {"pattern": "to.al", "regex": True}),
        ("grep", {"pattern": "return|total", "regex": True}),
        ("grep", {"pattern": "sum(xs)"}),
        sprites=Counting(),
    )
    # The regex mode really exec'd -- and the fixed-string mode did not.
    assert sum("grep -z" in script for script in seen) == 2
    matched, alternation, fixed = results
    # `to.al` matches "total" only under regex semantics; the local
    # fixed-string scan would find no literal "to.al" and answer empty.
    assert matched.status is Status.OK
    assert "def total(xs):" in matched.content.text
    assert alternation.status is Status.OK
    assert "return 0" in alternation.content.text
    assert fixed.status is Status.OK
    assert "sum(xs)" in fixed.content.text
    # The runner script carries the timeout the controller cannot impose
    # on an in-process regex engine.
    grep_script = next(script for script in seen if "grep -z" in script)
    assert "timeout -k" in grep_script


def test_an_invalid_regex_grep_is_a_gap_not_a_crash(tmp_path):
    """A common model typo in the regex mode reaches git, whose exit
    status and stderr become the result -- `FAILED`, a gap, with the
    reason surfaced -- not an uncaught `re.error` out of `Bridge.call`."""
    result = one(tmp_path, "grep", {"pattern": "(", "regex": True})
    assert result.status is Status.FAILED
    assert "unmatched" in (result.error.text if result.error else "").lower()


def test_the_controller_splice_matches_the_runner_script(tmp_path):
    """One splice semantics for the runner's mutant commit and the
    controller's mutant map: for every fixture shape, `_splice`'s mutated
    bytes and before/after are exactly what `MUTATION_SCRIPT` writes and
    prints."""
    guard = "def go(job):\n    if job.superseded or job.cancel.is_set():\n        return 0\n    return 1\n"
    loop = "def find(xs):\n    for x in xs:\n        if x:\n            break\n    return None\n"
    shapes = (
        (CALC, 2, "negate-condition", None),
        (CALC, 2, "remove-guard", None),
        (REQUIRE, 2, "negate-condition", None),
        (REQUIRE, 2, "remove-guard", None),
        (
            "def spin(n):\n    while n > 0:\n        n -= 1\n    return n\n",
            2,
            "negate-condition",
            None,
        ),
        ("def pick(n):\n    return 1 if n else 2\n", 2, "negate-condition", None),
        (
            "def pick(n):\n    if (\n        n\n    ):\n        return 1\n    return 2\n",
            2,
            "negate-condition",
            None,
        ),
        # drop-operand: keep either side, both orders
        (guard, 2, "drop-operand", 2),
        (guard, 2, "drop-operand", 1),
        # break-continue: break becomes continue; a continue becomes break
        (loop, 4, "break-continue", None),
        (
            "def find(xs):\n    for x in xs:\n        if x:\n            continue\n    return None\n",
            4,
            "break-continue",
            None,
        ),
        # flip-compare: each spelling pair, including the two-word ones
        ("def pick(n):\n    return 1 if n < 2 else 0\n", 2, "flip-compare", None),
        ("def pick(n):\n    return 1 if n >= 2 else 0\n", 2, "flip-compare", None),
        ("def same(a, b):\n    return a is not b\n", 2, "flip-compare", None),
        ("def has(xs, x):\n    return x in xs\n", 2, "flip-compare", None),
        ("def has(xs, x):\n    return x not in xs\n", 2, "flip-compare", None),
        # not applicable: both refuse
        ("x = 1\n", 1, "remove-guard", None),
        (guard, 2, "drop-operand", None),  # no operand named
        (guard, 2, "drop-operand", 3),  # index out of range
        (guard, 2, "break-continue", None),  # no break or continue at the line
        (loop, 4, "flip-compare", None),  # no comparison at the line
        (
            "def same(a, b):\n    return a != b\n",
            2,
            "break-continue",
            None,
        ),  # not a loop statement: compiles, but not a break/continue at the line
        ("x = 1\n", 99, "negate-condition", None),  # no statement at the line
        (
            "def pick(n):\n    return (n) == 2\n",
            2,
            "flip-compare",
            None,
        ),  # the spelling between the operands is not the bare operator
        ("def broken(:\n", 1, "negate-condition", None),  # the file does not parse
        # A multi-byte identifier earlier in the file shifts every byte
        # column against its character index: the AST's columns are
        # UTF-8 byte offsets, so a kept operand on a line whose prefix
        # carries one slices wrong unless both implementations convert
        # (the round-4 CodeRabbit finding on #845: `return eady`).
        (
            "def f(\u00e9, ready):\n    return \u00e9 or ready\n",
            2,
            "drop-operand",
            2,
        ),
        (
            "def f(\u00e9, ready):\n    return \u00e9 or ready\n",
            2,
            "drop-operand",
            1,
        ),
        (
            "value = f(\u00e9)\nif value == 2:\n    pass\n",
            2,
            "negate-condition",
            None,
        ),
    )
    for text, line, operator, operand in shapes:
        result, path = edit(tmp_path, text, line, operator, operand)
        status, rest = payload_of(result)
        spliced = _splice(text.encode(), line, operator, operand)
        if status == "no":
            assert spliced is None, (text, line, operator)
            # The aim check refuses with the script's own reason: the
            # pre-exec refusal says what the runner would have said.
            assert _aim_refusal(text.encode(), line, operator, operand) == (
                mutation_refusal(f"no {rest}".encode(), 0)
            ), (text, line, operator)
            continue
        assert spliced is not None
        before_b64, after_b64 = rest.split(" ")
        mutated, before, after = spliced
        assert path.read_bytes() == mutated, (text, line, operator)
        # The kept operand's own characters, not a byte-shifted misread
        # of them: the mutant's replacement text is the operand the
        # grammar named, byte-converted.
        if operator == "drop-operand" and status == "ok":
            after_decoded = base64.b64decode(after_b64).decode()
            assert "\u00e9" not in after_decoded or operand == 1, (
                text,
                after_decoded,
            )
        assert base64.b64decode(before_b64).decode() == before
        assert base64.b64decode(after_b64).decode() == after


def test_a_run_that_writes_into_the_repos_objects_does_not_reach_the_reads(tmp_path):
    """The surviving re-stage protection, pinned without the retired
    sweep (D80's retirement): a PR test writes a corrupt loose blob into
    the runner's repository during its run -- the shape the deleted
    between-call daemon fixture modeled -- and the later runner-side
    read re-stages first, so the forgery never reaches the diff trio and
    the next run executes the real tree."""
    poison = (
        "import glob, zlib, os\n"
        "from pathlib import Path\n\n"
        "def test_forge():\n"
        "    repo = Path(__file__).resolve().parents[2] / 'repo.git'\n"
        "    for path in glob.glob(os.path.join(repo, 'objects', '[0-9a-f][0-9a-f]', '*')):\n"
        "        raw = open(path, 'rb').read()\n"
        "        data = zlib.decompress(raw)\n"
        "        if b'def total' in data:\n"
        "            forged = data.replace(b'return sum(xs)', b'return 999')\n"
        "            tmp = path + '.tmp'\n"
        "            open(tmp, 'wb').write(zlib.compress(forged))\n"
        "            os.replace(tmp, path)\n"
    )
    old_calc = b"def total(xs):\n    return -1\n"
    source = trees(
        {**SUITE, "test_forge.py": poison.encode()}, base={"calc.py": old_calc}
    )
    collected = {}

    def body(bridge):
        out = {}
        # The forging run poisons the runner's own object store: the
        # corrupt blob is written at the real blob's path, so every
        # runner-side read that walks the tree hits it.
        out["run"] = bridge.call("run_tests", {"path": "test_forge.py"})
        # A runner-side read that follows an execution re-stages first.
        out["diff"] = bridge.call("diff_file", {"path": "calc.py"})
        out["run2"] = bridge.call("run_tests", {})
        collected.update(out)
        return "done"

    (report, *_) = bridge_run(tmp_path, body, source=source)
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert collected["diff"].status is Status.OK, collected["diff"].error.text
    # The re-stage served the controller-staged delta, not the forgery.
    assert "return sum(xs)" in collected["diff"].content.text
    assert "999" not in collected["diff"].content.text
    # The next run executes the re-staged real tree.
    (run2,) = collected["run2"].runs
    assert run2.exit == 0


# ------------------------------------------------- the execution environment


def test_the_no_root_guard_runs_the_argv_when_the_caller_is_not_root():
    """The guard is a no-op wrapper for a caller that is already not root
    and a drop to `nobody` for a root caller; this machine runs it both
    ways it can (D80's 2026-11-26 update)."""
    import os

    done = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            DROP_SHIM,
            sys.executable,
            "-I",
            "-c",
            "import os; print(os.geteuid())",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    expected = NOBODY_UID if os.geteuid() == 0 else os.geteuid()
    assert int(done.stdout.strip()) == expected


def test_the_no_root_guard_is_the_first_thing_the_run_scripts_name(tmp_path):
    call = validate("run_tests", {"path": "test_calc.py"}, frozenset(Rev))
    staged = Staged(
        str(tmp_path / "root"),
        "/usr/bin/git",
        MappingProxyType({Rev.HEAD: "h" * 40}),
        pytest=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
        shim_python=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
    )
    script = run_test_script(staged, call, ToolLimits(16 * 1024, 60))
    guard = f"{SYSTEM_PYTHON} -I -c"
    assert guard in script
    assert "atlas-privilege-drop failed" in script
    # The pytest argv follows the guard as separate shell arguments (the
    # shim payload's own newlines are inside its quoted argument).
    assert script.index(guard) < script.index("-m pytest")
    mutant = validate(
        "mutate",
        {"path": "calc.py", "line": 2, "operator": "remove-guard"},
        frozenset(Rev),
    )
    mscript = mutate_script(staged, mutant, ToolLimits(16 * 1024, 60))
    # Both test processes (the baseline and the mutated run) carry the
    # guard; the mutation edit does not -- it writes the mutated file and
    # stays a root exec.
    assert mscript.count("atlas-privilege-drop failed") == 2


def test_the_collection_probe_parses_its_verdicts():
    assert parse_collection(0, "atlas-collect:0:\n") == (True, "")
    ok_no_tests = parse_collection(0, "atlas-collect:5:\n")
    assert ok_no_tests == (True, "")
    broken = parse_collection(
        0,
        "atlas-collect:2:" + base64.b64encode(b"No module named 'jwt'").decode() + "\n",
    )
    assert broken == (False, "No module named 'jwt'")
    with pytest.raises(BoundaryError):
        parse_collection(0, "atlas-collect:-1:\n")
    with pytest.raises(BoundaryError):
        parse_collection(0, "no verdict line\n")
    with pytest.raises(BoundaryError):
        parse_collection(1, "atlas-collect:0:\n")


def test_a_broken_collection_is_a_named_gap_not_a_run(tmp_path):
    collected = []

    def answer(script):
        if "atlas-collect" in script and "__ATLAS_RUN__" not in script:
            tail = base64.b64encode(
                b"ModuleNotFoundError: No module named 'jwt'"
            ).decode()
            return f"atlas-collect:2:{tail}\n"
        collected.append(script)
        return "__ATLAS_RUN__ 0 5 1 5\n\n\n"

    (result,) = fake_bridge_collect(tmp_path, answer, (("run_tests", {}),))
    assert result.status is Status.UNAVAILABLE
    assert "the test environment is broken" in result.error.text
    assert "No module named 'jwt'" in result.error.text
    assert collected == []  # the refusal happens before any run script


def fake_bridge_collect(tmp_path, answer, requests, **kw):
    """fake_bridge with a scripted collection verdict."""
    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    f"atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", answer),
            ReplyRule("__ATLAS_RUN__", answer),
        )
    )
    results = []

    def body(bridge):
        results.extend(bridge.call(tool, args) for tool, args in requests)
        return "done"

    run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset({"calc.py"}),
        name="cqa-collect-test",
        deadline_s=300,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        **kw,
    )
    return results


def test_the_test_clock_default_and_override(tmp_path):
    assert DEFAULT_LIMITS["run_tests"].timeout_s == 180
    assert DEFAULT_LIMITS["mutate"].timeout_s == 180
    override = run_tool_limits({"ATLAS_TEST_TIMEOUT_S": "240"})
    assert override["run_tests"].timeout_s == 240
    assert override["mutate"].timeout_s == 240
    assert override["diff_file"] == DEFAULT_LIMITS["diff_file"]
    empty = run_tool_limits({"ATLAS_TEST_TIMEOUT_S": ""})
    assert empty["run_tests"].timeout_s == 180
    for bad in ("none", "29", "601", "-5"):
        with pytest.raises(BoundaryError) as exc:
            run_tool_limits({"ATLAS_TEST_TIMEOUT_S": bad})
        assert "ATLAS_TEST_TIMEOUT_S" in str(exc.value)


def test_run_bridge_applies_the_test_clock_override_to_the_scripts(tmp_path):
    scripts = []

    def answer(script):
        scripts.append(script)
        return staged() + framed(0, b"")

    (result,) = fake_bridge_collect(
        tmp_path,
        lambda s: answer(s) if "__ATLAS_RUN__" in s else "atlas-collect:0:\n",
        (("run_tests", {}),),
        env={"ATLAS_TEST_TIMEOUT_S": "240"},
    )
    assert result.status is Status.OK
    # An empty successful run: the reply's byte counts must match its
    # payload, or the lost-output guard fails the call instead.
    assert result.content.text == ""
    assert any("timeout -k 2 240" in script for script in scripts)


def test_the_bridge_starts_suspect_when_the_collection_probe_ran(tmp_path):
    """The collection probe executes the copy's own conftest.py -- PR
    code, in the runner, with the staged repository reachable -- so the
    bridge's first runner-side read re-stages from the controller-held
    tarballs, whatever the probe's verdict was. A conftest that rewrites
    a loose object during collection must not be served by the first
    diff read."""
    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    "atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
            ExecRule("__ATLAS_BRIDGE__", "__ATLAS_BRIDGE__ 0 0 9 0 0\n", 0),
        )
    )
    uploads = lambda: [
        c
        for c in sprites.calls
        if c[0] == "exec" and "cat >" in c[2] and ".tar.gz" in c[2]
    ]
    results = []

    def body(bridge):
        before = len(uploads())
        assert bridge._suspect is True
        results.append(bridge.call("grep", {"pattern": "total", "regex": True}))
        assert len(uploads()) - before == 2
        return "done"

    report = run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-collection-suspect",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert results[0].status is Status.OK


def test_every_built_copy_is_writable_and_made_when_empty(tmp_path):
    """The disposable copy is the PR's own writable space: its tests and
    the collection probe run in it as the no-root guard's user, which on
    a root runner is not the user that built it -- a test suite that
    writes into its own checkout (a conftest generating a file, a
    codegen test) fails on a read-only tree, and a conftest that fails
    at import disables every execution call. The copy's build ends by
    creating the work directory and making the tree writable; everything
    outside the copy keeps the builder's ownership. The creation is the
    point of the mkdir: `checkout-index` creates the work directory only
    when the tree has an entry, so an empty head tree must build its
    (empty) copy instead of failing the chmod on a path never made."""
    work = tmp_path / "bridge"
    scratch = work / "scratch" / "work"
    steps = stage_copy_steps(str(work), "/usr/bin/git", str(scratch), "c" * 40)
    chmod_steps = [s for s in steps if "chmod" in s]
    assert chmod_steps == [
        f"mkdir -p {shlex.quote(str(scratch))} && chmod -R a+rwX {shlex.quote(str(scratch))}"
    ]
    # Run the steps against a repository whose head commit has an EMPTY
    # tree, so checkout-index writes nothing and the work directory
    # exists only because the build makes it.
    repo = tmp_path / "repo.git"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", "init", "-q", "--bare", str(repo)], check=True)
    work.mkdir(parents=True, exist_ok=True)

    def git(*argv: str, stdin: str | None = None) -> str:
        done = subprocess.run(
            ["git", *argv], cwd=repo, capture_output=True, text=True,
            env=env, check=True, input=stdin,
        )  # fmt: skip
        return done.stdout.strip()

    empty_tree = git("mktree", stdin="")
    empty_commit = git("commit-tree", empty_tree, "-m", "empty")
    steps = stage_copy_steps(str(work), "/usr/bin/git", str(scratch), empty_commit)
    for step in steps:
        subprocess.run(["/bin/sh", "-c", step], check=False, capture_output=True)
    assert scratch.is_dir()
    assert (
        subprocess.run(
            ["/bin/sh", "-c", f"test -w {shlex.quote(str(scratch))}"], check=False
        ).returncode
        == 0
    )


# ------------------------------------------------- the operator set


def test_drop_operand_keeps_the_named_side_and_the_unpinned_one_survives(tmp_path):
    """The shape the unpinned guard Minors take (D80's 2026-11-26
    update): dropping one operand of an `or` the tests do not pin
    survives, dropping the pinned one is killed, and negating the whole
    condition is killed too -- the case the two older operators could not
    separate."""
    source = trees(
        {
            "clamp.py": (
                b"def clamp(n):\n"
                b"    if n < 0 or n > 9:\n"
                b"        return 0\n"
                b"    return n\n"
            ),
            "test_clamp.py": (
                b"from clamp import clamp\n\n"
                b"def test_middle():\n    assert clamp(5) == 5\n\n"
                b"def test_low():\n    assert clamp(-1) == 0\n"
            ),
        }
    )
    kept_low, kept_high, negated = calls(
        tmp_path,
        ("mutate", {"path": "clamp.py", "line": 2, "operator": "drop-operand", "operand": 1}),
        ("mutate", {"path": "clamp.py", "line": 2, "operator": "drop-operand", "operand": 2}),
        ("mutate", {"path": "clamp.py", "line": 2, "operator": "negate-condition"}),
        source=source,
    )[0]  # fmt: skip

    # Keeping `n < 0` and dropping `n > 9` survives -- the unpinned side
    # the drop exists to expose; keeping the pinned side is killed; and
    # negating the whole condition is killed too, which is why neither
    # older operator could separate the two.
    assert kept_low.outcome is MutantOutcome.SURVIVED
    assert kept_high.outcome is MutantOutcome.KILLED
    assert negated.outcome is MutantOutcome.KILLED


def test_break_continue_swap_is_a_real_verdict(tmp_path):
    source = trees(
        {
            "count.py": (
                b"def count_to(xs, stop):\n"
                b"    seen = 0\n"
                b"    for x in xs:\n"
                b"        if x == stop:\n"
                b"            break\n"
                b"        seen += 1\n"
                b"    return seen\n"
            ),
            "test_count.py": (
                b"from count import count_to\n\n"
                b"def test_stops_at_the_marker():\n"
                b"    assert count_to(['a', 'b', 'stop', 'c'], 'stop') == 2\n"
            ),
        }
    )
    result = one(
        tmp_path, "mutate",
        {"path": "count.py", "line": 5, "operator": "break-continue"},
        source=source,
    )  # fmt: skip
    # `continue` keeps scanning and counts the tail: killed, with a real
    # verdict rather than an operator that cannot express the defect.
    assert result.outcome is MutantOutcome.KILLED


def test_flip_compare_negates_the_first_comparison(tmp_path):
    """A flip on a comparison the tests execute is killed -- the branch
    always turns -- and one on a line no test reaches survives: the
    unpinned-guard evidence the flip exists to expose (D80's 2026-11-26
    update)."""
    source = trees(
        {
            "sign.py": (
                b"def sign(mode, n):\n"
                b"    if mode != 'pos':\n"
                b"        return 0\n"
                b"    if n > 0:\n"
                b"        return 1\n"
                b"    return 0\n"
            ),
            "test_sign.py": (
                b"from sign import sign\n\n"
                b"def test_other_mode():\n    assert sign('neg', 5) == 0\n"
            ),
        }
    )
    killed, survived = calls(
        tmp_path,
        ("mutate", {"path": "sign.py", "line": 2, "operator": "flip-compare"}),
        ("mutate", {"path": "sign.py", "line": 4, "operator": "flip-compare"}),
        source=source,
    )[0]  # fmt: skip
    assert killed.outcome is MutantOutcome.KILLED
    assert survived.outcome is MutantOutcome.SURVIVED


def test_a_misaimed_mutant_is_rejected_and_costs_nothing(tmp_path):
    result = one(
        tmp_path, "mutate",
        {"path": "calc.py", "line": 1, "operator": "negate-condition"},
    )  # fmt: skip
    assert result.status is Status.REJECTED
    assert "the mutant was refused" in result.error.text
    assert "does not apply" in result.error.text
    assert result.outcome is None


def test_drop_operand_names_the_operand_it_keeps(tmp_path):
    result = one(
        tmp_path, "mutate", {"path": "calc.py", "line": 2, "operator": "drop-operand"}
    )  # fmt: skip
    assert result.status is Status.REJECTED
    assert "drop-operand names the operand it keeps" in result.error.text


def test_only_drop_operand_takes_an_operand_index(tmp_path):
    result = one(
        tmp_path, "mutate",
        {"path": "calc.py", "line": 2, "operator": "negate-condition", "operand": 1},
    )  # fmt: skip
    assert result.status is Status.REJECTED
    assert "only drop-operand takes an operand index" in result.error.text


def test_the_operand_index_is_bounded(tmp_path):
    for bad in (0, 65, "2", True, 1.5):
        result = one(
            tmp_path, "mutate",
            {"path": "calc.py", "line": 2, "operator": "drop-operand", "operand": bad},
        )  # fmt: skip
        assert result.status is Status.REJECTED
        assert "operand" in result.error.text


def test_a_misaimed_mutant_is_refused_before_anything_runs(tmp_path):
    """The aim check runs against the controller's own copy of the head
    tree before any exec (round-2 review of #845): a mis-aimed mutate
    dispatches no runner exec at all -- no baseline included -- so the
    refusal spends nothing, the mutant cap never charges it, and a lens
    cannot spend its session on mis-aims that each ran a full baseline
    under the old post-exec refusal."""
    out = b"1 passed in 0.01s\n"

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return (
                staged()
                + framed(0, out)
                + staged()
                + mutation_block(0, "a" * 40, ok_payload(b"not xs", b"not (not xs):"))
                + framed(0, out)
            )
        return staged() + framed(0, out)

    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    "atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
            ReplyRule("__ATLAS_RUN__", answer),
        )
    )
    results = []

    def body(bridge):
        for _ in range(5):
            results.append(
                bridge.call(
                    "mutate",
                    {"path": "calc.py", "line": 1, "operator": "negate-condition"},
                )
            )
        results.append(
            bridge.call(
                "mutate", {"path": "calc.py", "line": 2, "operator": "negate-condition"}
            )
        )
        return "done"

    run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-aim-check",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
        session_limits=SessionLimits(max_mutants=1),
    )
    misaimed, valid = results[:5], results[5]
    assert all(r.status is Status.REJECTED for r in misaimed)
    assert all("the mutant was refused" in r.error.text for r in misaimed)
    # The refusal charged no slot: the valid mutant runs under a cap of 1.
    assert valid.status is Status.OK
    assert valid.outcome is MutantOutcome.SURVIVED
    # And the mis-aims dispatched no runner exec: one mutate exec total,
    # the valid call's (the fake records the sprite's name per exec, so
    # the execs are told apart by the mutation step's own temp-file name
    # in the script).
    mutate_execs = [
        c for c in sprites.calls if c[0] == "exec" and "atlas-mutant" in c[2]
    ]
    assert len(mutate_execs) == 1


def test_a_machinery_write_refusal_stays_inconclusive_and_charges(tmp_path):
    """The runner script's temporary-write OSError reads as a refusal --
    'the copy could not be written' -- but it is a machinery failure, not
    the model's mis-aim: the aim was valid (the preflight passed it) and
    the baseline already ran, so charging it as a free REJECTED would
    hide a broken runner behind the lens's clean state and skip the
    mutant slot its executed work earned. The write refusal stays on the
    inconclusive path."""
    out = b"1 passed in 0.01s\n"

    def answer(script):
        if "__ATLAS_MUT__" in script:
            reason = base64.b64encode(b"the copy could not be written").decode()
            return (
                staged()
                + framed(0, out)
                + staged()
                + mutation_block(0, "-", b"no " + reason.encode())
                + framed(0, out)
            )
        return staged() + framed(0, out)

    (result,), _ = fake_bridge(tmp_path, answer, (MUTATE_REQUEST,), source=trees(SUITE))
    # The machinery refusal stays on the inconclusive path: the tool
    # ran (the baseline executed and is charged), the verdict is the
    # named inconclusive, and the reason says what failed -- not a
    # REJECTED the caps would treat as free.
    assert result.status is Status.OK
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert "the copy could not be written" in (result.outcome_reason or "")


def test_a_parser_resource_failure_in_the_preflight_is_a_named_gap(
    tmp_path, monkeypatch
):
    """A file whose nesting exhausts the parser's stack raises
    RecursionError from ast.parse -- before any exec, outside every
    handler the exec path has. The preflight reports it as the named
    unavailable gap (machinery, not a mis-aim; nothing ran, nothing is
    charged) instead of letting the exception escape the bridge."""
    results = []

    def body(bridge):
        results.append(
            bridge.call(
                "mutate",
                {"path": "calc.py", "line": 2, "operator": "negate-condition"},
            )
        )
        results.append(bridge.call("read_file", {"path": "calc.py"}))
        return "done"

    from atlas_reviewer import bridge as bridge_module

    def exploding_parse(*args, **kwargs):
        raise RecursionError("the parser ran out of stack")

    monkeypatch.setattr(bridge_module.ast, "parse", exploding_parse)
    report, *_ = bridge_run(tmp_path, body)
    assert report.status is RunnerStatus.COMPLETED, report.note
    mutate, read = results
    assert mutate.status is Status.UNAVAILABLE
    assert "the mutant preflight could not parse the head file" in mutate.error.text
    assert "RecursionError" in mutate.error.text
    # The read tool is untouched by the preflight's own failure.
    assert read.status is Status.OK


# ------------------------------------------------- the controller sweep


SWEEP_MODULE = (
    b"def clamp(n):\n    if n < 0 or n > 9:\n        return 0\n    return n\n"
)
SWEEP_TEST = (
    b"from clamp import clamp\n\ndef test_middle():\n    assert clamp(5) == 5\n"
)
SWEEP_DIFF = """diff --git a/clamp.py b/clamp.py
--- a/clamp.py
+++ b/clamp.py
@@ -1,2 +1,4 @@
 def clamp(n):
+    if n < 0 or n > 9:
+        return 0
     return n
"""


def test_added_lines_reads_the_head_side_of_each_hunk():
    diff = (
        "--- a/m.py\n+++ b/m.py\n@@ -1,3 +1,5 @@\n ctx\n"
        "+added one\n ctx\n+added two\n-old\n ctx\n@@ -10 +12,2 @@\n+x\n y\n"
    )
    assert added_lines(diff) == frozenset({2, 4, 12})


def test_sweep_specs_names_the_changed_conditions():
    specs = sweep_specs(SWEEP_DIFF, {"clamp.py": SWEEP_MODULE})
    # The plan's rank order: the mutation classes (drop-operand,
    # break-continue) first, then the comparison flips, then the guard
    # negations -- within one line here, all tier 0 at distance 0.
    assert specs == (
        SweepSpec("clamp.py", 2, "drop-operand", 1),
        SweepSpec("clamp.py", 2, "drop-operand", 2),
        SweepSpec("clamp.py", 2, "flip-compare"),
        SweepSpec("clamp.py", 2, "negate-condition"),
    )


def test_sweep_specs_skips_test_files():
    diff = SWEEP_DIFF.replace("clamp.py", "test_clamp.py").replace(
        "a/clamp.py", "a/test_clamp.py"
    )
    assert sweep_specs(diff, {"test_clamp.py": SWEEP_MODULE}) == ()


def test_sweep_specs_dedupes_and_caps():
    doubled = SWEEP_DIFF + SWEEP_DIFF.replace("clamp.py", "other.py").replace(
        "a/clamp.py", "a/other.py"
    )
    specs = sweep_specs(doubled, {"clamp.py": SWEEP_MODULE, "other.py": SWEEP_MODULE})
    assert len(specs) == 8  # four per file, both files present
    assert len(sweep_specs(doubled, {"clamp.py": SWEEP_MODULE}, cap=2)) == 2
    # A file the controller's copy does not hold is not swept.
    assert sweep_specs(SWEEP_DIFF, {}) == ()


WIDEN_MODULE = (
    b"def guard(n):\n"
    b"    if n < 0 or n > 9:\n"
    b"        return 0\n"
    b"    return n\n"
    b"\n"
    b"def touched(n):\n"
    b"    return guard(n)\n"
)
WIDEN_CHANGED_MODULE = (
    b"def guard(n):\n"
    b"    if n < 0 or n > 9:\n"
    b"        return 0\n"
    b"    probe(n)\n"
    b"    return n\n"
)
WIDEN_RANKED_MODULE = (
    b"def guard(n):\n"
    b"    if n < 0 or n > 9:\n"
    b"        return 0\n"
    b"    return n\n"
    b"\n"
    b"def touched(n):\n"
    b"    if n == 3:\n"
    b"        return guard(n)\n"
    b"    return n\n"
)
WIDEN_CALLED_DIFF = (
    "diff --git a/widen.py b/widen.py\n"
    "--- a/widen.py\n"
    "+++ b/widen.py\n"
    "@@ -1,4 +1,7 @@\n"
    " def guard(n):\n"
    "     if n < 0 or n > 9:\n"
    "         return 0\n"
    "     return n\n"
    "+\n"
    "+def touched(n):\n"
    "+    return guard(n)\n"
)
WIDEN_CHANGED_DIFF = (
    "diff --git a/widen.py b/widen.py\n"
    "--- a/widen.py\n"
    "+++ b/widen.py\n"
    "@@ -1,4 +1,5 @@\n"
    " def guard(n):\n"
    "     if n < 0 or n > 9:\n"
    "         return 0\n"
    "+    probe(n)\n"
    "     return n\n"
)


def test_sweep_specs_reaches_a_guard_in_a_function_the_changed_code_calls():
    """The added-lines-only rule kept the anchors' key mutants out of the
    plan (#846's gap): `begin_post`'s cancel check is pre-existing code a
    changed caller reaches one hop away, and a plan that cannot name it
    cannot aim the controller's sweep at the finding. The guard a called
    function carries is in the plan now; without the widening this file's
    diff adds no guard line at all and the plan is empty."""
    specs = sweep_specs(WIDEN_CALLED_DIFF, {"widen.py": WIDEN_MODULE})
    assert specs == (
        SweepSpec("widen.py", 2, "drop-operand", 1),
        SweepSpec("widen.py", 2, "drop-operand", 2),
        SweepSpec("widen.py", 2, "flip-compare"),
        SweepSpec("widen.py", 2, "negate-condition"),
    )


def test_sweep_specs_reaches_a_guard_in_a_function_the_diff_changes():
    """A guard inside a changed function on a pre-existing line is
    sweep-relevant the same way: the change is what moved the function's
    behavior, and the plan reads its whole body, not only the added
    lines."""
    specs = sweep_specs(WIDEN_CHANGED_DIFF, {"widen.py": WIDEN_CHANGED_MODULE})
    assert specs == (
        SweepSpec("widen.py", 2, "drop-operand", 1),
        SweepSpec("widen.py", 2, "drop-operand", 2),
        SweepSpec("widen.py", 2, "flip-compare"),
        SweepSpec("widen.py", 2, "negate-condition"),
    )


def test_sweep_specs_ranks_the_mutation_classes_ahead_of_the_other_guards():
    """A dropped-operand mutant in a called function outranks the added
    lines' own flip and negate guards: the classes the parity key's
    mutants are sweep first, and a plan ordered only by tier or line
    would spend the cap on negate-conditions while the BoolOp went
    unswept."""
    diff = WIDEN_CALLED_DIFF.replace(
        "+    return guard(n)\n",
        "+    if n == 3:\n+        return guard(n)\n+    return n\n",
    ).replace("@@ -1,4 +1,7 @@", "@@ -1,4 +1,9 @@")
    specs = sweep_specs(diff, {"widen.py": WIDEN_RANKED_MODULE})
    assert specs == (
        SweepSpec("widen.py", 2, "drop-operand", 1),
        SweepSpec("widen.py", 2, "drop-operand", 2),
        SweepSpec("widen.py", 7, "flip-compare"),
        SweepSpec("widen.py", 2, "flip-compare"),
        SweepSpec("widen.py", 7, "negate-condition"),
        SweepSpec("widen.py", 2, "negate-condition"),
    )


def test_sweep_specs_ranks_nearer_to_the_diff_first_within_a_class():
    """Two pre-existing BoolOps in one changed function rank by their
    distance to the nearest added line: the guard nearest the change
    sweeps before the farther one."""
    module = (
        b"def guard(n):\n"
        b"    if n < 0 or n > 9:\n"
        b"        return 0\n"
        b"    if n == 1 or n == 2:\n"
        b"        return 1\n"
        b"    probe(n)\n"
        b"    return n\n"
    )
    diff = (
        "diff --git a/widen.py b/widen.py\n"
        "--- a/widen.py\n"
        "+++ b/widen.py\n"
        "@@ -1,5 +1,7 @@\n"
        " def guard(n):\n"
        "     if n < 0 or n > 9:\n"
        "         return 0\n"
        "     if n == 1 or n == 2:\n"
        "         return 1\n"
        "+    probe(n)\n"
        "+    return n\n"
    )
    specs = sweep_specs(diff, {"widen.py": module})
    assert specs == (
        SweepSpec("widen.py", 4, "drop-operand", 1),
        SweepSpec("widen.py", 4, "drop-operand", 2),
        SweepSpec("widen.py", 2, "drop-operand", 1),
        SweepSpec("widen.py", 2, "drop-operand", 2),
        SweepSpec("widen.py", 4, "flip-compare"),
        SweepSpec("widen.py", 2, "flip-compare"),
        SweepSpec("widen.py", 4, "negate-condition"),
        SweepSpec("widen.py", 2, "negate-condition"),
    )


def test_sweep_specs_spends_the_cap_round_robin_over_the_changed_files():
    """The cap used to fill from the first file in path order, so a big
    first file starved every other changed file's guards (#846's gap).
    The cap is spent one pick per file per pass: each changed file's most
    relevant guards are in the plan before any file gets a second."""
    doubled = SWEEP_DIFF + SWEEP_DIFF.replace("clamp.py", "other.py").replace(
        "a/clamp.py", "a/other.py"
    )
    contents = {"clamp.py": SWEEP_MODULE, "other.py": SWEEP_MODULE}
    specs = sweep_specs(doubled, contents, cap=4)
    assert specs == (
        SweepSpec("clamp.py", 2, "drop-operand", 1),
        SweepSpec("other.py", 2, "drop-operand", 1),
        SweepSpec("clamp.py", 2, "drop-operand", 2),
        SweepSpec("other.py", 2, "drop-operand", 2),
    )


def test_the_sweep_run_bound_matches_the_execution_tools_clock():
    """The sweep's scoped run is one of the execution tools' test
    processes (#843 raised their per-process clock from 60s for exactly
    the whole-suite reason the sweep's own bound shares): the two bounds
    move together, so a suite that fits `run_tests` fits the sweep's
    scoped run too."""
    assert SWEEP_RUN_BOUND_S == DEFAULT_LIMITS["run_tests"].timeout_s


def test_sweep_groups_group_by_module_and_require_an_importer():
    specs = sweep_specs(SWEEP_DIFF, {"clamp.py": SWEEP_MODULE})
    groups = sweep_groups(
        specs, {"clamp.py": SWEEP_MODULE, "test_clamp.py": SWEEP_TEST}
    )
    assert len(groups) == 1
    assert groups[0].module == "clamp.py"
    assert groups[0].selectors == ("test_clamp.py",)
    # A module whose importer is not staged forms no group.
    groups = sweep_groups(
        sweep_specs(SWEEP_DIFF, {"clamp.py": SWEEP_MODULE}), {"clamp.py": SWEEP_MODULE}
    )
    assert groups == ()  # the test file that imports it is not staged


def test_parse_sweep_maps_the_verdicts():
    group = SweepGroup(
        "clamp.py",
        ("test_clamp.py",),
        (
            SweepSpec("clamp.py", 2, "drop-operand", 1),
            SweepSpec("clamp.py", 2, "drop-operand", 2),
            SweepSpec("clamp.py", 3, "negate-condition"),
            SweepSpec("clamp.py", 3, "flip-compare"),
        ),
    )
    text = (
        "atlas-baseline:clamp.py:0:\n"
        "atlas-sweep:0:0:\n"
        "atlas-sweep:1:1:\n"
        "atlas-sweep:2:124:\n"
        "atlas-sweep:3:5:\n"
    )
    survived, killed, timed, empty = parse_sweep(text, group)
    assert survived.outcome == "survived" and survived.exit == 0
    assert killed.outcome == "killed" and killed.exit == 1
    assert timed.outcome == "inconclusive" and "wall clock" in timed.note
    assert empty.outcome == "inconclusive" and "no test" in empty.note


def test_parse_sweep_reports_the_baseline_and_the_refusal():
    group = SweepGroup(
        "clamp.py", ("test_clamp.py",), (SweepSpec("clamp.py", 2, "negate-condition"),)
    )
    text = (
        "atlas-baseline:clamp.py:1:"
        + base64.b64encode(b"1 failed").decode()
        + "\natlas-sweep:0:R:-:"
        + base64.b64encode(b"the operator does not apply").decode()
        + "\n"
    )
    (verdict,) = parse_sweep(text, group)
    assert verdict.outcome == "refused"
    assert "the operator does not apply" in verdict.note
    no_baseline = parse_sweep("atlas-sweep:0:0:\n", group)
    assert no_baseline[0].outcome == "inconclusive"
    failed_baseline = parse_sweep(
        "atlas-baseline:clamp.py:1:\natlas-sweep:0:2:\n", group
    )
    assert failed_baseline[0].outcome == "inconclusive"
    assert "baseline" in failed_baseline[0].note
    missing = parse_sweep("atlas-baseline:clamp.py:0:\n", group)
    assert missing[0].outcome == "inconclusive"
    assert "no verdict" in missing[0].note


def test_the_sweep_script_stages_copy_edit_run_and_cleans_up(tmp_path):
    staged = Staged(
        str(tmp_path / "root"),
        "/usr/bin/git",
        MappingProxyType({Rev.HEAD: "h" * 40}),
        pytest=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
        shim_python=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
    )
    group = SweepGroup(
        "clamp.py", ("test_clamp.py",),
        (SweepSpec("clamp.py", 2, "negate-condition"), SweepSpec("clamp.py", 2, "drop-operand", 2)),
    )  # fmt: skip
    script = sweep_script(staged, group, ToolLimits(16 * 1024, 60))
    assert "atlas-baseline:clamp.py:" in script
    assert "atlas-sweep:0:" in script and "atlas-sweep:1:" in script
    assert script.count("timeout -k 2 60") == 3  # baseline plus two runs
    assert script.count("atlas-privilege-drop failed") == 3  # every run is guarded
    assert script.count(MUTATION_SCRIPT[:40]) == 2  # one edit per spec
    assert "drop-operand 2" in script  # the operand rides the edit argv
    assert script.count("rm -rf") >= 3  # the copies die after their runs


def test_added_lines_counts_a_line_whose_content_starts_with_plus():
    # The old `not startswith("+++")` guard dropped a genuinely added
    # line whose content begins with `++` (here `++counter`) and shifted
    # every later number in the hunk by one.
    diff = "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,3 @@\n ctx\n+++counter\n+x\n"
    assert added_lines(diff) == frozenset({2, 3})


def test_imports_module_matches_the_from_package_form():
    assert _imports_module(
        "from atlas_reviewer import bridge\n", "atlas_reviewer.bridge"
    )
    assert _imports_module(
        "from atlas_reviewer.bridge import run_bridge\n", "atlas_reviewer.bridge"
    )
    assert not _imports_module(
        "from atlas_reviewer import other\n", "atlas_reviewer.bridge"
    )


CALC_SWEEP_DIFF = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,4 @@
 def total(xs):
+    if not xs:
+        return 0
     return sum(xs)
"""


def test_the_sweep_reports_what_no_test_imports(tmp_path):
    """A changed condition in a module no staged test file imports forms
    no group -- and the sweep now says so, an inconclusive verdict with
    the reason for every such spec, instead of dropping it silently so a
    lens could read the block as 'swept clean'. No runner exec is spent:
    the ungrouped specs never reach the script."""
    source = SourceTrees(
        source_tarball({**SUITE, "orphan.py": SWEEP_MODULE}),
        source_tarball({**SUITE, "orphan.py": SWEEP_MODULE}),
        OLD,
        HEAD,
    )
    orphan_diff = SWEEP_DIFF.replace("clamp.py", "orphan.py").replace(
        "a/clamp.py", "a/orphan.py"
    )
    results = []

    def body(bridge):
        results.append(bridge.sweep(bridge.sweep_plan(orphan_diff), clock=FakeClock()))
        return "done"

    report, *_ = bridge_run(tmp_path, body, source=source)
    assert report.status is RunnerStatus.COMPLETED, report.note
    (verdicts,) = results
    assert verdicts
    assert all(v.outcome == "inconclusive" for v in verdicts)
    assert all("no test file imports this module" in v.note for v in verdicts)


def _sweep_sprites(answer):
    return FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    "atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
            # Before __ATLAS_RUN__: the sweep script frames runs too, and
            # its own baseline/sweep tags identify it.
            ReplyRule("atlas-baseline", lambda _script: answer),
            ReplyRule(
                "__ATLAS_RUN__",
                lambda _script: staged() + framed(0, b"1 passed in 0.01s\n"),
            ),
        )
    )


def test_the_sweep_group_budget_is_clamped_to_what_is_left(tmp_path):
    """The between-groups check bounded the whole pass but not one group's
    own exec: a 24-spec group's budget could run ~40 minutes against a
    300-second sweep. Each group's exec budget is now clamped to the wall
    the pass has left, and a group the remainder cannot even start is
    reported inconclusive -- named -- instead of exec'd into its own
    clock."""
    sprites = _sweep_sprites("atlas-baseline:calc.py:0:\natlas-sweep:0:0:\n")
    results = []

    def body(bridge):
        floor = SWEEP_RUN_BOUND_S + KILL_AFTER_S + EXEC_SLACK_S
        results.append(
            bridge.sweep(
                bridge.sweep_plan(CALC_SWEEP_DIFF),
                clock=FakeClock(),
                budget_s=floor - 1,
            )
        )
        return "done"

    run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-sweep-clamp",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
    )
    (verdicts,) = results
    assert verdicts
    assert all(v.outcome == "inconclusive" for v in verdicts)
    assert all("could not fit this group's runs" in v.note for v in verdicts)
    assert not any(c[0] == "exec" and "atlas-sweep" in c[2] for c in sprites.calls)


def test_the_sweep_runs_when_the_budget_fits_and_is_memoized(tmp_path):
    """A group the budget fits runs and reports its verdict; a second
    sweep of the same specs -- the retry attempt's -- reads the cached
    verdicts and dispatches no new exec."""
    sprites = _sweep_sprites("atlas-baseline:calc.py:0:\natlas-sweep:0:0:\n")
    results = []

    def body(bridge):
        results.append(
            bridge.sweep(bridge.sweep_plan(CALC_SWEEP_DIFF), clock=FakeClock())
        )
        results.append(
            bridge.sweep(bridge.sweep_plan(CALC_SWEEP_DIFF), clock=FakeClock())
        )
        return "done"

    run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-sweep-memo",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
    )
    first, second = results
    assert first[0].outcome == "survived"
    assert second == first
    sweep_execs = [
        c for c in sprites.calls if c[0] == "exec" and "atlas-baseline" in c[2]
    ]
    assert len(sweep_execs) == 1


def test_a_failed_sweep_exec_still_marks_the_bridge_suspect(tmp_path):
    """PR code runs during the sweep's exec, whatever the exec's outcome:
    the suspect flag is set before the exec, so an exec that raises -- a
    lost connection mid-exec -- still leaves the bridge suspect, and the
    next runner-side read re-stages from the controller-held tarballs
    instead of serving what the failed exec's mutants left behind. Before
    this fix the flag was set only after the exec returned, and the
    lens-loop's degradation then carried the lens on a possibly rewritten
    tree."""
    import atlas_reviewer.bridge as bridge_module

    class ExplodingRule:
        match = "atlas-baseline"

        def handler(self, script, _stdin):
            raise bridge_module.BoundaryError("the sweep's exec died mid-run")

    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    "atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
            ExplodingRule(),
            ExecRule(
                "__ATLAS_BRIDGE__",
                "__ATLAS_BRIDGE__ 0 0 9 0 0\n",
                0,
            ),
        )
    )
    uploads = lambda: [
        c
        for c in sprites.calls
        if c[0] == "exec" and "cat >" in c[2] and ".tar.gz" in c[2]
    ]
    results = []

    def body(bridge):
        try:
            bridge.sweep(bridge.sweep_plan(CALC_SWEEP_DIFF), clock=FakeClock())
        except BoundaryError:
            pass
        assert bridge._suspect is True
        # The count starts at the read: the bridge may legitimately have
        # re-staged before the exec too, since the staging's collection
        # probe runs PR code and starts the bridge suspect.
        before = len(uploads())
        results.append(bridge.call("grep", {"pattern": "total", "regex": True}))
        # The runner-side read re-staged: both trees re-uploaded.
        assert len(uploads()) - before == 2
        return "done"

    report = run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-sweep-suspect",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert results[0].status is Status.OK


def test_a_failed_run_exec_still_marks_the_bridge_suspect(tmp_path):
    """The same invariant for the run tools' own exec: an exec that raises
    after the baseline's code ran -- here the machinery lost the reply --
    leaves the bridge suspect, and the next runner-side read re-stages.
    The old code set the flag only in the timeout handler and after a
    successful exec; a BoundaryError from the exec itself slipped
    through."""
    import atlas_reviewer.bridge as bridge_module

    class ExplodingRunRule:
        match = "__ATLAS_RUN__"

        def handler(self, script, _stdin):
            raise bridge_module.BoundaryError("the run exec died mid-run")

    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    "atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
            ExplodingRunRule(),
            ExecRule(
                "__ATLAS_BRIDGE__",
                "__ATLAS_BRIDGE__ 0 0 9 0 0\n",
                0,
            ),
        )
    )
    uploads = lambda: [
        c
        for c in sprites.calls
        if c[0] == "exec" and "cat >" in c[2] and ".tar.gz" in c[2]
    ]
    results = []

    def body(bridge):
        try:
            bridge.call("run_tests", {})
        except BoundaryError:
            pass
        assert bridge._suspect is True
        # The count starts at the read, for the same collection-probe
        # reason the sweep test names.
        before = len(uploads())
        results.append(bridge.call("grep", {"pattern": "total", "regex": True}))
        assert len(uploads()) - before == 2
        return "done"

    report = run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-run-suspect",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert results[0].status is Status.OK


# ------------------------------------------------- the probe tool


def test_a_probe_runs_the_written_file_and_leaves_nothing_behind(tmp_path):
    probe = (
        b"from calc import total\n\n"
        b"def test_probe_sees_the_real_total():\n"
        b"    assert total([1, 2, 3]) == 6\n"
    )
    (probe_result, grep_result), _bridge = calls(
        tmp_path,
        ("run_probe", {"content": probe.decode()}),
        ("grep", {"pattern": "test_atlas_probe"}),
    )
    assert probe_result.status is Status.OK
    assert "1 passed" in probe_result.content.text
    # The probe file never reaches the repository or the trees: the grep
    # over the head tree finds nothing, and the run's result is the only
    # trace.
    assert grep_result.status is Status.OK
    assert grep_result.content.text.strip() in ("", "no match")


def test_the_probe_script_writes_base64_and_guards_the_run(tmp_path):
    call = validate(
        "run_probe", {"content": "def test_x():\n    assert 1\n"}, frozenset(Rev)
    )
    staged = Staged(
        str(tmp_path / "root"),
        "/usr/bin/git",
        MappingProxyType({Rev.HEAD: "h" * 40}),
        pytest=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
        shim_python=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
    )
    script = run_probe_script(staged, call, ToolLimits(16 * 1024, 180))
    assert "test_atlas_probe_" in script and "base64 -d" in script
    assert "atlas-privilege-drop failed" in script  # the guard wraps the run
    assert "timeout -k 2 180" in script  # the same clock run_tests uses
    # The default selector is the probe file itself, at the copy's root.
    assert "test_atlas_probe_" in script.split("base64 -d")[1]
    # The named selector is a ::node-id suffix appended to the probe
    # file's own path -- the model never names the file, whose name is
    # the controller's.
    named = validate(
        "run_probe",
        {"content": "def test_x():\n    assert 1\n", "selector": "::TestX::test_x"},
        frozenset(Rev),
    )
    named_script = run_probe_script(staged, named, ToolLimits(16 * 1024, 180))
    # The shim's payload is multi-line, so the argv spans lines: assert the
    # suffix sits directly against the probe path's `.py` in the script.
    assert ".py::TestX::test_x" in named_script
    # Anything but a ::node-id suffix is refused: the model cannot name a
    # file (it does not know the probe file's name) and cannot smuggle a
    # second positional.
    for bad in ("test_probe_file.py::test_x", "::test x", "x", "::"):
        refused = one(
            tmp_path,
            "run_probe",
            {"content": "def test_x():\n    assert 1\n", "selector": bad},
        )  # fmt: skip
        assert refused.status is Status.REJECTED, bad


def test_the_probe_content_is_capped_and_control_character_free(tmp_path):
    too_big = one(tmp_path, "run_probe", {"content": "x = 1\n" * (16 * 1024 // 6 + 1)})
    assert too_big.status is Status.REJECTED
    assert "over" in too_big.error.text
    control = one(tmp_path, "run_probe", {"content": "x = 1\x00\n"})
    assert control.status is Status.REJECTED
    assert "control character" in control.error.text


def test_the_probe_shares_the_test_run_cap(tmp_path):
    probe = {"content": "def test_x():\n    assert True\n"}
    first, second = calls(
        tmp_path,
        ("run_probe", dict(probe)),
        ("run_probe", dict(probe)),
        session_limits=SessionLimits(max_test_runs=1),
    )[0]  # fmt: skip
    assert first.status is Status.OK
    assert second.status is Status.OVER_SESSION_LIMIT
    assert "all 1 run_tests calls" in second.error.text


def test_probe_content_with_an_unpaired_surrogate_is_a_rejected_call(tmp_path):
    """Python's JSON decoder accepts unpaired surrogates, which no UTF-8
    encoder will encode: the byte-cap check's encode raised
    UnicodeEncodeError out of the validator, past the tool boundary's
    RejectedError handler -- a crashed call instead of the rejected one
    the model can re-issue from. The same hole sat in every validator
    that measured UTF-8 length (paths, patterns, commands, the probe's
    content), so the fix is one helper all of them share -- and the
    post-merge check of #849 found the bash command's validator had been
    left on the bare encode: it is driven here through its real entry
    point, with the unpaired surrogate in the model-written command."""
    surrogate = '"' + chr(0xD800) + '"'
    for tool, args in (
        # The probe's content, a read's path, and the bash command: three
        # validators whose UTF-8 length check used to raise past the
        # boundary.
        ("run_probe", {"content": surrogate}),
        ("read_file", {"path": surrogate}),
        ("bash", {"command": surrogate}),
    ):
        refused = one(tmp_path, tool, args)
        assert refused.status is Status.REJECTED, tool
        assert "not encodable as UTF-8" in refused.error.text


# ------------------------------------------------- the history tools


def _seed_history(tmp_path: Path) -> tuple[Path, str, str, bytes]:
    """A real git repository with a two-commit history and a bundle of it:
    the base commit carries the pre-change calc, the head commit the
    change and its test. Returns the repo path, the base SHA, the head
    SHA, and the bundle's bytes."""
    repo = tmp_path / "seed"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }

    def git(*argv: str) -> str:
        done = subprocess.run(
            ["git", *argv],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    (repo / "calc.py").write_text("def total(xs):\n    return sum(xs)\n")
    git("add", "-A")
    git("commit", "-qm", "base: the unchanged total")
    base = git("rev-parse", "HEAD")
    (repo / "calc.py").write_text(
        "def total(xs):\n    return sum(xs)  # rounded later\n"
    )
    (repo / "test_calc.py").write_text(
        "from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n"
    )
    git("add", "-A")
    git("commit", "-qm", "head: the change under review")
    head = git("rev-parse", "HEAD")
    git("update-ref", "refs/heads/atlas-history", head)
    git(
        "bundle", "create", str(tmp_path / "history.bundle"), "refs/heads/atlas-history"
    )
    return repo, base, head, (tmp_path / "history.bundle").read_bytes()


def test_the_history_tools_read_the_staged_bundle(tmp_path):
    """The git-history tools (D80's git-history update): the staged
    repository carries the real history the bundle brought, the range's
    log reads, a range commit shows, base's history is reachable, and a
    revision outside both is a rejected call, not a failed one."""
    _repo, base, head, bundle = _seed_history(tmp_path)
    source = SourceTrees(
        source_tarball(
            {
                "calc.py": b"def total(xs):\n    return sum(xs)  # rounded later\n",
                "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
            }
        ),
        source_tarball(
            {
                "calc.py": b"def total(xs):\n    return sum(xs)  # rounded later\n",
                "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
            }
        ),
        base,
        head,
    )
    results = []

    def body(bridge):
        results.extend(
            (
                bridge.call("git_log", {}),
                bridge.call("git_show", {"rev": head}),
                bridge.call("git_show", {"rev": base, "path": "calc.py"}),
                bridge.call("git_blame", {"path": "calc.py", "line": 1, "end_line": 2}),
                bridge.call("git_show", {"rev": "f" * 40}),
            )
        )
        return "done"

    report = run_bridge(
        LocalSprites(),
        MemoryLedger(),
        source,
        body,
        redactor=Redactor(),
        changed=frozenset({"calc.py"}),
        name="cqa-history-test",
        deadline_s=300,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        history_bundle=bundle,
        history_base=base,
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    log, show_head, show_base, blame, outside = results
    assert log.status is Status.OK
    assert "the change under review" in log.content.text
    assert head[:7] in log.content.text
    assert show_head.status is Status.OK
    assert "rounded later" in show_head.content.text
    # A commit reachable from base is a valid rev too.
    assert show_base.status is Status.OK
    assert "def total" in show_base.content.text
    assert blame.status is Status.OK
    assert "def total(xs):" in blame.content.text
    assert outside.status is Status.REJECTED
    assert "outside the pull request" in outside.content.text


def test_the_history_tools_report_a_run_with_no_bundle(tmp_path):
    (no_log,) = calls(tmp_path, ("git_log", {}))[0]
    assert no_log.status is Status.UNAVAILABLE
    assert "no repository history was staged" in no_log.error.text


def test_the_bundle_is_uploaded_in_chunks_and_the_cap_refuses(tmp_path, monkeypatch):
    """A bundle over one exec's stdin rides in parts the staging step
    concatenates; a bundle over the whole cap refuses the run named."""
    import atlas_reviewer.bridge_staging as staging

    _repo, base, head, bundle = _seed_history(tmp_path)
    monkeypatch.setattr(staging, "HISTORY_CHUNK_BYTES", 256)
    source = SourceTrees(
        source_tarball(
            {
                "calc.py": b"def total(xs):\n    return sum(xs)  # rounded later\n",
                "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
            }
        ),
        source_tarball(
            {
                "calc.py": b"def total(xs):\n    return sum(xs)  # rounded later\n",
                "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
            }
        ),
        base,
        head,
    )
    results = []

    def body(bridge):
        results.append(bridge.call("git_log", {}))
        return "done"

    report = run_bridge(
        LocalSprites(),
        MemoryLedger(),
        source,
        body,
        redactor=Redactor(),
        changed=frozenset({"calc.py"}),
        name="cqa-chunk-test",
        deadline_s=300,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        history_bundle=bundle,
        history_base=base,
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    (log,) = results
    assert log.status is Status.OK
    assert "the change under review" in log.content.text
    # A bundle over the cap degrades to the named no-history gap on the
    # history tools: the run completes and every other tool is untouched.
    over = bundle + b"x" * (staging.HISTORY_BUNDLE_MAX_BYTES)
    results2 = []

    def body2(bridge):
        results2.append(bridge.call("git_log", {}))
        results2.append(bridge.call("read_file", {"path": "calc.py"}))
        return "done"

    report2 = run_bridge(
        LocalSprites(),
        MemoryLedger(),
        source,
        body2,
        redactor=Redactor(),
        changed=frozenset({"calc.py"}),
        name="cqa-over-cap",
        deadline_s=300,
        clock=FakeClock(),
        root=str(tmp_path / "bridge2"),
        history_bundle=over,
    )
    assert report2.status is RunnerStatus.COMPLETED, report2.note
    no_history, read = results2
    assert no_history.status is Status.UNAVAILABLE
    assert "exceeds" in no_history.error.text
    assert read.status is Status.OK


def test_a_refetch_that_fails_after_a_restage_names_the_gap(tmp_path):
    """The re-stage's re-fetch can fail -- the bundle the controller held
    no longer fetches into the rebuilt repository. The history tools then
    report the named gap, saying the re-fetch failed, not a broken git
    error, and the run's other tools are untouched."""
    calls = []

    class FlakyHistory:
        match = "refs/atlas-history/head"

        def handler(self, script, _stdin):
            calls.append(script)
            if len(calls) == 1:
                return "atlas-history:ok", 0
            return "atlas-history:fetch-failed", 0

    out = b"1 passed in 0.01s\n"

    def answer(script):
        return staged() + framed(0, out)

    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    "atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
            FlakyHistory(),
            ReplyRule("__ATLAS_RUN__", answer),
        )
    )
    results = []

    def body(bridge):
        results.append(bridge.call("run_tests", {}))
        results.append(bridge.call("git_log", {}))
        results.append(bridge.call("read_file", {"path": "calc.py"}))
        return "done"

    run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-refetch-fails",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
        history_bundle=b"fake bundle bytes",
        history_base="a" * 40,
    )
    run_result, log, read = results
    assert run_result.status is Status.OK
    assert log.status is Status.UNAVAILABLE
    assert "re-fetch failed" in log.error.text
    assert "the history bundle" in log.error.text
    assert read.status is Status.OK
    assert len(calls) == 2


def test_the_history_survives_a_restage(tmp_path):
    """A run tool executes PR code and marks the bridge suspect; the next
    call re-stages from the tarballs. The real history the bundle brought
    lives in the repository the staging rebuilds, so the bridge keeps the
    bundle and re-uploads and re-fetches it as part of that re-stage: a
    history call after a run tool still reads, and one whose re-fetch
    fails reports the named gap instead of a broken git error."""
    _repo, base, head, bundle = _seed_history(tmp_path)
    source = SourceTrees(
        source_tarball(
            {
                "calc.py": b"def total(xs):\n    return sum(xs)  # rounded later\n",
                "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
            }
        ),
        source_tarball(
            {
                "calc.py": b"def total(xs):\n    return sum(xs)  # rounded later\n",
                "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
            }
        ),
        base,
        head,
    )
    results = []

    def body(bridge):
        results.append(bridge.call("run_tests", {}))
        results.append(bridge.call("git_log", {}))
        results.append(bridge.call("git_blame", {"path": "calc.py", "line": 2}))
        return "done"

    report, *_ = bridge_run(
        tmp_path,
        body,
        source=source,
        history_bundle=bundle,
        history_base=base,
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    run_result, log, blame = results
    assert run_result.status is Status.OK and run_result.head_sha == head
    assert log.status is Status.OK
    assert "the change under review" in log.content.text
    assert blame.status is Status.OK
    assert blame.content.text.count("rounded later") == 1


def test_parse_history_refuses_a_wrong_head_verdict():
    """The verification is what stands between a stale or wrong bundle's
    history and the lenses reading it as the pull request's own: a
    `wrong-head:<sha>` verdict is a staging failure naming the SHA the
    bundle actually carried (the round-1 review's mutant silenced the
    verdict and survived the suite -- this pins the branch)."""
    with pytest.raises(BoundaryError) as excinfo:
        parse_history(0, "atlas-history:wrong-head:" + "d" * 40 + "\n", "c" * 40)
    assert "not the pull request's" in str(excinfo.value)
    assert "d" * 40 in str(excinfo.value)


def test_a_bundle_carrying_a_different_head_is_a_named_staging_failure(
    tmp_path,
):
    """End to end: a bundle whose `atlas-history` ref points at a commit
    that is not the pull request's head is refused at staging -- the run
    completes, the history tools report the named no-history gap carrying
    the wrong-head reason, and no other tool is touched."""
    _repo, base, _head, _bundle = _seed_history(tmp_path)
    # A bundle whose atlas-history ref points at the BASE commit: the
    # fetched head is not the trees' head, which is the wrong-head
    # verdict's whole job to catch.
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }

    def git(*argv: str) -> None:
        subprocess.run(
            ["git", *argv],
            cwd=_repo,
            capture_output=True,
            env=env,
            check=True,
        )

    git("update-ref", "refs/heads/atlas-history", base)
    git("bundle", "create", str(tmp_path / "wrong.bundle"), "refs/heads/atlas-history")
    wrong_bundle = (tmp_path / "wrong.bundle").read_bytes()
    content = {
        "calc.py": b"def total(xs):\n    return sum(xs)  # rounded later\n",
        "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
    }
    source = SourceTrees(source_tarball(content), source_tarball(content), base, HEAD)
    results = []

    def body(bridge):
        results.append(bridge.call("git_log", {}))
        results.append(bridge.call("read_file", {"path": "calc.py"}))
        return "done"

    report, *_ = bridge_run(
        tmp_path,
        body,
        source=source,
        history_bundle=wrong_bundle,
        history_base=base,
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    log, read = results
    assert log.status is Status.UNAVAILABLE
    assert "not the pull request's" in log.error.text
    assert read.status is Status.OK


# ------------------------------------------------- the sandboxed bash tool


def test_the_bash_script_carries_the_no_root_guard():
    """The guard is structural, not incidental: the probe tool's test
    pins its guard by the shim's markers in the script, because an
    assertion on the command's printed euid cannot distinguish the guard
    on a runner whose test user is already non-root (the round-1 review's
    mutant -- as_nobody dropped from bash_script -- survived the suite
    for exactly that reason). The same structural pin here: the bash
    command runs wrapped in the guard shim, so dropping it fails."""
    staged = Staged(
        "/tmp/bridge",
        "/usr/bin/git",
        MappingProxyType({Rev.HEAD: "h" * 40}),
        pytest=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
        shim_python=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
    )
    script = bash_script(
        staged,
        validate("bash", {"command": "echo hi"}, frozenset(Rev)),
        ToolLimits(16 * 1024, 60),
    )
    assert "atlas-privilege-drop failed" in script  # the guard wraps the run
    assert "timeout -k 2 60" in script  # the same clock the run tools use


def test_a_bash_command_runs_in_the_copy_as_the_non_root_user(tmp_path):
    """The sandboxed bash tool (D80's bash-tool update): the command runs
    in the lens's own disposable copy, as the non-root user, and sees the
    copy's files; nothing it writes reaches the repository or a later
    call."""
    (run, check, grep) = calls(
        tmp_path,
        (
            "bash",
            {"command": "id -u; ls; echo marker-written > bash_wrote_this.txt"},
        ),
        ("bash", {"command": "test ! -e bash_wrote_this.txt && echo gone"}),
        ("grep", {"pattern": "bash_wrote_this"}),
    )[0]  # fmt: skip
    assert run.status is Status.OK
    # The non-root user's id, not root's.
    assert run.content.text.splitlines()[0] != "0"
    assert "calc.py" in run.content.text
    # The file the first command wrote died with its copy.
    assert check.status is Status.OK
    assert "gone" in check.content.text
    assert grep.status is Status.OK
    assert grep.content.text.strip() in ("", "no match")


def test_a_bash_command_reads_the_staged_history_in_the_copy(tmp_path):
    """Git history over the pull request's range is readable inside the
    copy: the copy's .git file points at the staged repository, whose
    real history the bundle brought, so the model's own `git log` works
    without knowing where anything is staged."""
    _repo, base, head, bundle = _seed_history(tmp_path)
    head_content = {
        "calc.py": b"def total(xs):\n    return sum(xs)  # rounded later\n",
        "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
    }
    source = SourceTrees(
        source_tarball(head_content), source_tarball(head_content), base, head
    )
    (result,) = calls(
        tmp_path,
        (
            "bash",
            {
                "command": (
                    "git log --oneline --no-decorate "
                    f"{base}..refs/atlas-history/head"
                )
            },
        ),
        source=source,
        history_bundle=bundle,
        history_base=base,
    )[0]  # fmt: skip
    assert result.status is Status.OK
    assert "the change under review" in result.content.text


def test_a_bash_command_runs_under_verified_deny_all(tmp_path):
    """The egress rule the sandbox rests on: the bash exec runs after the
    verified deny-all flip, like every other exec of the review."""
    sprites = LocalSprites()
    (result,) = calls(
        tmp_path,
        ("bash", {"command": "echo marker-in-the-bash-script"}),
        sprites=sprites,
    )[0]  # fmt: skip
    assert result.status is Status.OK
    scripts = [argv[-1] for argv in sprites.argv_seen]
    bash_index = next(
        i for i, script in enumerate(scripts) if "marker-in-the-bash-script" in script
    )
    denied = [flag for _name, flag in sprites.policy_deny_named]
    assert denied[bash_index] is True


def test_a_bash_command_past_its_clock_times_out(tmp_path):
    limits = {**DEFAULT_LIMITS, "bash": ToolLimits(16 * 1024, 1)}
    (result,) = calls(
        tmp_path,
        ("bash", {"command": "sleep 5"}),
        limits=limits,
    )[0]  # fmt: skip
    assert result.status is Status.TIMED_OUT


def test_a_bash_command_is_refused_without_the_guard_interpreter(tmp_path):
    (result,) = calls(
        tmp_path,
        ("bash", {"command": "echo hi"}),
        pytest_candidates=(),
    )[0]  # fmt: skip
    assert result.status is Status.UNAVAILABLE
    assert "no interpreter on the runner image runs the no-root guard" in (
        result.error.text
    )


def test_a_bash_write_into_the_staged_repository_does_not_survive(tmp_path):
    """The copy's .git file points at the staged repository itself, so the
    model's command can write into repo.git -- a ref, a loose object, a
    config edit -- as the non-root user. The re-stage discipline that
    guards every other exec tool guards bash too: the next call's copy is
    built from the controller-held tarballs' repository, so nothing an
    earlier command left in repo.git reaches a later call."""
    (make, read) = calls(
        tmp_path,
        (
            "bash",
            {"command": 'echo tampered > "$(git rev-parse --git-dir)/marker"'},
        ),
        (
            "bash",
            {
                "command": (
                    'test ! -e "$(git rev-parse --git-dir)/marker" '
                    "&& echo wiped || echo survived"
                )
            },
        ),
    )[0]  # fmt: skip
    assert make.status is Status.OK
    # The file the first command wrote into repo.git is gone: the second
    # call's repository was rebuilt from the tarballs.
    assert read.status is Status.OK
    assert "wiped" in read.content.text


def test_a_bash_command_over_its_cap_is_refused(tmp_path):
    refused = one(tmp_path, "bash", {"command": "x" * (MAX_BASH_CHARS + 1)})
    assert refused.status is Status.REJECTED
    assert "over" in refused.error.text


def test_a_failed_bash_exec_still_marks_the_bridge_suspect(tmp_path):
    """The same invariant the base pinned for the run tools and the sweep,
    for the bash tool's own exec: the command's code runs during the
    exec, whatever the exec's outcome -- and the command's `.git` file
    points at the staged repository, so what it leaves behind reaches the
    next call's copy unless the bridge is marked suspect. An exec that
    raises -- here the machinery losing the reply mid-command -- leaves
    the bridge suspect, and the next call re-stages from the
    controller-held tarballs."""
    import atlas_reviewer.bridge as bridge_module

    class ExplodingBashRule:
        match = 'echo "gitdir:'

        def handler(self, script, _stdin):
            raise bridge_module.BoundaryError("the bash exec died mid-command")

    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    "atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
            ExplodingBashRule(),
            ExecRule("__ATLAS_BRIDGE__", "__ATLAS_BRIDGE__ 0 0 9 0 0\n", 0),
        )
    )
    uploads = lambda: [
        c
        for c in sprites.calls
        if c[0] == "exec" and "cat >" in c[2] and ".tar.gz" in c[2]
    ]
    results = []

    def body(bridge):
        try:
            bridge.call("bash", {"command": "echo hi"})
        except BoundaryError:
            pass
        assert bridge._suspect is True
        # A runner-side read (the regex grep) is what re-stages; the
        # content reads serve the controller's own copy and never touch
        # the runner. The count starts at the read, for the same
        # collection-probe reason the base's suspect tests name.
        before = len(uploads())
        results.append(bridge.call("grep", {"pattern": "total", "regex": True}))
        assert len(uploads()) - before == 2
        return "done"

    report = run_bridge(
        sprites,
        MemoryLedger(),
        trees(SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-bash-suspect",
        deadline_s=60,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert results[0].status is Status.OK


def test_every_guarded_script_declares_the_copy_a_safe_directory():
    """On a root runner the guarded execs run as the no-root guard's
    user, which is not the user that built the copy, its `.git` file or
    the staged repository -- and git (>= 2.35.2) refuses that ownership
    mismatch outright (`detected dubious ownership`), so every git call
    PR code makes in the copy would die. Each guarded script declares
    the copy a safe directory via the environment (protected config,
    honored in the subshell, unreachable from repo-local config),
    scoped to the copy's own path -- never `*` (the round-5 review's
    Major on #851; local tests run without the drop and cannot see
    this, so the pin is structural)."""
    staged = Staged(
        "/tmp/bridge",
        "/usr/bin/git",
        MappingProxyType({Rev.HEAD: "h" * 40}),
        pytest=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
        shim_python=TrustedPython(SYSTEM_PYTHON, "3.12.3"),
    )
    expected = (
        "GIT_CONFIG_COUNT=1 "
        "GIT_CONFIG_KEY_0=safe.directory "
        "GIT_CONFIG_VALUE_0=/tmp/bridge/scratch/work"
    )
    scripts = {
        "bash": bash_script(
            staged,
            validate("bash", {"command": "echo hi"}, frozenset(Rev)),
            ToolLimits(16 * 1024, 60),
        ),
        "run_tests": run_test_script(
            staged,
            validate("run_tests", {}, frozenset(Rev)),
            ToolLimits(16 * 1024, 180),
        ),
        "run_probe": run_probe_script(
            staged,
            validate(
                "run_probe",
                {"content": "def test_x():\n    assert True\n"},
                frozenset(Rev),
            ),
            ToolLimits(16 * 1024, 180),
        ),
        "mutate": mutate_script(
            staged,
            validate(
                "mutate",
                {"path": "calc.py", "line": 2, "operator": "negate-condition"},
                frozenset(Rev),
            ),
            ToolLimits(16 * 1024, 180),
        ),
        "collection": collection_script(
            "/tmp/bridge",
            "/usr/bin/git",
            "/tmp/bridge/scratch/work",
            "h" * 40,
            TrustedPython(SYSTEM_PYTHON, "3.12.3"),
        ),
        "sweep": sweep_script(
            staged,
            SweepGroup(
                "calc.py",
                ("test_calc.py",),
                (SweepSpec("calc.py", 2, "negate-condition"),),
            ),
            ToolLimits(16 * 1024, 60),
        ),
    }
    for name, script in scripts.items():
        assert "GIT_CONFIG_VALUE_0=" in script, name
        assert expected in script, name
    # Scoped to the copy's own path: never the wildcard.
    for name, script in scripts.items():
        assert 'GIT_CONFIG_VALUE_0="*"' not in script, name
        assert "GIT_CONFIG_VALUE_0=*" not in script, name


def test_guarded_env_exports_quotes_its_own_path():
    """The helper takes the raw scratch path and quotes it itself: a
    caller cannot hand it a pre-quoted word and double-quote the value
    into the environment (the contract the callers were silently
    depending on when they passed `shlex.quote`d strings)."""
    assert guarded_env_exports("/tmp/bridge/scratch/work") == (
        "export GIT_CONFIG_COUNT=1 "
        "GIT_CONFIG_KEY_0=safe.directory "
        "GIT_CONFIG_VALUE_0=/tmp/bridge/scratch/work; "
    )
    assert guarded_env_exports("/tmp/a b/work") == (
        "export GIT_CONFIG_COUNT=1 "
        "GIT_CONFIG_KEY_0=safe.directory "
        "GIT_CONFIG_VALUE_0='/tmp/a b/work'; "
    )


RANK_ORDER_SUITE = {
    "aa_slow.py": b"def slow(n):\n    if n > 9:\n        return 0\n    return n\n",
    "test_aa_slow.py": (
        b"from aa_slow import slow\n\ndef test_slow():\n    assert slow(5) == 5\n"
    ),
    "zz_auth.py": (
        b"def top(n):\n    if n < 0 or n > 9:\n        return 0\n    return n\n"
    ),
    "test_zz_auth.py": (
        b"from zz_auth import top\n\ndef test_top():\n    assert top(5) == 5\n"
    ),
}
RANK_ORDER_DIFF = (
    "diff --git a/aa_slow.py b/aa_slow.py\n"
    "--- a/aa_slow.py\n"
    "+++ b/aa_slow.py\n"
    "@@ -1,3 +1,4 @@\n"
    " def slow(n):\n"
    "+    if n > 9:\n"
    "+        return 0\n"
    "     return n\n"
    "diff --git a/zz_auth.py b/zz_auth.py\n"
    "--- a/zz_auth.py\n"
    "+++ b/zz_auth.py\n"
    "@@ -1,3 +1,4 @@\n"
    " def top(n):\n"
    "+    if n < 0 or n > 9:\n"
    "+        return 0\n"
    "     return n\n"
)


def test_the_sweep_spends_its_wall_on_the_best_ranked_groups_first(tmp_path):
    """The plan is ranked by relevance, but the groups ran alphabetically
    by module against the one shared wall budget -- the #846 defect moved
    from plan time back to run time: the alphabetically first module's
    slow scoped runs spent the wall, and the top-ranked spec's group, in
    a later module, came back inconclusive named. The groups now run in
    the plan's own rank order -- a group's place is its best spec's
    place -- so a slow low-ranked module cannot starve the spec the plan
    put first. The clock the first group's exec advances is the fake
    clock the loop reads between groups."""
    clock = FakeClock()
    budget = SWEEP_BUDGET_S

    def answer(script):
        module = "aa_slow" if "aa_slow.py" in script else "zz_auth"
        if "aa_slow" in module:
            # The low-ranked module's scoped runs are slow: its group's
            # exec consumes more than the pass's whole wall.
            clock.advance(budget + 1.0)
        return f"atlas-baseline:{module}.py:0:\natlas-sweep:0:0:\n"

    sprites = FakeSprites(
        rules=(
            ReplyRule(
                "atlas-git",
                lambda _script: (
                    "atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    f"atlas-pytest:{PYENV_PYTHON}:3.13.7\n"
                    f"atlas-shim:{PYENV_PYTHON}:3.13.7\n"
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
            ReplyRule("atlas-collect", lambda _script: "atlas-collect:0:\n"),
            ReplyRule("atlas-baseline", answer),
            ReplyRule(
                "__ATLAS_RUN__",
                lambda _script: staged() + framed(0, b"1 passed in 0.01s\n"),
            ),
        )
    )
    results = []

    def body(bridge):
        results.append(bridge.sweep(bridge.sweep_plan(RANK_ORDER_DIFF), clock=clock))
        return "done"

    run_bridge(
        sprites,
        MemoryLedger(),
        trees(RANK_ORDER_SUITE),
        body,
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-sweep-rank-order",
        deadline_s=60,
        clock=clock,
        root=str(tmp_path / "bridge"),
        pytest_candidates=(PYENV_PYTHON,),
    )
    (verdicts,) = results
    by_spec = {(v.spec.path, v.spec.operator, v.spec.operand): v for v in verdicts}
    top = by_spec[("zz_auth.py", "drop-operand", 1)]
    assert top.outcome == "survived", (
        f"the top-ranked spec's group was starved: {top.note}"
    )


def test_the_changed_spans_rank_only_the_innermost_changed_def():
    """A line added inside a nested def changes the nested def, not
    every function that encloses it: the outer function's own
    pre-existing guards do not rank as changed-function guards because
    an inner def they contain was edited."""
    module = (
        b"def outer(n):\n"
        b"    if n < 0 or n > 9:\n"  # the outer's own guard, pre-existing
        b"        return 0\n"
        b"    def inner(v):\n"
        b"        probe(v)\n"  # the added line lives here
        b"        return v\n"
        b"    return inner(n)\n"
    )
    diff = (
        "diff --git a/widen.py b/widen.py\n"
        "--- a/widen.py\n"
        "+++ b/widen.py\n"
        "@@ -1,6 +1,7 @@\n"
        " def outer(n):\n"
        "     if n < 0 or n > 9:\n"
        "         return 0\n"
        "     def inner(v):\n"
        "+        probe(v)\n"
        "         return v\n"
        "     return inner(n)\n"
    )
    specs = sweep_specs(diff, {"widen.py": module})
    # The nested def carries no guard, so nothing ranks tier 1 here; the
    # outer's own BoolOp must not appear by virtue of enclosing the edit.
    assert SweepSpec("widen.py", 2, "drop-operand", 1) not in specs
    assert SweepSpec("widen.py", 2, "drop-operand", 2) not in specs
