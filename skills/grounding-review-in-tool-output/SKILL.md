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
  taxonomy_version: v0.13
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
- **Running the repo's tools runs the repo's code.** Lint and build configuration is executable in most ecosystems — an `eslint.config.js` is JavaScript, a `Makefile` target is a shell command, a pre-commit hook fetches and runs a remote repository, dbt renders Jinja — and plugins load from the lockfile. On an untrusted branch (a fork PR, an unreviewed contributor) treat the pre-pass as executing untrusted code: run it only in the isolation CI already uses, or skip it and say so under coverage. A grounding pre-pass must never be the reason untrusted code executes with credentials in scope.
- **Bound the cost, and call a timeout a coverage gap.** Scope each run through the tool's own scope mechanism (see step 2) — never a whole-tree sweep on a diff review when the tool has a diff mode, and never a whole-tree sweep reported as though it were scoped. A tool that exceeds its budget, needs a toolchain that is absent, or fails to build is a stated limitation — never a finding, and never a silent omission.
- **Keep judgment and measurement distinguishable.** A confirmed finding names both the lens that owns it and the rule that evidenced it, so a reader can tell what was measured from what was judged, and so a false positive is traceable to the rule that produced it.

## What to hand on

Two things go forward from this pass:

1. **An evidence bundle per lens** — the hits routed to it, each with the tool, the rule id, and the location, so the lens can confirm, contextualize, or dismiss them alongside its own reading of the code.
2. **A coverage line** for the merged report's *Coverage & limitations* section, which `synthesizing-review-findings` already reserves. Three facts, one line each when non-empty:

```text
Tools run: <tool (rule set), ...> over <scope>.
Not run: <tool> — <missing toolchain | timed out | untrusted branch | not configured>.
No deterministic coverage: <lens or category names> — judgment only.
```

That last line is the one a reader cannot reconstruct for themselves, and the one a confident-looking review most often omits. A category with no tool behind it is not a category that passed.

## Going deeper

- [choosing-review-lenses](../choosing-review-lenses/SKILL.md) — picks the lenses this pre-pass gathers evidence for.
- [synthesizing-review-findings](../synthesizing-review-findings/SKILL.md) — merges the lenses' findings, including the ones this pre-pass evidenced, into one verdict.
- Each lens's own `reference/tool-rules.md` — the specific rule ids in that lens's domain, for wiring a tool up in a repo that has none.
