# How to walk this map

This map follows the Interpretable Context Methodology (ICM), vendored at
`.claude/skills/icm-architect/` for this repo's own Claude Code sessions
(local and cloud — see `docs/distribution.md`'s channel matrix for why
`.claude/skills/` is the right place for a repo's own tooling, distinct from
the `skills/`/`collapsed/` this repo distributes as its own plugin). Extend
this map by following `.claude/skills/icm-architect/references/system-map.md`
directly rather than re-deriving the method from this file alone — this
`CONTEXT.md` documents this specific map's own state, not the method.

## Universes

| Universe | Meaning |
|---|---|
| **live** | in force; implement and cite against these |
| **leftover** | still present, no longer the main path; touch only if that path is in scope |
| **ghost** | named or filed, not wired; do not implement against these |

## Name collisions

Product language and the repo's own field/file names sometimes disagree.
State both once here rather than re-discovering the mismatch per session:

- **"wave"** means two unrelated things. `skills/manifest.yaml`'s `wave:`
  field on each lens entry is the *original skill-build wave* (when the lens
  was first authored). The Q21 eval-hardening campaign's "wave 3" (in
  `docs/open-questions.md` and `docs/session-log.md`) is a *separate,
  unrelated* numbering for the order lenses get their eval suites hardened
  in. A lens can carry an old `wave:` value in the manifest and still be
  un-hardened, or vice versa — check which sense a document means from
  context, never from the number alone.
- **"tier"** carries at least five distinct senses. (1) The manifest's
  per-lens `tier: floor | preference` field (Q13's overlay: floor-tier
  findings can be `acknowledge`d but never silently `suppress`ed). (2) The
  triage mode's "critical tier" (`docs/review-depth-modes.md`) — a **subset**
  of (1)'s floor-tier lenses (4 of the 5, missing `hunting-silent-failures`),
  not the same set. (3) A depth mode itself, used loosely as a tier name
  (`docs/review-depth-modes.md`: "the repo arm of the **comprehensive tier**").
  (4) The self-improvement loop's `feedback:` opt-in tier
  (`docs/team-preferences-overlay.md`: off/local/draft/auto). (5) A
  model-capability tier in cross-model eval gating (`docs/open-questions.md`
  D17: "model-tier shunting"; "the 7-8B tier"). Check which sense a document
  means from context, never from the bare word.
- **"floor"** carries at least four distinct senses, and (1) and (2) are the
  most easily confused since both appear together in the same depth-mode
  discussion. (1) Q13's floor-tier lens classification (see "tier" above —
  a lens property). (2) The synthesizer's per-mode **severity floor**
  (`Mode.floor` in the manifest; "floor Major+", "floor pinned at Nit") — an
  unrelated axis: which severities a report surfaces, not which lenses are
  suppressible. (3) The eval-scenario floor (Q21's `eval_min`, "D8's baseline"
  of 3 scenarios per lens). (4) A model's "reliable floor" for a given lens in
  cross-model eval gating (`docs/open-questions.md`: "below this lens's
  reliable floor for lethal-trifecta..."). Same rule: context decides which,
  never the bare word.

## Reading order

Making a specific change? Start at `effects/CONTEXT.md` instead of the list
below — it names which cards to open for a recognized scenario, so you
don't have to guess. The list below is for general orientation, not a
specific change:

1. `_meta/schema.md` for the closed node types.
2. `objects/_index.md` for a one-line-per-type map (stub | verified | stale).
3. Open one object card, not the whole `objects/` folder.
4. `processes/` for a repeating movement — small enough today to browse
   directly, no index yet. Each card names the object types it `consumes`/
   `produces` in its own frontmatter.

## Entry-file twins

`CLAUDE.md` is the hand-edited source. `AGENTS.md` and `routing.md` in this
same folder are byte-identical copies, per `icm-architect`'s own convention
(`.claude/skills/icm-architect/references/system-map.md`: "Generate
`AGENTS.md` and `routing.md` as byte-identical twins... Tools that ignore
`CLAUDE.md` still get the catalog") — `AGENTS.md` for the cross-agent
onboarding convention, `routing.md` for tooling that expects neither name.
Edit `CLAUDE.md` only, then re-copy it
to both twins in the same change — never hand-edit a twin directly. This is
CI-enforced the same way the root `CLAUDE.md`/`AGENTS.md` routing block is
(`tests/test_map_twins_sync.py`, precedent: `tests/test_routing_snippet_sync.py`,
issue #167).

## What this map does not track

Live counts — lens counts, scenario counts, assertion counts, file counts,
"as of this writing" snapshots of current state. Those live only in the
source (`skills/manifest.yaml`, each lens's `evals/eval.json`, the directory
tree itself) and in generated output, never restated as a number describing
*current* state in this map's prose or in any other doc's routing/orientation
text. A current-state count written into a markdown file is a count that
goes stale the next time someone lands a PR — this repo has already paid
real PR-review-churn cost for exactly that pattern (see
`docs/session-log.md`'s SKILL.md file-count reconciliation, and its
recall/precision reconciliation, both from the same PR round). Ask the
source, or run `python -m tooling.cli generate` / `drift` and read its own
output, rather than trusting a written-down current-state number.

This does not apply to a dated, point-in-time record — `docs/session-log.md`'s
own reconciliations (cited above) are exactly that: a number that was true
when written and is recorded as history, not asserted as the current state.
The distinction is "as of right now" vs. "as of this dated entry" — the
first goes stale, the second is already correctly timestamped.
