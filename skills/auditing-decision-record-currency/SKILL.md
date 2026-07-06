---
name: auditing-decision-record-currency
description: 'Audits the decision records already in a repository (ADRs/RFCs on disk),
  on a schedule rather than at authoring time: status-graph consistency (an accepted
  record contradicted by a later one with no supersedes link, or a decision the code
  has visibly reversed), a revisit-trigger whose stated condition current repo signals
  suggest may now hold, a record with no checkable revisit-trigger at all, an adopted
  technology now end-of-life or on hold with no revisit noted, and orphaned records
  nothing in the repo still implements. Detects and routes revisit signals to the
  decision''s owner rather than reversing the call itself. A repo-wide / scheduled
  audit — the periodic-currency companion to reviewing-decision-lifecycle''s authoring-time
  review. Use when auditing an ADR directory, a decisions/RFC archive, or a whole-repo
  health scan.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 39
    source: docs/research/cluster-6-evolution.md#39
    hash: 18744a28ce80a74fdac4c5ff320e9afc2f78b772d5f0401ddce88bd4051ea487
---

# auditing-decision-record-currency

*Do the repo's existing decision records still hold? Status-graph consistency, revisit-triggers due, EOL adoptions, orphaned records.*

## When to use

Audits the decision records already in a repository (ADRs/RFCs on disk), on a schedule rather than at authoring time: status-graph consistency (an accepted record contradicted by a later one with no supersedes link, or a decision the code has visibly reversed), a revisit-trigger whose stated condition current repo signals suggest may now hold, a record with no checkable revisit-trigger at all, an adopted technology now end-of-life or on hold with no revisit noted, and orphaned records nothing in the repo still implements. Detects and routes revisit signals to the decision's owner rather than reversing the call itself. A repo-wide / scheduled audit — the periodic-currency companion to reviewing-decision-lifecycle's authoring-time review. Use when auditing an ADR directory, a decisions/RFC archive, or a whole-repo health scan.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Status-graph consistency:** does any decision record's status contradict another's — two `accepted` records making incompatible choices with no `supersedes`/`superseded-by` link between them — or is a record marked `accepted` for a choice the codebase has visibly reversed (the named technology is no longer a dependency, no longer referenced in config/infra)?
- **Revisit-trigger condition plausibly met:** where a record names a concrete, checkable revisit condition (a scale threshold, a team-size figure, a vendor-support date), does anything visible in the repo (config, infra manifests, dependency graph, `CODEOWNERS` size) suggest that condition may now hold — flagged as "revisit due," not resolved unilaterally?
- **No checkable revisit-trigger recorded:** does the record state only a vague "revisit periodically" with no date or measurable condition — the base case the sweep can't check further, worth flagging once per record rather than silently skipping?
- **Adopted technology now EOL or on Hold:** does a record's chosen dependency/framework/platform appear on an end-of-life feed, or would the adoption read as `Hold` on a technology-radar-style scale today, with no revisit noted since?
- **Orphaned or contradicted record:** is a decision record referenced by nothing else in the repo (no code, config, or doc still implements what it decided) and left `accepted` rather than marked `superseded`/`deprecated` — a stale entry cluttering the log worse than an absent one (per Azure Well-Architected's framing)?
- **Escalate the judgment call, don't resolve it:** a plausibly-met revisit-trigger or an EOL adoption is evidence a human should re-open the decision, not a verdict that the original choice was wrong — report the signal and route to the decision's owner (cross #29, the G8 boundary), never assert the ADR should be reversed.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
