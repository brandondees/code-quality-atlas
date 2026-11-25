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
import subprocess
import sys
from dataclasses import dataclass
from types import MappingProxyType

import pytest

from atlas_reviewer import local_runner
from atlas_reviewer.bridge import (
    DEFAULT_LIMITS,
    MUTATION_SCRIPT,
    MutantOutcome,
    SessionLimits,
    Status,
    ToolLimits,
    _MutBlock,
    _pytest_argv,
    _run_status,
    _RunBlock,
    _splice,
    mutant_outcome,
    parse_mutation,
    parse_run_blocks,
    parse_summary,
    render,
    run_bridge,
)
from atlas_reviewer.bridge_args import Rev, validate
from atlas_reviewer.bridge_staging import (
    SYSTEM_PYTHON,
    SourceTrees,
    Staged,
    choose_pytest,
)
from atlas_reviewer.domain import CleanupStatus, RunnerStatus
from atlas_reviewer.fakes import PYENV_PYTHON, FakeSprites, MemoryLedger
from atlas_reviewer.local_runner import _SWEEP_REAP_S, LocalSprites
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


def edit(tmp_path, text, line, operator):
    path = tmp_path / "m.py"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", "-c", MUTATION_SCRIPT, str(path), str(line), operator],
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


def test_a_mutation_that_does_not_apply_is_inconclusive_and_commits_nothing(tmp_path):
    (result,), bridge = calls(
        tmp_path,
        ("mutate", {"path": "calc.py", "line": 1, "operator": "negate-condition"}),
    )
    assert result.status is Status.OK
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert "the operator does not apply" in result.outcome_reason
    (baseline,) = result.runs
    assert baseline.exit == 0
    assert "mutated run: not run" in render(result)
    assert result.mutation.commit == ""
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
                ),
            ),
            ReplyRule(
                "atlas-staged",
                lambda _script: (
                    f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n"
                ),
            ),
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
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == (
        "the mutation did not apply: the file does not parse"
    )


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
                ),
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


# --------------------------------------------- round 2: the between-call daemon


DAEMON_LOADER = (
    "import glob, os, time, zlib\n"
    "\n"
    "repo = os.path.join(os.environ['ATLAS_DAEMON_BRIDGE'], 'repo.git')\n"
    "deadline = time.time() + 30\n"
    "while time.time() < deadline:\n"
    "    for path in glob.glob(os.path.join(repo, 'objects', '[0-9a-f][0-9a-f]', '*')):\n"
    "        try:\n"
    "            raw = open(path, 'rb').read()\n"
    "            data = zlib.decompress(raw)\n"
    "        except (OSError, zlib.error):\n"
    "            continue\n"
    "        if b'sum(xs)' in data:\n"
    "            forged = data.replace(b'return sum(xs)', b'return 999  # DAEMON')\n"
    "            tmp = path + '.tmp'\n"
    "            open(tmp, 'wb').write(zlib.compress(forged))\n"
    "            os.replace(tmp, path)\n"
)

DAEMON_CONFTEST = (
    "import os, subprocess, sys\n"
    "from pathlib import Path\n"
    "\n"
    "BRIDGE = Path(__file__).resolve().parents[2]\n"
    "LOADER = " + repr(DAEMON_LOADER) + "\n"
    "\n"
    "def pytest_configure(config):\n"
    "    subprocess.Popen(\n"
    "        [sys.executable, '-c', LOADER],\n"
    "        start_new_session=True,\n"
    "        stdout=subprocess.DEVNULL,\n"
    "        stderr=subprocess.DEVNULL,\n"
    "        stdin=subprocess.DEVNULL,\n"
    "        env={**os.environ, 'ATLAS_DAEMON_BRIDGE': str(BRIDGE)},\n"
    "    )\n"
)

DAEMON_SUITE = {
    "calc.py": CALC.encode(),
    "test_calc.py": TEST_TOTAL.encode(),
    "conftest.py": DAEMON_CONFTEST.encode(),
}


