#!/usr/bin/env bash
# code-quality-atlas PostToolUse(Skill) hook — Q17/D17 stage 1 ("Process notes
# + local log"). Registered in hooks.json with matcher "Skill", so it fires
# once per skill invocation and receives that invocation's hook JSON on stdin.
#
# Opt-in and off by default: no-ops unless the reviewed repo has turned the
# feedback loop on (see hooks/lib/feedback-tier.sh and
# docs/self-improvement-loop.md §5). When on, appends one compact JSON line
# per invocation to `.code-quality-atlas/learnings/invocations.jsonl` in the
# project's working directory — the missing lens-invocation evidence Q14
# needed ("the suite emits no naming findings in practice" was inferred, never
# measured) and S1 (routing miss)/S5 (contract violation) capture material for
# a future retro pass (docs/self-improvement-loop.md §3.4, stage 2+, unbuilt).
#
# Deliberately raw: this hook does not try to parse which skill/lens was
# invoked out of `tool_input` — that shape isn't documented for the Skill
# tool as of this writing, and guessing a field name wrong would silently
# drop data. It stores `tool_input` verbatim; a later analysis pass (§3.4)
# parses whatever shape it turns out to be, once, instead of every one of
# these hook invocations guessing.
#
# Always exits 0 — a broken or absent dependency (jq), an unwritable
# directory, or malformed input degrades to "don't log this one", never to
# blocking or slowing down the tool call. Milliseconds-cheap, no LLM work,
# no network (docs/self-improvement-loop.md §3.1).
#
# bash 3.2 compatible (macOS default), matching tooling/keep-plugin-current.sh.

set -u

input="$(cat)"   # drain stdin unconditionally so the caller never blocks on a full pipe

# Resolve the sibling lib relative to CLAUDE_PLUGIN_ROOT when the plugin runtime
# set it (the normal case); fall back to this script's own directory so the
# hook is also runnable directly (manual testing, this repo's own test suite).
_hook_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  _lib="${CLAUDE_PLUGIN_ROOT}/hooks/lib/feedback-tier.sh"
else
  _lib="${_hook_dir}/lib/feedback-tier.sh"
fi
# shellcheck source=lib/feedback-tier.sh
source "$_lib"

case "$(feedback_tier)" in
  local|draft|auto) ;;
  *) exit 0 ;;
esac

command -v jq >/dev/null 2>&1 || exit 0   # no jq: skip logging rather than guess-parse JSON by hand

log_dir=".code-quality-atlas/learnings"
mkdir -p "$log_dir" 2>/dev/null || exit 0

plugin_sha=""
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  plugin_sha="$(git -C "$CLAUDE_PLUGIN_ROOT" rev-parse HEAD 2>/dev/null || true)"
fi

record="$(printf '%s' "$input" | jq -c \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg plugin_sha "$plugin_sha" \
  '{
    ts: $ts,
    plugin_sha: (if $plugin_sha == "" then null else $plugin_sha end),
    session_id: (.session_id // null),
    tool_name: (.tool_name // null),
    tool_input: (.tool_input // null)
  }' 2>/dev/null)"

[ -n "$record" ] || exit 0   # malformed stdin JSON: nothing sane to append, skip silently

printf '%s\n' "$record" >> "$log_dir/invocations.jsonl" 2>/dev/null

exit 0
