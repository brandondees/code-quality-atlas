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

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Does every branch and early return preserve the function's stated invariant/postcondition?
- Are boundary values (0, 1, n−1, n, empty, max, negative) explicitly handled — and tested?
- Any off-by-one in ranges, slices, loop bounds, inclusive/exclusive ends?
- Is every externally-sourced value null/undefined-checked at the boundary, or typed non-null?
- Is every acquired resource (file, socket, connection, lock, cursor) released on **all** paths including errors (`with`/`using`/`defer`/`ensure`)?
- Does anything that grows (logs, cache, queue, temp files, sessions) have a bound / eviction / TTL (steady state)?
- Money/currency stored as integer minor units or a decimal `Money` type — never binary float — and currency carried?
- Float comparisons use a tolerance, not `==`?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
