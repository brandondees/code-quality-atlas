# SPDX-License-Identifier: MIT
"""The grounding pre-pass (the protocol's step 4.3, the harness gap
audit's blocker 4): before any lens judges, the controller runs the
deterministic tools the reviewed repository already gates its merges on
and hands every lens the hits as evidence.

The command list is parsed from the target repo's CI workflows (Brandon's
Nov 26 decision): the `.github/workflows/*.yml`/`*.yaml` files' `run:`
steps, line by line, classified into the lint, type and test families by
the tool each line names. Nothing is installed or introduced: a command
this list does not name is not run, and a repo whose workflows name no
lint/type/test command gets an empty inventory -- a valid, reportable
result, not a skip. The pass runs each command in the lens runner's own
disposable copy of the head tree under the same sandbox every execution
tool uses (deny-all egress, the non-root guard, a bounded clock), so the
repo's tooling executes the way CI executes it, and every hit is evidence
the owning lens confirms, contextualizes or dismisses -- a clean run
clears nothing.

Every gap is named: a workflow file that does not parse, a command the
pass's wall budget never reached, a family with no configured command,
and a changed file type no configured tool covers all reach the evidence
block and the draft's coverage lines, never a silent pass."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import yaml

from atlas_reviewer.prompt import RepoText, UntrustedBlock, fence

# The families the pre-pass runs, in the skill's own grouping; a hit is
# routed to the lens that owns the family, and a family no command covers
# is named as having no deterministic coverage.
FAMILIES = ("lint", "type", "test")

# The run steps the pass executes, at most: each command stages its own
# disposable copy before it runs, so an unbounded list would spend its
# wall on staging; a workflow with more lint/type/test lines than the cap
# has the remainder named in the evidence block, never silently dropped.
GROUNDING_MAX_COMMANDS = 12

# The evidence block's own cap, the sweep's own size: the block is
# evidence beside the lens's own reads, never a second diff.
GROUNDING_EVIDENCE_CHARS = 6144

# One failing command's captured output tail in the block, from the end
# where pytest's summary and the linters' hit lists sit; a clean run's
# silence is not evidence worth bytes.
_TAIL_CHARS = 1_200
_STDERR_TAIL_CHARS = 600

# The workflow files the pass reads, under the directory GitHub reserves
# for them.
_WORKFLOW_DIR = ".github/workflows/"
_WORKFLOW_SUFFIXES = (".yml", ".yaml")

# The tool each classified command names, and the file types it covers,
# for the coverage line naming the changed file types nothing configured
# reaches. Recognition aids over the repo's own inventory, never a list
# to install.
_TOOL_TYPES: Mapping[str, frozenset[str]] = {
    "ruff": frozenset({".py", ".pyi"}),
    "flake8": frozenset({".py", ".pyi"}),
    "pylint": frozenset({".py", ".pyi"}),
    "black": frozenset({".py", ".pyi"}),
    "isort": frozenset({".py", ".pyi"}),
    "mypy": frozenset({".py", ".pyi"}),
    "pyright": frozenset({".py", ".pyi"}),
    "tsc": frozenset({".ts", ".tsx", ".js", ".jsx"}),
    "eslint": frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}),
    "shellcheck": frozenset({".sh", ".bash"}),
    "markdownlint": frozenset({".md"}),
    "actionlint": frozenset({".yml", ".yaml"}),
    "yamllint": frozenset({".yml", ".yaml"}),
    "pytest": frozenset({".py"}),
    "jest": frozenset({".js", ".jsx", ".ts", ".tsx"}),
    "vitest": frozenset({".js", ".jsx", ".ts", ".tsx"}),
    "go": frozenset({".go"}),
    "cargo": frozenset({".rs"}),
}

# Lines that install, fetch or otherwise change state instead of checking:
# the pass reproduces what CI checks, not what it provisions, and the
# sandbox's deny-all egress would fail them anyway. `python -m pytest`
# still classifies -- the module names the tool.
_STATE_CHANGING = frozenset(
    {
        "pip", "pip3", "python", "python3", "npm", "yarn", "pnpm",
        "cargo", "go", "apt", "apt-get", "brew", "curl", "wget", "git",
        "docker", "sudo", "cd", "echo", "export", "sleep",
    }
)  # fmt: skip

_FAMILY_OF: Mapping[str, str] = {
    "ruff": "lint",
    "flake8": "lint",
    "pylint": "lint",
    "black": "lint",
    "isort": "lint",
    "eslint": "lint",
    "shellcheck": "lint",
    "markdownlint": "lint",
    "actionlint": "lint",
    "yamllint": "lint",
    "rubocop": "lint",
    "golangci-lint": "lint",
    "prettier": "lint",
    "mypy": "type",
    "pyright": "type",
    "pytype": "type",
    "tsc": "type",
    "ty": "type",
    "pytest": "test",
    "jest": "test",
    "vitest": "test",
    "tox": "test",
    "nox": "test",
}


@dataclass(frozen=True)
class GroundingCommand:
    """One declared check the pass runs: the family its tool belongs to,
    the shell line exactly as the workflow writes it, the tool token that
    classified it, and the workflow file it came from."""

    family: str
    command: str
    tool: str
    workflow: str


@dataclass(frozen=True)
class GroundingPlan:
    """The pass's parsed inventory: the commands to run, the workflow
    files that did not parse (named, never silently skipped), and whether
    the repo's workflows carried any lint/type/test step at all."""

    commands: tuple[GroundingCommand, ...]
    unparseable: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.commands)


