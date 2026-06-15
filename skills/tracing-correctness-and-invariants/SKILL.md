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
  taxonomy_version: v0.3
  built_from:
  - category: 1
    source: docs/research/cluster-1-correctness.md#1
    hash: a731dbba0203ecaecbea20b4f5fd55e427df59cff4565a35e865895ab4557a64
  - category: 4
    source: docs/research/cluster-1-correctness.md#4
    hash: 9a8288ba9a0155c5b816ae033497849954224582cc461daf7baeb8b6af4e5afc
---

# tracing-correctness-and-invariants

*Does the code do what it claims? Invariants, boundaries, off-by-one, resource cleanup.*

## When to use

Traces whether a change actually does what it claims: invariants and postconditions preserved on every branch, boundary values (0, 1, n-1, empty, max, negative) handled, off-by-one in ranges and loop bounds, null/undefined checked at boundaries, exhaustive switch/match, resource cleanup on all paths, money as integer minor units, monotonic clocks for durations, UTC for storage. Use when reviewing logic, algorithms, loops, conditionals, edge cases, or whether the implementation matches the stated intent.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

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
