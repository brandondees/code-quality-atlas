---
name: reviewing-naming-and-readability
description: 'Reviews code for naming and local readability: intention-revealing names
  vs placeholders, function length and cyclomatic/cognitive complexity, deep nesting,
  magic numbers/strings, mixed levels of abstraction, and comment accuracy. Use when
  reviewing readability, naming, complexity, nesting, magic values, or comments.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 5
    source: docs/research/cluster-2-readability.md#5
    hash: bed0a9380176c7dba9c8db79f4210b17fe0c0394535b60b13f4a03ad9f363be0
  - category: 6
    source: docs/research/cluster-2-readability.md#6
    hash: fbcdaa81071892f915f9c0153acab661785875cfc1bd85dce73cf751479baad4
  - category: 7
    source: docs/research/cluster-2-readability.md#7
    hash: 834a07c39d7656d1186eb6d5990f09f1e3cb3689a86a2002532d7391c7015134
---

# reviewing-naming-and-readability

*Can a newcomer read this function? Names, length, nesting, magic values, comment accuracy.*

## When to use

Reviews code for naming and local readability: intention-revealing names vs placeholders, function length and cyclomatic/cognitive complexity, deep nesting, magic numbers/strings, mixed levels of abstraction, and comment accuracy. Use when reviewing readability, naming, complexity, nesting, magic values, or comments.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Does each name state *intent* (what/why) rather than *mechanism* or type? (`activeUsers` over `userListFiltered`; `retryBudget` over `n`.)
- Is name length proportional to scope? (One letter fine for a 3-line loop; a field or exported symbol needs a descriptive name.)
- Any placeholder/temporary name surviving into the diff? (`tmp`, `data`, `data2`, `obj`, `foo`, `handleStuff`, `Manager`, `Helper`, `Util`.) Flag as "stage: nonsense/honest-incomplete — refine one stage."
- Does this function do *one* thing at *one* level of abstraction? (Altitude: if it mixes high-level policy with low-level byte/string twiddling, extract the low part.)
- Can you state the function's job in a single verb phrase without "and"? If not, likely SRP violation — split.
- Nesting depth ≤ ~3? Replace arrow-shaped nesting with **guard clauses / early returns**; invert conditions to de-nest the happy path.
- Does each comment explain **why** (intent, constraint, trade-off, gotcha, issue link) rather than restate **what**? Delete pure restatements.
- Any **commented-out code**? Delete it — VCS is the archive. Flag every block.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
