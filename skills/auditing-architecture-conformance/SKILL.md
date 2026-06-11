---
name: auditing-architecture-conformance
description: 'Audits a repository for architecture conformance: dependency direction
  violations between layers/modules, cyclic dependencies, reach-arounds past a boundary,
  accidental coupling to internals, and drift between the documented architecture
  and the import graph. A repo-wide / scheduled audit rather than a single-diff review.
  Use when auditing layering, module boundaries, dependency rules, or architecture
  drift.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 12
    source: docs/research/cluster-3-structure.md#12
    hash: 73ad9e27e4e66a75d4c2d99dec397b8536fa4b835edc22a07de4f7e034cdea45
---

# auditing-architecture-conformance

## When to use

Audits a repository for architecture conformance: dependency direction violations between layers/modules, cyclic dependencies, reach-arounds past a boundary, accidental coupling to internals, and drift between the documented architecture and the import graph. A repo-wide / scheduled audit rather than a single-diff review. Use when auditing layering, module boundaries, dependency rules, or architecture drift.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

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
