---
name: reviewing-module-design
description: 'Reviews module and type design: cohesion and coupling (via connascence),
  encapsulation, hard-to-misuse interfaces, and making illegal states unrepresentable.
  Use when reviewing class/module structure, interfaces, type or data modeling, coupling,
  or API ergonomics for callers.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 9
    source: docs/research/cluster-3-structure.md#9
    hash: 920b16f870efcf593612b37ea17cab42ea05eec36f269b9b2b9c5f53e0fbbc6f
  - category: 10
    source: docs/research/cluster-3-structure.md#10
    hash: 1c888a10ae9486b6847ee871fea455cde8e1b4c46db42200a751e589301839b3
---

# reviewing-module-design

## When to use

Reviews module and type design: cohesion and coupling (via connascence), encapsulation, hard-to-misuse interfaces, and making illegal states unrepresentable. Use when reviewing class/module structure, interfaces, type or data modeling, coupling, or API ergonomics for callers.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
