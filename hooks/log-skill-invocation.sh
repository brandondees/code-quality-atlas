#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
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
# Abstracted, not raw (#364): this hook does not try to parse which skill/lens
# was invoked out of `tool_input` — that shape isn't documented for the Skill
# tool as of this writing, and guessing a field name wrong would silently
# drop data. Rather than store the payload itself (which can carry file
# contents, paths, or other reviewed-repo material the design promises stays
# abstracted), it records only the payload's byte length and, when a hashing
# tool is on PATH (sha256sum or shasum — best-effort, not guaranteed: the
# digest is `null` on a system with neither, while the length is still
# recorded), a SHA-256 digest — enough for a later analysis pass (§3.4) to
# see that invocations happened and whether their inputs repeat or change
# shape, without capturing what they contained.
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
# A missing/unreadable lib can't tell us the tier at all, so this exits the
# same way "off" would rather than let `set -u` and no lib functions defined
# fail loudly out from under `source` (#365).
[ -f "$_lib" ] || exit 0
# shellcheck source=lib/feedback-tier.sh
source "$_lib"

_tier="$(feedback_tier)"
case "$_tier" in
  local) ;;
  draft | auto)
    # Stages 2+ (drafting a PR comment, auto-posting it) are unbuilt — both
    # tiers are accepted and currently behave exactly like "local" (#365).
    # One trace line so an operator who deliberately opted into draft/auto
    # isn't left assuming they got that tier's not-yet-existing behavior.
    printf 'code-quality-atlas: feedback tier %s is not yet distinguished from local\n' \
      "$_tier" >&2
    ;;
  *) exit 0 ;;
esac

if ! command -v jq >/dev/null 2>&1; then
  printf 'code-quality-atlas: jq not found on PATH; skipping this invocation\n' >&2
  exit 0
fi

log_dir="$(_code_quality_atlas_project_dir)/.code-quality-atlas/learnings"
if ! mkdir -p "$log_dir" 2>/dev/null; then
  printf 'code-quality-atlas: could not create %s; skipping this invocation\n' "$log_dir" >&2
  exit 0
fi

plugin_sha=""
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  plugin_sha="$(git -C "$CLAUDE_PLUGIN_ROOT" rev-parse HEAD 2>/dev/null || true)"
fi

# Compact tool_input first so length/hash are computed over one canonical
# serialization rather than whatever whitespace the caller happened to send.
# -cS (sorted keys) so two equivalent payloads with reordered keys hash the
# same; an explicit `if == null` (not `// null`) so a genuinely falsy but
# present value (e.g. tool_input: false) is preserved rather than folded
# into the same "no input" bucket as an absent/null tool_input.
tool_input_json="$(printf '%s' "$input" | jq -cS 'if .tool_input == null then null else .tool_input end' 2>/dev/null)"
[ -n "$tool_input_json" ] || exit 0   # malformed stdin JSON: nothing sane to append, skip silently

tool_input_len=0
tool_input_sha256=""
if [ "$tool_input_json" != "null" ]; then
  tool_input_len="$(printf '%s' "$tool_input_json" | wc -c | tr -d ' [:space:]')"
  if command -v sha256sum >/dev/null 2>&1; then
    tool_input_sha256="$(printf '%s' "$tool_input_json" | sha256sum | cut -d' ' -f1)"
  elif command -v shasum >/dev/null 2>&1; then
    tool_input_sha256="$(printf '%s' "$tool_input_json" | shasum -a 256 | cut -d' ' -f1)"
  fi
fi

record="$(printf '%s' "$input" | jq -c \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg plugin_sha "$plugin_sha" \
  --argjson tool_input_len "${tool_input_len:-0}" \
  --arg tool_input_sha256 "$tool_input_sha256" \
  '{
    ts: $ts,
    plugin_sha: (if $plugin_sha == "" then null else $plugin_sha end),
    session_id: (.session_id // null),
    tool_name: (.tool_name // null),
    tool_input_len: $tool_input_len,
    tool_input_sha256: (if $tool_input_sha256 == "" then null else $tool_input_sha256 end)
  }' 2>/dev/null)"

[ -n "$record" ] || exit 0   # malformed stdin JSON (shouldn't happen — already checked above): skip silently

_code_quality_atlas_append "$log_dir/invocations.jsonl" "$record"

exit 0
