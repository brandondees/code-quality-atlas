---
name: checking-restraint
description: Reviews changes for over-engineering — premature abstraction, speculative
  generality, the wrong abstraction, and premature optimization without a profile.
  The restraint / brake-pedal lens. Use when a change adds abstraction layers, config
  knobs, generality, or hand-optimized code, or when asking whether a change is doing
  too much.
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 11
    source: docs/research/cluster-3-structure.md#11
    hash: e510fd2362c34f2524d4eed76104d001fb032f4d62aac866e38da82ad61c368f
  - category: 15
    source: docs/research/cluster-4-runtime.md#15
    hash: 95468df6094ec91160285d106ef87d4c7f1de2709ea9f0befebe9aa676028351
---

# checking-restraint

## When to use

Reviews changes for over-engineering — premature abstraction, speculative generality, the wrong abstraction, and premature optimization without a profile. The restraint / brake-pedal lens. Use when a change adds abstraction layers, config knobs, generality, or hand-optimized code, or when asking whether a change is doing too much.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

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

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
