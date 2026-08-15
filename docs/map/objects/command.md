---
type: "Command"
cluster: "—"
universe: live
status: verified
entity: "commands/"
---

# Command

A Claude Code slash-command entry point — a file under `commands/`, invoked
as `/code-quality-atlas:<name>` (or `/<name>` inside this repo's own
sessions).

## Why this shape

Some workflows need to be triggered deliberately rather than picked up by a
skill's own auto-trigger description — a PR review someone explicitly asks
for, a one-time repo-init step, a scheduled sweep. A `Command` is a named,
directly-invokable action instead of relying on trigger-phrase matching.

## Shape

- File: `commands/<name>.md` — the filename is the command name (`_meta/
  schema.md`'s Naming rule).
- YAML frontmatter: `description` (shown in command listings and used for
  matching), `argument-hint` (what, if anything, follows the command name),
  and often `allowed-tools` (a pre-approved tool list scoped to what the
  command actually needs — e.g. `commands/atlas-rebase-stale.md:1-4` scopes
  to GitHub MCP tools only, no `Skill`/`Edit`).
- Body: the instructions the command runs, written the same way a skill's
  prose would be.

## Connected to

- **owns:** —
- **owned-by:** —
- **joins:** `CollapsedEntrypoint` (`atlas-review-pr`/`atlas-code-review`
  invoke `reviewing-a-change` via the `Skill` tool); `Lens`/`Manifest`
  indirectly through whichever entrypoint or lens a command's body invokes
- **looks-like-but-is-not:** `Runbook` — a `Command` is a slash-invoked,
  frontmatter-declared action Claude Code itself lists and runs; a
  `Runbook` is prose a human or agent reads and follows manually, with no
  slash-command surface at all

## If you change this

- **Hits:** nothing generated — commands are hand-authored; a template sync
  in `templates/agents-routing-snippet.md` if the routing table's own
  command references change
- **Does not hit:** other commands, or the `Lens`/`CollapsedEntrypoint` a
  command's body invokes (those are separate files, referenced not owned)

## Surfaces

| Surface | Role |
|---|---|
| Root `CLAUDE.md`/`AGENTS.md` routing table | names `/atlas-review-pr` and `/atlas-code-review` as the preferred entrypoints |
| `templates/agents-routing-snippet.md` | the canonical copy `atlas-init` writes into consumer repos |

## See

- Source: `commands/`
- Verified 2026-08-15 @ `ff7c642`
