# code-quality-atlas — system map

Read this when you need "what is X" or "what else moves if I touch X"
answered without re-deriving it from the source tree. This map cites the
repo; it is never the spec. If the map and the source disagree, the source
wins and the map is stale — fix the card, not your mental model.

## Where things live

| Folder | Holds | Status |
|---|---|---|
| `CONTEXT.md` | how to walk this map, the universes, name collisions | built |
| `_meta/schema.md` | the closed set of node types | built |
| `_templates/` | blank object/process card starters | built |
| `objects/` | one card per noun, clustered by how an editor asks | built — one card per noun type in `_index.md` |
| `processes/` | one card per real, repeating movement | not yet built |
| `effects/CONTEXT.md` | "if you're changing X, open these cards" | not yet built |

## Route by what's actually here

| If you're | Go to |
|---|---|
| Learning how to walk this map | `CONTEXT.md` |
| Looking up a node type | `_meta/schema.md` |
| Looking up a specific noun ("what is a Lens") | `objects/_index.md`, then that noun's own card |
| Anything else | the repo root `CLAUDE.md`'s own orientation section — this map's process cards and change-impact index don't exist yet |

Do not route to `processes/*.md` or `effects/CONTEXT.md` by name until the
"Where things live" table above says they're built — those are later,
separately-gated slices of the same audit pipeline this map follows
(`icm-architect`'s `references/system-map.md`).

## The one rule

This map never becomes a second spec. Every card cites source; a claim with
no citation gets fixed or deleted, not trusted.
