---
name: reviewing-module-design
description: 'Reviews module and type design: cohesion and coupling (via connascence),
  encapsulation, hard-to-misuse interfaces, and making illegal states unrepresentable.
  Use when reviewing class/module structure, interfaces, type or data modeling, coupling,
  or API ergonomics for callers.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 9
    source: docs/research/cluster-3-structure.md#9
    hash: 920b16f870efcf593612b37ea17cab42ea05eec36f269b9b2b9c5f53e0fbbc6f
  - category: 10
    source: docs/research/cluster-3-structure.md#10
    hash: 1c888a10ae9486b6847ee871fea455cde8e1b4c46db42200a751e589301839b3
---

# reviewing-module-design

*Are the boundaries right? Coupling, encapsulation, interfaces that are hard to misuse, illegal states unrepresentable.*

## When to use

Reviews module and type design: cohesion and coupling (via connascence), encapsulation, hard-to-misuse interfaces, and making illegal states unrepresentable. Use when reviewing class/module structure, interfaces, type or data modeling, coupling, or API ergonomics for callers.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Does the unit have **one** clear responsibility (high cohesion)? State its job in a sentence without "and."
- Is the interface **narrow relative to the behavior** behind it (deep module), or a shallow pass-through adding no value?
- What is the **strongest connascence crossing the boundary**, and is it local? (Position/Algorithm connascence across modules is a smell; prefer Name/Type.)
- Does it **hide its implementation** so internals can change without breaking callers?
- Are **invalid states representable**? Could you construct a value the domain forbids (an order both `draft` and `shipped`)? Model with a tagged union / state machine instead.
- Is untrusted input **parsed into a precise type at the boundary** (parse-don't-validate), or validated then passed onward as raw primitives (re-validatable downstream)?
- **Primitive obsession**: are domain concepts (email, money, id, %) raw `string`/`number`, or wrapped in domain types carrying invariants/units (cross #4)?
- Are optional/nullable fields modeled explicitly (`Option`/`Maybe`/`| null`) rather than sentinel values (`-1`, `""`)?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
