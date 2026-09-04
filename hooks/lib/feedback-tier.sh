# shellcheck shell=bash
# SPDX-License-Identifier: MIT
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
# every other tier's default-off, no-op-until-configured behavior. A *set*
# env var that isn't one of the four known tiers is treated the same way —
# terminal "off", not a fall-through to the preferences file (#365): an
# operator who deliberately set the override (even to a typo) gets the
# safe default, not a value from a different precedence layer they didn't
# ask this call site to consult.
#
# bash 3.2 compatible (macOS default), matching tooling/keep-plugin-current.sh.

_CODE_QUALITY_ATLAS_FEEDBACK_TIERS="off local draft auto"

# Every append this feedback loop makes goes through _code_quality_atlas_append
# below, so every hook script agrees on where the log directory lives and how
# writes to it are guarded — defined once here rather than duplicated across
# log-skill-invocation.sh and queue-session-retro.sh (and their collapsed/
# mirrors), which must stay byte-identical to this file's siblings anyway.
_CODE_QUALITY_ATLAS_LOG_SIZE_CAP=$((5 * 1024 * 1024))  # 5 MiB; no rotation/TTL yet (#365)

_code_quality_atlas_valid_tier() {
  local t="$1" candidate
  for candidate in $_CODE_QUALITY_ATLAS_FEEDBACK_TIERS; do
    [ "$t" = "$candidate" ] && return 0
  done
  return 1
}

# Anchored to the project root via $CLAUDE_PROJECT_DIR when the harness sets
# it, matching lens-coverage/track-lens-reads.sh's established pattern —
# a hook can run with a working directory other than the project root, and
# a ratified `.code-quality-atlas/preferences.md` (or an enabled log
# destination) must resolve the same way regardless (#365). Falls back to
# the existing cwd-relative behavior when unset.
_code_quality_atlas_project_dir() {
  printf '%s' "${CLAUDE_PROJECT_DIR:-.}"
}

feedback_tier() {
  local env_tier="${CODE_QUALITY_ATLAS_FEEDBACK_TIER:-}"
  if [ -n "$env_tier" ]; then
    if _code_quality_atlas_valid_tier "$env_tier"; then
      printf '%s' "$env_tier"
    else
      printf 'off'
    fi
    return 0
  fi

  local prefs file_tier
  prefs="$(_code_quality_atlas_project_dir)/.code-quality-atlas/preferences.md"
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
    # line further down, resolving to "off" with no error. Strip a trailing
    # `# ...` inline comment next (#251 — the template's own shown format,
    # `feedback: local      # off (default...) | local (...`, carries one;
    # the strict end-anchored grep below would otherwise silently miss a
    # team's correctly-ratified line — copied verbatim from the template —
    # and fall through to "off" with no error). Then take the first
    # `feedback: <value>` line, checked against the same tier list this file
    # already keeps as the single source of truth (#365 — this grep and
    # _CODE_QUALITY_ATLAS_FEEDBACK_TIERS previously named the four tiers
    # twice, so adding/renaming one meant remembering both spots).
    file_tier="$(awk '
      /<!--.*-->/ { next }
      /<!--/      { incomment=1; next }
      /-->/       { incomment=0; next }
      !incomment  { print }
    ' "$prefs" 2>/dev/null \
      | sed -E 's/[[:space:]]*#.*$//' \
      | grep -m1 -E "^[[:space:]]*feedback:[[:space:]]*($(printf '%s' "$_CODE_QUALITY_ATLAS_FEEDBACK_TIERS" | tr ' ' '|'))[[:space:]]*\$" \
      | sed -E 's/^[[:space:]]*feedback:[[:space:]]*//; s/[[:space:]]*$//')"
    if [ -n "$file_tier" ] && _code_quality_atlas_valid_tier "$file_tier"; then
      printf '%s' "$file_tier"
      return 0
    fi
  fi

  printf 'off'
}

# Appends one line to $1, called only once a hook has already confirmed its
# tier is non-off — so every trace line below fires exactly on a genuine
# degradation of an opted-in destination, never as noise for the (default,
# silent) off case. Three protections, all from #365:
#   - refuses a destination that exists but is a symlink or any other
#     non-regular file (a cloned repo could ship the log path as a symlink
#     pointing outside the tree, and this hook would otherwise happily
#     append there);
#   - refuses once the file has grown past a size cap, since nothing here
#     rotates or expires old entries yet;
#   - serializes concurrent writers with a `mkdir`-based lock (portable,
#     atomic, bash-3.2-safe) rather than risking two hooks' `printf >>`
#     interleaving mid-line — a single write(2) is only guaranteed atomic up
#     to PIPE_BUF (~4 KiB), and two sessions in the same project both opted
#     into feedback can fire this at the same moment. The retry is bounded
#     (a handful of short attempts) and falls through to an unlocked append
#     rather than blocking indefinitely — every hook in this suite must stay
#     milliseconds-cheap and never delay the tool call it's attached to, so
#     losing the lock race degrades this one line's atomicity guarantee
#     rather than the hook's responsiveness.
_code_quality_atlas_append() {
  local target="$1" line="$2" lock_dir size attempt locked
  # -L is checked independently of, and before, -e: -e follows a symlink
  # and reports on its TARGET, so a symlink pointing at a not-yet-existing
  # path outside the repo (the exact shape a cloned-in-Git symlink can have
  # before anything has ever written through it) makes `[ -e "$target" ]`
  # false and would otherwise skip this whole guard, letting the append
  # below create the very file the symlink points at.
  if [ -L "$target" ]; then
    printf 'code-quality-atlas: refusing to write to %s (it is a symlink)\n' \
      "$target" >&2
    return 1
  fi
  if [ -e "$target" ]; then
    if [ ! -f "$target" ]; then
      printf 'code-quality-atlas: refusing to write to %s (not a regular file)\n' \
        "$target" >&2
      return 1
    fi
    size="$(wc -c <"$target" 2>/dev/null | tr -d '[:space:]')"
    case "$size" in
      '' | *[!0-9]*) size=0 ;;
    esac
    if [ "$size" -ge "$_CODE_QUALITY_ATLAS_LOG_SIZE_CAP" ]; then
      printf 'code-quality-atlas: %s has reached its size cap; skipping this line\n' \
        "$target" >&2
      return 1
    fi
  fi

  lock_dir="${target}.lock"
  locked=0
  attempt=0
  while [ "$attempt" -lt 5 ]; do
    if mkdir "$lock_dir" 2>/dev/null; then
      locked=1
      break
    fi
    attempt=$((attempt + 1))
    sleep 0.02 2>/dev/null || true
  done
  printf '%s\n' "$line" >>"$target" 2>/dev/null
  [ "$locked" -eq 1 ] && rmdir "$lock_dir" 2>/dev/null
  return 0
}
