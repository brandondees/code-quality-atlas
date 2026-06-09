# Overview

## What this is

A research project whose deliverable is a **standalone agent skill suite for code review and maintenance**, designed from first principles.

"From first principles" means: rather than starting from the skills/tools that already exist and extending them, we first build an independent, comprehensive model of *what code quality actually is* — every dimension a reviewer or maintainer could legitimately care about — and only then ask which of those dimensions deserve a skill, and how those skills should be shaped.

## Why a *map* before *skills*

If you build review skills directly, you build them around whatever you happened to think of, or around the seams of tools you already had. The blind spots become permanent. Building the map first forces coverage to be a deliberate decision: every category is either claimed by a skill, explicitly merged into another, or explicitly deferred — never silently missed.

The map is also the thing we keep *iterating research into*. References, heuristics, checklists, war stories, and tool capabilities all get filed against categories. By the time we design skills, each category should carry its own body of supporting material.

## Scope decision: maximal

We chose the **widest** possible net for what counts as "code quality" — not just the source as written, but everything a reviewer or maintainer assesses:

- **Intrinsic** — correctness, readability, structure, simplicity, naming, types.
- **Cross-cutting runtime** — security, performance, concurrency, observability, resilience.
- **The system around the code** — tests, dependencies, build/CI, data/persistence safety.
- **Evolution & humans** — maintainability, documentation, accessibility/i18n, process & collaboration.

Rationale: the suite is for **review and maintenance**, and real reviewers/maintainers route across all of these. A narrow "intrinsic only" map would push the most expensive failure modes (a security hole, an N+1, an unsafe migration) out of scope.

The counter-risk of a maximal scope — that the suite sprawls into 24 thin skills — is handled in **phase 2 (granularity)**, not by shrinking the map.

## Phases

1. **Research & taxonomy** *(current)* — build and refine the comprehensive map; gather references and prior art per category; resolve open questions about coverage and granularity.
2. **Skill-suite architecture** — decide how the 24 categories collapse into a buildable, composable set of skills; define triggering, scope, inputs/outputs, and how skills compose during a review.
3. **Build** — implement, test, and dogfood the skills.

## Working principles

- **YAGNI applies to this project too.** Don't pre-build structure (per-category directories, tooling) before the research demands it. Grow the repo as the research grows.
- **Two counterweights are first-class.** Quality is about restraint as much as addition — *premature abstraction* and *premature optimization* are explicit factors in the map, not afterthoughts. Any review skill needs a brake pedal, not just an accelerator.
- **Cross-links are expected.** Categories overlap (concurrency ↔ correctness, security ↔ dependencies). The map embraces this rather than forcing a strict tree.
- **Prior art is fuel, not fence.** We mine existing skills/linters/tools for heuristics and checklists, but we don't inherit their boundaries.
