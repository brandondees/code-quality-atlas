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


def test_the_plan_runs_at_most_its_command_cap_and_names_the_rest():
    """The cap bounds the pass's staging cost, not the record: every
    distinct command past it is carried in the plan's `dropped`, so the
    evidence block and the coverage lines can name what the cap never
    ran -- a family whose only commands fell past the cap must not read
    as one the repo never configured."""
    steps = "".join(f"      - run: ruff check f{i}.py\n" for i in range(20))
    contents = {
        ".github/workflows/many.yml": ("jobs:\n  gate:\n    steps:\n" + steps).encode()
    }
    plan = grounding_plan(contents)
    assert len(plan.commands) == GROUNDING_MAX_COMMANDS
    assert [c.command for c in plan.dropped] == [
        f"ruff check f{i}.py" for i in range(GROUNDING_MAX_COMMANDS, 20)
    ]
    outcome = GroundingOutcome(plan, tuple(GroundingResult(c) for c in plan.commands))
    text = grounding_evidence(outcome, nonce="f00dfeed")
    assert (
        f"Commands past the pass's {GROUNDING_MAX_COMMANDS}-command cap, not run: "
        "ruff check f12.py; ruff check f13.py" in text
    )
    lines = grounding_coverage_lines(outcome, set())
    assert any(
        "ruff check f19.py (past the pass's command cap)" in line for line in lines
    )
    # The lint family's commands were all dropped, not never configured.
    assert not any("lint (no configured command)" in line for line in lines)


def test_the_plan_joins_continuations_and_classifies_by_segment():
    """A run step is a shell script, not a list of lines: a backslash or
    operator continuation joins, and each `&&`/`||`/`;` segment of the
    joined line classifies on its own tool, so `cd package && pytest`
    classifies by the check it chains to -- and the command that runs is
    the whole chain, with the step's `working-directory` and `env`
    carried in front of it. A `cargo test`/`go test` subcommand is the
    check its workflow runs; the same tool's build verb is not."""
    contents = {
        ".github/workflows/shaped.yml": (
            b"jobs:\n"
            b"  gate:\n"
            b"    steps:\n"
            b"      - run: |\n"
            b"          ruff check \\\n"
            b"            --select E501 .\n"
            b"      - run: cd package && python3 -m pytest -q\n"
            b"      - working-directory: app\n"
            b"        env:\n"
            b"          PYTHONDONTWRITEBYTECODE: '1'\n"
            b"        run: mypy src\n"
            b"      - run: cargo test --release\n"
            b"      - run: cargo build --release\n"
        )
    }
    plan = grounding_plan(contents)
    assert [(c.family, c.command, c.tool) for c in plan.commands] == [
        ("lint", "ruff check --select E501 .", "ruff"),
        ("test", "cd package && python3 -m pytest -q", "pytest"),
        (
            "type",
            "cd app && export PYTHONDONTWRITEBYTECODE=1; mypy src",
            "mypy",
        ),
        ("test", "cargo test --release", "cargo"),
    ]


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
    assert _classify("cargo test --release") == ("test", "cargo")
    assert _classify("go test ./...") == ("test", "go")
    assert _classify("cargo build --release") is None
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
    assert "No deterministic coverage: type (configured, none ran)" in lines[2]
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


def test_an_over_cap_evidence_block_names_its_cut():
    """The block's cap cuts from the tail -- where the later families and
    the gap notes sit -- and the cut carries the repo's own truncation
    marker, so a reader can tell the block ended from the block said
    nothing (round-1 review of #871, the unmarked tail cut)."""
    plan = GroundingPlan(
        tuple(
            GroundingCommand("lint", f"ruff check f{i}.py", "ruff", "ci.yml")
            for i in range(12)
        )
    )
    tail = "E501 line too long " * 60
    outcome = GroundingOutcome(
        plan,
        tuple(GroundingResult(c, exit=1, tail=tail) for c in plan.commands),
    )
    text = grounding_evidence(outcome, nonce="f00dfeed")
    assert "[... truncated by atlas_reviewer ...]" in text


def test_the_script_and_target_names_match_as_delimited_stems():
    """A script or make target's name declares its family when a
    delimited part of the name starts with it -- `typecheck`, `tests`,
    `test_unit` and `test:unit` all classify, the stems the usual script
    names are built from -- while a family name buried inside another
    word (`attest`, `latest`) does not. The stem prefix is what round 2's
    word-boundary match got wrong: it dropped the most common check
    names, silently, and the coverage section then reported the family
    as unconfigured."""
    from atlas_reviewer.grounding import _classify

    assert _classify("npm run typecheck") == ("type", "npm")
    assert _classify("pnpm typecheck") == ("type", "pnpm")
    assert _classify("make typecheck") == ("type", "make")
    assert _classify("make tests") == ("test", "make")
    assert _classify("npm run tests") == ("test", "npm")
    assert _classify("make test_unit") == ("test", "make")
    assert _classify("npm run test:unit") == ("test", "npm")
    assert _classify("npm run attest") is None
    assert _classify("make latest") is None
    assert _classify("make lint") == ("lint", "make")


