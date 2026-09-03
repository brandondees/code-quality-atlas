#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# code-quality-atlas PreToolUse hook -- lens-coverage gate (#357, Q23).
#
# Blocks a review post that attributes a finding to a lens whose body.md/
# SKILL.md was never Read this session -- see track-lens-reads.sh, the
# PostToolUse(Read) companion that builds the evidence this hook checks
# against. This exists because #357 found a live session that loaded one
# lens's bundle and fabricated findings for several more, styled from their
# one-line routing-table descriptions rather than their actual checklists --
# and nothing caught it, because the only "coverage" claim in play was the
# reviewer's own say-so.
#
# Registered with a matcher covering the tool(s) that actually post review
# content, e.g.:
#   mcp__github__pull_request_review_write|mcp__github__add_comment_to_pending_review
# KEEP THAT MATCHER IN SYNC with whatever GitHub MCP server/tool names the
# reviewing session actually uses -- this is a stated, known limitation, not
# a silent one: a differently-named posting tool is simply not gated.
#
# Design choices, stated explicitly:
#   - Infra failure (no jq, malformed hook JSON, no state file yet because no
#     lens has been read at all) fails OPEN -- exit 0, never block on our own
#     breakage or on a repo where lens content isn't vendored/available
#     locally (see track-lens-reads.sh's stated scope gap for the GitHub-API-
#     fetch fallback case).
#   - A cited lens slug is only ever checked against lenses that exist for
#     real on this filesystem (see known_lenses below) -- otherwise an
#     ordinary parenthetical in review prose ("(see below)", "(TODO)") would
#     misread as a phantom lens citation and block an innocent post.
#   - Only a clean, positive signal -- a real lens slug cited with zero
#     matching recorded read -- fails CLOSED (exit 2, blocking the tool call,
#     per Claude Code's PreToolUse blocking contract), with the reason on
#     stderr so the agent can self-correct: load the missing bundle, or drop
#     the attribution if the finding didn't actually come from that lens.
#
# Opt-in and off by default, deliberately -- unlike the telemetry hooks
# (log-skill-invocation.sh, queue-session-retro.sh) which only ever no-op or
# log, THIS hook can block a real tool call, and it hasn't been through this
# repo's own eval-first bar (D8) the way a shipped lens has -- five manual
# scenarios during drafting, no adversarial/cross-model gate. Mirrors the
# Q17/D17 precedent (stage 1 approved, later stages held for evidence): ship
# it inert, let a repo turn it on deliberately, promote to on-by-default only
# once it's run for real without false blocks. Turn on with a
# `lens-coverage-gate: on` line in `.code-quality-atlas/preferences.md`.
#
# bash 3.2 compatible (macOS default), matching tooling/keep-plugin-current.sh.

set -u

input="$(cat)"

command -v jq >/dev/null 2>&1 || exit 0

# TODO before this ships for real: this duplicates ../lib/feedback-tier.sh's
# HTML-comment-stripping + `key: value` extraction instead of sharing it --
# acceptable for a first draft, not for a merged feature (checking-idioms-
# and-consistency would flag the duplication). Factor a generic
# "read one key from preferences.md" helper into lib/ and have both this and
# feedback-tier.sh call it. The comment-stripping below is otherwise the
# exact copy of feedback-tier.sh's own logic and must stay that way -- an
# un-stripped raw grep here previously matched a `lens-coverage-gate: on`
# line sitting inside the preferences template's commented-out example
# block, silently turning the gate on (round-1 review finding).
gate_prefs=".code-quality-atlas/preferences.md"
gate_on=""
if [ -f "$gate_prefs" ]; then
  gate_on="$(awk '
    /<!--.*-->/ { next }
    /<!--/      { incomment=1; next }
    /-->/       { incomment=0; next }
    !incomment  { print }
  ' "$gate_prefs" 2>/dev/null \
    | sed -E 's/[[:space:]]*#.*$//' \
    | grep -m1 -E '^[[:space:]]*lens-coverage-gate:[[:space:]]*on[[:space:]]*$')"
fi
[ -n "$gate_on" ] || exit 0   # opt-in, default off -- see this header

session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
[ -n "$session_id" ] || exit 0
# Defense in depth (Copilot review, PR #398): session_id is interpolated
# straight into a filesystem path below. It's harness-supplied, not
# attacker-controlled in the threat models this hook actually runs under --
# but reject anything outside a safe charset before it ever reaches a path,
# rather than trust that shape by assumption. A rejected session_id is the
# same as an empty one: fail open, this hook only records/gates evidence.
case "$session_id" in
  *[!A-Za-z0-9_-]*) exit 0 ;;
esac

state_file=".claude/.atlas-lens-coverage/$session_id.txt"
# No reads recorded yet this session: nothing to check against, and the
# common case on a repo where the suite isn't vendored/enabled locally at
# all. Fail open rather than block every review on an environment gap this
# hook didn't create.
[ -f "$state_file" ] || exit 0

# Every string leaf anywhere in tool_input, regardless of which posting
# tool's shape this is -- a single inline comment's `body`, a batch
# `comments[]`, or a full review `body` -- so this doesn't need to know each
# posting tool's exact schema.
posted_text="$(printf '%s' "$input" | jq -r '[.tool_input | .. | strings] | join("\n")' 2>/dev/null)"
[ -n "$posted_text" ] || exit 0

# Lenses that exist for real on this filesystem, in either shape a bundle can
# ship in -- the allowlist that keeps an ordinary parenthetical from being
# misread as a lens citation.
known_lenses="$(
  {
    find . -maxdepth 6 -type d -path '*/reference/lenses/*' -not -path '*/.git/*' 2>/dev/null \
      | sed -E 's#.*/reference/lenses/##; s#/.*##'
    find . -maxdepth 3 -type d -path '*/skills/*' -not -path '*/.git/*' 2>/dev/null \
      | sed -E 's#.*/skills/##; s#/.*##'
  } | sort -u
)"
[ -n "$known_lenses" ] || exit 0   # can't tell what a real lens is here -- nothing safe to enforce

# The finding-line convention (skills/synthesizing-review-findings/examples.md):
# "... (lens-slug)." -- pull every parenthesized, lens-slug-shaped token,
# then keep only the ones that are actually a known lens.
cited_lenses="$(
  printf '%s' "$posted_text" \
    | grep -oE '\([a-z][a-z0-9-]+\)' \
    | tr -d '()' \
    | sort -u \
    | comm -12 - <(printf '%s\n' "$known_lenses")
)"
[ -n "$cited_lenses" ] || exit 0   # nothing that resolves to a real lens -- e.g. a plain ACK comment

read_lenses="$(cat "$state_file" 2>/dev/null)"

missing=""
while IFS= read -r slug; do
  [ -n "$slug" ] || continue
  if ! printf '%s\n' "$read_lenses" | grep -Fxq "$slug"; then
    missing="$missing $slug"
  fi
done <<EOF
$cited_lenses
EOF

if [ -n "$missing" ]; then
  printf 'atlas-lens-coverage: this post attributes finding(s) to%s, but that lens'"'"'s body.md/SKILL.md was never Read this session. Load reference/lenses/<lens>/body.md (or skills/<lens>/SKILL.md) for each lens before attributing a finding to it, or drop the attribution if the finding did not actually come from that lens'"'"'s checklist.\n' "$missing" >&2
  exit 2
fi

exit 0
