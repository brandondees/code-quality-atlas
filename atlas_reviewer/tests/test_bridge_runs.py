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
import subprocess
import sys
from dataclasses import dataclass
from types import MappingProxyType

import pytest

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
from atlas_reviewer.local_runner import LocalSprites
from atlas_reviewer.ports import StreamTimeoutError
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
    whole = base64.b64decode(before).decode()
    assert whole == "if not xs:\n        return 0"
    assert base64.b64decode(after).decode() == "if not not xs:\n    return 0"
    assert "if not not xs:" in path.read_text()


def test_remove_guard_replaces_the_body_with_pass(tmp_path):
    result, path = edit(tmp_path, REQUIRE, 2, "remove-guard")
    assert result.returncode == 0
    status, rest = payload_of(result)
    assert status == "ok"
    before, _ = rest.split(" ")
    assert base64.b64decode(before).decode() == (
        'if xs is None:\n        raise ValueError("xs is required")'
    )
    assert "if xs is None:\n        pass" in path.read_text()


def test_negate_condition_applies_to_while_and_the_conditional_expression(tmp_path):
    result, path = edit(
        tmp_path, "def spin(n):\n    while n > 0:\n        n -= 1\n    return n\n",
        2, "negate-condition",
    )  # fmt: skip
    assert result.returncode == 0
    assert "while not n > 0:" in path.read_text()
    result, path = edit(
        tmp_path, "def pick(n):\n    return 1 if n else 2\n", 2, "negate-condition"
    )
    assert result.returncode == 0
    assert "1 if not n else 2" in path.read_text()


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
    assert base64.b64decode(before).decode() == (
        "if (\n        n\n    ):\n        return 1"
    )


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
    assert result.mutation.before.startswith("if xs is None:")
    assert "raise ValueError" in result.mutation.before
    assert result.mutation.after.startswith("if not xs is None:")
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
    assert "if not xs is None:" in read.content.text
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
    assert result.outcome_reason == (
        "no test was collected for the baseline run (exit 4)"
    )


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
    assert "if not xs is None:" in read.content.text


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


def framed(code, out, shown=None):
    shown = out if shown is None else shown
    return (
        f"__ATLAS_RUN__ {code} {len(out)} {len(out.splitlines())} {len(shown)}\n"
        f"{base64.b64encode(shown).decode()}\n"
        f"{base64.b64encode(b'').decode()}\n"
    )


def mutation_block(apply_exit, commit, payload=b""):
    return (
        f"__ATLAS_MUT__ {apply_exit} {commit}\n{base64.b64encode(payload).decode()}\n"
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
                framed(0, out)
                + mutation_block(
                    0, commit, ok_payload(b"if not xs:", b"if not (not xs):")
                )
                + framed(0, out)
            )
        return framed(0, out)

    (result,), _ = fake_bridge(tmp_path, answer, (MUTATE_REQUEST,), source=trees(SUITE))
    assert result.status is Status.OK
    assert result.outcome is MutantOutcome.SURVIVED
    assert result.mutation.commit == commit
    assert result.mutation.before == "if not xs:"
    rendered = render(result)
    assert "baseline run: exit 0, 1 passed" in rendered
    assert "mutated run: exit 0, 1 passed" in rendered
    assert f"head {HEAD}" in rendered
    assert "mutation at calc.py:2 (negate-condition)" in rendered
    assert 'if not xs:"` -> `"if not (not xs):"' in rendered


def test_a_mutation_step_that_failed_is_inconclusive(tmp_path):
    out = b"1 passed in 0.01s\n"

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return framed(0, out) + mutation_block(1, "-")
        return framed(0, out)

    (result,), _ = fake_bridge(
        tmp_path, answer,
        (("mutate", {"path": "calc.py", "line": 2, "operator": "remove-guard"}),),
    )  # fmt: skip
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == (
        "the mutation did not apply: the mutation step failed (exit 1)"
    )
    assert "mutated run: not run" in render(result)


def test_a_refusal_reason_from_the_mutation_script_is_carried(tmp_path):
    out = b"1 passed in 0.01s\n"
    payload = b"no " + base64.b64encode(b"the file does not parse")

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return framed(0, out) + mutation_block(0, "-", payload)
        return framed(0, out)

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
            return framed(0, out) + mutation_block(0, "-", ok_payload(b"a", b"b"))
        return framed(0, out)

    (result,), _ = fake_bridge(tmp_path, answer, (MUTATE_REQUEST,))
    assert result.outcome is MutantOutcome.INCONCLUSIVE
    assert result.outcome_reason == "the mutated run did not run"


def test_a_killed_verdict_from_a_scripted_pair_of_runs(tmp_path):
    out = b"1 failed in 0.01s\n"

    def answer(script):
        if "__ATLAS_MUT__" in script:
            return (
                framed(0, b"1 passed\n")
                + mutation_block(0, "a" * 40, ok_payload(b"a", b"b"))
                + framed(1, out)
            )
        return framed(0, b"1 passed\n")

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
        lambda _script: mutation_block(0, "-", b"no x"),
        (("run_tests", {}),),
    )
    assert result.status is Status.UNAVAILABLE
    assert "not one test run" in result.error.text


def test_a_mutate_reply_without_a_mutation_block_is_unavailable(tmp_path):
    (result,), _ = fake_bridge(
        tmp_path,
        lambda _script: framed(0, b"1 passed in 0.01s\n") + framed(0, b"1 passed\n"),
        (MUTATE_REQUEST,),
    )
    assert result.status is Status.UNAVAILABLE
    assert "not a baseline run, a mutation and a mutated run" in result.error.text


def test_a_run_without_a_summary_line_renders_its_exit_alone(tmp_path):
    (result,), _ = fake_bridge(
        tmp_path, lambda _script: framed(0, b"no summary here\n"), (("run_tests", {}),)
    )
    (run,) = result.runs
    assert run.summary is None
    assert "test run: exit 0" in render(result)
    assert "test run: exit 0," not in render(result)


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
