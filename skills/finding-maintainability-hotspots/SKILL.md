---
name: finding-maintainability-hotspots
description: 'Scans a repository for maintainability hotspots: high churn × complexity
  files, change-coupling, bus-factor / knowledge concentration, and untracked tech
  debt. A repo-wide / scheduled scan rather than a single-diff review. Use when auditing
  maintainability, tech debt, refactoring targets, or risky areas across the codebase.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 21
    source: docs/research/cluster-6-evolution.md#21
    hash: e05463da683114d3b89971a92025fe650fe0579d060a11de66779506d3b1b9ce
---

# finding-maintainability-hotspots

*Where does the repo hurt most? Churn × complexity, change-coupling, bus factor, untracked debt.*

## When to use

Scans a repository for maintainability hotspots: high churn × complexity files, change-coupling, bus-factor / knowledge concentration, and untracked tech debt. A repo-wide / scheduled scan rather than a single-diff review. Use when auditing maintainability, tech debt, refactoring targets, or risky areas across the codebase.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Change amplification:** did one conceptual change force edits in N>3 files/modules? If so, is that essential (one concept, many sites) or accidental (a missing abstraction / leaked detail)?
- **Shotgun surgery smell:** the same constant, enum case, validation, or shape is edited in multiple places in this diff — flag for consolidation.
- **Blast radius:** does the change touch a high fan-in module (many importers)? Is there a contract/compat note or test proving downstream callers still hold?
- **Refactorability gate:** is the changed code covered by tests *before* the change? If not, was a characterization/pin-down test added first?
- **Debt visibility:** new `TODO`/`FIXME`/`HACK` — does it link to a tracked issue and say *why* (Fowler quadrant: deliberate+prudent is OK if recorded)? Reject silent/untracked debt.
- **Knowledge concentration / bus factor:** does this PR touch a file with a single historical author or a long-abandoned area? Flag for a second reviewer / knowledge-spreading.
- **Onboarding cost:** would a new engineer understand *why* this exists from the code + nearby docs alone, or only from tribal knowledge?
- **Hidden coupling:** are two files that "shouldn't" know about each other being changed together again (change-coupling)? Name the implicit contract.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