def test_a_detached_daemon_cannot_reach_a_later_read_or_run(tmp_path):
    """Round 2's B1 (the review's probe, as a fixture): a PR test spawns a
    daemon detached from its exec's process group (`start_new_session`),
    which keeps re-forging the `calc.py` loose blob in place for as long
    as it lives. The sweep that precedes every re-stage and every
    execution kills it and verifies none remain, the re-stage rebuilds
    from the controller-held tarballs, and the content reads are answered
    from the controller's own copy -- so the reads, the diff and the next
    run are all genuine. (At the pre-sweep head this test fails: the
    daemon outlives every exec and both post-re-stage reads serve its
    forgery.)"""
    collected = {}

    def body(bridge):
        out = {}
        out["before"] = bridge.call("read_file", {"rev": "HEAD", "path": "calc.py"})
        out["daemon_run"] = bridge.call("run_tests", {"path": "test_calc.py"})
        # Two reads, each preceded by a sweep and (an execution having
        # run) a re-stage: the daemon's window is what these close.
        out["read1"] = bridge.call("read_file", {"rev": "HEAD", "path": "calc.py"})
        out["read2"] = bridge.call("read_file", {"rev": "HEAD", "path": "calc.py"})
        out["diff"] = bridge.call("diff_stat", {})
        out["run2"] = bridge.call("run_tests", {})
        collected.update(out)
        return "done"

    report = bridge_run(
        tmp_path,
        body,
        source=trees(
            DAEMON_SUITE, base={"calc.py": b"def total(xs):\n    return sum(xs)\n"}
        ),
    )[0]
    assert report.status is RunnerStatus.COMPLETED, report.note
    for name in ("before", "read1", "read2"):
        result = collected[name]
        assert result.status is Status.OK
        assert result.content.text == CALC
    assert "DAEMON" not in collected["read2"].content.text
    # The diff still reads the real repository: the sweep and the
    # re-stage healed it before the read.
    assert collected["diff"].status is Status.OK
    assert "calc.py" in collected["diff"].content.text
    # And the next execution runs the real tree: the daemon's forgery
    # would fail the real test.
    (run2,) = collected["run2"].runs
    assert collected["run2"].status is Status.OK and run2.exit == 0
    assert run2.summary is not None and run2.summary.count("passed") == 1


def test_the_sweep_kills_a_runner_descendant(tmp_path):
    """The local sweep's contract, on a real process: a child the runner
    process spawned -- the daemon shape, detached into its own session --
    is killed and reaped by the sweep, and the sweep stays clean."""
    import time as time_module

    sprites = LocalSprites()
    daemon = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        assert daemon.poll() is None
        sprites.sweep("cqa-sweep-test")
        deadline = time_module.monotonic() + 5
        while daemon.poll() is None and time_module.monotonic() < deadline:
            time_module.sleep(0.05)
        assert daemon.poll() is not None  # killed and reaped
    finally:
        if daemon.poll() is None:  # pragma: no cover - only on a failed sweep
            daemon.kill()
            daemon.wait()


def test_the_sweep_waits_out_a_slow_sigkill(monkeypatch: pytest.MonkeyPatch):
    """Three scans, on a clock the test owns.

    The first two scans still list the process. The third finds it gone.
    The reap window is half a second of the clock passed in. A wall clock
    that jumps a second on each sleep used to fail the sweep while the
    process was still listed.
    """
    wall = {"t": 0.0}

    def wall_now() -> float:
        return wall["t"]

    def wall_sleep(_seconds: float) -> None:
        wall["t"] += 1.0

    monkeypatch.setattr(local_runner.time, "monotonic", wall_now)
    monkeypatch.setattr(local_runner.time, "sleep", wall_sleep)
    clock = FakeClock()

    class Slow(LocalSprites):
        def __init__(self) -> None:
            super().__init__()
            self.scans = 0

        def _stray_descendants(self) -> set[int]:
            self.scans += 1
            if self.scans < 3:
                return {os.getpid() + 4_194_304}
            return set()

    slow = Slow()
    slow.sweep("cqa-slow", monotonic=clock.monotonic, sleep=clock.advance)
    assert slow.scans == 3
    assert clock.t < _SWEEP_REAP_S
    assert wall["t"] == 0.0


def test_the_sweep_fails_closed_on_a_survivor():
    """A sweep that cannot clear the runner's strays is a fail-closed
    boundary error -- the `unavailable` gap -- never a silent pass."""
    import os as os_module

    class Haunted(LocalSprites):
        def _stray_descendants(self):
            return {os_module.getpid() + 4_194_304}

    with pytest.raises(BoundaryError, match="survivor"):
        Haunted().sweep("cqa-haunted")