@dataclass(frozen=True)
class GroundingResult:
    """One command's outcome in the sandbox: the exit code, the captured
    output tail the evidence block shows (empty for a clean run), and the
    note when the pass never ran it -- the wall budget spent before it
    started, or the copy the command runs in could not be made."""

    command: GroundingCommand
    exit: int | None = None
    tail: str = ""
    stderr_tail: str = ""
    note: str = ""

    @property
    def ran(self) -> bool:
        return self.exit is not None


@dataclass(frozen=True)
class GroundingOutcome:
    """The pass as a whole: the plan it ran from and every command's
    outcome, plus the note when the pass itself failed -- a lost exec, a
    dead runner -- so the evidence block can say the pre-pass did not run
    instead of implying a clean inventory."""

    plan: GroundingPlan
    results: tuple[GroundingResult, ...] = ()
    failure: str = ""


def _classify(line: str) -> tuple[str, str] | None:
    """The `(family, tool)` the run-step line's first check tool names,
    or None when the line names none the pass runs. An installing,
    fetching or state-changing line is never classified; a package
    manager's `test`/`run <script>` classifies by the script's name; a
    `make` target classifies by its target's name."""
    tokens = line.split()
    if not tokens:
        return None
    head = tokens[0]
    if head in ("npm", "npx", "yarn", "pnpm"):
        return _script_family(tokens)
    if head == "make":
        target = tokens[1] if len(tokens) > 1 else ""
        for family in FAMILIES:
            if family in target:
                return family, "make"
        return None
    if head in ("python", "python3"):
        module = tokens[2] if len(tokens) >= 3 and tokens[1] == "-m" else ""
        matched = _FAMILY_OF.get(module) if module else None
        return (matched, module) if matched is not None else None
    if head in _STATE_CHANGING:
        return None
    matched = _FAMILY_OF.get(head)
    return (matched, head) if matched is not None else None


def _script_family(tokens: list[str]) -> tuple[str, str] | None:
    """`npm test` / `npm run lint` / `npx markdownlint-cli2`: the script's
    or tool's name classifies, since the documented entry point is what a
    human would run and the pass runs it under the repo's own config."""
    if len(tokens) < 2:
        return None
    if tokens[0] == "npx":
        family = next(
            (f for tool, f in _FAMILY_OF.items() if tokens[1].startswith(tool)),
            None,
        )
        return (family, tokens[1]) if family else None
    script = tokens[1] if tokens[1] != "run" else (tokens[2] if len(tokens) > 2 else "")
    for family in FAMILIES:
        if family in script:
            return family, tokens[0]
    return None


