---
name: auditing-enforcement-and-meta-artifacts
description: 'Audits the enforcement apparatus and meta-artifacts wrapped around the
  code, as their own reviewable surface: suppression hygiene (blanket or unjustified
  `# noqa` / `eslint-disable` / `# type: ignore`, unused/stale suppressions, a lint
  or type baseline growing rather than shrinking), monitoring config as an artifact
  (cause-based or unactionable alerts, alert rules with no runbook or `for:` duration,
  dashboards referencing renamed/dead metrics, click-ops that drift instead of monitoring-as-code),
  and codegen-to-source drift (checked-in generated artifacts that can silently diverge
  from their generator/spec with no regenerate-and-diff gate in CI). A repo-wide /
  scheduled audit rather than a single-diff review. Use when auditing lint/type suppressions,
  alert rules, dashboards, or checked-in generated code.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 30
    source: docs/research/cluster-5-verification.md#30
    hash: b9db9c469aa7757488cd49121c5053d31b766f3eef5c1b78070853fa05578e12
---

# auditing-enforcement-and-meta-artifacts

## When to use

Audits the enforcement apparatus and meta-artifacts wrapped around the code, as their own reviewable surface: suppression hygiene (blanket or unjustified `# noqa` / `eslint-disable` / `# type: ignore`, unused/stale suppressions, a lint or type baseline growing rather than shrinking), monitoring config as an artifact (cause-based or unactionable alerts, alert rules with no runbook or `for:` duration, dashboards referencing renamed/dead metrics, click-ops that drift instead of monitoring-as-code), and codegen-to-source drift (checked-in generated artifacts that can silently diverge from their generator/spec with no regenerate-and-diff gate in CI). A repo-wide / scheduled audit rather than a single-diff review. Use when auditing lint/type suppressions, alert rules, dashboards, or checked-in generated code.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Blanket suppressions:** any file-wide or unscoped `/* eslint-disable */`, bare `# noqa`, bare `# type: ignore`, or `@ts-ignore` that disables *all* checks rather than a named rule? Flag to scope to the specific rule and justify — a blanket disable hides unrelated future violations at that location.
- **Unjustified suppressions:** does each suppression carry a reason (and ideally an issue link or expiry)? `# noqa: E501  # long external URL` is reviewable; a bare suppression with no rationale is undocumented debt.
- **Unused / stale suppressions:** are there suppressions for problems that no longer exist (ESLint unused-disable, Ruff `RUF100`, mypy `warn_unused_ignores`)? They mask the *next* real violation at that spot — remove them.
- **Baseline accretion:** is the lint/type baseline (detekt, lint-baseline.xml, bulk-suppressions) *growing* over time rather than shrinking? A ratchet must only tighten; a growing baseline is silent debt — track the count as a trend, not a point-in-time pass.
- **Suppression density hotspots:** which files concentrate suppressions? A file full of disables is either genuinely hard (flag for refactor) or a place where enforcement is theater — name it.
- **Alert actionability:** does every alert rule describe a user-visible **symptom** and link a runbook, or are there cause-based / noisy / unactionable alerts that train responders to ignore the pager? Alert on SLO burn, not raw resource gauges.
- **Alert-rule sanity:** do rules have a `for:` duration, severity/labels, and thresholds tied to an SLO rather than arbitrary numbers? Run a rule linter (`pint` / `promtool`) over them as part of the audit.
- **Monitoring drift & as-code parity:** are dashboards/monitors referencing metrics that were renamed or removed (dead panels giving false confidence)? Is monitoring defined **as code** (versioned, reviewable, restorable) rather than click-ops that silently drift?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
