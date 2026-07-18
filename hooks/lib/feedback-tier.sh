# code-quality-atlas — shared feedback-tier resolution (Q17/D17 stage 1).
#
# Resolves which opt-in tier the reviewed repo has enabled for the
# self-improvement loop (docs/self-improvement-loop.md §5): off (default),
# local, draft, or auto. Meant to be `source`d by the PostToolUse/SessionEnd
# hooks in this directory, then called as `feedback_tier`, which prints one
# of the four tier names to stdout.
#
# Precedence: the CODE_QUALITY_ATLAS_FEEDBACK_TIER env var (a harness-level
# override, e.g. for CI) beats a `feedback:` line under the reviewed repo's
# own `.code-quality-atlas/preferences.md`, which beats the default "off".
# Any ambiguity — missing file, no Feedback section, a malformed value —
# resolves to "off": these hooks must never turn on by accident, matching
# every other tier's default-off, no-op-until-configured behavior.
#
# bash 3.2 compatible (macOS default), matching tooling/keep-plugin-current.sh.

_CODE_QUALITY_ATLAS_FEEDBACK_TIERS="off local draft auto"

_code_quality_atlas_valid_tier() {
  local t="$1" candidate
  for candidate in $_CODE_QUALITY_ATLAS_FEEDBACK_TIERS; do
    [ "$t" = "$candidate" ] && return 0
  done
  return 1
}

feedback_tier() {
  local env_tier="${CODE_QUALITY_ATLAS_FEEDBACK_TIER:-}"
  if [ -n "$env_tier" ] && _code_quality_atlas_valid_tier "$env_tier"; then
    printf '%s' "$env_tier"
    return 0
  fi

  local prefs=".code-quality-atlas/preferences.md" file_tier
  if [ -f "$prefs" ]; then
    # The template ships every example commented out inside HTML comment
    # blocks (only a ratified, uncommented line counts) — usually with the
    # `<!--`/`-->` markers each on their own line, but a hand-edited file can
    # just as well carry a self-contained single-line comment (e.g. `<!--
    # ratified 2026-01-01 -->`). Strip those first (the `/<!--.*-->/ { next }`
    # rule, checked before the multi-line-open rule so it wins via `next` when
    # a line matches both) so a one-line comment earlier in the file can never
    # leave `incomment` stuck on for everything after it — that previously let
    # a single-line comment silently swallow a real, ratified `feedback:`
    # line further down, resolving to "off" with no error. Then take the
    # first `feedback: <value>` line restricted to the four known tiers.
    file_tier="$(awk '
      /<!--.*-->/ { next }
      /<!--/      { incomment=1; next }
      /-->/       { incomment=0; next }
      !incomment  { print }
    ' "$prefs" 2>/dev/null \
      | grep -m1 -E '^[[:space:]]*feedback:[[:space:]]*(off|local|draft|auto)[[:space:]]*$' \
      | sed -E 's/^[[:space:]]*feedback:[[:space:]]*//; s/[[:space:]]*$//')"
    if [ -n "$file_tier" ] && _code_quality_atlas_valid_tier "$file_tier"; then
      printf '%s' "$file_tier"
      return 0
    fi
  fi

  printf 'off'
}
