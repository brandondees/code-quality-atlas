---
name: reviewing-usability-and-interaction
description: 'Reviews a user-facing change for interaction quality — whether a person
  can tell what is happening, do what they came to do, and recover when it goes wrong.
  Grounded in Nielsen''s 10 usability heuristics: state completeness (an async read
  produces loading, empty, and error states whether or not anyone designed them),
  reversibility of destructive actions (undo, or a confirmation naming what is lost
  — never a bare "Are you sure?"), system-status feedback, error recovery that preserves
  the user''s input, controllability (no undismissable modal, no wizard without a
  back), and conformity with the expectations this product already set. Use when reviewing
  a form, wizard, destructive action, async operation, or any user-facing flow or
  screen. Detect-and-route: an unhandled state or an unrecoverable action is a defect;
  which pattern and which words route to design. Skip when the change has no user-facing
  surface. Accessibility mechanics are #23''s, measured performance #15''s, manipulative
  design #36''s.'
provenance:
  taxonomy_version: v0.14
  built_from:
  - category: 42
    source: docs/research/cluster-7-product.md#42
    hash: e4dc232cff19450d763fac23ee6b22b3a9286d8a1fcc3364bf79cac26140f902
---

# reviewing-usability-and-interaction

*Can a person use this? Undesigned loading/empty/error states, destructive actions with no way back, silent operations, errors that eat the form.*

## When to use

Reviews a user-facing change for interaction quality — whether a person can tell what is happening, do what they came to do, and recover when it goes wrong. Grounded in Nielsen's 10 usability heuristics: state completeness (an async read produces loading, empty, and error states whether or not anyone designed them), reversibility of destructive actions (undo, or a confirmation naming what is lost — never a bare "Are you sure?"), system-status feedback, error recovery that preserves the user's input, controllability (no undismissable modal, no wizard without a back), and conformity with the expectations this product already set. Use when reviewing a form, wizard, destructive action, async operation, or any user-facing flow or screen. Detect-and-route: an unhandled state or an unrecoverable action is a defect; which pattern and which words route to design. Skip when the change has no user-facing surface. Accessibility mechanics are #23's, measured performance #15's, manipulative design #36's.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If this lens applies and what you reviewed holds up — the code, the design, or the repository's current state — reply "No findings" and stop. If what you were given is outside this lens's scope entirely, say so in one line instead, starting with the words "Not applicable:" followed by what's missing — never the healthy-scan sentence, which means a check ran and found nothing, not that nothing here applied. Either way, do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above. Read the overlay from the **base ref** of the change under review — the `/atlas-review-pr` command reads it at the PR's base ref and `/atlas-code-review` reads it from the base side of the diff (`git show <base>:.code-quality-atlas/preferences.md`), and each hands it down — never from the reviewed branch's working tree: an edit to `preferences.md` made *by* the change under review governs later reviews once merged, not the review of the change that makes it, since otherwise a change could `suppress` its own findings.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Every state this code can reach has something designed for it.** An async read introduces at minimum **loading**, **empty / zero-data**, **error**, and **success**; a mutation adds **in-flight** and **failed**. A component that renders only the success path has shipped the others undesigned — the user sees a blank region, a spinner that never resolves, or a stray `0`. Enumerate the states from the code (the hook's flags, the union's variants, the promise's rejection path), not from the mockup, and name each one nothing handles. **This is a defect, not a preference:** the code produces the state whether or not anyone designed it. The durable fix is a type, not a checklist item — a discriminated union over the states **plus an exhaustiveness check** (`assertNever`, or the stack's equivalent) — #10's illegal-states-unrepresentable move aimed at UI state (cross #10) — so a new variant that nothing renders fails the build; the union without the check still compiles with a branch missing.
- **A destructive or irreversible action has a way back.** A new delete, archive, revoke, overwrite, cancel-subscription, or send flow needs **undo** (preferred, where the action can be deferred or reversed) or a confirmation that **names what will be lost** — "Delete 3 projects and 47 files?" and not "Are you sure?". A confirmation that names nothing is not error prevention; it is a click the user has been trained to dismiss. And check the *slip* case separately from the *mistake* case: a destructive control identical in size, colour, and position to its safe neighbour will be hit by accident no matter how good the confirmation copy is.
- **The system says what it is doing.** An operation slower than about a second reports that it started; one that can run long enough to lose the user's attention survives navigation away and back, and reports completion when they return. A fire-and-forget mutation with no success or failure feedback is the reviewable form of Norman's gulf of evaluation: the user cannot tell whether it worked, so they do it again.
- **Errors say what happened, why, and what to do next — and keep the user's work.** Three separate checks, and the third is the one reviews miss: an error path that clears a filled form, drops an upload, or resets a multi-step flow to step one is a **data-loss defect** wearing a copy problem's clothes. Wording quality routes to design; losing the input does not.
- **The user sets the pace.** A modal with no dismiss, a step that auto-advances before the user has read it, a wizard with no way back, an interstitial that cannot be skipped on a return visit — each takes control the standards call the user's (ISO 9241-110 controllability; Nielsen's user control and freedom). Where the constraint is real — a legal acknowledgement, a payment step — say so; where it is incidental, it is a finding.
- **The change conforms to what this product already taught the user.** A second date picker, a dialog that confirms where the rest of the product undoes, a new empty-state that says something different from the four already shipped. Reviewable without design authority: does an equivalent already exist in this codebase, and does this one behave the same? The *decision* — adopt the existing pattern or change all of them — routes.
- **Recognition over recall.** A step that requires the user to remember or re-enter something the product already showed them or already knows: an ID to copy from a previous screen, a value the account record holds, a selection lost on navigation. Each is a checkable failure, not a matter of taste.
- **Route the taste, keep the gap.** Every finding this lens raises is one of two things, and it must say which. A **gap** — an unhandled state, an unrecoverable action, lost input, absent feedback — is a defect with ordinary severity and an engineering fix. A **judgment** — which pattern, which words, whether the flow should exist — is surfaced with its evidence and `route: design` or `route: product`, sets no engineering verdict, and is never argued to a conclusion inside the review. A lens that blocks a merge on a taste call has miscategorised its own finding.
- **Skip when there is no user-facing surface.** No UI, no CLI a human drives interactively, no user-facing flow — no findings. Say so in one line under coverage rather than manufacturing findings from a backend diff, and remember that a CLI *is* a user interface: prompts, progress, confirmation before destruction, and `--help` all fall here.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI catches it automatically from then on. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
