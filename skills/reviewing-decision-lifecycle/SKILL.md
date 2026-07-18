---
name: reviewing-decision-lifecycle
description: 'Reviews a decision as it is made — an ADR, RFC, design doc, adoption
  PR, or deprecation/rollout plan — rather than the code that implements it: is the
  choice (dependency, framework, platform, build-vs-buy) justified against cheaper
  options; is lock-in and exit cost assessed; is the rationale and its assumptions
  recorded with a revisit-trigger; is retirement planned on a schedule with a sunset
  date and migration path. Use when reviewing an architecture decision record, an
  RFC, a dependency or technology adoption, a vendor or build-vs-buy choice, or a
  deprecation/sunset plan.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 29
    source: docs/research/cluster-6-evolution.md#29
    hash: e82ed355ddc199ee5a8f523e7511931d289b8b063c03023baac0fa6ac1f62a3b
---

# reviewing-decision-lifecycle

*Is this decision sound and recorded? Adoption justification, lock-in/exit, ADR assumptions, revisit-triggers, planned retirement.*

## When to use

Reviews a decision as it is made — an ADR, RFC, design doc, adoption PR, or deprecation/rollout plan — rather than the code that implements it: is the choice (dependency, framework, platform, build-vs-buy) justified against cheaper options; is lock-in and exit cost assessed; is the rationale and its assumptions recorded with a revisit-trigger; is retirement planned on a schedule with a sunset date and migration path. Use when reviewing an architecture decision record, an RFC, a dependency or technology adoption, a vendor or build-vs-buy choice, or a deprecation/sunset plan.

**Shape: decision.** Reviewed at decision time — an ADR, RFC, design doc, adoption PR, or deprecation/rollout plan — not a diff of implementation code. Apply the checks to the decision and its record (rationale, assumptions, alternatives, exit/rollback), not to lines of code.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Adoption justification recorded:** for a new dependency / framework / platform, is there a rationale weighed against the cheaper options (stdlib, a few lines, an existing in-house capability, a smaller library)? "We need X" is not a justification; an evaluated A/B/build comparison is.
- **Right-sizing (build-vs-buy):** does the chosen option's weight match the need? A 40-dependency framework for one screen, or a hand-rolled implementation where a maintained library exists, both warrant a second look (cross #11 restraint, #18 deps).
- **Lock-in & exit cost assessed:** is the cost of *leaving* considered — is data exportable, is the integration behind a portable boundary/adapter, or is this a one-way door into proprietary surface that's expensive to reverse?
- **Reversibility matched to scrutiny:** is this a two-way door (cheap to undo → decide fast) or a one-way door (expensive to undo → demand a recorded decision and an exit plan)? Flag heavy process on trivial reversible calls, and casual adoption of irreversible ones.
- **Decision record present & complete:** for a non-obvious choice, is there an ADR capturing context, options considered, decision, and consequences — the *why*, not just the *what*?
- **Assumptions stated and still valid:** does the decision name the assumptions it rests on (load, team size, vendor support, scale)? On revisit, do they still hold — or has a premise expired, making the decision stale debt?
- **Revisit-triggers named:** does the record state the conditions that should reopen it ("revisit if write volume > 10k/s"; "if the vendor drops Kafka")? A decision with no trigger rots silently.
- **Retirement planned on a schedule:** when something is deprecated, is removal *planned and clocked* — a `Deprecation`/`Sunset` header or `deprecated` marker, a sunset date, a consumer-migration path, and a tracked removal ticket — rather than left to surface later as dead code (cross #1, #13)?

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
