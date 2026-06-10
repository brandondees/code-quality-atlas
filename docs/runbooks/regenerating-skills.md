# Runbook — Regenerating skills after a docs change

The taxonomy + `docs/research/cluster-*.md` are the source of truth. Skills are
derived. After you critique/improve a research section, flow it into the skills:

1. **See what's affected:** `python -m tooling.cli drift`
   Lists every skill whose source sections changed (by `#n`).
2. **Regenerate:** `python -m tooling.cli generate`
   Rebuilds each skill's `SKILL.md` + `reference/*` from current docs and
   re-stamps provenance hashes. `examples.md` and `evals/eval.json` are NOT
   overwritten (hand-refined content is preserved).
3. **Re-validate evals:** for each affected skill, re-run its `evals/eval.json`
   scenarios against your model tiers (see the skill's evals). Fix regressions
   by tightening `reference/heuristics.md` (via the docs) or `examples.md`.
4. **Confirm sync:** `python -m tooling.cli drift` → "No drift".
5. **Commit** the regenerated skills with the docs change.

Adapting granularity later: edit `skills/manifest.yaml` (merge/split skills or
re-map `built_from` categories), then run steps 2–4. No research edits needed.

## Cross-model evals (the portability gate, D7/D8)

Validate eval *structure* (≥3 scenarios) for one or all skills:

```
python -m tooling.cli eval                 # all skills
python -m tooling.cli eval --skill <name>  # one skill
```

Run a skill's scenarios against a local model via Ollama and read the responses
next to their `expected_behavior` (the harness assembles the same context a
model with the skill loaded would see: SKILL.md + reference/heuristics.md +
examples.md):

```
python -m tooling.run_evals --skill <name> --model llama3.2:3b
```

Grade each response against `expected_behavior`. Skills must be tested on at
least two tiers (a strong model and a small/local one). Known failure mode on
small models: **over-flagging clean code** (inventing issues on the "good"
scenario). Fix by strengthening that skill's `examples.md` (good→no-finding
pairs carry the most weight for weak models) and/or adding an explicit
"don't invent issues; report no finding when the code is correct" guard.

**Tuning lessons (from `hunting-silent-failures` on `llama3.2:3b`, 3B):**
- The suite-wide "Reviewer discipline" guard (in every generated `SKILL.md`) must be
  **recall-safe**: a blanket "prefer reporting nothing over a false positive" made the
  3B model under-report on a genuinely bad case. Keep "report no findings when the code
  is correct, *but still report every genuine issue with full detail*."
- Targeted `examples.md` good-to-no-finding pairs reliably kill **specific** false-positive
  classes (e.g. "don't recommend broadening a narrow `except`").
- **Model-capability ceiling:** a 3B model misreads control flow (e.g. that an early
  `return` prevents a later line) even when an example states it explicitly — prompt
  tuning can't close this. Treat **~7-8B as the practical floor** for *clean-code
  precision* (no-finding reliability); below that, detection still works but expect
  over-flagging on correct code. For high-stakes correctness, pair the skill with a
  deterministic check rather than trusting a tiny model's "no findings".
