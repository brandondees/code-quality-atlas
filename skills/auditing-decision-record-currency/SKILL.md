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
  health scan. Skip when the repo has no decision-record directory or archive at all.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 39
    source: docs/research/cluster-6-evolution.md#39
    hash: 671362ba00b61ca6e5956c293bc0befef32384fb72b299045b6cd6e1ad934e56
---

# auditing-decision-record-currency

*Do the repo's existing decision records still hold? Status-graph consistency, revisit-triggers due, EOL adoptions, orphaned records.*

## When to use

Audits the decision records already in a repository (ADRs/RFCs on disk), on a schedule rather than at authoring time: status-graph consistency (an accepted record contradicted by a later one with no supersedes link, or a decision the code has visibly reversed), a revisit-trigger whose stated condition current repo signals suggest may now hold, a record with no checkable revisit-trigger at all, an adopted technology now end-of-life or on hold with no revisit noted, and orphaned records nothing in the repo still implements. Detects and routes revisit signals to the decision's owner rather than reversing the call itself. A repo-wide / scheduled audit — the periodic-currency companion to reviewing-decision-lifecycle's authoring-time review. Use when auditing an ADR directory, a decisions/RFC archive, or a whole-repo health scan. Skip when the repo has no decision-record directory or archive at all.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Status-graph consistency:** does any decision record's status contradict another's — two `accepted` records making incompatible choices with no `supersedes`/`superseded-by` link between them — or is a record marked `accepted` for a choice the codebase has visibly reversed (the named technology is no longer a dependency, no longer referenced in config/infra)?
- **Revisit-trigger condition plausibly met:** where a record names a concrete, checkable revisit condition (a scale threshold, a team-size figure, a vendor-support date), does anything visible in the repo (config, infra manifests, dependency graph, `CODEOWNERS` size) suggest that condition may now hold — flagged as "revisit due," not resolved unilaterally?
- **No checkable revisit-trigger recorded:** does the record state only a vague "revisit periodically" with no date or measurable condition — the base case the sweep can't check further, worth flagging once per record rather than silently skipping?
- **Adopted technology now EOL or on Hold:** does a record's chosen dependency/framework/platform appear on an end-of-life feed, or would the adoption read as `Hold` on a technology-radar-style scale today, with no revisit noted since?
- **Orphaned or contradicted record:** is a decision record referenced by nothing else in the repo (no code, config, or doc still implements what it decided) and left `accepted` rather than marked `superseded`/`deprecated` — a stale entry cluttering the log worse than an absent one?
- **Stalled proposed record:** is a record left in `proposed` status for a long time with no resolution — neither accepted nor rejected — while downstream work proceeds as though it were settled? A decision that never closes is its own currency defect, distinct from an accepted one going stale.
- **Duplicate or conflicting record identifiers:** do two records share the same ID, or does the archive's own index/table-of-contents omit a file present on disk? A drifted index means the sweep itself may be walking an incomplete set — surface it as a scan-reliability finding, not a decision-content one.
- **Silent supersession (naming-only, no cross-reference):** does a newer record's title/content clearly replace an older one's subject, but neither carries a `supersedes`/`superseded-by` field linking them — a convention followed in spirit but not in the machine-checkable field the rest of this sweep depends on?

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
