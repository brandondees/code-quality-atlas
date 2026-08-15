---
type: "EvalScenario"
cluster: "eval-hardening"
universe: live
status: verified
entity: "skills/*/evals/eval.json"
---

# EvalScenario

One `{query, expected_behavior}` pair in a lens's `evals/eval.json` — the
regression net for regeneration (D8) and the unit the Q21 campaign raises
per lens.

## Why this shape

D8: every lens ships evals *before* prose, so a docs → regenerate → re-run
cycle has something to confirm no behavioral regression. Q21 raised the bar
per lens beyond D8's 3-scenario baseline, adding an A-E adversarial taxonomy
(below) so a suite tests more than the easy cases.

## Shape

- File: `skills/<lens>/evals/eval.json` — a JSON object with `"skills":
  [<lens name>]` and a `"scenarios"` array of `{query, expected_behavior}`.
- No `id` or tag field in the JSON itself — a scenario is addressed by
  **ordinal position** in the array (`<lens>#<n>`, per `_meta/schema.md`'s
  Naming rule), 1-indexed as scenario prose in `docs/open-questions.md`
  counts it.
- **The A-E taxonomy tag is not a JSON field.** Q21-hardened suites are
  *authored* against five groups — **A** design-doc-shaped firing (only for
  `design: true` lenses), **B** per-axis coverage of the lens's own
  checklist, **C** delegate/escalate-boundary (proves the lens hands a
  finding to its true owner instead of over-reaching), **D**
  adversarial/red-team (suppression comments, distractor overload,
  sycophancy framing), **E** precision (`No findings` on a clean or
  out-of-scope diff) — but that grouping lives only in prose: the Q21 entry
  in `docs/open-questions.md` for the lens, and often the lens's own
  `reference/heuristics.md`/`examples.md`. A scenario's group is not
  queryable from `eval.json` alone.
- A lens's floor is `skills/manifest.yaml`'s `eval_min` on that `Lens`
  entry (`None` = D8's baseline of 3); `tooling/evals.py`'s
  `validate_evals` enforces it via `tooling.cli eval`.

## Connected to

- **owns:** —
- **owned-by:** `Lens` (one `eval.json` per lens)
- **joins:** `Decision` — a hardened suite's A-E breakdown and its
  cross-model re-gate result are recorded in the lens's own `Q21` entry in
  `docs/open-questions.md`, not in the JSON
- **looks-like-but-is-not:** a `Decision` itself — the scenario is the
  eval unit; the Q21 `Decision` entry is where its rationale and re-gate
  history are recorded

## If you change this

- **Hits:** `tooling.cli eval`'s pass/fail for that lens; a hardened
  suite's own re-gate history in `docs/open-questions.md` if the scenario
  set materially changes
- **Does not hit:** other lenses' `eval.json` files, or the lens's
  `SKILL.md` (evals don't regenerate prose)

## Surfaces

| Surface | Role |
|---|---|
| `tooling/evals.py` | validates scenario count against `eval_min` |
| `tooling/run_evals.py` | runs a suite against a local model (`query_ollama`) for a cross-model re-gate |
| `docs/runbooks/cross-model-re-gate.md` | the manual procedure for a re-gate run |

## See

- Source: `skills/<lens>/evals/eval.json` (e.g.
  `skills/hunting-silent-failures/evals/eval.json`)
- `docs/open-questions.md` D8, Q21
- `docs/threat-modeling-design-time-security.md` §5.1 (the A-E taxonomy's
  origin, first applied to `sweeping-for-security`)
- Verified 2026-08-15 @ `ff7c642`
