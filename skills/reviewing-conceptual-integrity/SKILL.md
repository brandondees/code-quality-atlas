---
name: reviewing-conceptual-integrity
description: 'Reviews whether a change fits one coherent model of what the product
  is — Brooks''s conceptual integrity, the product counterweight to sprawl. Checks
  for a new user-facing concept duplicating one the product already has (two nouns
  for one idea), a second path to a job it already does, a rule it already enforces
  that this change breaks without saying so, one term with two meanings across UI
  copy/docs/API fields, a special case carved into a general rule, and the Nth option
  on a surface with no governing idea. Use when reviewing a change that adds a user-facing
  concept, entity, mode, page, command, endpoint, or setting — or a design doc proposing
  one. Requires evidence: name the existing concept or report nothing. Whether the
  concept should exist and what to call it route to product; a broken promise the
  product already made is a defect. Skip changes introducing no user-facing concept.
  Amount-of-surface is #11''s, interaction mechanics #42''s, code-level consistency
  #8''s.'
provenance:
  taxonomy_version: v0.14
  built_from:
  - category: 44
    source: docs/research/cluster-7-product.md#44
    hash: 52efbd89dd139e4466abe3a41ff777815fe1892bd376c91c748796358c368220
---

# reviewing-conceptual-integrity

*Does the product still say one thing? A second noun for an existing idea, a second path to the same job, a rule this change quietly breaks.*

## When to use

Reviews whether a change fits one coherent model of what the product is — Brooks's conceptual integrity, the product counterweight to sprawl. Checks for a new user-facing concept duplicating one the product already has (two nouns for one idea), a second path to a job it already does, a rule it already enforces that this change breaks without saying so, one term with two meanings across UI copy/docs/API fields, a special case carved into a general rule, and the Nth option on a surface with no governing idea. Use when reviewing a change that adds a user-facing concept, entity, mode, page, command, endpoint, or setting — or a design doc proposing one. Requires evidence: name the existing concept or report nothing. Whether the concept should exist and what to call it route to product; a broken promise the product already made is a defect. Skip changes introducing no user-facing concept. Amount-of-surface is #11's, interaction mechanics #42's, code-level consistency #8's.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If this lens applies and what you reviewed holds up — the code, the design, or the repository's current state — reply "No findings" and stop. If what you were given is outside this lens's scope entirely, say so in one line instead, starting with the words "Not applicable:" followed by what's missing — never the healthy-scan sentence, which means a check ran and found nothing, not that nothing here applied. Either way, do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above. Read the overlay from the **base ref** of the change under review (the `/atlas-review-pr` command resolves it there and hands it down; in a local review, the copy committed on the branch the change will merge into) — never from the reviewed branch's working tree: an edit to `preferences.md` made *by* the change under review governs later reviews once merged, not the review of the change that makes it, since otherwise a change could `suppress` its own findings.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **A new user-facing concept either earns its place or reuses one that already exists.** When a change introduces a noun a user must learn — an entity, a mode, a status, a container — name it, then find whether the product already has one covering the job. **Evidence is required before reporting anything:** the existing concept, where it lives, and the one-sentence rule a user would apply to choose between them. If you cannot state that rule, that *is* the finding — and if you cannot name an existing concept at all, there is no finding, because a genuinely new idea filling a real gap is not a defect for being new.
- **A second path to a job the product already does.** Distinct from a second *widget* (`#42`'s): a new page, command, endpoint, or setting that reaches an outcome the product already reaches, with nothing retiring or subsuming the old one. The reviewable fact is narrow and checkable — both now exist, and the change says nothing about the relationship. Whether to unify them is product's call and routes; that the review found two is not a matter of opinion.
- **A rule the product already enforces still holds — or the change says why not.** This is the defect half and the only place this lens sets an engineering verdict. Every other resource of this kind cascades on delete and this one orphans children; every other collection paginates one way and this one invents another; every other object is archivable and this one silently is not. A user or a consumer generalizes from what they have already seen, so an unannounced exception is a broken promise with ordinary severity, not a preference.
- **One term, one meaning — inside a named context.** The same idea under two names, or one name covering two ideas, across UI copy, docs, API fields, and events. Evans's ubiquitous language is the standard; Evans's bounded context is the discipline that keeps it from over-firing, so a term that differs across a boundary the product genuinely has (billing's "account" versus auth's "account") is not a finding unless the boundary is invisible to the user. Name the context, or drop the objection.
- **The change is explainable in vocabulary the product already uses — *once the gate above has found an overlap*.** A practical proxy for duplication, not an independent tax on novelty: write the one-sentence release note, and if it can only be written by first teaching the reader when to use the new concept **instead of the existing one**, that choice is a real cost the product now carries forever — say so and route it. **This check does not fire on its own.** A genuinely new concept that cleared the gate needs a new word in its release note by definition, and that is not a finding; treating it as one would convict exactly the case the gate exists to clear. A *cost to state* when duplication is already established, never a veto and never a standalone trigger.
- **A special case carved into a general rule doubles what the user must remember.** "Everything can be shared, except reports" is sometimes exactly right and sometimes an implementation constraint that leaked into the model. Require the reason; route the resolution.
- **Second-system watch: what is the N, and what governs it?** For a change adding the Nth option, mode, flag, or entry point to a surface, count what is already there and ask whether a governing idea decides what belongs — or whether each addition was justified only against the one before it. This is Brooks's second-system effect made countable, and it is where this lens most often *agrees* with `checking-restraint` rather than competing with it. Report it once, under whichever lens's evidence is stronger.
- **Route the model, keep the contradiction.** Same split as the rest of the cluster, and it is what makes this lens usable: a **contradiction** with a rule the product already enforces is a defect with ordinary severity and an engineering fix. A **judgment** — whether the concept should exist, what to call it, whether to unify or accept two — is surfaced with its evidence, routed to product or design, and never argued to a conclusion inside the review. A lens that blocks a merge on coherence alone has miscategorised its own finding.
- **Skip when the change introduces no user-facing concept.** An internal refactor, a dependency bump, infrastructure, or a bug fix that changes no vocabulary and adds no surface has nothing here. Say the lens did not apply, in one line. This lens firing on every diff is the failure mode that gets it muted, and it is more likely than the incoherence it guards against.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI catches it automatically from then on. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
