# Reviewable heuristics — finding-maintainability-hotspots

## Contents

- From category #21

## From category #21

### Reviewable heuristics (skill-checklist seeds)

- **Change amplification:** did one conceptual change force edits in N>3 files/modules? If so, is that essential (one concept, many sites) or accidental (a missing abstraction / leaked detail)?
- **Shotgun surgery smell:** the same constant, enum case, validation, or shape is edited in multiple places in this diff — flag for consolidation.
- **Blast radius:** does the change touch a high fan-in module (many importers)? Is there a contract/compat note or test proving downstream callers still hold?
- **Refactorability gate:** is the changed code covered by tests *before* the change? If not, was a characterization/pin-down test added first?
- **Debt visibility:** new `TODO`/`FIXME`/`HACK` — does it link to a tracked issue and say *why* (Fowler quadrant: deliberate+prudent is OK if recorded)? Reject silent/untracked debt.
- **Knowledge concentration / bus factor:** does this PR touch a file with a single historical author or a long-abandoned area? Flag for a second reviewer / knowledge-spreading.
- **Onboarding cost:** would a new engineer understand *why* this exists from the code + nearby docs alone, or only from tribal knowledge?
- **Hidden coupling:** are two files that "shouldn't" know about each other being changed together again (change-coupling)? Name the implicit contract.
- **Connascence locality:** does the change introduce connascence (of position, meaning, value, timing…) that crosses a module boundary? Stronger/longer-distance connascence = higher amplification.
- **Reversibility:** is this change easy to undo, or does it bake in a one-way decision (data format, public API, migration)? One-way doors deserve more scrutiny.
- **Complexity trend:** does the diff raise cyclomatic/cognitive complexity of an already-hot function, or reduce it? Net direction matters more than absolute number.
- **Tidy-first economics (timing & sequencing):** if the diff mixes a structural tidying (rename, extract, reorder, dedupe) with a behavioral change, should the tidying land *first and separately* so the behavioral diff stays small and reviewable? Judge the *now / after / never* call by coupling-and-cohesion — tidy **now** when it removes coupling the change must otherwise fight, **defer** when the payoff is speculative, **never** on leaf/stable code — rather than tidying reflexively. (Beck, *Tidy First?*; the *sequencing* lives in #24, the *economics* here.)
- **Speculative generality (counterweight):** is added "flexibility" (config knobs, plugin points, abstract base) justified by a *present* second use, or is it pre-emptive and itself future maintenance cost?

---
