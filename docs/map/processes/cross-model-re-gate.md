---
type: process
status: verified
consumes: [EvalScenario, Lens]
produces: [Decision]
---

# cross-model-re-gate

Run a hardened `EvalScenario` suite against the floor-of-record local model
and grade recall/precision separately, so a raised `eval_min` means the
suite discriminates on the weakest supported model, not just a strong one.

## Input → Movement → Output

Input: a lens's `EvalScenario` set and a local model substrate (Ollama,
`qwen2.5-coder:7b` as floor-of-record). Movement: run the suite through
`tooling/run_evals.py` against the model, grade each response against its
`expected_behavior`. Output: a recall figure and a separate precision
figure, folded into the lens's `Decision` (Q21) entry as the re-gate
result — sometimes with a tuning pass (an `examples.md` addition) and a
second re-gate if the first run under-performs.

## Why this shape

`docs/runbooks/cross-model-re-gate.md`: "a hardened suite is only as
meaningful as the bar it is measured against... without the re-gate,
`eval_min: 26` asserts that 26 scenarios exist, not that any of them
discriminate." Recall and precision are graded and reported **separately**
because a single total hides which failure mode a model has — the runbook's
own example: a model that scored 10/24 total broke down as 10/20 recall and
0/4 precision, meaning it fired the same canned finding on every input
regardless of correctness. A total alone would have looked identical to a
genuinely discriminating 10/24.

## Steps

1. Stand up the substrate: `ollama serve` with `OLLAMA_MAX_LOADED_MODELS=1`
   (not optional on a memory-constrained host — a second model loading
   while the first is still resident OOM-kills the new one), pull the floor
   model, send a throwaway warm-up request first
   (`docs/runbooks/cross-model-re-gate.md:17-58`).
2. Run: `python -m tooling.run_evals --skill <name> --model
   qwen2.5-coder:7b` (`docs/runbooks/cross-model-re-gate.md:62-65`); check
   the exit code — a failed scenario's empty response is byte-identical to
   a genuine "no findings" miss, so an uncaught transport failure silently
   inflates the miss count (`docs/runbooks/cross-model-re-gate.md:72-75`).
3. Grade recall (of the defect-planting scenarios, how many caught) and
   precision (of the clean E-group scenarios, how many correctly left
   alone) as two separate numbers, never one total
   (`docs/runbooks/cross-model-re-gate.md:80-97`).
4. If the suite under-performs: add a targeted worked example to
   `examples.md`, then **re-run the whole suite**, not just the target
   scenario — an edit aimed at one behavior can flip unrelated scenarios in
   either direction, confirmed twice in the same session
   (`docs/runbooks/cross-model-re-gate.md:121-132`).
5. Record the result — pass/fail, recall/precision split, any tuning
   delta — as a dated addition to the lens's `Decision` (Q21) entry in
   `docs/open-questions.md`.

## If you change this

- **Hits:** the lens's `Decision` (Q21) entry's recorded re-gate result; a
  tuning pass's target `EvalScenario` and, per the collateral-damage
  finding above, potentially unrelated scenarios in the same suite
- **Does not hit:** the lens's `eval_min` itself (re-gating measures against
  an existing floor, it doesn't change it — `harden-eval-suite` does that)

## Surfaces

| Surface | Role |
|---|---|
| `tooling/run_evals.py` | queries the local model and returns raw responses |
| `docs/runbooks/cross-model-re-gate.md` | the full procedure, including infra traps (OOM, runaway generation, grading pitfalls) |

## See

- Objects: `EvalScenario`, `Lens`, `Decision`
- Source: `tooling/run_evals.py`, `docs/runbooks/cross-model-re-gate.md`
- `docs/open-questions.md` Q21
- Verified 2026-08-15 @ `1ed3006`
