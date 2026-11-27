---
name: grounding-review-in-tool-output
description: Runs the deterministic linters, type checkers, scanners, and test/coverage
  tools the reviewed repository has *already* configured, scoped to what is being
  reviewed, and turns their raw output into evidence the code-quality-atlas lenses
  confirm, contextualize, or dismiss. Use before the lenses run on any review where
  the repo carries its own tooling — a pull request, a local diff, or a whole-repo
  audit — so findings that a tool can prove are grounded in a rule id instead of re-derived
  by judgment, and so the review can state which categories had deterministic coverage
  and which did not. Never installs or introduces a tool the repo has not adopted,
  and never treats a clean tool run as clearing a lens.
provenance:
  taxonomy_version: v0.14
  built_from: []
---

# grounding-review-in-tool-output

## When to use

Gather deterministic evidence before the lenses judge. Discover which linters, type checkers, scanners, and data/infra tools this repository already runs, run those (and only those) over the scope under review, and hand each lens the hits that fall in its territory. Tool output is an input to the review, never a substitute for it: every hit is confirmed, contextualized, or dismissed by the owning lens, and every tool that could not run becomes a stated coverage limitation rather than a silent pass.

**Shape: composition.** Runs after `choosing-review-lenses` has picked the lenses and before those lenses judge the change. It adds no checks of its own — it gathers evidence, and every finding it contributes is owned and stated by a lens.

## Why this runs first

Where a mature linter or scanner already covers a category, the lens's job is to **triage its output, not to re-derive the finding by judgment alone**. A rule id is reproducible, cheap, and checkable by the author; a judgment call is none of those. Running the repo's own tools first means the review spends its judgment where judgment is the only thing that works — whether the invariant is right, whether the boundary belongs, whether the change should exist at all — instead of re-deriving by inference what the repo's own linter already prints.

The inverse matters just as much: **tool output is an input, never a verdict.** A hit that no lens confirms is not a finding, and a clean run is not an approval.

## 1. Discover what the repo already runs

Read, in this order — the earlier sources say what is **enforced**, the later ones what is merely installed or documented:

