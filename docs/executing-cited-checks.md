# Executing cited checks: forcing the atlas to *apply* the rule it names

**Status: Phase 1 shipped (2026-09-01, owner-approved); Phase 2 still owner-gated.**
Resolved the *shape* of a fix for [`open-questions.md`](open-questions.md) **Q22**
on 2026-08-22; the owner then approved Phase 1 for build. See
[`plans/2026-09-01-executing-cited-checks-phase1.md`](plans/2026-09-01-executing-cited-checks-phase1.md)
for what shipped (M1, the standing-dispute check, in `synthesizing-review-findings`,
plus 3 meta-review eval scenarios). Phase 2 (M2, falsification attempts on
affirmatively-applied rule classes) remains gated on Phase 1 producing signal and a
non-self-authored instance, exactly as phased below. Phasing below is deliberately
reversible and gated on evidence, mirroring how D16/D17 approved a shape first and
built each piece against evidence rather than up front.

## The gap, stated precisely

Q22 records three measured instances (PRs
[#215](https://github.com/brandondees/code-quality-atlas/pull/215),
[#216](https://github.com/brandondees/code-quality-atlas/pull/216),
[#253](https://github.com/brandondees/code-quality-atlas/pull/253)) where the atlas
review **selected the correct lens, named the exact rule that governed the defect,
and cleared the change anyway** — with an external reviewer finding the defect
minutes later in every case. Lens selection was never the failure; the *execution*
of the named check was.

A review that reports "checked X, found nothing" is, in its output, indistinguishable
from one that genuinely tried to falsify X and one that named X and never ran it.
Nothing in the current pass forces the attempt or records its result.

**What is already covered — so the fix does not duplicate it.** The synthesizer's
`How to synthesize` step 6 (*State coverage & limitations*) already requires the
report to name "any finding asserted without direct evidence," and step 7
(*Note the process*) carries the self-improvement signal. Those cover the case where
the review *knows* it is uncertain. Q22's failure is the case where the review is
**confident and wrong** — it believes it verified X. #215 and #216 are silent misses
("named the check, ran it, found nothing"); #253 is the sharper shape — a *positive
affirmation* ("the AWS `public-read-write` claim is also correct") of a statement
that was, at that moment, already publicly disputed as wrong in the same PR's comment
thread. Step 6 does not catch either, because the model does not classify a
confident-but-wrong conclusion as "asserted without evidence."

## Two candidate mechanisms

The two shapes Q22 already sketches, made concrete. They are not exclusive; M1 is the
cheaper and more mechanically preventable, M2 the more general and more expensive.

### M1 — Standing-dispute check (cheap, greppable, catches #253 alone)

Before the review **affirms** any claim it did not independently re-derive, scan the
PR's existing comment threads and prior review rounds for a standing dispute of that
exact claim; if one exists, treat the claim as unresolved rather than clearing it.

- **Cost:** one read of the PR's existing comments, already available to any
  PR-review entry path. No new machinery, no per-check ceremony.
- **Coverage:** #253's failure is caught by this alone — CodeRabbit had flagged the
  exact sentence ~1.5 minutes before the atlas self-review affirmed it. It does
  nothing for #215/#216, where no external dispute existed yet.
- **Boundary:** it fires only when the review *affirms* a specific claim (its own or
  another party's). It is not a rule to defer to every external comment — a standing
  dispute makes a claim *unresolved and worth re-deriving*, not *automatically
  correct*; the review still has to adjudicate, it just may not skip the adjudication.

### M2 — Falsification attempt on affirmatively-applied rules (general, uneven cost)

For a rule the review **claims to have applied**, record an attempt to *falsify* the
"no defect" conclusion, with its result — rather than concluding from the rule's
presence in the checklist that it was run.

- **Cheap where the check is greppable.** Authoring rule 1 ("is this true
  unconditionally? superlatives are the tell") is the model case: enumerate the
  absolutes in the diff (`strictly better`, `always`, `no X permits`, `makes it a
  compile error`) and try to find one counterexample each. #216's three uncaught
  absolutes ("Measured — no", "The harness is deterministic", "an edit *will* flip
  unrelated scenarios") are exactly this shape.
- **Much less mechanical elsewhere.** "Did you consider the empty-string case"
  (#215) has no greppable enumeration — the falsification attempt is itself an act of
  reasoning the model may perform as poorly as the original check. M2's value is
  uneven across rule classes, and forcing it on every claim is the ceremony cost Q22
  warns against.

## Where the step lives

**Recommendation: `synthesizing-review-findings`, as a discipline step**, extending
the existing `How to synthesize` sequence and `Reviewer discipline` guard rather than
adding a new artifact.

- It is the merge/verdict layer — the one place every lens's affirmed conclusions
  converge before a verdict is written, so a claim-execution check applies once to the
  whole review instead of being restated per lens.
- The generator already ships this skill into **both** surfaces from one source: the
  standalone `synthesizing-review-findings/SKILL.md` and each collapsed entrypoint's
  bundled `reference/synthesis.md`. One edit reaches both; no per-entrypoint copy to
  keep in sync.

**Rejected alternatives.**

- *Per-entrypoint `reference/tool-evidence.md`.* Four copies (one per collapsed
  entrypoint), a `checking-idioms`-class convention-drift risk, and the wrong layer —
  tool-evidence is the *pre-pass grounding* step, not the affirm-and-verdict step
  where the Q22 failures occur.
- *A new shared reference file.* Adds a fetch and a maintenance surface for a step
  that is a few sentences of discipline; the synthesizer is where reviewer-discipline
  guards already live.

## Open sub-questions and their disposition

- **Is this self-review-specific?** All three instances were the atlas reviewing a
  PR authored in the same session, so none separates "meta-review gap" from "lens was
  weak on that diff." An instance on a diff the atlas did **not** author would settle
  it. *Disposition:* M1 is worth building regardless of the answer — scanning an
  existing thread for a standing dispute is general review hygiene, not a self-review
  patch. M2's *necessity* is what waits on the self-review-specificity answer: if the
  failure turns out lens-specific, the fix belongs in the affected lenses' `examples.md`,
  not in a synthesizer ritual imposed on every review.
- **How would we know it worked?** The campaign's own instrument — eval scenarios —
  but with an unusual input shape: the input is a *review transcript* (a claim plus
  the evidence available at review time), and the expected behavior is that the named
  check is *executed*, not merely cited. This meta-review eval is a different shape
  from the 40 lens suites (whose input is a diff or an artifact) and likely wants to
  be evaluated **separately** from them, possibly on its own harness path.
- **What is the ceremony budget?** The failure is measured three times; the fix must
  not tax every review to prevent it. M1 is a single existing-comment read. M2 is
  scoped to claims the review *affirmatively makes* and only where falsification is
  cheap and greppable; "did you consider case Y" stays in lens examples, not a
  blanket synthesizer step.

## Proposed build (all phases owner-gated; approve per phase)

**Phase 1 — M1 + a meta-review eval seed. ✅ Shipped 2026-09-01.** Added the
standing-dispute check as a `Reviewer discipline` bullet in
`synthesizing-review-findings` (reaching both surfaces via the generator), plus 3
meta-review eval scenarios in the new transcript-input shape, including a direct
reconstruction of #253. See
[`plans/2026-09-01-executing-cited-checks-phase1.md`](plans/2026-09-01-executing-cited-checks-phase1.md).

**Phase 2 — M2 for greppable claim classes (deferred).** Gate on Phase 1 producing
signal *and* on a non-self-authored instance (or an eval that stands in for one).
Scope M2 to rule classes with a real enumeration — authoring rule 1's absolutes
first, since #216 is exactly that and the falsification is a grep. Do not extend M2 to
non-enumerable checks without evidence it helps there.

**Not in scope.** A general "re-run every lens's reasoning" pass (that is just running
the review twice); a rule to defer to external comments automatically (M1 makes a
disputed claim *unresolved*, never *correct*); any change to lens selection, which
Q22 confirms was never the failure.

## What this doc does not do

It does not change any shipped behavior, add a manifest section, or run the
generator. It is the shape-first artifact the owner asked for before the suite is
touched — the analog of D16's design-approved-build-deferred split. On approval, a
Phase 1 implementation plan lands under [`plans/`](plans/) in the dated,
`built_from`-clean style the other pipeline plans use.
