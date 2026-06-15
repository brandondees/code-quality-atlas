---
name: auditing-architecture-conformance
description: 'Audits a repository for architecture conformance: dependency direction
  violations between layers/modules, cyclic dependencies, reach-arounds past a boundary,
  accidental coupling to internals, and drift between the documented architecture
  and the import graph. A repo-wide / scheduled audit rather than a single-diff review.
  Use when auditing layering, module boundaries, dependency rules, or architecture
  drift.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 12
    source: docs/research/cluster-3-structure.md#12
    hash: 49051cc3b2f556cac15149bd8a1834bb93672eb5eb558dc04a4f80caed8e8235
---

# auditing-architecture-conformance

*Does the import graph still match the intended architecture? Layers, cycles, reach-arounds.*

## When to use

Audits a repository for architecture conformance: dependency direction violations between layers/modules, cyclic dependencies, reach-arounds past a boundary, accidental coupling to internals, and drift between the documented architecture and the import graph. A repo-wide / scheduled audit rather than a single-diff review. Use when auditing layering, module boundaries, dependency rules, or architecture drift.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Do source dependencies respect the **intended direction** (domain doesn't import infrastructure; UI→app→domain, not back)?
- Any **dependency cycles** between modules/packages/services (ADP)?
- Is there a **god module / hub** with huge fan-in *and* fan-out that everything routes through?
- Does the change honor existing layer/boundary contracts, or smuggle a cross-layer import?
- Could the intended rule be expressed as a **fitness function** (an ArchUnit/import-linter check)? If a rule is repeatedly violated, the boundary is wrong or unclear.
- New cross-service/cross-context coupling via an **explicit contract** (API/event), not a shared DB or internal reach-in?
- Is the architecture style **consistent** with the rest of the system (not a competing pattern bolted on)?
- Does it scale along the expected axis (data volume, traffic, team size), or bake in a single-node assumption (cross #3, #15)?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
