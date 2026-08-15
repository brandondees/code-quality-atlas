# effects/ — change-impact index

If you're changing X, open these cards. This index doesn't restate what a
card's own "If you change this" section says — if this index and a card
ever disagree, fix the card, not this file.

Only scenarios that cross more than one card are listed. A single-card
change (a `Command`, a `Runbook`, a `Hook`, a standalone `Decision`, a
`PlanDoc`) doesn't need a row here — `objects/_index.md` already points
straight at the one card that covers it.

## If you're

| If you're | Open |
|---|---|
| Editing a `docs/research/cluster-*.md` section | `Category`, `Lens`, `generate`, `drift-check` |
| Raising a lens's eval floor past D8's baseline (the Q21 pattern) | `EvalScenario`, `Lens`, `harden-eval-suite`, `Decision` |
| Re-gating a hardened suite against the floor-of-record model | `EvalScenario`, `cross-model-re-gate`, `Decision` |
| Editing `skills/manifest.yaml` (new/merged/split lens, new entrypoint) | `Manifest`, `Lens` or `CollapsedEntrypoint`, `generate` |
| Promoting a `Gap` into a new `Category` | `Gap`, `Category`, `promote-gap-into-category`, `Decision`, `generate` |

Object cards live under `objects/<cluster>/` (see `objects/_index.md` for
the path); process cards live flat under `processes/`.

## Extending this map itself

Not a row above, on purpose: this index catalogs change-impact in the
*subject repo*, and extending the map itself is a different kind of change
with its own already-documented procedure — follow
`.claude/skills/icm-architect/references/system-map.md` directly, per
`CONTEXT.md`'s own pointer, rather than adding a self-referential row here.
