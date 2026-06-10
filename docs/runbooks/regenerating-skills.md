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
