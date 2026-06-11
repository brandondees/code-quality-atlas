# code-quality-atlas

A from-first-principles research project — and, eventually, a **standalone agent skill suite for code review and maintenance.**

The goal is two-part:

1. Map *everything* that factors into code quality, as comprehensively as possible.
2. Distill that map into a coherent set of composable agent skills that help **review** and **maintain** code.

All three phases are complete — the suite is built and installable (see Install below). Ongoing work is the compounding loop: critique the research, let drift flag affected skills, regenerate, re-gate.

## Status

**Phase 1 — Research & taxonomy (complete, 2026-06-09)**

- [x] Scope decision: **maximal** — intrinsic code properties **plus** all cross-cutting concerns (security, performance, tests, deps, build/CI, data, docs, accessibility, observability, …).
- [x] Taxonomy v0.2 (pressure-tested): **6 clusters / 27 categories / ~80 factors** → [`docs/taxonomy.md`](docs/taxonomy.md)
- [x] **Per-cluster research — all 6 clusters written & web-verified:** references, static-analysis tool rules, reviewable heuristics → [`docs/research/`](docs/research/)
- [x] Prior-art survey → [`docs/prior-art.md`](docs/prior-art.md); cross-cutting findings → [`docs/map-gaps.md`](docs/map-gaps.md)

**Phase 2 — Skill-suite architecture (complete, 2026-06-09)** → [`docs/phase-2-skill-suite-design.md`](docs/phase-2-skill-suite-design.md): docs are the source of truth; skills are generated from [`skills/manifest.yaml`](skills/manifest.yaml) with provenance hashes, a drift-checker, and eval-first refinement. 22 behaviors mapped over the 27 categories, built in waves.

**Phase 3 — Build the skills (complete, 2026-06-10)**

- [x] **Wave 1 — the 6 ★ skills** (LLM-judgment-heavy, highest unique value) → [`skills/`](skills/): generated, refined with examples + ≥3 eval scenarios each, cross-model-tested down to small local models (see [`docs/runbooks/regenerating-skills.md`](docs/runbooks/regenerating-skills.md)).
- [x] **Wave 2 — high-stakes triage** (5 skills): security sweep, migration & data safety, performance & efficiency, test quality, accessibility & i18n — same refine-and-eval loop; small-model gaps + linter pairings documented in the runbook.
- [x] **Wave 3 — remainder + repo/cron-shaped audits** (11 skills): tracing correctness, concurrency & async, idioms & consistency, API contract safety, observability & operability, PR & process hygiene; plus repo-shaped audits for architecture conformance, dependencies & supply chain, config & build hygiene, documentation health, and compliance & provenance.
- [x] **G1 single-owner enforcement:** the manifest validator rejects a category with two primary owners; double-booked categories carry explicit `cross_ref` markers.
- [x] **Q12 packaging:** the repo is itself a Claude Code plugin + marketplace (commit-SHA versioned) → see Install below.

All **22 behaviors / 27 categories** from the [phase-2 design](docs/phase-2-skill-suite-design.md) are built.

## Install (Claude Code)

In an interactive Claude Code session on your machine (terminal CLI, desktop app, or IDE extension):

```
/plugin marketplace add brandondees/code-quality-atlas
/plugin install code-quality-atlas@code-quality-atlas
```

Or from a plain shell, non-interactively (add `--scope project` to scope to one repo):

```bash
claude plugin marketplace add brandondees/code-quality-atlas
claude plugin install code-quality-atlas@code-quality-atlas
```

Or per-repo via settings — commit this to a project's `.claude/settings.json` and
anyone who trusts the folder gets the suite, **including Claude Code web sessions**
(which don't expose the interactive `/plugin` command):

```json
{
  "extraKnownMarketplaces": {
    "code-quality-atlas": {
      "source": { "source": "github", "repo": "brandondees/code-quality-atlas" }
    }
  },
  "enabledPlugins": {
    "code-quality-atlas@code-quality-atlas": true
  }
}
```

> **Note:** while this repo is private, the installing machine needs git credentials
> that can read it (`gh` auth or SSH keys; web sessions clone with your GitHub
> credentials). Make the repo public for zero-friction sharing.

All 22 skills load with provenance intact; updates ship with every merged commit
(commit-SHA versioning) — refresh with `/plugin marketplace update code-quality-atlas`.
The skills are plain markdown and remain harness-agnostic; the plugin wrapper is
additive (D9 in [`docs/open-questions.md`](docs/open-questions.md)).

## Approach

Built fresh from **first principles**. Existing skills, plugins, linters, and review tools (Anthropic's, the community's, the author's own) are treated as **prior art to learn from and borrow from** — not as constraints. The catalog lives in [`docs/prior-art.md`](docs/prior-art.md).

## Map of this repo

| File | What's in it |
|---|---|
| [`docs/overview.md`](docs/overview.md) | Project intent, scope decision, phase plan, working principles |
| [`docs/taxonomy.md`](docs/taxonomy.md) | The master map: clusters → categories → factors |
| [`docs/references.md`](docs/references.md) | Annotated references by cluster — the active research surface |
| [`docs/prior-art.md`](docs/prior-art.md) | Existing skills / tools that already cover parts of the map |
| [`docs/research/`](docs/research/) | Per-cluster research: references, tooling rules, reviewable heuristics |
| [`docs/map-gaps.md`](docs/map-gaps.md) | Cross-cutting structural findings feeding phase-2 (double-booked concerns, decomposition tension, etc.) |
| [`docs/open-questions.md`](docs/open-questions.md) | Decisions made + unresolved questions |
| [`docs/plans/`](docs/plans/) | Implementation plans (e.g. the wave-1 pipeline build) |
| [`docs/session-log.md`](docs/session-log.md) | Chronological record of how this evolved |
| [`skills/`](skills/) | The 22 generated + refined skills (see `manifest.yaml`) |
| [`tooling/`](tooling/) | The pipeline: generator, drift-checker, eval validator, cross-model runner |
