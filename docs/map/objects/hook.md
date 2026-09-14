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
  `PostToolUse`, `PreToolUse`, `SessionEnd` (`hooks/hooks.json:3,13,37,48`).
  There is no `name` field on an individual hook entry.
- Each event key holds an array of `{matcher?, hooks: [{type: "command",
  command}]}` objects — an event can carry more than one such object, each
  with its own matcher. `PostToolUse` has two: `"Skill"`
  (`hooks/hooks.json:15`, fires the D17 usage logger and the lens-coverage
  tracker) and `"Read"` (`hooks/hooks.json:28`, fires the lens-coverage
  tracker again, on the file reads a skill invocation alone wouldn't catch).
  `PreToolUse` has one, on
  `"mcp__github__pull_request_review_write|mcp__github__add_comment_to_pending_review"`
  (`hooks/hooks.json:39`, the lens-coverage gate, fires only ahead of a
  review actually posting). `SessionStart`/`SessionEnd` carry no matcher at
  all — they fire unconditionally on the lifecycle event itself.
- More than one script per event today, not one: `PostToolUse` fires
  `hooks/log-skill-invocation.sh` (D17 stage-1 usage logging) and
  `hooks/lens-coverage/track-lens-reads.sh` (Q23's lens-coverage tracker,
  from both its matcher blocks). `hooks/route.sh` (SessionStart, steers a
  bare "review this" toward the atlas suite), `hooks/queue-session-retro.sh`
  (SessionEnd, D17 stage-1), and `hooks/lens-coverage/gate-lens-coverage.sh`
  (PreToolUse, blocks a review post if lens coverage is missing) round out
  the set. `hooks/lib/feedback-tier.sh` is a shared resolver the logging
  hooks source, not an event handler itself.
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
  `hooks/lens-coverage/` (`track-lens-reads.sh`, `gate-lens-coverage.sh`),
  `collapsed/hooks/` (its mirror)
- `docs/open-questions.md` D17, Q23
- Verified 2026-09-14 (#504) — rewrote the `## Shape` section: added
  `PreToolUse` to the event-key enumeration, corrected the
  "`PostToolUse` is the only one with a `matcher`" claim (`PostToolUse` in
  fact carries two matcher blocks and `PreToolUse` a third), and corrected
  "one script per event" to name every script actually wired per event
- Verified 2026-09-14 @ `1e1079b` — re-checked `hooks/hooks.json:3,13,48`
  against current content (unchanged, still correct); the `## Shape`
  section's omission of the `PreToolUse`/`gate-lens-coverage.sh` hook and
  its now-false "`PostToolUse` is the only one with a `matcher`" claim
  (falsified by `hooks/hooks.json:39`) are tracked separately in #504
  rather than fixed here
- Verified 2026-09-05 @ `33504c1` — documented the `collapsed/hooks/` twin
  and its `route.sh` exception (issue #376)
