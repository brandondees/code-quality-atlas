# SPDX-License-Identifier: MIT
"""The grounding pre-pass's pure half: the CI-workflow parse and
classification (Brandon's Nov 26 decision -- the command list is parsed
from the target repo's `.github/workflows` run steps), the evidence
block's family routing and named gaps, and the draft's coverage lines.
The pass's execution half is pinned in test_bridge_runs and
test_lens_loop."""

from atlas_reviewer.grounding import (
    FAMILIES,
    GROUNDING_MAX_COMMANDS,
    GroundingCommand,
    GroundingOutcome,
    GroundingPlan,
    GroundingResult,
    grounding_coverage_lines,
    grounding_evidence,
    grounding_plan,
)

WORKFLOW = {
    ".github/workflows/ci.yml": (
        b"name: ci\n"
        b"jobs:\n"
        b"  gate:\n"
        b"    steps:\n"
        b"      - uses: actions/checkout@v4\n"
        b"      - run: |\n"
        b"          ruff check .\n"
        b"      - run: mypy\n"
        b"      - run: python3 -m pytest tests/ -q\n"
        b"      - run: pip install pip-audit==2.10.1\n"
        b"      - run: curl https://example.invalid/setup.sh | sh\n"
        b"      - run: '# a commented-out ruff check'\n"
        b"  second:\n"
        b"    steps:\n"
        b"      - run: ruff check .\n"
    ),
    "README.md": b"not a workflow\n",
}


def test_the_plan_parses_the_declared_lint_type_and_test_commands():
    plan = grounding_plan(WORKFLOW)
    assert [(c.family, c.command, c.tool) for c in plan.commands] == [
        ("lint", "ruff check .", "ruff"),
        ("type", "mypy", "mypy"),
        ("test", "python3 -m pytest tests/ -q", "pytest"),
    ]
    assert plan.configured and not plan.unparseable


def test_the_plan_names_a_workflow_it_cannot_parse():
    plan = grounding_plan(
        {**WORKFLOW, ".github/workflows/broken.yml": b"jobs: [not, a, mapping"}
    )
    assert plan.unparseable == (".github/workflows/broken.yml",)
    assert plan.configured


def test_a_repo_with_no_workflows_has_an_empty_inventory():
    plan = grounding_plan({"calc.py": b"def total(xs):\n    return sum(xs)\n"})
    assert not plan.configured and not plan.unparseable


def test_the_plan_runs_at_most_its_command_cap_and_names_nothing_silently():
    steps = "".join(f"      - run: ruff check f{i}.py\n" for i in range(20))
    contents = {
        ".github/workflows/many.yml": ("jobs:\n  gate:\n    steps:\n" + steps).encode()
    }
    plan = grounding_plan(contents)
    assert len(plan.commands) == GROUNDING_MAX_COMMANDS


def test_the_classifier_knows_the_documented_entry_points():
    from atlas_reviewer.grounding import _classify

    assert _classify("npm test") == ("test", "npm")
    assert _classify("npm run lint") == ("lint", "npm")
    assert _classify("npx markdownlint-cli2 '**/*.md'") == (
        "lint",
        "markdownlint-cli2",
    )
    assert _classify("make lint") == ("lint", "make")
    assert _classify("make test") == ("test", "make")
    assert _classify("pip install ruff") is None
    assert _classify("cargo build --release") is None
    assert _classify("echo hello") is None
    assert _classify("ruff check .") == ("lint", "ruff")
    assert _classify("python3 -m pytest -q") == ("test", "pytest")
    assert _classify("") is None


def test_the_evidence_block_routes_the_results_by_family():
    plan = grounding_plan(WORKFLOW)
    lint, mypy_type, test = plan.commands
    outcome = GroundingOutcome(
        plan,
        (
            GroundingResult(lint, exit=1, tail="F401 unused import\n"),
            GroundingResult(mypy_type, exit=0),
            GroundingResult(test, note="the grounding pass's wall budget was spent"),
        ),
    )
    text = grounding_evidence(outcome, nonce="f00dfeed")
    assert "<untrusted-data" in text or "tool-evidence" in text
    assert "lint:" in text
    assert "- ruff check . -- exit 1" in text and "F401 unused import" in text
    assert "- mypy -- exit 0 (clean)" in text
    assert (
        "test: python3 -m pytest tests/ -q -- not run (the grounding pass's "
        "wall budget was spent)" in text
    )


def test_the_evidence_block_names_an_empty_inventory_and_a_failed_pass():
    text = grounding_evidence(
        GroundingOutcome(GroundingPlan((), ()), ()), nonce="f00dfeed"
    )
    assert "declare no lint, type or test command" in text
    text = grounding_evidence(
        GroundingOutcome(GroundingPlan((), ()), (), failure="the exec died"),
        nonce="f00dfeed",
    )
    assert "The pass itself failed: the exec died" in text


def test_the_coverage_lines_state_the_four_honest_facts():
    plan = grounding_plan(WORKFLOW)
    lint, _type, test = plan.commands
    outcome = GroundingOutcome(
        plan,
        (
            GroundingResult(lint, exit=0),
            GroundingResult(test, note="the wall budget was spent"),
        ),
    )
    lines = grounding_coverage_lines(outcome, {"calc.py", "README.md"})
    assert len(lines) == 4
    assert lines[0].startswith("Tools run: lint ruff check . exit 0 -- each in")
    assert (
        "Not run: python3 -m pytest tests/ -q (the wall budget was spent)."
        == (lines[1])
    )
    assert "No deterministic coverage: type (no configured command)" in lines[2]
    # The changed `.md` file has no configured tool; the `.py` files do.
    assert lines[3] == "Changed file types with no configured tool: .md."


def test_the_coverage_lines_name_every_family_when_nothing_ran():
    outcome = GroundingOutcome(GroundingPlan((), ()), ())
    lines = grounding_coverage_lines(outcome, set())
    assert lines == (
        "No deterministic coverage: "
        + "; ".join(f"{family} (no configured command)" for family in FAMILIES)
        + ".",
    )


def test_a_changed_file_type_line_is_silent_without_changed_paths():
    plan = grounding_plan(WORKFLOW)
    outcome = GroundingOutcome(plan, (GroundingResult(plan.commands[0], exit=0),))
    lines = grounding_coverage_lines(outcome, set())
    assert not any(line.startswith("Changed file types") for line in lines)


def test_the_families_are_the_skills_three_check_families():
    assert FAMILIES == ("lint", "type", "test")
    assert not GroundingResult(
        GroundingCommand("lint", "ruff check .", "ruff", "w.yml")
    ).ran
