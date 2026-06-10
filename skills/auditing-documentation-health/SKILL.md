---
name: auditing-documentation-health
description: 'Audits documentation health across a repository: API-surface-to-docs
  parity, docstring accuracy against current signatures, README front-door freshness,
  runnable examples that still run, ADR coverage for non-obvious decisions, changelog
  discipline, orphaned or contradictory docs, and stale diagrams. A repo-wide / scheduled
  audit. Use when auditing docs, READMEs, docstrings, changelogs, ADRs, or onboarding
  material.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 22
    source: docs/research/cluster-6-evolution.md#22
    hash: c2b968248bfa961bf8a9ca267334e64935892ae4074bd2a1cf1028044482c669
---

# auditing-documentation-health

## When to use

Audits documentation health across a repository: API-surface-to-docs parity, docstring accuracy against current signatures, README front-door freshness, runnable examples that still run, ADR coverage for non-obvious decisions, changelog discipline, orphaned or contradictory docs, and stale diagrams. A repo-wide / scheduled audit. Use when auditing docs, READMEs, docstrings, changelogs, ADRs, or onboarding material.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
