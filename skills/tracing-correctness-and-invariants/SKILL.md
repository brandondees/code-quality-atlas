---
name: tracing-correctness-and-invariants
description: 'Traces whether a change actually does what it claims: invariants and
  postconditions preserved on every branch, boundary values (0, 1, n-1, empty, max,
  negative) handled, off-by-one in ranges and loop bounds, null/undefined checked
  at boundaries, exhaustive switch/match, resource cleanup on all paths, money as
  integer minor units, monotonic clocks for durations, UTC for storage. Use when reviewing
  logic, algorithms, loops, conditionals, edge cases, or whether the implementation
  matches the stated intent.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 1
    source: docs/research/cluster-1-correctness.md#1
    hash: 67804c59cce91a8a7d54c299022f532bd6f99b79926a841fdb5cc8e10fb41ef3
  - category: 4
    source: docs/research/cluster-1-correctness.md#4
    hash: 3edce8248eeb84bff46c3aa7e7c5ad1ada54d091f9366fb17fba234616ec27c7
---

# tracing-correctness-and-invariants

## When to use

Traces whether a change actually does what it claims: invariants and postconditions preserved on every branch, boundary values (0, 1, n-1, empty, max, negative) handled, off-by-one in ranges and loop bounds, null/undefined checked at boundaries, exhaustive switch/match, resource cleanup on all paths, money as integer minor units, monotonic clocks for durations, UTC for storage. Use when reviewing logic, algorithms, loops, conditionals, edge cases, or whether the implementation matches the stated intent.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
