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
| `Decision` | a tracked design question and its resolution state | a `DN` bullet ("Decisions made") or `QN` header ("Open questions") in `docs/open-questions.md` |
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

Every type below is named by a rule, not by convention left to guess at card
creation time:

| Type | Named by |
|---|---|
| `Manifest` | fixed name `Manifest` — one instance |
| `Lens` | the literal kebab-case directory name under `skills/` |
| `Category` | its marker-plus-number exactly as `docs/research/cluster-*.md` writes it (`#N`) |
| `CollapsedEntrypoint` | the literal kebab-case directory name under `collapsed/skills/` |
| `EvalScenario` | its owning `Lens` name plus ordinal position in `evals/eval.json` (`<lens>#<n>`) |
| `Decision` | its marker-plus-number in `docs/open-questions.md` — either a `DN` bullet under "Decisions made" or a `QN` header under "Open questions"; see the `Decision` object card for the distinction |
| `Gap` | its marker-plus-number in `docs/map-gaps.md` (`GN`) |
| `PlanDoc` | the literal filename (already dated and scoped) under `docs/plans/` |
| `Command` | the literal filename under `commands/` |
| `Runbook` | the literal filename under `docs/runbooks/` |
| `Hook` | its identifier as `hooks/hooks.json` names it |

Never invent a different label for the same thing than the rule above
produces — a card's name must be re-derivable from its source alone.
