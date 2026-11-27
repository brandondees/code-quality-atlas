# objects/ — one card per noun

Cluster by how an editor asks a question, not by the repo's own folder
layout — this map's clusters do not have to mirror the source tree's
directories.

## Clusters

| Cluster | Covers |
|---|---|
| `generation-pipeline/` | Manifest, Lens, Category, CollapsedEntrypoint — "what generates what" |
| `eval-hardening/` | EvalScenario, the A-E adversarial taxonomy — "what does a hardened suite look like" |
| `decisions-and-tracking/` | Decision, Gap, PlanDoc — "where is this question tracked, is it resolved" |

Command, Runbook, and Hook are cataloged in `_index.md` but don't yet have a
dedicated cluster — add one only once enough cards accumulate to need it,
not preemptively.

## Card status

Each line in `_index.md` carries a status: `stub` (named, not yet carded),
`verified` (carded, cited, dated against a commit), or `stale` (carded once,
since drifted — flagged, not deleted). Read the index before opening a
cluster folder; do not open all three clusters to find one noun.

## Templates: object.md is a deliberate fork, process.md is not

`../_templates/object.md` started as a plain copy of
`.claude/skills/icm-architect/assets/templates/object.md`. It no longer is,
on purpose: it quotes its `cluster`/`entity` placeholder values and uses
`type: "{ObjectType}"` instead of the vendored original's unquoted `{cluster}`
and literal `type: object` — an unfilled copy of the vendored version doesn't
actually parse as valid YAML frontmatter (the brace placeholders read as a
nested mapping) and `object` reads as if it were itself one of
`_meta/schema.md`'s closed types, which it isn't.

This is why `object.md` isn't just repointed at the vendored copy: the
vendored one stays pristine (so it diffs cleanly against upstream on a
re-vendor), and this one is the safe-to-copy-directly version for actually
authoring a card in this repo. If upstream `icm-architect` ever fixes the
same issue, re-check whether this fork is still needed — don't let it become
stale just because nothing forces a re-comparison.

`../_templates/process.md` has no equivalent bug — `type: process`,
`consumes: []`, and `produces: []` have no brace placeholders to misparse —
so it stays an intentional, exact copy of
`.claude/skills/icm-architect/assets/templates/process.md` rather than a
fork. `tests/test_map_twins_sync.py` enforces that byte-for-byte match the
same way it enforces the `CLAUDE.md`/`AGENTS.md`/`routing.md` twins, so
drift here is caught automatically rather than relying on this paragraph
staying accurate by hand.
