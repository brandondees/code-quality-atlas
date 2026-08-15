# Schema — closed node types

Every object card in `objects/` has a `type:` in its frontmatter drawn from
this closed list. Do not invent a new type without adding it here first.

## Object types

| Type | What it is | Source of truth |
|---|---|---|
| `Manifest` | the single central schema driving generation | `skills/manifest.yaml` |
| `Lens` | one reviewable skill | an entry in `manifest.yaml`'s `skills:` list; materialized at `skills/<name>/` |
| `Category` | one research-derived heuristic group a lens is `built_from` | a `## #N` section in `docs/research/cluster-*.md` |
| `CollapsedEntrypoint` | a bundled multi-lens skill | `manifest.yaml`'s `entrypoints:`; materialized at `collapsed/skills/<name>/` |
| `EvalScenario` | one query/expected_behavior pair, A-E taxonomy-tagged | an item in a lens's `evals/eval.json` |
| `Decision` | a tracked design question and its resolution state | a `### QN` entry in `docs/open-questions.md` |
| `Gap` | a structural taxonomy gap feeding future categories/lenses | a `GN` entry in `docs/map-gaps.md` |
| `PlanDoc` | a dated, scoped, `**Status:**`-tagged design doc | a file in `docs/plans/` |
| `Command` | a slash-command entry point | a file in `commands/` |
| `Runbook` | a how-to procedure for a recurring manual task | a file in `docs/runbooks/` |
| `Hook` | a session-automation trigger | an entry in `hooks/hooks.json` |

## Process types

Processes have no closed type list — see `_templates/process.md`'s
frontmatter for the shape. A process's `consumes`/`produces` link to object
types above by name.

## Naming

Lens and Command cards are named by the literal kebab-case directory/file
name. Category, Decision, and Gap cards are named by their letter+number
(`#N`, `QN`, `GN`) exactly as the source document names them — do not invent
a different label for the same thing.
