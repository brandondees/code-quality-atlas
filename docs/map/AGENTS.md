# code-quality-atlas — system map

Read this when you need "what is X" or "what else moves if I touch X"
answered without re-deriving it from the source tree. This map cites the
repo; it is never the spec. If the map and the source disagree, the source
wins and the map is stale — fix the card, not your mental model.

## Where things live

| Folder | Holds |
|---|---|
| `CONTEXT.md` | how to walk this map, the universes, name collisions |
| `_meta/schema.md` | the closed set of node types |
| `_templates/` | blank object/process card starters |
| `objects/` | one card per noun, clustered by how an editor asks |
| `processes/` | one card per real, repeating movement |
| `effects/CONTEXT.md` | "if you're changing X, open these cards" |

## Route by what you're doing

| If you're | Go to |
|---|---|
| Adding or hardening a lens | `objects/generation-pipeline/`, `objects/eval-hardening/`, `processes/harden-an-eval-suite.md` |
| Running or debugging generation/drift/eval gates | `processes/generate.md`, `processes/drift-check.md`, `processes/eval-gate.md` |
| Cross-model re-gating a suite | `processes/cross-model-re-gate.md` |
| Reviewing a PR or change with the atlas itself | `processes/review-a-change.md` |
| Not sure what a change touches | `effects/CONTEXT.md` |
| Anything not covered above | the repo root `CLAUDE.md`'s own orientation section |

## The one rule

This map never becomes a second spec. Every card cites source; a claim with
no citation gets fixed or deleted, not trusted.
