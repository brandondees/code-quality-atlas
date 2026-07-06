---
name: reviewing-module-design
description: 'Reviews module and type design: cohesion and coupling (via connascence),
  encapsulation, hard-to-misuse interfaces, and making illegal states unrepresentable.
  Use when reviewing class/module structure, interfaces, type or data modeling, coupling,
  or API ergonomics for callers.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 9
    source: docs/research/cluster-3-structure.md#9
    hash: 38ffd004ead3132595eb8c0abef6604be65c2ff741e304912c5fe25a0356ef3e
  - category: 10
    source: docs/research/cluster-3-structure.md#10
    hash: ff175300df2b146d5d226fef720a42eb2ade21d990ac1f022fe7d2e6df51707a
---

# reviewing-module-design

*Are the boundaries right? Coupling, encapsulation, interfaces that are hard to misuse, illegal states unrepresentable.*

## When to use

Reviews module and type design: cohesion and coupling (via connascence), encapsulation, hard-to-misuse interfaces, and making illegal states unrepresentable. Use when reviewing class/module structure, interfaces, type or data modeling, coupling, or API ergonomics for callers.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Is it **hard to misuse** — invalid argument/call-sequence prevented by types, not docs (caller ergonomics / pit of success)?
- Does the unit have **one** clear responsibility (high cohesion)? State its job in a sentence without "and."
- Is the interface **narrow relative to the behavior** behind it (deep module), or a shallow pass-through adding no value?
- What is the **strongest connascence crossing the boundary**, and is it local? (Position/Algorithm connascence across modules is a smell; prefer Name/Type.)
- Does it **hide its implementation** so internals can change without breaking callers?
- Are **invalid states representable**? Could you construct a value the domain forbids (an order both `draft` and `shipped`)? Model with a tagged union / state machine instead.
- Is untrusted input **parsed into a precise type at the boundary** (parse-don't-validate), or validated then passed onward as raw primitives (re-validatable downstream)?
- **Primitive obsession**: are domain concepts (email, money, id, %) raw `string`/`number`, or wrapped in domain types carrying invariants/units (cross #4)?
- Are optional/nullable fields modeled explicitly (`Option`/`Maybe`/`| null`) rather than sentinel values (`-1`, `""`)?

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
