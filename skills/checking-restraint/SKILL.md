---
name: checking-restraint
description: Reviews changes for over-engineering — premature abstraction, speculative
  generality, the wrong abstraction, and premature optimization without a profile.
  The restraint / brake-pedal lens. Use when a change adds abstraction layers, config
  knobs, generality, or hand-optimized code, or when asking whether a change is doing
  too much.
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 11
    source: docs/research/cluster-3-structure.md#11
    hash: 8449117110d3d31227f83daec22bc0fd1a27e6fa0ca15ac8cfa209ddec674188
  - category: 15
    source: docs/research/cluster-4-runtime.md#15
    hash: a5e2b6c50fe7043fed8828b7b6e1a33123f348ae55dcb0ce95ffb061b1231586
---

# checking-restraint

*Is this change too much? Premature abstraction or optimization — the brake pedal.*

## When to use

Reviews changes for over-engineering — premature abstraction, speculative generality, the wrong abstraction, and premature optimization without a profile. The restraint / brake-pedal lens. Use when a change adds abstraction layers, config knobs, generality, or hand-optimized code, or when asking whether a change is doing too much.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Is this abstraction introduced on **real, repeated need** (rule of three), or speculatively for one/two uses (YAGNI)?
- Does it have a single, nameable responsibility — or is it a grab-bag taking flags/conditionals to fit multiple callers (the **wrong-abstraction** smell)?
- Is there an **existing** abstraction this duplicates/competes with (reuse/extend it, don't fork — cross #8)?
- Would **inlining** make the code clearer? If the abstraction fights its callers, recommend re-inlining.
- Is the indirection earning its keep, or a **shallow wrapper** that just adds a layer to read through (Ousterhout)?
- Any **speculative generality**: config options, plugin hooks, "just in case" parameters with a single caller? Remove.
- Is there a loop that issues a query/RPC/HTTP call per iteration? (N+1.) Push to a single batched/`IN`/join query or a bulk endpoint. Flag `await` inside `for` over independent items.
- What is the worst-case complexity on the hot path as input grows? Flag accidental O(n²) (nested loops over the same collection, `Array.includes` inside a loop → use a Set/Map), and unbounded growth.

**Shared categories:** category #15 checks are shared with **reviewing-performance-and-efficiency** (their primary owner). When both lenses run on the same change, report each shared finding once, under the primary owner.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
