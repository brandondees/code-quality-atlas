# Reviewable heuristics — auditing-enforcement-and-meta-artifacts

## Contents

- From category #30

## From category #30

### Reviewable heuristics (skill-checklist seeds)

- **Blanket suppressions:** any file-wide or unscoped `/* eslint-disable */`, bare `# noqa`, bare `# type: ignore`, or `@ts-ignore` that disables *all* checks rather than a named rule? Flag to scope to the specific rule and justify — a blanket disable hides unrelated future violations at that location.
- **Unjustified suppressions:** does each suppression carry a reason (and ideally an issue link or expiry)? `# noqa: E501  # long external URL` is reviewable; a bare suppression with no rationale is undocumented debt.
- **Unused / stale suppressions:** are there suppressions for problems that no longer exist (ESLint unused-disable, Ruff `RUF100`, mypy `warn_unused_ignores`)? They mask the *next* real violation at that spot — remove them.
- **Baseline accretion:** is the lint/type baseline (detekt, lint-baseline.xml, bulk-suppressions) *growing* over time rather than shrinking? A ratchet must only tighten; a growing baseline is silent debt — track the count as a trend, not a point-in-time pass.
- **Alert actionability:** does every alert rule describe a user-visible **symptom** and link a runbook, or are there cause-based / noisy / unactionable alerts that train responders to ignore the pager? Alert on SLO burn, not raw resource gauges.
- **Monitoring drift & as-code parity:** are dashboards/monitors referencing metrics that were renamed or removed (dead panels giving false confidence)? Is monitoring defined **as code** (versioned, reviewable, restorable) rather than click-ops that silently drift?
- **Codegen freshness:** for checked-in generated/compiled artifacts (protobuf, OpenAPI clients, sqlc, ORM models, bundled assets), does CI regenerate and `git diff --exit-code` to prove they match their source — or can they silently drift from the generator/spec?
- **Generated-file provenance:** are generated files marked as generated (header / `linguist-generated`) and kept out of hand-editing, so the next regeneration doesn't clobber a manual patch?
- **Suppression density hotspots:** which files concentrate suppressions? A file full of disables is either genuinely hard (flag for refactor) or a place where enforcement is theater — name it.
- **Alert-rule sanity:** do rules have a `for:` duration, severity/labels, and thresholds tied to an SLO rather than arbitrary numbers? Run a rule linter (`pint` / `promtool`) over them as part of the audit.

---
