#!/usr/bin/env bash
# code-quality-atlas SessionEnd hook — Q17/D17 stage 1 ("Process notes + local
# log"). Queues the just-ended session's transcript for later post-hoc
# digestion (docs/self-improvement-loop.md §3.4's `/atlas-retro`, stage 2+,
# unbuilt) instead of doing any analysis here — this hook stays
# milliseconds-cheap and does no LLM work and no network, by design.
#
# Opt-in and off by default: no-ops unless the reviewed repo has turned the
# feedback loop on (see hooks/lib/feedback-tier.sh and
# docs/self-improvement-loop.md §5). When on, appends one compact JSON line
# per session to `.code-quality-atlas/learnings/pending-retro.jsonl` in the
# project's working directory: the transcript path, the plugin commit SHA
# (D9 — so a later regeneration's champion/challenger comparison knows which
# suite version reviewed), and why the session ended.
#
# Always exits 0 — a broken or absent dependency (jq), an unwritable
# directory, or malformed input degrades to "don't queue this one", never to
# blocking or delaying session teardown.
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

command -v jq >/dev/null 2>&1 || exit 0   # no jq: skip queuing rather than guess-parse JSON by hand

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
    transcript_path: (.transcript_path // null),
    reason: (.reason // null)
  }' 2>/dev/null)"

[ -n "$record" ] || exit 0   # malformed stdin JSON: nothing sane to append, skip silently

printf '%s\n' "$record" >> "$log_dir/pending-retro.jsonl" 2>/dev/null

exit 0