| Look at | What it tells you |
|---|---|
| The pre-commit config — `.pre-commit-config.yaml` | the richest single signal — each hook names its tool, its arguments, and the file filter it runs under, so it gives scope as well as inventory |
| CI workflow definitions — `.github/workflows/*.yml` and `*.yaml`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/config.yml` | what the repo actually gates merges on, which is the set worth reproducing — a tool configured but not wired into CI is weaker evidence that the team stands behind its rules |
| Package manifests — `package.json` (scripts, devDependencies), `pyproject.toml`, `Gemfile`, `Cargo.toml`, `go.mod` | which tools are installed and which command name invokes them |
| Per-tool config files — `eslint.config.js`, `.eslintrc*`, `ruff.toml`, `.rubocop.yml`, `.golangci.yml`, `.semgrep.yml`, `.sqlfluff`, `.tflint.hcl`, `sgconfig.yml` | the repo's own rule selection — always run the tool under its config, never under your own defaults, or the output is about a rule set the team never chose |
| Task runners and contributor docs — `Makefile`, `justfile`, `Taskfile.yml`, `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md` | the documented entry point (`make lint`, `npm run check`), which is often a bundle of several tools and is what a human would have run |

Write down the resulting inventory before running anything: tool, the command that invokes it, its config file, and whether CI gates on it. If the repo configures **nothing**, say so and go straight to the lenses — an empty inventory is a valid, reportable result.

Then match that inventory against **every path the diff touches**, not against the type most of the diff happens to be written in. A file's own extension or filename pattern is what selects a tool — a changed `.md` file against a configured markdownlint, a changed `.github/workflows/*.yml` file against actionlint, a changed `.sh` file against ShellCheck — even when every other changed file is in some other language entirely. Do this for each changed file independently; a diff is not one language for tool-selection purposes just because most of its files are.

## 2. Run them, scoped and under their own config

- **Scope to what is under review — through each tool's own idea of scope.** Linters and type checkers usually take a file list, and on a diff review that is what to pass. Plenty of tools have no meaningful per-file mode: a dependency auditor reads the lockfile, a coverage threshold is computed over the project, an IaC validator works per directory or stack, a data tool works over its DAG. For those, use the tool's own documented diff mode if it has one, otherwise its normal project scope — then **filter the output** to what the change touches rather than pretending the run was scoped. Record which it was: "ran over the tree, filtered to the diff" is a different fact from "ran over the 6 changed files," and only one of them says anything about the rest of the repo.
- **Use the repo's config, never your own defaults.** Output about a rule set the team never chose is noise, and reporting it as findings is how a review loses its credibility on the first PR.
- **Prefer the documented entry point** (`make lint`, `npm run check`, `pre-commit run --files ...`) — it is what a human would have run and it already carries the repo's arguments — **but only while it preserves the scope you need.** A `make lint` that always sweeps the whole tree costs more than the review's budget and surfaces findings the diff did not cause; when that happens, invoke the adopted tool directly, still under the repo's config, with the changed files.
- **Capture the raw output**, including exit codes and any tool that failed to start. What did not run is as important to the report as what did.

## 3. Route each hit to the lens that owns it

Tool families and the lenses whose findings their output can evidence. The named tools are recognition aids for the inventory in step 1, not a list to install:

| Family | Tools you may find configured | Grounds |
|---|---|---|
| Lint & style | ESLint, Ruff, RuboCop, golangci-lint, Clippy, ShellCheck, markdownlint-cli2 | `checking-idioms-and-consistency`, `reviewing-naming-and-readability` |
| Types & static correctness | mypy, Pyright, `tsc --noEmit`, `go vet`, Infer | `tracing-correctness-and-invariants`, `hunting-silent-failures` |
| Security & SAST | Semgrep, Bandit, CodeQL, gosec, Brakeman, gitleaks | `sweeping-for-security` |
| Dependency & supply chain | pip-audit, npm audit, cargo-audit, osv-scanner, Dependabot, Syft/Grype | `auditing-dependencies-and-supply-chain`, `reviewing-ai-authored-code` |
| Infrastructure as code | tflint, Checkov, `terraform validate`, kube-linter, Hadolint | `auditing-infrastructure-as-code` |
| Structure & architecture | dependency-cruiser, import-linter, ArchUnit, madge | `auditing-architecture-conformance`, `reviewing-module-design` |
| Tests & coverage | the repo's own test runner plus its coverage config (.coveragerc, pyproject.toml [tool.coverage], a jest coverageThreshold) | `reviewing-test-quality` |
| Accessibility | axe-core, eslint-plugin-jsx-a11y, Lighthouse CI | `reviewing-accessibility-and-i18n` |
| Data plane | sqlfluff, dbt tests, Great Expectations, schema-registry compatibility checks | `reviewing-data-transformations-and-contracts`, `auditing-data-pipeline-health` |

A hit in a family no selected lens owns is still worth passing along to the lens nearest it — but it never becomes a finding on its own authority.

## 4. Confirm, contextualize, or dismiss — every hit, exactly once

Each hit gets exactly one of **confirm**, **contextualize**, **dismiss**. Passing a hit through unexamined is not a fourth option: an unreviewed tool dump is what the author already had before the review started.

| Disposition | When | What to do |
|---|---|---|
| **confirm** | the owning lens independently agrees the flagged code is wrong | report one finding attributed to the lens, citing the tool and rule id as evidence — the lens owns the finding, the tool owns the proof |
| **contextualize** | the hit is real but its severity or urgency is not what the tool's default says in this codebase | keep the finding and restate its severity on the atlas's scale, saying what about the context moved it |
| **dismiss** | the hit does not hold here — a false positive, a deliberate pattern the repo applies consistently, or a rule the team has opted out of elsewhere | drop it and say why in one line, so the dismissal is auditable and a misconfigured rule is visible rather than silently absorbed |

## Discipline

- **Never introduce a tool the repo has not adopted.** Run what the repo already configures. A linter the team never chose emits a wall of style hits that are not defects in this codebase; at most, its absence is a `route: eng` suggestion to adopt it, never a set of findings against the diff.
- **A clean run clears nothing.** Deterministic tools have no opinion on whether an invariant is the right one, whether a boundary belongs, whether a test proves anything, or whether the change should exist. Every selected lens still runs in full. Absence of tool output is absence of evidence, not evidence of absence.
- **Check every hit against the diff before reporting it.** Tool output can come from a different revision, a stale cache, or a rule the repo has since reconfigured. An unreproduced tool hit reported as a finding is an unsupported claim — the same defect `reviewing-pr-and-process-hygiene` flags in a PR description.
- **A reported run is a claim, not evidence.** "Type-checks clean", "all tests pass", "0 errors", "confirmed dead by a full type-check" in a PR description or an author's comment is a claim about a run this review did not see. It becomes evidence only when the pre-pass reproduces it or CI shows it on this exact head commit — and either way only for the files the run actually covered: a tool whose config or file filter excludes the code in question reports zero errors vacuously, so check the run's scope before counting its silence. When the run cannot be reproduced here, say so under coverage and name the command that would settle it; if the change rests on the claim (a deleted suppression, a removed guard), the synthesizer holds it as provisional rather than affirmed.
- **Running the repo's tools runs the repo's code.** Lint and build configuration is executable in most ecosystems — an `eslint.config.js` is JavaScript, a `Makefile` target is a shell command, a pre-commit hook fetches and runs a remote repository, dbt renders Jinja — and plugins load from the lockfile. On an untrusted branch (a fork PR, an unreviewed contributor) treat the pre-pass as executing untrusted code: run it only in the isolation CI already uses, or skip it and say so under coverage. A grounding pre-pass must never be the reason untrusted code executes with credentials in scope.
- **Bound the cost, and call a timeout a coverage gap.** Scope each run through the tool's own scope mechanism (see step 2) — never a whole-tree sweep on a diff review when the tool has a diff mode, and never a whole-tree sweep reported as though it were scoped. A tool that exceeds its budget, needs a toolchain that is absent, or fails to build is a stated limitation — never a finding, and never a silent omission.
- **Keep judgment and measurement distinguishable.** A confirmed finding names both the lens that owns it and the rule that evidenced it, so a reader can tell what was measured from what was judged, and so a false positive is traceable to the rule that produced it.
- **A narrowing flag changes what "unused" means — never run one to check a suppression.** Some tools expose an override flag that *replaces* the project's configured rule set for that invocation rather than adding to it — ruff's `--select` is the canonical example: `ruff check --select RUF100 .` makes RUF100 the only enabled rule for that run, so every `# noqa` in the repo looks unused regardless of whether its named rule actually fires under the real configuration. Checking whether a suppression is stale this way manufactures false positives rather than detecting real ones — e.g. a self-audit that reported several genuinely-necessary suppressions as dead on exactly this invocation. Ground a stale-suppression finding in the tool's additive form instead (`--extend-select` for ruff, or the equivalent for another tool/linter) or in a project-config change plus the tool's own default invocation. Before reporting a finding that would change code (removing the suppression), confirm it by removing the directive and running the project's own unmodified invocation with no override flags: if a diagnostic fires, the suppression was necessary and the additive finding was a false positive; if none does, the additive finding is confirmed.
- **Select tools by every changed file's type, not the diff's dominant language.** Match the inventory from step 1 against every path the diff touches, not against the type most of the diff is written in. A PR that changes four Python files and one Markdown file still owes whatever tool the repo has configured for `.md` — if `.markdownlint-cli2.jsonc` and a CI job for it exist, select markdownlint-cli2 because that one file matches, not because it loses a popularity count to the other four. The same holds for a lone shell script against ShellCheck or a single workflow YAML against actionlint. This failure mode is specific to a file outnumbered by a different language in the same diff — a same-language diff never hits it — and it is exactly how a configured markdownlint run went unselected on a Python-dominant PR while CI and a second reviewer still caught the violation it would have caught first (#576).
- **A changed file type with no matching tool is a coverage gap, not silence.** When a changed path's extension or filename pattern has no entry in the step-1 inventory, that absence belongs in the coverage line by name — the dedicated slot in What to hand on below — not folded into "No deterministic coverage," which names lenses and categories, never file types. A reader scanning "Tools run: ruff, mypy" on a diff that also touched a `.md` file has no way to tell whether the repo simply has no Markdown tooling or whether one exists and was never selected; naming the untested extension removes that ambiguity instead of leaving a silent, implied clean result (#576).
- **Name the pending job and its linters, not just "in progress".** A CI check still running is not yet evidence, but "in progress" alone tells the reader nothing about what it would have covered once it finished. When a required check that gates deterministic tooling has not reported yet, name the specific job(s) still pending and the linter(s) each one runs — sourced from the same workflow file the step-1 inventory already read — e.g. "the `gate` job is still running; it runs ruff, mypy, and markdownlint-cli2" — so a reader can tell which categories are only provisionally clear rather than genuinely covered (#576).

## What to hand on

Two things go forward from this pass:

1. **An evidence bundle per lens** — the hits routed to it, each with the tool, the rule id, and the location, so the lens can confirm, contextualize, or dismiss them alongside its own reading of the code.
2. **A coverage line** for the merged report's *Coverage & limitations* section, which `synthesizing-review-findings` already reserves. Five facts, one line each when non-empty:

```text
Tools run: <tool (rule set), ...> over <scope>.
Not run: <tool> — <missing toolchain | timed out | untrusted branch | not configured>.
Pending in CI: <job name> — runs <tool, ...>; not yet reported.
No deterministic coverage: <lens or category names> — judgment only.
Changed file types with no configured tool: <extension or filename pattern, ...>.
```

The last two lines are the ones a reader cannot reconstruct for themselves, and the ones a confident-looking review most often omits. A category with no tool behind it is not a category that passed, and a changed `.md`, workflow, or `.sh` file with no matching inventory entry is a real gap, not an implied clean result — name the extension or filename pattern rather than folding it silently into "No deterministic coverage," which names lenses and categories, never file types. When a required check that gates deterministic tooling is still running rather than finished, use the Pending in CI line to name the job and the linter(s) it runs — "in progress" alone tells the reader nothing about what that check would have covered if it had finished.

## Going deeper

- [choosing-review-lenses](../choosing-review-lenses/SKILL.md) — picks the lenses this pre-pass gathers evidence for.
- [synthesizing-review-findings](../synthesizing-review-findings/SKILL.md) — merges the lenses' findings, including the ones this pre-pass evidenced, into one verdict.
- Each lens's own `reference/tool-rules.md` — the specific rule ids in that lens's domain, for wiring a tool up in a repo that has none.

<!-- GENERATED by `python -m tooling.cli generate` — do not edit this file directly.
     Canonical sources: skills/manifest.yaml.
     Direct edits are overwritten on regeneration and fail the CI drift/regenerate gate. -->
