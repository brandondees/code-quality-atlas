# How to walk this map

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

## Reading order

1. `_meta/schema.md` for the closed node types.
2. `objects/_index.md` for a one-line-per-type map (stub | verified | stale).
3. Open one object card, not the whole `objects/` folder.
4. For a specific change, once `effects/CONTEXT.md` exists (a later slice —
   check `objects/_index.md`'s status first) start there instead — it names
   which cards to open, so you don't have to guess.

## Entry-file twins

`CLAUDE.md` is the hand-edited source. `AGENTS.md` and `routing.md` in this
same folder are byte-identical copies, per `icm-architect`'s own convention
(`references/system-map.md`: "Generate `AGENTS.md` and `routing.md` as
byte-identical twins... Tools that ignore `CLAUDE.md` still get the
catalog") — `AGENTS.md` for the cross-agent onboarding convention, `routing.md`
for tooling that expects neither name. Edit `CLAUDE.md` only, then re-copy it
to both twins in the same change — never hand-edit a twin directly. This is
CI-enforced the same way the root `CLAUDE.md`/`AGENTS.md` routing block is
(`tests/test_map_twins_sync.py`, precedent: `tests/test_routing_snippet_sync.py`,
issue #167).

## What this map does not track

Counts — lens counts, scenario counts, assertion counts, file counts, "as of
this writing" snapshots. Those live only in the source (`skills/manifest.yaml`,
each lens's `evals/eval.json`, the directory tree itself) and in generated
output, never restated as a number in this map's prose. A count written into
a markdown file is a count that goes stale the next time someone lands a PR —
this repo has already paid real PR-review-churn cost for exactly that pattern
(see `docs/session-log.md`'s SKILL.md file-count reconciliation, and its
recall/precision reconciliation, both from the same PR round). Ask the
source, or run `python -m tooling.cli generate` / `drift` and read its own
output, rather than trusting a written-down number here — in this map or
anywhere else in the repo's prose docs.
