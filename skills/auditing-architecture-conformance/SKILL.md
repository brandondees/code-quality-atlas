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

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
