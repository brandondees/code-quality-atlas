#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# tooling/vendor-skills.sh
#
# Vendor the suite's skills into a TARGET repo's .claude/skills/ so they load in
# that repo's Claude Code sessions — including web/cloud, where marketplace plugins
# do NOT load (see docs/distribution.md). Committing the bodies is the one path the
# cloud docs confirm ("skills committed to the cloned repository"); it fetches
# nothing at runtime.
#
# Copies each skill's runtime resources — SKILL.md, reference/, examples.md — and
# excludes the dev-only evals/. Idempotent: re-running refreshes in place. A marker
# (.claude/skills/.atlas-vendored) records which skills this tool placed and the
# source commit, so --prune can safely remove only previously-vendored skills that
# have since left the suite — never the target repo's own skills.
#
# The vendored content (docs/ and skills/, per LICENSE) is CC BY 4.0, which
# requires attribution on redistribution — satisfied by a link back to this
# repository. Each run writes/refreshes a NOTICE file alongside the vendored
# skills so that attribution travels with the copy.
#
# Usage:
#   tooling/vendor-skills.sh <target-repo-dir>               # vendor/refresh
#   tooling/vendor-skills.sh <target-repo-dir> --collapsed   # vendor the 4 collapsed entrypoints instead
#   tooling/vendor-skills.sh <target-repo-dir> --prune       # also drop stale vendored skills
#   tooling/vendor-skills.sh <target-repo-dir> --force       # overwrite a colliding non-vendored dir
#   tooling/vendor-skills.sh <target-repo-dir> --with-lens-coverage-hook
#                                                             # also vendor the #357/Q23
#                                                             # lens-coverage enforcement hook
#
# After running, review and commit the .claude/skills/ changes in the target repo.
#
# bash 3.2 compatible (macOS default).

set -euo pipefail

REQUIRED_PROGRAMS=("git")

TARGET=""
PRUNE=0
FORCE=0
WITH_LENS_COVERAGE_HOOK=0
SUBDIR=".claude/skills"
MARKER_NAME=".atlas-vendored"
# Which tree to vendor: the 44 standalone skills (default) or the 4 collapsed
# entrypoints (--collapsed).
SRC_SUBDIR="skills"
# Destination for --with-lens-coverage-hook's two scripts, relative to the
# target repo root. Deliberately NOT under .claude/skills/ (SUBDIR) — that
# tree's contents are Skill-tool-loaded bundles governed by the
# .atlas-vendored marker/--prune machinery above; the hook scripts are
# neither, so they get their own destination and their own (much simpler)
# no-prune vendoring below.
HOOK_SUBDIR=".claude/hooks/lens-coverage"