def test_a_chain_that_provisions_before_its_check_is_named_not_run():
    """`pip install x && pytest` is what CI runs, but the sandbox's
    deny-all egress fails the install the chain runs first -- and that
    failure must not reach a lens as the test run's own. The check is
    carried as `unreproducible`, named in the evidence block and the
    coverage lines, and counted as the configured tool it is; a chain of
    harmless context (`cd`, `export`) and its check still runs whole."""
    contents = {
        ".github/workflows/mixed.yml": (
            b"jobs:\n"
            b"  gate:\n"
            b"    steps:\n"
            b"      - run: pip install -r requirements.txt && python3 -m pytest -q\n"
            b"      - run: cd package && python3 -m pytest -q\n"
        )
    }
    plan = grounding_plan(contents)
    assert [c.command for c in plan.commands] == ["cd package && python3 -m pytest -q"]
    assert [(c.family, c.command) for c in plan.unreproducible] == [
        (
            "test",
            "pip install -r requirements.txt && python3 -m pytest -q",
        )
    ]
    text = grounding_evidence(
        GroundingOutcome(plan, (GroundingResult(plan.commands[0], exit=0),)),
        nonce="f00dfeed",
    )
    assert (
        "Checks the sandbox cannot reproduce (their chain provisions or "
        "fetches first, under deny-all egress), not run: pip install -r "
        "requirements.txt && python3 -m pytest -q" in text
    )
    lines = grounding_coverage_lines(
        GroundingOutcome(plan, (GroundingResult(plan.commands[0], exit=0),)),
        set(),
    )
    assert any(
        "pip install -r requirements.txt && python3 -m pytest -q (the chain "
        "provisions or fetches first, not reproducible here)" in line
        for line in lines
    )
    # The unreproducible check's tool still covers its file types, and
    # its family is configured: the Not run line carries the why.
    assert not any(".py" in line for line in lines if "no configured tool" in line)


def test_offline_chain_segments_do_not_make_a_check_unreproducible():
    """A chain's segment makes its check unreproducible only when the
    segment installs or fetches -- what deny-all egress actually fails.
    Offline segments (`git diff`, a plain `python3 script.py`, a package
    manager's check verbs) ride along, and the check runs whole:
    `npm run typecheck && npm test` must not lose its test to the
    round-3 provisioning set, and `pip install x && pytest` still does."""
    contents = {
        ".github/workflows/chains.yml": (
            b"jobs:\n"
            b"  gate:\n"
            b"    steps:\n"
            b"      - run: ruff format --check . && git diff --exit-code\n"
            b"      - run: npm run typecheck && npm test\n"
            b"      - run: python3 scripts/gen.py && python3 -m pytest -q\n"
            b"      - run: pip install -r requirements.txt && python3 -m pytest -q\n"
        )
    }
    plan = grounding_plan(contents)
    assert [c.command for c in plan.commands] == [
        "ruff format --check . && git diff --exit-code",
        "npm run typecheck && npm test",
        "python3 scripts/gen.py && python3 -m pytest -q",
    ]
    assert [(c.family, c.command) for c in plan.unreproducible] == [
        (
            "test",
            "pip install -r requirements.txt && python3 -m pytest -q",
        )
    ]


def test_an_all_unreproducible_block_does_not_contradict_itself():
    """A repo whose every declared check sits in a provisioning chain
    still declared them: the block must not open with 'the workflows
    declare no lint, type or test command' and then list the checks it
    just named (round-3 review of #871)."""
    contents = {
        ".github/workflows/provisioned.yml": (
            b"jobs:\n"
            b"  gate:\n"
            b"    steps:\n"
            b"      - run: pip install -r requirements.txt && python3 -m pytest -q\n"
        )
    }
    plan = grounding_plan(contents)
    assert not plan.configured and plan.unreproducible
    text = grounding_evidence(GroundingOutcome(plan, ()), nonce="f00dfeed")
    assert "declare no lint, type or test command" not in text
    assert (
        "Checks the sandbox cannot reproduce" in text and "python3 -m pytest -q" in text
    )
    lines = grounding_coverage_lines(GroundingOutcome(plan, ()), set())
    assert any("Not run:" in line and "not reproducible here" in line for line in lines)
    assert any("type (no configured command)" in line for line in lines)
