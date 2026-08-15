---
type: process
status: verified
consumes: [Category, Manifest]
produces: [Lens, CollapsedEntrypoint]
---

# generate

Turn a `Manifest` (and the `Category` research it cites) into the actual
`Lens`/`CollapsedEntrypoint` skill files on disk.

## Input → Movement → Output

Input: `skills/manifest.yaml` plus whatever `docs/research/cluster-*.md`
prose it cites via `built_from`. Movement: `python -m tooling.cli generate`
loads and validates the manifest, then emits one skill/composition file set
per manifest section. Output: every `skills/<name>/` and
`collapsed/skills/<name>/` folder, freshly (re)written and provenance-hashed
against the source it was built from.

## Why this shape

D6: docs are the source of truth, skills are derived and regenerable, not
hand-maintained. If a lens's `SKILL.md` could be hand-edited independently
of the research it cites, the two would silently diverge the moment either
one changed — the exact failure this movement exists to make structurally
impossible: there is no path from "edit `docs/research/`" to "shipped
skill" that skips this step.

## Steps

1. `python -m tooling.cli drift` — see what changed before regenerating
   blind (`docs/runbooks/regenerating-skills.md:6-7`).
2. `python -m tooling.cli generate` loads and validates the manifest, then
   for each `skills:` entry calls `generate_skill` (`tooling/cli.py:47-55`);
   if `router:`/`prepass:`/`synthesizer:` are present, generates
   `choosing-review-lenses`/`grounding-review-in-tool-output`/
   `synthesizing-review-findings` (`tooling/cli.py:56-64`); if
   `entrypoints:` is present, calls `generate_collapsed` for every
   `CollapsedEntrypoint` (`tooling/cli.py:65-78`), which also bundles the
   pre-pass/synthesizer into each entrypoint's own `reference/` files
   (`docs/runbooks/regenerating-skills.md:21-23`).
3. `examples.md` and `evals/eval.json` are **never** overwritten — hand-
   refined content survives regeneration untouched
   (`docs/runbooks/regenerating-skills.md:12-13`).
4. Re-validate: re-run the affected `EvalScenario` set against the model
   tiers this suite targets (`docs/runbooks/regenerating-skills.md:24-26`).
5. `python -m tooling.cli drift` again — confirm "No drift" before
   committing (`docs/runbooks/regenerating-skills.md:27-28`).

## If you change this

- **Hits:** every `Lens`/`CollapsedEntrypoint` whose `skills:`/`entrypoints:`
  entry or cited `Category` changed; `tests/` that assert generated output
  matches source
- **Does not hit:** a lens's `examples.md`/`evals/eval.json` (hand-authored,
  preserved across regeneration by design)

## Surfaces

| Surface | Role |
|---|---|
| `tooling/cli.py` (`generate` subcommand) | the entry point this movement runs through |
| `tooling/generate*.py` | per-artifact emission logic (skill/router/prepass/synthesizer/collapsed) |
| `tests/` | regression coverage asserting generated output tracks source |

## See

- Objects: `Manifest`, `Lens`, `CollapsedEntrypoint`, `Category`
- Source: `tooling/cli.py:47-79`, `docs/runbooks/regenerating-skills.md`
- `docs/open-questions.md` D6, D10, D12
- Verified 2026-08-15 @ `1ed3006`
