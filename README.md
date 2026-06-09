# code-quality-atlas

A from-first-principles research project — and, eventually, a **standalone agent skill suite for code review and maintenance.**

The goal is two-phased:

1. Map *everything* that factors into code quality, as comprehensively as possible.
2. Distill that map into a coherent set of composable agent skills that help **review** and **maintain** code.

We are in phase 1.

## Status

**Phase 1 of 3 — Research & taxonomy (in progress)**

- [x] Scope decision: **maximal** — intrinsic code properties **plus** all cross-cutting concerns (security, performance, tests, deps, build/CI, data, docs, accessibility, observability, …).
- [x] First-pass taxonomy: **6 clusters / 24 categories / ~70 factors** → [`docs/taxonomy.md`](docs/taxonomy.md)
- [ ] Reference gathering — books, papers, tools, linters, heuristics → [`docs/references.md`](docs/references.md)
- [ ] Prior-art survey → [`docs/prior-art.md`](docs/prior-art.md)
- [ ] Resolve open questions → [`docs/open-questions.md`](docs/open-questions.md)

**Phase 2 — Skill-suite architecture** (not started): decide granularity, group categories into buildable skills, define how they're invoked and composed.

**Phase 3 — Build the skills** (not started).

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
| [`docs/session-log.md`](docs/session-log.md) | Chronological record of how this evolved |