usage() {
  cat <<'EOF'
Usage: tooling/vendor-skills.sh <target-repo-dir> [--collapsed] [--prune] [--force]

Copies skills/<name>/{SKILL.md, reference/, examples.md} (no evals/) into
<target-repo-dir>/.claude/skills/<name>/. Run the script from inside the
code-quality-atlas clone; pass the OTHER repo as the argument.

Arguments:
  target-repo-dir   Repo to vendor the suite into (its .claude/skills/ is written)

Options:
  --collapsed   Vendor the 4 collapsed entrypoints (collapsed/skills/) instead of
                the 44 standalone skills (skills/)
  --prune       Remove skills previously vendored by this tool that are no longer
                in the suite (safe: only touches names recorded in the marker)
  --force       Overwrite a target directory at a colliding skill name even if
                it wasn't vendored by a prior run of this tool (default: skip
                it with a warning and a non-zero exit; see the marker check
                in vendor_one)
  --with-lens-coverage-hook
                Also vendor the #357/Q23 lens-coverage enforcement hook: two
                scripts copied to .claude/hooks/lens-coverage/, plus a
                PostToolUse(Read)/PreToolUse hook wiring merged (not
                clobbered) into the target repo's .claude/settings.json.
                Explicit opt-in, separate from the hook's OWN opt-in
                enforcement gate (a `lens-coverage-gate: on` line in the
                target repo's .code-quality-atlas/preferences.md) --
                writing hook execution into a consumer's settings.json is a
                more sensitive action than copying skill markdown, so this
                is never vendored implicitly. Requires jq. No --prune
                equivalent yet: turning this flag off on a later run does
                NOT retract already-vendored hook wiring (see
                vendor_lens_coverage_hook's own header).
  -h, --help    Show this help

External tools:
  git
  jq   (only required when --with-lens-coverage-hook is passed)

Examples:
  tooling/vendor-skills.sh ~/code/my-service
  tooling/vendor-skills.sh ~/code/my-service --prune
  tooling/vendor-skills.sh ~/code/my-service --with-lens-coverage-hook
EOF
}

check_requirements() {
  local missing=0
  local program
  local required=("${REQUIRED_PROGRAMS[@]}")
  # jq is only needed to merge (not clobber) the target's .claude/settings.json
  # for --with-lens-coverage-hook -- every other path in this script has never
  # needed it, so it stays out of the always-required list.
  [ "$WITH_LENS_COVERAGE_HOOK" -eq 1 ] && required+=("jq")
  for program in "${required[@]}"; do
    if ! command -v "$program" >/dev/null 2>&1; then
      printf 'Error: Required program %s is not installed or not on PATH. Please install it first.\n' "$program" >&2
      missing=1
    fi
  done
  if [ "$missing" -ne 0 ]; then
    printf '\n' >&2
    usage >&2
    return 1
  fi
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --collapsed) SRC_SUBDIR="collapsed/skills" ;;
      --prune) PRUNE=1 ;;
      --force) FORCE=1 ;;
      --with-lens-coverage-hook) WITH_LENS_COVERAGE_HOOK=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      -*)
        printf 'Error: Unknown option: %s\n\n' "$1" >&2
        usage >&2
        exit 1
        ;;
      *)
        if [ -n "$TARGET" ]; then
          printf 'Error: unexpected extra argument: %s\n\n' "$1" >&2
          usage >&2
          exit 1
        fi
        TARGET=$1
        ;;
    esac
    shift
  done

  if [ -z "$TARGET" ]; then
    printf 'Error: a target repo directory is required.\n\n' >&2
    usage >&2
    exit 1
  fi
  if [ ! -d "$TARGET" ]; then
    printf 'Error: target is not a directory: %s\n' "$TARGET" >&2
    exit 1
  fi
}

# Echo the source repo root (the code-quality-atlas clone), or fail.
repo_root() {
  local root
  if root=$(git rev-parse --show-toplevel 2>/dev/null) && [ -d "$root/skills" ]; then
    printf '%s\n' "$root"
    return 0
  fi
  local here
  here=$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)
  if [ -n "$here" ] && [ -d "$here/skills" ]; then
    printf '%s\n' "$here"
    return 0
  fi
  printf 'Error: run this from inside the code-quality-atlas clone (no skills/ found).\n' >&2
  return 1
}

# Populate SKILL_NAMES (bash 3.2: no mapfile).
collect_skill_names() {
  SKILL_NAMES=()
  local md name
  for md in "$SRC_SUBDIR"/*/SKILL.md; do
    [ -e "$md" ] || continue
    name=$(basename "$(dirname "$md")")
    SKILL_NAMES+=("$name")
  done
  if [ "${#SKILL_NAMES[@]}" -eq 0 ]; then
    printf 'Error: no %s/*/SKILL.md found under %s\n' "$SRC_SUBDIR" "$(pwd)" >&2
    return 1
  fi
}

contains() {
  local needle=$1
  shift
  local item
  for item in "$@"; do
    [ "$item" = "$needle" ] && return 0
  done
  return 1
}

# Appends a trailing, do-not-edit marker to a vendored SKILL.md — the file an
# agent asked to "fix lens X" is actually likely to open and edit directly
# (it's literally what the Skill tool resolves and loads), unlike the
# directory-level .atlas-vendored marker / NOTICE.md that don't sit next to
# it. Appended at the very END of the file, never before the frontmatter
# fence, so it can never interfere with frontmatter parsing.
# reference/*.md and examples.md deliberately do NOT get this — SKILL.md is
# the concrete edit target the finding named, and marking every runtime file
# would multiply the sync-test's stripping logic for little added benefit.
append_generated_marker() {
  local file=$1 name=$2
  {
    printf '\n<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh\n'
    printf '     from %s/%s/SKILL.md in code-quality-atlas.\n' "$SRC_SUBDIR" "$name"
    printf '     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->\n'
  } >>"$file"
}

