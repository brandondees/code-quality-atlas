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
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) plugin="$arg" ;;
  esac
done
[ -n "$plugin" ] || plugin="$DEFAULT_PLUGIN"

# marketplace is the part after the '@' (the marketplace name the plugin came from)
marketplace="${plugin#*@}"
if [ "$marketplace" = "$plugin" ]; then
  echo "expected <plugin@marketplace>, got: $plugin" >&2
  exit 2
fi

check_requirements() {
  local missing=0 bin
  for bin in claude jq; do
    if ! command -v "$bin" >/dev/null 2>&1; then
      echo "error: required command not found: $bin" >&2
      missing=1
    fi
  done
  return "$missing"
}
check_requirements || exit 1

# Each `claude` call can fail (network, auth, a bad scope). Track that instead of
# letting the final success line print unconditionally — an operator who restarts
# on a false "Done" would still be on the old version. We deliberately do NOT use
# `set -e`: one failing project scope must not abort the remaining updates.
fail=0

echo "Refreshing marketplace '$marketplace'…"
claude plugin marketplace update "$marketplace" \
  || { echo "  marketplace refresh failed" >&2; fail=1; }

echo "Updating '$plugin' (user scope)…"
claude plugin update "$plugin" --scope user \
  || { echo "  user-scope update failed" >&2; fail=1; }

# Every project-scope install, enumerated from installed_plugins.json, so new
# projects are picked up automatically without editing this script. Read via
# process substitution (not a pipe) so the loop runs in THIS shell and `fail`
# survives it. A missing/malformed JSON file is tolerated (jq stderr silenced) —
# that's the one place we intentionally keep silent-OK semantics.
if [ "$user_only" -eq 0 ] && [ -f "$INSTALLED" ]; then
  while IFS= read -r proj; do
    [ -z "$proj" ] && continue
    if [ -d "$proj" ]; then
      echo "Updating '$plugin' (project scope: $proj)…"
      ( cd "$proj" && claude plugin update "$plugin" --scope project ) \
        || { echo "  project-scope update failed: $proj" >&2; fail=1; }
    else
      echo "skipped (project path missing): $proj" >&2
    fi
  done < <(jq -r --arg k "$plugin" \
      '.plugins[$k][]? | select(.scope == "project") | .projectPath // empty' \
      "$INSTALLED" 2>/dev/null)
fi

if [ "$fail" -ne 0 ]; then
  echo "One or more updates FAILED — you may still be on the old version (see errors above)." >&2
  exit 1
fi
echo "Done. Restart Claude to apply staged updates."
