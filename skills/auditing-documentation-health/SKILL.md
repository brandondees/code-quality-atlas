---
name: auditing-documentation-health
description: 'Audits documentation health across a repository: API-surface-to-docs
  parity, docstring accuracy against current signatures, README front-door freshness,
  runnable examples that still run, ADR coverage for non-obvious decisions, changelog
  discipline, orphaned or contradictory docs, and stale diagrams. A repo-wide / scheduled
  audit. Use when auditing docs, READMEs, docstrings, changelogs, ADRs, or onboarding
  material.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 22
    source: docs/research/cluster-6-evolution.md#22
    hash: a7e66646fdd831a46d37765f29794abebc92ef33369b97723210bcdc9647d25d
---

# auditing-documentation-health

*Do the docs still tell the truth? API parity, stale examples, ADR coverage, changelog discipline.*

## When to use

Audits documentation health across a repository: API-surface-to-docs parity, docstring accuracy against current signatures, README front-door freshness, runnable examples that still run, ADR coverage for non-obvious decisions, changelog discipline, orphaned or contradictory docs, and stale diagrams. A repo-wide / scheduled audit. Use when auditing docs, READMEs, docstrings, changelogs, ADRs, or onboarding material.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **API surface ↔ docs parity:** does every new/changed public function, endpoint, CLI flag, or config key have a docstring/doc updated in the same diff? Stale signature-vs-doc = drift.
- **Docstring accuracy:** do param names, types, return, and `raises`/`throws` in the docstring match the actual signature *after* this change? (params renamed but docstring not — flag.)
- **Diátaxis coverage:** for a new feature, is there at least the right *mode* of doc — a how-to for a task, reference for an API? Don't accept a tutorial as a substitute for reference.
- **README front-door:** does the README still answer what/why/install/minimal-example/next-steps after this change? New setup step but no README update = onboarding regression.
- **Runnable example:** does the example actually run against the new code (compiles, imports resolve, no removed API)? Prefer doctests/CI-checked snippets.
- **ADR for non-obvious decisions:** does an architecturally significant or surprising choice (new dependency, pattern, boundary, trade-off) have an ADR capturing context/decision/consequences? Code comments are not a substitute for the *why*.
- **Changelog discipline:** does a user-facing change add a CHANGELOG entry in the right category, and is the SemVer impact (patch/minor/major, esp. breaking) correct?
- **Runbook for operability:** for a new operational surface (job, queue, feature flag, alert), is there a runbook saying how to detect, diagnose, and remediate / roll back?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