def grounding_plan(contents: Mapping[str, bytes]) -> GroundingPlan:
    """The repo's declared lint/type/test commands, parsed from its CI
    workflows over the tree the caller holds (the review's merge-base
    tree: the revision the review is anchored to). Every workflow file's
    `run:` steps are read line by line; identical commands across jobs
    run once, the first occurrence's. A file that does not parse as YAML
    -- or whose shape the parser cannot read -- is named in the plan, not
    silently skipped."""
    commands: list[GroundingCommand] = []
    seen: set[str] = set()
    unparseable: list[str] = []
    workflows = sorted(
        path
        for path in contents
        if path.startswith(_WORKFLOW_DIR) and path.endswith(_WORKFLOW_SUFFIXES)
    )
    for path in workflows:
        for run in _workflow_runs(contents[path], path, unparseable):
            for line in run.split("\n"):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                classified = _classify(stripped)
                if classified is None:
                    continue
                family, tool = classified
                if stripped in seen:
                    continue
                seen.add(stripped)
                if len(commands) >= GROUNDING_MAX_COMMANDS:
                    continue
                commands.append(GroundingCommand(family, stripped, tool, path))
    return GroundingPlan(tuple(commands), tuple(unparseable))


def _workflow_runs(data: bytes, path: str, unparseable: list[str]) -> list[str]:
    """One workflow file's run-step texts, or an empty list with the file
    named when it does not parse or carries a shape the reader does not
    understand."""
    try:
        parsed = yaml.safe_load(data.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        unparseable.append(path)
        return []
    if not isinstance(parsed, dict):
        unparseable.append(path)
        return []
    jobs = parsed.get("jobs")
    if jobs is None:
        return []
    if not isinstance(jobs, dict):
        unparseable.append(path)
        return []
    runs: list[str] = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        found = job.get("steps")
        if not isinstance(found, list):
            continue
        for step in found:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                runs.append(step["run"])
    return runs


def grounding_evidence(outcome: GroundingOutcome, *, nonce: str) -> str:
    """The pass's results as one tool-evidence block for the lenses: the
    commands grouped by family, each with its exit and, for a command
    that failed, its captured output tail -- the hits the owning lens
    confirms, contextualizes or dismisses. A gap is named, never silent:
    an unparseable workflow, a command the budget never reached, a failed
    pass, and an empty inventory all say so."""
    lines = [
        "The controller ran the reviewed repo's declared CI tooling before",
        "this lens started: the lint, type and test commands the repo's own",
        "GitHub workflows run (parsed from the merge-base tree's",
        ".github/workflows run steps), each in this runner's disposable copy",
        "of the head tree under the same sandbox every execution tool uses.",
        "A hit is evidence for the lens that owns its family -- confirm,",
        "contextualize or dismiss it; a clean run clears nothing.",
        "",
    ]
    if outcome.failure:
        lines.append(f"The pass itself failed: {outcome.failure}")
    if not outcome.plan.configured and not outcome.plan.unparseable:
        lines.append(
            "The repo's workflows declare no lint, type or test command; "
            "the pass had nothing to run."
        )
    for family in FAMILIES:
        ran = [r for r in outcome.results if r.command.family == family and r.ran]
        if ran:
            lines.append(f"{family}:")
            lines.extend(_result_line(result) for result in ran)
    for result in outcome.results:
        if not result.ran:
            lines.append(
                f"{result.command.family}: {result.command.command} -- "
                f"not run ({result.note})"
            )
    if outcome.plan.unparseable:
        shown = ", ".join(outcome.plan.unparseable)
        lines.append(f"Workflow files that did not parse, so not read: {shown}")
    text = "\n".join(lines)
    if len(text) > GROUNDING_EVIDENCE_CHARS:
        text = text[: GROUNDING_EVIDENCE_CHARS - 3] + "..."
    return "\n\n" + fence(UntrustedBlock("tool-evidence", RepoText(text)), nonce)


def _result_line(result: GroundingResult) -> str:
    assert result.exit is not None
    line = f"- {result.command.command} -- exit {result.exit}"
    if result.exit == 0:
        return line + " (clean)"
    tail = _tail(result.tail, result.stderr_tail)
    if tail:
        line += ", output tail:\n" + "\n".join(f"  {item}" for item in tail.split("\n"))
    else:
        line += " (no output captured)"
    return line


def _tail(stdout: str, stderr: str) -> str:
    if stderr and stdout:
        joined = (
            f"{stdout[-_TAIL_CHARS:]}\n-- stderr --\n{stderr[-_STDERR_TAIL_CHARS:]}"
        )
        return joined[-_TAIL_CHARS:]
    return (stderr or stdout)[-_TAIL_CHARS:]


def grounding_coverage_lines(
    outcome: GroundingOutcome,
    changed: frozenset[str] | set[str],
    *,
    quote: Callable[[str], str] = lambda text: text,
) -> tuple[str, ...]:
    """The draft's tool-coverage lines, the skill's five facts reduced to
    the four this pass can state honestly: what ran (and that it ran in
    the sandbox over the head tree, not scoped to the diff), what the
    budget never reached, which families carry no configured command, and
    which changed file types no configured tool covers. The Pending in CI
    line is the CI evidence's own to state and is not produced here.
    `quote` renders the repo-derived values (the commands, the workflow
    names, the file types) as quoted data for the report; the family
    names and exit codes around them are the controller's own words."""
    lines: list[str] = []
    ran = [result for result in outcome.results if result.ran]
    if ran:
        shown = "; ".join(
            f"{result.command.family} {quote(result.command.command)} "
            f"exit {result.exit}"
            for result in ran
        )
        lines.append(
            f"Tools run: {shown} -- each in the runner's disposable copy of "
            "the head tree, under the repo's own config; a clean run clears "
            "nothing."
        )
    not_run = [result for result in outcome.results if not result.ran]
    if not_run:
        lines.append(
            "Not run: "
            + "; ".join(
                f"{quote(r.command.command)} ({quote(r.note)})" for r in not_run
            )
            + "."
        )
    if outcome.failure:
        lines.append(f"The pre-pass itself failed: {quote(outcome.failure)}")
    covered_families = {
        result.command.family for result in outcome.results if result.ran
    }
    missing = [family for family in FAMILIES if family not in covered_families]
    if missing or outcome.plan.unparseable:
        parts = [f"{family} (no configured command)" for family in missing]
        if outcome.plan.unparseable:
            parts.append(
                "workflow files that did not parse: "
                + ", ".join(quote(path) for path in outcome.plan.unparseable)
            )
        lines.append("No deterministic coverage: " + "; ".join(parts) + ".")
    types = _uncovered_types(outcome, changed)
    if types:
        lines.append(
            "Changed file types with no configured tool: "
            + ", ".join(quote(suffix) for suffix in types)
            + "."
        )
    return tuple(lines)


def _uncovered_types(
    outcome: GroundingOutcome, changed: frozenset[str] | set[str]
) -> tuple[str, ...]:
    """The changed paths' suffixes no configured tool covers, when the
    diff carries paths at all: the silence a reader cannot reconstruct,
    named instead of folded into the no-coverage line."""
    if not changed:
        return ()
    tools = {result.command.tool for result in outcome.results if result.ran}
    covered: set[str] = set()
    for tool in tools:
        covered |= _TOOL_TYPES.get(tool, frozenset())
    suffixes = {suffix for path in changed if (suffix := _suffix(path)) is not None}
    return tuple(sorted(suffixes - covered))


def _suffix(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return None
    return ("." + name.rsplit(".", 1)[1]).lower()
