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
    hash: ef5524f6b86410b40675952273e78597c8a0fc5d94ea821f67059064c6624c6c
---

# auditing-enforcement-and-meta-artifacts

*Is the enforcement apparatus healthy? Suppression hygiene & baseline trend, actionable alerts/monitoring-as-code, codegen-source drift gate.*

## When to use

Audits the enforcement apparatus and meta-artifacts wrapped around the code, as their own reviewable surface: suppression hygiene (blanket or unjustified `# noqa` / `eslint-disable` / `# type: ignore`, unused/stale suppressions, a lint or type baseline growing rather than shrinking), monitoring config as an artifact (cause-based or unactionable alerts, alert rules with no runbook or `for:` duration, dashboards referencing renamed/dead metrics, click-ops that drift instead of monitoring-as-code), and codegen-to-source drift (checked-in generated artifacts that can silently diverge from their generator/spec with no regenerate-and-diff gate in CI). A repo-wide / scheduled audit rather than a single-diff review. Use when auditing lint/type suppressions, alert rules, dashboards, or checked-in generated code.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Blanket suppressions:** any file-wide or unscoped `/* eslint-disable */`, bare `# noqa`, bare `# type: ignore`, or `@ts-ignore` that disables *all* checks rather than a named rule? Flag to scope to the specific rule and justify — a blanket disable hides unrelated future violations at that location.
- **Unjustified suppressions:** does each suppression carry a reason (and ideally an issue link or expiry)? `# noqa: E501  # long external URL` is reviewable; a bare suppression with no rationale is undocumented debt.
- **Unused / stale suppressions:** are there suppressions for problems that no longer exist (ESLint unused-disable, Ruff `RUF100`, mypy `warn_unused_ignores`)? They mask the *next* real violation at that spot — remove them.
- **Baseline accretion:** is the lint/type baseline (detekt, lint-baseline.xml, bulk-suppressions) *growing* over time rather than shrinking? A ratchet must only tighten; a growing baseline is silent debt — track the count as a trend, not a point-in-time pass.
- **Alert actionability:** does every alert rule describe a user-visible **symptom** and link a runbook, or are there cause-based / noisy / unactionable alerts that train responders to ignore the pager? Alert on SLO burn, not raw resource gauges.
- **Monitoring drift & as-code parity:** are dashboards/monitors referencing metrics that were renamed or removed (dead panels giving false confidence)? Is monitoring defined **as code** (versioned, reviewable, restorable) rather than click-ops that silently drift?
- **Codegen freshness:** for checked-in generated/compiled artifacts (protobuf, OpenAPI clients, sqlc, ORM models, bundled assets), does CI regenerate and `git diff --exit-code` to prove they match their source — or can they silently drift from the generator/spec?
- **Generated-file provenance:** are generated files marked as generated (header / `linguist-generated`) and kept out of hand-editing, so the next regeneration doesn't clobber a manual patch?

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
