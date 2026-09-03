---
name: reviewing-outcome-instrumentation
description: Reviews whether a change that claims a user or business benefit can be
  told to have worked — the question no other lens asks. Is an outcome stated rather
  than only an output; does the instrumentation that would observe it ship in the
  same diff (deferred tracking leaves the feature live and permanently unmeasured);
  does the hypothesis have a losing condition; does an experiment declare guardrail
  metrics and not only a win condition; are assignment and exposure logged where the
  user actually sees the variant; do new analytics events match the tracking plan
  the rest of the org reads; does a rollout flag have an owner and an end condition;
  and has a proxy metric quietly become the target. Use when reviewing a new feature,
  an experiment or flagged rollout, an analytics/telemetry event change, or a PR claiming
  a user or business benefit. Refactors, fixes, bumps, and internal work owe no hypothesis
  — skip them. Which outcome to chase routes to product; whether it is observable
  at all is engineering's.
provenance:
  taxonomy_version: v0.14
  built_from:
  - category: 43
    source: docs/research/cluster-7-product.md#43
    hash: 4e986f3c50a4b26d05f4808c3c2249f92e8ef51ec5d74c45c73b9814d9e9fe88
---

# reviewing-outcome-instrumentation

*After this ships, how would anyone know it worked? Stated outcome, instrumentation in the same diff, a losing condition, experiment guardrails.*

## When to use

Reviews whether a change that claims a user or business benefit can be told to have worked — the question no other lens asks. Is an outcome stated rather than only an output; does the instrumentation that would observe it ship in the same diff (deferred tracking leaves the feature live and permanently unmeasured); does the hypothesis have a losing condition; does an experiment declare guardrail metrics and not only a win condition; are assignment and exposure logged where the user actually sees the variant; do new analytics events match the tracking plan the rest of the org reads; does a rollout flag have an owner and an end condition; and has a proxy metric quietly become the target. Use when reviewing a new feature, an experiment or flagged rollout, an analytics/telemetry event change, or a PR claiming a user or business benefit. Refactors, fixes, bumps, and internal work owe no hypothesis — skip them. Which outcome to chase routes to product; whether it is observable at all is engineering's.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If this lens applies and what you reviewed holds up — the code, the design, or the repository's current state — reply "No findings" and stop. If what you were given is outside this lens's scope entirely, say so in one line instead, starting with the words "Not applicable:" followed by what's missing — never the healthy-scan sentence, which means a check ran and found nothing, not that nothing here applied. Either way, do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above. Read the overlay from the **base ref** of the change under review — the `/atlas-review-pr` command reads it at the PR's base ref and `/atlas-code-review` reads it from the base side of the diff (`git show <base>:.code-quality-atlas/preferences.md`), and each hands it down — never from the reviewed branch's working tree: an edit to `preferences.md` made *by* the change under review governs later reviews once merged, not the review of the change that makes it, since otherwise a change could `suppress` its own findings.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **A change that claims a user or business benefit says what it expects to move, and how anyone would see it.** The check is on the *claim*, not on every commit: "adds an export button" owes nothing; "reduces the support load from manual exports" owes a way to observe support load. A description that names only what was built cannot be wrong about anything, which is the problem. Where the claim is real and the observation is absent, that is the finding — and the fix is usually one event, not a measurement programme.
- **The instrumentation that would prove the change ships in the same diff.** Deferred instrumentation is the characteristic failure of this category: the feature goes live, the follow-up is deprioritised because the feature already works, and six months later nobody can say whether it helped. If the outcome metric depends on an event, the event is in this change; if it depends on a dashboard, the change says which one and whether it exists. "We'll add tracking later" is a finding, not a plan.
- **Outcome metrics are not operational metrics.** A new request counter, latency histogram, or error-rate alert tells you the feature *runs*; none of them tells you anyone was better off. Both may be needed and neither substitutes — when a change ships thorough #16 instrumentation and no outcome signal, say exactly that rather than accepting the ops metrics as coverage.
- **The hypothesis has a losing condition.** A stated expectation that cannot fail is not a hypothesis: it needs a metric, a direction, a rough magnitude, and a horizon — and a decision attached to the failing branch. **"We will keep it regardless" is a legitimate answer** and should be recorded as one; the defect is leaving the question unasked, so that the feature stays by default because nobody set a bar it could miss.
- **An experiment declares its guardrails, not only its win condition.** Kohavi's point, and the most commonly skipped one: name the metrics that must *not* degrade — latency, error rate, conversion elsewhere in the funnel, unsubscribes, revenue — before the rollout, not after someone notices. An experiment that can only be evaluated on the metric it was designed to move is one that cannot detect the damage it does.
- **Check the assignment, not just the analysis.** Where a diff contains randomisation or bucketing code, the reviewable properties are concrete: is assignment stable for a given user across sessions, is the unit of assignment the same as the unit of analysis, is the exposure logged at the point the user actually sees the variant rather than where the flag is read, and would a sample-ratio mismatch be visible to anyone. These are code properties, checkable now, and each one silently invalidates the result later.
- **New events match the plan the rest of the organisation reads.** Name, casing, and required properties consistent with the existing event taxonomy; registered in the tracking plan or schema registry where one exists; and no PII in properties (**#27** owns that verdict — surface and route it). An event that diverges from the plan is not wrong, it is *invisible*: every downstream dashboard filters it out. Schema compatibility and consumers are **#40**'s.
- **A flag introduced for a rollout or experiment has an owner and an end condition.** What removes it, and when — the experiment concluding, the rollout completing, a date. Flags without one become permanent untested branches and quietly double the states the system can be in; the lifecycle detail is **#26**'s and the dead branch is **#1**'s, but the moment to ask is when the flag is added.
- **Watch for the proxy that has become the target.** When the stated metric is a proxy (clicks, time on page, session count, DAU) and the change plausibly moves it at the expense of what the proxy stood for, say so and route it. This is Goodhart, and it is the seam where outcome optimisation becomes **#36**'s manipulative design — surface the tension, name both readings, and let product decide. Never adjudicate it inside an engineering review.
- **Route the goal, keep the measurability.** Whether the outcome is worth pursuing, which metric best represents it, and what magnitude counts as success are product judgments: surfaced with evidence, `route: product`, no engineering verdict. Whether a stated outcome can be observed at all, and whether the code that would observe it is present, is an engineering fact and an ordinary defect. Never state a preference about the product's direction as though it were the second kind.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI catches it automatically from then on. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