vendor_one() {
  local name=$1 dest_root=$2
  local src="$SRC_SUBDIR/$name"
  # Guard dest_root directly, not just the concatenated dest: "$dest_root/$name"
  # is never empty even when dest_root is (it's still "/$name"), so a dest-only
  # guard can't catch an empty dest_root widening the delete to a rooted path.
  local dest="${dest_root:?}/$name"

  # Refuse to clobber a pre-existing, non-tool-managed directory at this skill
  # name: if $dest already exists but isn't recorded in the marker from a
  # prior run of this tool (OLD_NAMES, populated by main() before this loop),
  # a target repo's own unrelated content there would otherwise be silently
  # destroyed by the unconditional `rm -rf` below (#175). --force overrides.
  if [ -e "$dest" ] && [ "$FORCE" -ne 1 ]; then
    local already_owned=1
    if [ "${#OLD_NAMES[@]}" -gt 0 ] && contains "$name" "${OLD_NAMES[@]}"; then
      already_owned=0
    fi
    if [ "$already_owned" -ne 0 ]; then
      printf 'Warning: %s already exists and was not vendored by a prior run of this tool; skipping (pass --force to overwrite it).\n' "$dest" >&2
      SKIPPED_COLLISIONS+=("$name")
      return 0
    fi
  fi

  rm -rf "${dest:?}"
  mkdir -p "$dest"
  cp "$src/SKILL.md" "$dest/SKILL.md"
  append_generated_marker "$dest/SKILL.md" "$name"
  [ -f "$src/examples.md" ] && cp "$src/examples.md" "$dest/examples.md"
  [ -d "$src/reference" ] && cp -R "$src/reference" "$dest/reference"
  return 0
}

