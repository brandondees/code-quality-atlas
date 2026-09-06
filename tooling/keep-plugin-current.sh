#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# tooling/keep-plugin-current.sh
#
# Opt-in helper: keep a Claude Code plugin install current across EVERY scope.
#
# Plugin installs are git-SHA-pinned per scope in
# ~/.claude/plugins/installed_plugins.json and do NOT auto-update unless you turn
# on auto-update (interactive installs) or use the settings-based install (which
# reinstalls fresh each session). This script is for the remaining case: an
# interactive cached install you want to keep current without remembering to run
# `/plugin marketplace update` by hand. It refreshes the marketplace clone, then
# re-pins the user scope and every project scope to the latest commit.
#
# A Claude restart is still required to APPLY an update — this only stages the
# new version so the NEXT session is current.
#
# Usage:
#   tooling/keep-plugin-current.sh                       # default: this plugin
#   tooling/keep-plugin-current.sh <plugin@marketplace>  # any plugin
#   tooling/keep-plugin-current.sh --user-only [<p@m>]   # skip project scopes
#
# Wire it up yourself (NOT shipped as an auto-running plugin hook — it runs
# update commands and so is deliberately left to the operator). Example: throttle
# it to ~once/day from your personal ~/.claude/settings.json SessionStart hook —
# see docs/install.md "Keeping an interactive install current" section.
#
# bash 3.2 compatible (macOS default).

set -u

DEFAULT_PLUGIN="code-quality-atlas@code-quality-atlas"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
INSTALLED="$CLAUDE_DIR/plugins/installed_plugins.json"

user_only=0
plugin=""
for arg in "$@"; do
  case "$arg" in
    --user-only) user_only=1 ;;
    -h|--help)
      # Print the leading comment header (after shebang + SPDX), stripping "# ".
      # Reads until the first non-comment line, so there's no line range to keep
      # in sync as the header grows.
      awk 'NR<=2 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
      exit 0 ;;
    -*) printf 'Error: unknown option: %s\n' "$arg" >&2; exit 2 ;;
    *) plugin="$arg" ;;
  esac
done
[ -n "$plugin" ] || plugin="$DEFAULT_PLUGIN"

# marketplace is the part after the '@' (the marketplace name the plugin came from)
marketplace="${plugin#*@}"
if [ "$marketplace" = "$plugin" ]; then
  printf 'Error: expected <plugin@marketplace>, got: %s\n' "$plugin" >&2
  exit 2
fi

check_requirements() {
  local missing=0 bin
  for bin in claude jq; do
    if ! command -v "$bin" >/dev/null 2>&1; then
      printf 'Error: required command not found: %s\n' "$bin" >&2
      missing=1
    fi
  done
  return "$missing"
}
check_requirements || exit 1

# Single-instance guard (#389 dees-bot finding): the recommended SessionStart
# wiring in docs/install.md now writes its throttle stamp only after this
# script exits 0 (fixing a silent-failure bug), which widens the window
# during which several session starts in quick succession could each see a
# stale/missing stamp and launch their own concurrent run -- racing `claude
# plugin update` invocations and git operations against the same marketplace
# clone. `mkdir` is atomic even across processes/machines sharing $CLAUDE_DIR,
# and portable to bash 3.2/macOS with no extra dependency (no flock there).
# Best-effort only: a lock left behind by a killed process blocks future runs
# until removed by hand -- an accepted trade-off over the alternative (no
# guard at all).
# A nonzero exit here matters, not just for this script's own caller: the
# recommended SessionStart wrapper only writes its throttle stamp when this
# script exits 0, specifically so a run that did NOT complete an update never
# resets the throttle (issue #389 CodeRabbit round-2 finding -- an earlier
# version of this guard exited 0 on lock contention, which meant a session
# that merely detected another run in progress would still stamp the
# throttle on the wrapper's behalf, exactly the silent-reset bug the wrapper
# fix was meant to close, just moved here instead).
LOCK_DIR="$CLAUDE_DIR/.keep-plugin-current.lock"
if ! mkdir -p "$CLAUDE_DIR" 2>/dev/null; then
  printf 'Error: could not create %s\n' "$CLAUDE_DIR" >&2
  exit 1
fi
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  printf 'Error: another keep-plugin-current.sh run appears to be in progress (%s exists) -- skipping to avoid racing it. If no run is actually active (e.g. a previous run was killed), remove %s and retry.\n' "$LOCK_DIR" "$LOCK_DIR" >&2
  exit 1
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# Each `claude` call can fail (network, auth, a bad scope). Track that instead of
# letting the final success line print unconditionally — an operator who restarts
# on a false "Done" would still be on the old version. We deliberately do NOT use
# `set -e`: one failing project scope must not abort the remaining updates.
fail=0

printf 'Refreshing marketplace %s…\n' "$marketplace"
claude plugin marketplace update "$marketplace" \
  || { printf '  Error: marketplace refresh failed\n' >&2; fail=1; }

printf 'Updating %s (user scope)…\n' "$plugin"
claude plugin update "$plugin" --scope user \
  || { printf '  Error: user-scope update failed\n' >&2; fail=1; }

# Every project-scope install, enumerated from installed_plugins.json, so new
# projects are picked up automatically without editing this script. A missing
# file (no project-scope installs yet — the [ -f ] guard above) is fine and
# silent; a malformed/unreadable one is not (#389: this used to silence jq's
# stderr unconditionally via process substitution, so a bad file produced
# zero loop iterations with jq's own exit status nowhere to check, and still
# printed "Done" — a false all-clear with zero project scopes actually
# checked). Capture jq's output (and, on failure, its stderr) into a variable
# first so `$?` right after is jq's own status, then feed the captured text
# to the loop via a herestring — same "loop runs in THIS shell" property
# process substitution gave, without losing jq's exit status to it.
if [ "$user_only" -eq 0 ] && [ -f "$INSTALLED" ]; then
  project_paths="$(jq -r --arg k "$plugin" \
      '.plugins[$k][]? | select(.scope == "project") | .projectPath // empty' \
      "$INSTALLED" 2>&1)"
  jq_status=$?
  if [ "$jq_status" -ne 0 ]; then
    printf '  Error: could not read project-scope installs from %s: %s\n' "$INSTALLED" "$project_paths" >&2
    fail=1
  else
    while IFS= read -r proj; do
      [ -z "$proj" ] && continue
      if [ -d "$proj" ]; then
        printf 'Updating %s (project scope: %s)…\n' "$plugin" "$proj"
        ( cd "$proj" && claude plugin update "$plugin" --scope project ) \
          || { printf '  Error: project-scope update failed: %s\n' "$proj" >&2; fail=1; }
      else
        printf 'skipped (project path missing): %s\n' "$proj" >&2
      fi
    done <<< "$project_paths"
  fi
fi

if [ "$fail" -ne 0 ]; then
  printf 'Error: one or more updates failed -- you may still be on the old version (see errors above).\n' >&2
  exit 1
fi
printf 'Done. Restart Claude to apply staged updates.\n'
