---
name: checking-restraint
description: Reviews changes for over-engineering — premature abstraction, speculative
  generality, the wrong abstraction, and premature optimization without a profile.
  The restraint / brake-pedal lens. Use when a change adds abstraction layers, config
  knobs, generality, or hand-optimized code, or when asking whether a change is doing
  too much.
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 11
    source: docs/research/cluster-3-structure.md#11
    hash: e510fd2362c34f2524d4eed76104d001fb032f4d62aac866e38da82ad61c368f
  - category: 15
    source: docs/research/cluster-4-runtime.md#15
    hash: 0a3ca5033ee175b2933254b92caa1e23b8536ab91cc08680d1fa63143183c7c9
---

# checking-restraint

## When to use

Reviews changes for over-engineering — premature abstraction, speculative generality, the wrong abstraction, and premature optimization without a profile. The restraint / brake-pedal lens. Use when a change adds abstraction layers, config knobs, generality, or hand-optimized code, or when asking whether a change is doing too much.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