def test_the_live_sweep_answer_is_parsed_fail_closed():
    """The live sweep script's answer is controller-parsed: clean passes,
    a survivor count or a failed or missing answer is a boundary error."""
    from atlas_reviewer.runner import parse_sweep

    parse_sweep(0, "atlas-sweep:clean\n")
    with pytest.raises(BoundaryError, match="survivor"):
        parse_sweep(1, "atlas-sweep:survivors:2\n")
    with pytest.raises(BoundaryError, match="failed"):
        parse_sweep(1, "sh: id: not found\n")
    with pytest.raises(BoundaryError, match="failed"):
        parse_sweep(0, "nothing the sweep would print\n")


def test_the_live_sweep_script_excludes_its_own_ancestry():
    """The uid scope the live sweep kills under excludes the exec chain
    the sweep itself runs in: the script walks `PPid` to init and skips
    every pid on it, skips zombies, and verifies with a second scan whose
    survivor count is the fail-closed marker."""
    from atlas_reviewer.runner import SWEEP_TAG, sweep_script

    script = sweep_script()
    assert 'ancestors="$ancestors $p"' in script
    assert "p=$(awk '/^PPid:/{print $2}' /proc/$p/status" in script
    assert '"$state" = Z' in script
    assert 'kill -9 "$pid"' in script
    assert f'echo "{SWEEP_TAG}:survivors:$survivors"' in script
    assert f'echo "{SWEEP_TAG}:clean"' in script


def test_the_live_sweep_script_never_signals_pid_1_or_a_session_root():
    """The live Sprite runs the whole container under the exec user, and
    its exec processes report `PPid 0`, so the ancestor walk cannot name
    the container's own processes: the unguarded sweep SIGKILLed pid 1
    (`tini`) and the session root and took the container down with every
    tool call (the live checks of Nov 25). The script skips pid 1 and
    every `PPid 0` process in both the kill scan and the verification,
    and kills only the pids it collected, so the guards cannot drift
    between the kill and the verification. A PR daemon reparented to pid
    1 is still a victim: pid 1's own `PPid` shields only itself."""
    from atlas_reviewer.runner import sweep_script

    script = sweep_script()
    kill_scan = script.split("victims=''")[1].split("for pid in $victims")[0]
    assert '[ "$pid" = 1 ] && continue' in kill_scan
    assert '[ "$ppid" = 0 ] && continue' in kill_scan
    assert '[ "$uid" = "$me" ] || continue' in kill_scan
    assert 'victims="$victims $pid"' in kill_scan
    kill = script.split("for pid in $victims; do")[1].split("done")[0]
    assert 'kill -9 "$pid"' in kill
    verify = script.split("survivors=0")[1].split("done")[0]
    assert "[ -d /proc/$pid ] || continue" in verify
    assert '"$state" = Z' in verify
    # The verification re-checks exactly the victim list, not a fresh
    # scan, so a protected process can never be counted a survivor.
    assert "/proc/[0-9]*" not in verify


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
    shapes = (
        (CALC, 2, "negate-condition"),
        (CALC, 2, "remove-guard"),
        (REQUIRE, 2, "negate-condition"),
        (REQUIRE, 2, "remove-guard"),
        (
            "def spin(n):\n    while n > 0:\n        n -= 1\n    return n\n",
            2,
            "negate-condition",
        ),
        ("def pick(n):\n    return 1 if n else 2\n", 2, "negate-condition"),
        (
            "def pick(n):\n    if (\n        n\n    ):\n        return 1\n    return 2\n",
            2,
            "negate-condition",
        ),
        ("x = 1\n", 1, "remove-guard"),  # not applicable: both refuse
    )
    for text, line, operator in shapes:
        result, path = edit(tmp_path, text, line, operator)
        status, rest = payload_of(result)
        spliced = _splice(text.encode(), line, operator)
        if status == "no":
            assert spliced is None, (text, line, operator)
            continue
        assert spliced is not None
        before_b64, after_b64 = rest.split(" ")
        mutated, before, after = spliced
        assert path.read_bytes() == mutated, (text, line, operator)
        assert base64.b64decode(before_b64).decode() == before
        assert base64.b64decode(after_b64).decode() == after