# The skill content copied by vendor_one is CC BY 4.0 (LICENSE-CC-BY-4.0), which
# requires attribution on redistribution. Vendor the actual license text
# alongside the notice — not just a link to it — so a target repo's copy is
# self-contained and doesn't depend on a live fetch from GitHub to see the
# terms it's actually operating under (issue #1157, filed against a consumer
# repo whose copy had only the link).
write_attribution() {
  local dest_root=$1 sha=$2
  cp "LICENSE-CC-BY-4.0" "$dest_root/LICENSE-CC-BY-4.0"
  cat >"$dest_root/NOTICE.md" <<EOF
# Attribution notice

The skill content in this directory was vendored from
[brandondees/code-quality-atlas](https://github.com/brandondees/code-quality-atlas)
(commit \`$sha\`) by \`tooling/vendor-skills.sh\`.

It is licensed under CC BY 4.0. The full license text is vendored alongside
this notice as \`LICENSE-CC-BY-4.0\`, copied verbatim from the source
repository at the commit above (see also
[LICENSE-CC-BY-4.0](https://github.com/brandondees/code-quality-atlas/blob/$sha/LICENSE-CC-BY-4.0)
in the source repository, pinned to the same commit so the linked text
matches what was actually vendored). This notice satisfies the attribution
requirement for this vendored copy; do not remove either file while the
content remains here.
EOF
}

# Ensure one PostToolUse/PreToolUse hook entry exists in a settings.json
# object, without disturbing anything else already there. Idempotent: checks
# for an existing hooks-array entry whose (matcher, command) PAIR already
# matches before appending a new one -- re-running this is a no-op once
# vendored, and dedupe is keyed on the pair (not command alone) precisely so
# the same script can still be wired under two different matchers, as
# track-lens-reads.sh is (see the jq filter's own comment below for the
# concrete bug that shipped from deduping on command alone). Reads the
# current settings JSON on stdin, writes the updated JSON to stdout; the
# caller is responsible for atomically replacing the file
# (vendor_lens_coverage_hook does, via a temp-file-then-mv write).
merge_settings_hook() {
  local event=$1 matcher=$2 command=$3
  jq --arg event "$event" --arg matcher "$matcher" --arg command "$command" '
    .hooks = (.hooks // {}) |
    .hooks[$event] = (.hooks[$event] // []) |
    # Dedupe on the (matcher, command) PAIR, not command alone -- the same
    # script legitimately gets wired under two different matchers (e.g.
    # track-lens-reads.sh under both "Read" and "Skill"), and deduping by
    # command alone would make the second call a no-op, silently dropping
    # that matcher entry (round-1 review on PR #398, caught by re-running
    # this vendoring against a scratch target and finding only one
    # PostToolUse entry where two were expected).
    ( .hooks[$event] | any(.matcher == $matcher and (.hooks[]?.command == $command)) ) as $exists |
    if $exists then .
    else .hooks[$event] += [{matcher: $matcher, hooks: [{type: "command", command: $command}]}]
    end
  '
}

# Vendors the #357/Q23 lens-coverage enforcement hook into a target repo:
# the two scripts under hooks/lens-coverage/, plus the settings.json wiring
# that makes them fire. This is deliberately NOT part of the main skill-
# vendoring loop above (vendor_one/the .atlas-vendored marker/--prune) --
# those exist to manage Skill-tool-loaded content; this writes hook
# EXECUTION wiring into the target's own settings.json, a different and more
# sensitive kind of change, gated behind its own explicit
# --with-lens-coverage-hook flag rather than happening implicitly.
#
# Committed, non-plugin settings.json hooks were confirmed to actually fire
# in a Claude Code cloud/routine session on 2026-09-01 (docs/open-questions.md
# Q23) -- that result is what makes vendoring this into a target's own
# settings.json (rather than only the plugin's hooks.json, which never loads
# in cloud at all per distribution.md) worth doing.
#
# The command paths written into settings.json are relative to the target
# repo root (".claude/hooks/lens-coverage/<script>.sh"), matching how
# gate-lens-coverage.sh and track-lens-reads.sh already reference their own
# state file (.claude/.atlas-lens-coverage/) the same way -- this assumes
# Claude Code invokes hook commands with the project root as the working
# directory, not that any particular env var is set (unlike the plugin path,
# which uses ${CLAUDE_PLUGIN_ROOT} -- not applicable here since there's no
# plugin runtime involved).
#
# No --prune equivalent: unlike the skill marker above, there's no record of
# "hook entries this tool previously added" to safely reverse. Turning
# --with-lens-coverage-hook off on a later run leaves prior runs' vendored
# scripts and settings.json entries in place; removing them is a manual step
# for now. Stated here as a known gap, not silently accepted.
vendor_lens_coverage_hook() {
  local abs_target=$1
  local hook_src="hooks/lens-coverage"
  local hook_dest="$abs_target/$HOOK_SUBDIR"
  local settings_file="$abs_target/.claude/settings.json"

  mkdir -p "$hook_dest"
  cp "$hook_src/track-lens-reads.sh" "$hook_dest/track-lens-reads.sh"
  cp "$hook_src/gate-lens-coverage.sh" "$hook_dest/gate-lens-coverage.sh"
  chmod +x "$hook_dest/track-lens-reads.sh" "$hook_dest/gate-lens-coverage.sh"

  local current='{}'
  if [ -f "$settings_file" ]; then
    if ! current="$(cat "$settings_file")" || ! printf '%s' "$current" | jq -e . >/dev/null 2>&1; then
      printf 'Error: %s exists but is not valid JSON; refusing to touch it. Merge the lens-coverage hook in by hand -- see hooks/lens-coverage/ in code-quality-atlas.\n' "$settings_file" >&2
      return 1
    fi
  fi

  # Every failure path below is an EXPLICIT check, not a reliance on `set -e`
  # catching a failing pipeline: this function is called as
  # `vendor_lens_coverage_hook "$abs_target" || exit 1` in main(), and bash
  # suspends errexit for the full duration of a function invoked as the
  # non-final part of an `||` (or `&&`) list -- an internal jq failure here
  # previously did NOT stop execution, silently continuing to the final
  # `> "$settings_file"` and printing a false success message (Copilot
  # review, PR #398, confirmed by reproduction: a settings.json with a
  # non-array `.hooks.PostToolUse` shape made the merge jq error, and the
  # unguarded `... | jq . > "$settings_file"` truncated the target to an
  # EMPTY file before jq could report that error -- real data loss, not a
  # theoretical one).
  local updated
  if ! updated="$(printf '%s' "$current" \
      | merge_settings_hook "PostToolUse" "Read" "$HOOK_SUBDIR/track-lens-reads.sh" \
      | merge_settings_hook "PostToolUse" "Skill" "$HOOK_SUBDIR/track-lens-reads.sh" \
      | merge_settings_hook "PreToolUse" "mcp__github__pull_request_review_write|mcp__github__add_comment_to_pending_review" "$HOOK_SUBDIR/gate-lens-coverage.sh")" \
     || ! printf '%s' "$updated" | jq -e . >/dev/null 2>&1; then
    printf 'Error: failed to merge the lens-coverage hook wiring into %s -- an existing .hooks entry may have an unexpected shape (expected an array under .hooks.<Event>). Left untouched; merge it in by hand -- see hooks/lens-coverage/ in code-quality-atlas.\n' "$settings_file" >&2
    return 1
  fi

  # Atomic write: stage in a temp file in the same directory (so the final
  # `mv` is a same-filesystem rename, not a copy), then move it into place.
  # A failure between here and the mv leaves the existing settings_file
  # (if any) completely untouched, instead of truncated.
  local tmp_settings
  tmp_settings="$(mktemp "${settings_file}.XXXXXX")" || {
    printf 'Error: could not create a temp file to stage %s\n' "$settings_file" >&2
    return 1
  }
  if ! printf '%s\n' "$updated" | jq . > "$tmp_settings"; then
    rm -f "$tmp_settings"
    printf 'Error: failed writing the merged settings JSON; %s left untouched.\n' "$settings_file" >&2
    return 1
  fi
  mv "$tmp_settings" "$settings_file"

  # The tracker writes one state file per session under this directory
  # (never meant to be committed); append the ignore entry to the target's
  # own .gitignore, idempotently, same as this repo's own (round-1 review on
  # PR #398 -- nothing previously ignored this path here or in a vendored
  # target).
  local gitignore_file="$abs_target/.gitignore" ignore_line=".claude/.atlas-lens-coverage/"
  if [ ! -f "$gitignore_file" ] || ! grep -Fxq "$ignore_line" "$gitignore_file"; then
    # Decide the leading newline BEFORE opening the redirect below -- doing
    # the `-s` check inside the same `{ ... } >> "$gitignore_file"` block
    # reads and writes the same file in one pipeline (shellcheck SC2094);
    # computing it into a plain variable first sidesteps that entirely.
    local leading_newline=""
    [ -s "$gitignore_file" ] && leading_newline=1
    {
      [ -n "$leading_newline" ] && printf '\n'
      printf '# Per-session lens-coverage state (code-quality-atlas hooks/lens-coverage/) -- ephemeral, never committed\n%s\n' "$ignore_line"
    } >> "$gitignore_file"
  fi

  printf 'Vendored lens-coverage hook -> %s (wiring merged into %s, %s updated)\n' "$hook_dest" "$settings_file" "$gitignore_file"
}

main() {
  parse_args "$@"
  check_requirements || exit 1

  local root
  root=$(repo_root) || exit 1
  cd "$root"
  collect_skill_names || exit 1

  local abs_target
  abs_target=$(cd "$TARGET" && pwd)
  local dest_root="$abs_target/$SUBDIR"
  local marker="$dest_root/$MARKER_NAME"
  mkdir -p "$dest_root"

  # Previously-vendored names (for safe prune), from the marker if present.
  OLD_NAMES=()
  if [ -f "$marker" ]; then
    local line
    while IFS= read -r line; do
      case "$line" in
        '#'*) ;;     # comment/header
        '') ;;       # blank
        *) OLD_NAMES+=("$line") ;;
      esac
    done <"$marker"
  fi

  local sha
  sha=$(git rev-parse --short HEAD 2>/dev/null || printf 'unknown')

  # Populated by vendor_one when it skips a name it doesn't own (#175).
  SKIPPED_COLLISIONS=()

  local name
  for name in "${SKILL_NAMES[@]}"; do
    vendor_one "$name" "$dest_root"
  done
  write_attribution "$dest_root" "$sha"
  printf 'Vendored %s skill(s) -> %s\n' \
    "$((${#SKILL_NAMES[@]} - ${#SKIPPED_COLLISIONS[@]}))" "$dest_root"

  if [ "$WITH_LENS_COVERAGE_HOOK" -eq 1 ]; then
    vendor_lens_coverage_hook "$abs_target" || exit 1
  fi

  local pruned=0
  if [ "$PRUNE" -eq 1 ] && [ "${#OLD_NAMES[@]}" -gt 0 ]; then
    local old
    for old in "${OLD_NAMES[@]}"; do
      if ! contains "$old" "${SKILL_NAMES[@]}"; then
        rm -rf "${dest_root:?}/$old"
        printf '  - pruned stale: %s\n' "$old"
        pruned=$((pruned + 1))
      fi
    done
  fi

  # Rewrite the marker: everything vendored this run, plus any name from the
  # previous marker not covered by this run and not just pruned above.
  # Previously this unconditionally overwrote the marker with only
  # SKILL_NAMES, so switching modes (standalone <-> --collapsed) against the
  # same target silently dropped the other form's names from the marker —
  # orphaning those directories beyond --prune's reach (issue #112).
  # Names skipped this run due to a collision (#175) are excluded: this tool
  # does not own that directory, so the marker must not claim it does.
  local marker_names=()
  for name in "${SKILL_NAMES[@]}"; do
    if [ "${#SKIPPED_COLLISIONS[@]}" -gt 0 ] && contains "$name" "${SKIPPED_COLLISIONS[@]}"; then
      continue
    fi
    marker_names+=("$name")
  done
  if [ "${#OLD_NAMES[@]}" -gt 0 ]; then
    local old
    for old in "${OLD_NAMES[@]}"; do
      if contains "$old" "${SKILL_NAMES[@]}"; then
        continue
      fi
      if [ "$PRUNE" -eq 1 ]; then
        continue  # removed from disk above; drop from the marker too
      fi
      marker_names+=("$old")
    done
  fi

  {
    printf '# code-quality-atlas vendored skills — do not hand-edit; regenerate with tooling/vendor-skills.sh\n'
    printf '# source=brandondees/code-quality-atlas@%s\n' "$sha"
    # Guard the empty case explicitly: unlike the pre-#175 code (marker_names
    # was always seeded from the never-empty SKILL_NAMES), a run where every
    # skill collides with non-tool-managed content and OLD_NAMES is also
    # empty (e.g. the target's first-ever vendoring attempt) now leaves
    # marker_names genuinely empty. Expanding "${marker_names[@]}" directly
    # in that state is a bash 3.2 `set -u` nounset hazard (fixed in bash 4.4+
    # but this script targets 3.2/macOS) — mirror the same guard already used
    # for OLD_NAMES/SKIPPED_COLLISIONS elsewhere in this function.
    if [ "${#marker_names[@]}" -gt 0 ]; then
      for name in "${marker_names[@]}"; do
        printf '%s\n' "$name"
      done
    fi
  } >"$marker"

  printf 'Source: code-quality-atlas@%s' "$sha"
  [ "$pruned" -gt 0 ] && printf ' (pruned %s)' "$pruned"
  printf '\nNext: review and commit %s in the target repo.\n' "$SUBDIR"

  if [ "${#SKIPPED_COLLISIONS[@]}" -gt 0 ]; then
    printf 'Skipped %s skill(s) due to a pre-existing, non-tool-managed directory: %s\n' \
      "${#SKIPPED_COLLISIONS[@]}" "${SKIPPED_COLLISIONS[*]}" >&2
    return 1
  fi
}

main "$@"
