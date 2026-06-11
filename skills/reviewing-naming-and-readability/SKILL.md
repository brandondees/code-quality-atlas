---
name: reviewing-naming-and-readability
description: 'Reviews code for naming and local readability: intention-revealing names
  vs placeholders, function length and cyclomatic/cognitive complexity, deep nesting,
  magic numbers/strings, mixed levels of abstraction, and comment accuracy. Use when
  reviewing readability, naming, complexity, nesting, magic values, or comments.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 5
    source: docs/research/cluster-2-readability.md#5
    hash: 4fd8ccbcd0d75b9096e4eef4473c4094359580c70d674fbd1d4ab8812e447de3
  - category: 6
    source: docs/research/cluster-2-readability.md#6
    hash: 83d93caa4375a3edb09084a4f9e70173aca94284a7d20fecca4d3ede457ff669
  - category: 7
    source: docs/research/cluster-2-readability.md#7
    hash: 71929b9f969c7303f581d400195ba89e99059f0288f6a2701a2cefdcdac125b0
---

# reviewing-naming-and-readability

## When to use

Reviews code for naming and local readability: intention-revealing names vs placeholders, function length and cyclomatic/cognitive complexity, deep nesting, magic numbers/strings, mixed levels of abstraction, and comment accuracy. Use when reviewing readability, naming, complexity, nesting, magic values, or comments.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

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
