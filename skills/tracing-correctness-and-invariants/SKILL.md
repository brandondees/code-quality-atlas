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
  taxonomy_version: v0.9
  built_from:
  - category: 1
    source: docs/research/cluster-1-correctness.md#1
    hash: a731dbba0203ecaecbea20b4f5fd55e427df59cff4565a35e865895ab4557a64
  - category: 4
    source: docs/research/cluster-1-correctness.md#4
    hash: 63ae9d27a00a6a9575d63c6bc8a91c2d785f7d0ba313fd9416e3f61f8f730043
---

# tracing-correctness-and-invariants

*Does the code do what it claims? Invariants, boundaries, off-by-one, resource cleanup.*

## When to use

Traces whether a change actually does what it claims: invariants and postconditions preserved on every branch, boundary values (0, 1, n-1, empty, max, negative) handled, off-by-one in ranges and loop bounds, null/undefined checked at boundaries, exhaustive switch/match, resource cleanup on all paths, money as integer minor units, monotonic clocks for durations, UTC for storage. Use when reviewing logic, algorithms, loops, conditionals, edge cases, or whether the implementation matches the stated intent.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, but this is a **floor-tier** lens: it can never `suppress` a finding outright. The strongest override available is `acknowledge` — a recorded rationale that keeps the finding visible, tagged `acknowledged deviation: <reason>`, and non-blocking rather than removing it. Absent the file, apply this lens's defaults exactly as written above.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Are numeric overflow/underflow and counter wraparound considered for the actual value ranges?
- **Calendar/clock time-bombs (correct at merge, detonates on a future date):** does date/time logic survive the triggers that pass review only because today is an ordinary day — leap year (Feb 29) and leap second, DST spring-forward/fall-back gaps and overlaps, month/year rollover, and the 32-bit `time_t` **epoch-2038** ceiling? Flag hardcoded years/dates, `day + 1`-style arithmetic that ignores real calendars, and "always 365 days / 24 hours" assumptions — latent defects that a clock eventually arms.
- Does every branch and early return preserve the function's stated invariant/postcondition?
- Are boundary values (0, 1, n−1, n, empty, max, negative) explicitly handled — and tested?
- Any off-by-one in ranges, slices, loop bounds, inclusive/exclusive ends?
- Is every externally-sourced value null/undefined-checked at the boundary, or typed non-null?
- Is every acquired resource (file, socket, connection, lock, cursor) released on **all** paths including errors (`with`/`using`/`defer`/`ensure`)?
- Does anything that grows (logs, cache, queue, temp files, sessions) have a bound / eviction / TTL (steady state)?
- Money/currency stored as integer minor units or a decimal `Money` type — never binary float — and currency carried?
- Float comparisons use a tolerance, not `==`?

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
