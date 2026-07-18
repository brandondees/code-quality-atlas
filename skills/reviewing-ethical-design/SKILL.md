---
name: reviewing-ethical-design
description: 'Reviews a change for diff-visible, code-level ethical / responsible-design
  defects — the non-ML analog of harmful-output review, a sibling of security (harm
  to the user/subject, not via an attacker): dark patterns and deceptive flows (sneaking,
  fabricated urgency/scarcity, misdirection/confirmshaming, obstruction, forced action,
  nagging), manipulative defaults and asymmetric choices (pre-checked consent, opt-out
  harder than opt-in, auto-renew), discriminatory business logic in plain conditionals
  (a hardcoded threshold or proxy disadvantaging a group, no model in sight), dishonest
  state/signals, and consent theater. Strictly detect-and-route: name the pattern
  with evidence, then route the decision — consent-as-law to #27/legal, product trade-offs
  to product, a11y mechanics to #23. Use when reviewing consent/opt-out flows, defaults,
  pricing/eligibility conditionals, or onboarding/checkout/cancellation funnels. Skip
  internal code with no user-facing behavior; deep model-fairness auditing is out
  of scope.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 36
    source: docs/research/cluster-4-runtime.md#36
    hash: c454ac4bb51dff97993fa5759ac150755d28d20daecfda0b4675599482c03815
---

# reviewing-ethical-design

*Does this manipulate or disadvantage the user? Dark patterns, manipulative defaults, discriminatory conditionals — detect-and-route to product/legal.*

## When to use

Reviews a change for diff-visible, code-level ethical / responsible-design defects — the non-ML analog of harmful-output review, a sibling of security (harm to the user/subject, not via an attacker): dark patterns and deceptive flows (sneaking, fabricated urgency/scarcity, misdirection/confirmshaming, obstruction, forced action, nagging), manipulative defaults and asymmetric choices (pre-checked consent, opt-out harder than opt-in, auto-renew), discriminatory business logic in plain conditionals (a hardcoded threshold or proxy disadvantaging a group, no model in sight), dishonest state/signals, and consent theater. Strictly detect-and-route: name the pattern with evidence, then route the decision — consent-as-law to #27/legal, product trade-offs to product, a11y mechanics to #23. Use when reviewing consent/opt-out flows, defaults, pricing/eligibility conditionals, or onboarding/checkout/cancellation funnels. Skip internal code with no user-facing behavior; deep model-fairness auditing is out of scope.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Dark pattern / deceptive flow (detect-and-route):** Does the change introduce a recognized dark pattern — **sneaking** (hidden costs, sneak-into-basket), **fabricated urgency/scarcity** (a countdown or "only 2 left" not backed by truth), **misdirection / confirmshaming**, **obstruction** (roach-motel cancel), **forced action**, or **nagging** (Mathur's 7 / the EDPB's 6 families)? Name the specific category and cite the code that implements it; route the keep-or-kill product judgment to `product` and any consent-law facet to #27 / `legal`. Surface with evidence — never decide the product trade-off here, never drop it either.
- **Manipulative defaults & asymmetric choices:** Are defaults set to benefit the business against the user's likely intent — **pre-checked** consent / marketing opt-in, opt-out materially harder than opt-in, "accept all" prominent while "reject" is buried or absent, negative-option / auto-renew with no clear disclosure? The default value and the *asymmetry of the choice* are the defect, visible right in the code that sets them.
- **Discriminatory business logic in plain conditionals:** Does a hardcoded threshold, branch, or rule disadvantage a protected or vulnerable group with **no model in sight** — pricing / eligibility / scoring keyed (directly, or by proxy: ZIP, surname, device, locale) on a protected attribute, or a cutoff with a foreseeable disparate effect? Flag the conditional with evidence; route the legal/fairness adjudication to #27 / `legal` and the policy call to `product` / `leadership`. (Deep dataset/metric fairness auditing is out of scope — no diff artifact.)
- **Honest state & truthful signals:** Do the user-facing claims the code emits match reality — a "secure" / "private" / "deleted" label for data that isn't, a **fabricated** progress bar / "N people are viewing this" / fake low-stock, or a synthetic error/system message engineered to drive a choice? A signal the code knows to be false is a defect regardless of product intent.
- **Consent & opt-out actually wired (not theater):** When the change gates behavior on consent, does *declining* actually stop the behavior rather than just hide a toggle, and is **withdrawal as easy as granting** (GDPR Art. 7(3))? Consent theater — a dialog whose "no" path still proceeds — is the defect; the consent-as-law verdict routes to #27.
- **Asymmetric friction (obstruction vs. protection):** Is the user-favorable path (cancel, unsubscribe, delete account, export data) made disproportionately harder than the business-favorable one (sign up, buy, opt in)? Distinguish **obstruction** (friction that serves the business against the user's clear intent) from **legitimate protective friction** (a confirmation on a destructive action, step-up auth, a cooling-off period) — route the protective-control side to #14 / `sweeping-for-security`; obstruction stays a finding here.
- **Coercion / pressure in control flow:** Does the flow block or repeatedly push toward the "preferred" choice — interstitials with no genuine dismiss, re-prompts after a clear "no," a continue button disabled until an upsell is taken, confirmshaming microcopy? Pressure engineered into ordinary control flow is reviewable code, not just visual design.
- **Vulnerable-user & high-stakes context:** For flows touching minors, health, finance, or addiction-adjacent mechanics (loot boxes, variable-reward infinite scroll, streak pressure), is there heightened care rather than the same growth-optimized defaults? Surface for `product` / `legal` with evidence; the bar is higher and the defaults that pass elsewhere may not pass here.
- **Accessibility-as-exclusion (xref #23):** Is an ethical harm delivered *through* an accessibility gap — the consent or cancel control operable only by sighted/mouse users, or contrast/affordance used to hide the user-favorable option while surfacing the business-favorable one? Route the a11y mechanics to #23; the deceptive intent is owned here.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
