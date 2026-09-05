---
type: process
status: verified
consumes: [Lens, EvalScenario, Category]
produces: [EvalScenario, Decision]
---

# harden-eval-suite

Raise one lens's eval suite past D8's 3-scenario baseline to a
comprehensive, A-E-adversarial-taxonomy suite with a matching `eval_min`
floor — the Q21 campaign's recurring unit of work.

## Input → Movement → Output

Input: a lens's existing `EvalScenario` set and its `reference/
heuristics.md` checklist (the `Category` it's `built_from`). Movement:
author new scenarios per A-E group (design-doc firing, per-axis coverage,
delegate/escalate boundaries, adversarial/red-team, precision), set
`eval_min` on the lens's `Manifest` entry, and record the rationale.
Output: a larger `evals/eval.json`, a raised `eval_min`, and a new dated
entry in the `Decision` (Q21) narrative documenting the A-E breakdown.

## Why this shape

Q21 (`docs/open-questions.md`): D8's "≥3 scenarios" baseline proves a suite
exists, not that it discriminates a real reviewer from one that fires on
everything or nothing. Structuring new scenarios by A-E group is what makes
"hardened" mean something specific and checkable — a suite missing a whole
group (no precision scenarios, no adversarial ones) has a known, nameable
gap rather than an unexamined one.

## Steps

1. Author scenarios per A-E group against the lens's own
   `reference/heuristics.md` checklist and `cross_ref` categories — see the
   `EvalScenario` object card for what each group covers and why the
   grouping itself lives only in prose, not in `eval.json`.
2. Set `eval_min` on the lens's `skills:` entry in `skills/manifest.yaml`
   once the suite actually meets it (`docs/open-questions.md` Q21
   sub-question 2's `Skill.eval_min: int | None` mechanism).
3. `python -m tooling.cli eval` confirms the new floor is enforced
   (`tooling/evals.py`'s `validate_evals`).
4. `python -m pytest` confirms the mechanism and the new scenario count.
5. Record the A-E breakdown, scenario count, and rationale as a dated entry
   under the lens's name in the `Decision` (Q21 in `docs/open-questions.md`)
   — e.g. the first hardened instance, `sweeping-for-security`
   (`docs/open-questions.md:848`).
6. Often followed by `cross-model-re-gate` (a separate process — the
   hardening and the re-gate are independently schedulable, per Q21's own
   deferred-re-gate entries).

## If you change this

- **Hits:** the lens's `EvalScenario` count and `eval_min`; the `Decision`
  (Q21) narrative; `tooling.cli eval`'s enforced floor for that lens
- **Does not hit:** other lenses' suites or floors (each lens's `eval_min`
  is independent, opt-in per `docs/open-questions.md` Q21 sub-question 2)

## Surfaces

| Surface | Role |
|---|---|
| `tooling/evals.py` | enforces `eval_min` via `validate_evals` |
| `docs/threat-modeling-design-time-security.md` §5.1 | origin of the A-E taxonomy, first applied here |
| `docs/session-log.md` | narrates individual hardening passes in more detail than the Q21 entry alone |

## See

- Objects: `Lens`, `EvalScenario`, `Category`, `Decision`
- Source: `skills/manifest.yaml` (`eval_min` field), `tooling/evals.py`
- `docs/open-questions.md` D8, Q21
- Verified 2026-09-05 @ `33504c1` — re-pinned the drifted
  `open-questions.md` citation (issue #376)
