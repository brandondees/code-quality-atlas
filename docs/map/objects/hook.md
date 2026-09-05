---
type: "Hook"
cluster: "—"
universe: live
status: verified
entity: "hooks/hooks.json"
---

# Hook

A session-automation trigger — an entry in `hooks/hooks.json` firing a
script on a Claude Code lifecycle event.

## Why this shape

Two problems a skill's own trigger description can't solve: getting the
suite noticed on a bare "review this" request when dozens of installed
skills compete for a thin trigger-listing budget (`hooks/route.sh`'s own
comment explains this directly, `hooks/route.sh:5-11`), and the D17
self-improvement loop's opt-in usage logging, which has to fire on every
skill invocation and session end regardless of what the session asked for.

## Shape

- `hooks/hooks.json` is keyed by **event name**, not by a per-hook
  identifier — `_meta/schema.md`'s Naming rule ("its identifier as
  `hooks.json` names it") means the event key itself: `SessionStart`,
  `PostToolUse`, `SessionEnd` (`hooks/hooks.json:3,13,24`). There is no
  `name` field on an individual hook entry.
- Each event key holds an array of `{matcher?, hooks: [{type: "command",
  command}]}` objects — `PostToolUse` is the only one with a `matcher`
  (`"Skill"`, `hooks/hooks.json:15`), since it only needs to fire when a
  skill tool actually ran.
- One script per event today: `hooks/route.sh` (SessionStart, steers a
  bare "review this" toward the atlas suite), `hooks/log-skill-invocation.sh`
  (PostToolUse, D17 stage-1 usage logging), `hooks/queue-session-retro.sh`
  (SessionEnd, D17 stage-1). `hooks/lib/feedback-tier.sh` is a shared
  resolver the logging hooks source, not an event handler itself.
- D17's logging hooks gate on an opt-in `feedback:` tier
  (`.code-quality-atlas/preferences.md` or an env-var override, default
  `off`) and degrade to a clean no-op on a missing `jq` or malformed input.
- `hooks/` isn't the only copy: the collapsed plugin ships its own
  `collapsed/hooks/`, and `tests/test_hooks.py`'s
  `test_collapsed_hooks_json_matches_standalone` and
  `test_collapsed_generic_hook_scripts_match_standalone` byte-gate that
  `hooks.json` plus every generic script (`log-skill-invocation.sh`,
  `queue-session-retro.sh`, `lib/feedback-tier.sh`, and the
  `lens-coverage/` pair) stay identical between the two. `route.sh` is the
  deliberate exception — its steering message differs because the
  collapsed plugin installs only the 4 collapsed entrypoints, not the
  standalone's 44 skills/router/commands, and
  `test_collapsed_route_hook_names_collapsed_entrypoints_not_standalone_surface`
  checks the collapsed copy names the right surface instead.

## Connected to

- **owns:** —
- **owned-by:** —
- **joins:** `CollapsedEntrypoint`/`Lens` (`route.sh`'s steering message
  points sessions at the same routing this repo's `CLAUDE.md`/`AGENTS.md`
  documents by hand)
- **looks-like-but-is-not:** `Command` — see the `Command` card's own
  looks-like-but-is-not entry for the reverse framing: a `Hook` fires
  automatically on a lifecycle event, never by name

## If you change this

- **Hits:** every session's `SessionStart`/`PostToolUse`/`SessionEnd`
  behavior once the plugin is installed — a hook bug is repo-wide and
  silent (no user-visible invocation to notice); the `collapsed/hooks/`
  mirror, which must be updated to match (`route.sh`'s content excepted)
  or `tests/test_hooks.py` fails
- **Does not hit:** any `Lens`/`CollapsedEntrypoint` file directly (hooks
  steer toward them via injected context, they don't generate or edit them)

## Surfaces

| Surface | Role |
|---|---|
| `hooks/lib/feedback-tier.sh` | shared opt-in-tier resolver for the D17 logging hooks |
| `.code-quality-atlas/preferences.md` (consumer repo) | sets the `feedback:` tier the logging hooks gate on |
| `collapsed/hooks/` | byte-identical mirror of `hooks/` (except `route.sh`) for the collapsed plugin install; gated by `tests/test_hooks.py` |

## See

- Source: `hooks/hooks.json`, `hooks/route.sh`, `hooks/log-skill-invocation.sh`,
  `hooks/queue-session-retro.sh`, `hooks/lib/feedback-tier.sh`,
  `collapsed/hooks/` (its mirror)
- `docs/open-questions.md` D17
- Verified 2026-09-05 @ `33504c1` — documented the `collapsed/hooks/` twin
  and its `route.sh` exception (issue #376)
