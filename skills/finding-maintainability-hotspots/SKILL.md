---
name: finding-maintainability-hotspots
description: "Scans a repository for maintainability hotspots: high churn \xD7 complexity\
  \ files, change-coupling, bus-factor / knowledge concentration, and untracked tech\
  \ debt. A repo-wide / scheduled scan rather than a single-diff review. Use when\
  \ auditing maintainability, tech debt, refactoring targets, or risky areas across\
  \ the codebase."
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 21
    source: docs/research/cluster-6-evolution.md#21
    hash: a9146894743cfe64e936fd9995aaf7498d7d694fe1e1873c6d375d981d4eaca7
---

# finding-maintainability-hotspots

## When to use

Scans a repository for maintainability hotspots: high churn × complexity files, change-coupling, bus-factor / knowledge concentration, and untracked tech debt. A repo-wide / scheduled scan rather than a single-diff review. Use when auditing maintainability, tech debt, refactoring targets, or risky areas across the codebase.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
