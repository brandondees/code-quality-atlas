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
#   tooling/vendor-skills.sh <target-repo-dir> --dry-run     # report what would happen, touch nothing
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
DRY_RUN=0
WITH_LENS_COVERAGE_HOOK=0
SUBDIR=".claude/skills"
MARKER_NAME=".atlas-vendored"
# Bumped only if the marker's line shape changes in a way an older reader
# would misparse (#377) -- the per-line `[a-z0-9-]+` validation below is the
# actual safety net for that; this is a secondary, explicit signal.
MARKER_FORMAT=1
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
Usage: tooling/vendor-skills.sh <target-repo-dir> [--collapsed] [--prune] [--force] [--dry-run] [--with-lens-coverage-hook]

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
  --dry-run     Report what would be vendored/pruned/skipped without writing,
                deleting, or overwriting anything
  --with-lens-coverage-hook
                Also vendor the #357/Q23 lens-coverage enforcement hook: two
                scripts copied to .claude/hooks/lens-coverage/, plus
                PostToolUse(Read)/PostToolUse(Skill)/PreToolUse hook wiring
                merged (not clobbered) into the target repo's
                .claude/settings.json.
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
  tooling/vendor-skills.sh ~/code/my-service --dry-run
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
      --dry-run) DRY_RUN=1 ;;
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

# #377: confirms $target's parent directory really resolves to $dest_root
# before anything deletes it -- defense in depth alongside the marker-line
# validation below (is_bare_skill_name), independent of it: if a future
# edit ever weakens or removes that validation, this still refuses to
# delete outside dest_root rather than trusting the string concatenation
# that built $target. Aborts loudly rather than deleting anything on any
# resolution failure or mismatch.
confirm_child_of_dest_root() {
  local target=$1 dest_root=$2
  local parent
  parent=$(cd "$(dirname -- "$target")" 2>/dev/null && pwd -P) || {
    printf 'Error: refusing to delete %s -- cannot resolve its parent directory.\n' "$target" >&2
    return 1
  }
  local resolved_root
  resolved_root=$(cd "$dest_root" 2>/dev/null && pwd -P) || {
    printf 'Error: refusing to delete %s -- cannot resolve dest root %s.\n' "$target" "$dest_root" >&2
    return 1
  }
  if [ "$parent" != "$resolved_root" ]; then
    printf 'Error: refusing to delete %s -- its resolved parent (%s) is not %s.\n' \
      "$target" "$parent" "$resolved_root" >&2
    return 1
  fi
}

# #377: a marker line must be a bare skill name (the manifest's own name
# shape) -- anything else (a path, a traversal segment like "../../victim",
# a future field an older copy of this script doesn't understand) is dropped
# with a warning rather than fed into OLD_NAMES, where it would otherwise
# reach the --prune `rm -rf` below or the vendor_one collision check.
is_bare_skill_name() {
  case "$1" in
    '' | *[!a-z0-9-]*) return 1 ;;
    *) return 0 ;;
  esac
}

# #377: the target repo a maintainer runs this against, and the state of
# .claude/skills/ inside it, are exactly what --prune/--force delete or
# overwrite -- warn (never abort; some legitimate targets, e.g. a scratch
# directory in a test) so the run isn't silent about the two things that
# would otherwise make a bad delete unrecoverable.
check_target_git_state() {
  local abs_target=$1 subdir=$2
  if ! git -C "$abs_target" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf 'Warning: %s does not look like a git working tree -- there is no version-control safety net if --prune or --force deletes/overwrites something unexpected.\n' "$abs_target" >&2
    return 0
  fi
  if [ -n "$(git -C "$abs_target" status --porcelain -- "$subdir" 2>/dev/null)" ]; then
    printf 'Warning: %s has uncommitted changes under %s -- review them before running with --prune or --force, since this tool cannot tell your own edits there from ones it is about to overwrite or delete.\n' \
      "$abs_target" "$subdir" >&2
  fi
}

# #377: the *source* repo's tree state and the $sha stamped into NOTICE.md/
# the marker are two separate claims that can silently disagree -- a dirty
# source tree means the content actually copied may not match what commit
# $sha's blobs contain, and an unpushed commit means the NOTICE.md link to
# github.com/.../blob/$sha/... 404s until it's pushed. Both are warnings,
# mirroring package-account-zips.sh's existing unresolvable-SHA warning
# below rather than failing the run outright.
check_source_repo_provenance() {
  local sha=$1
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
  if [ -n "$(git status --porcelain -- "$SRC_SUBDIR" LICENSE-CC-BY-4.0 2>/dev/null)" ]; then
    printf 'Warning: this source repo has uncommitted changes under %s or LICENSE-CC-BY-4.0 -- the content just vendored may not match commit %s exactly.\n' "$SRC_SUBDIR" "$sha" >&2
  fi
  if [ "$sha" != "unknown" ] && ! git branch -r --contains "$sha" 2>/dev/null | grep -q .; then
    printf 'Warning: commit %s does not appear on any remote-tracking branch -- NOTICE.md links to a GitHub blob URL at this commit that may 404 until it is pushed.\n' "$sha" >&2
  fi
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

  # #377: --dry-run reports what a real run would do (including the
  # collision check above, so a skipped-due-to-collision name is reported
  # accurately) without touching the filesystem at all.
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '(dry-run) would vendor: %s\n' "$name"
    return 0
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

  if ! mkdir -p "$hook_dest" \
    || ! cp "$hook_src/track-lens-reads.sh" "$hook_dest/track-lens-reads.sh" \
    || ! cp "$hook_src/gate-lens-coverage.sh" "$hook_dest/gate-lens-coverage.sh" \
    || ! chmod +x "$hook_dest/track-lens-reads.sh" "$hook_dest/gate-lens-coverage.sh"; then
    printf 'Error: failed to install the lens-coverage hook scripts into %s; %s left untouched.\n' "$hook_dest" "$settings_file" >&2
    return 1
  fi

  local current='{}'
  if [ -f "$settings_file" ]; then
    if ! current="$(cat "$settings_file")" || ! printf '%s' "$current" | jq -e . >/dev/null 2>&1; then
      printf 'Error: %s exists but is not valid JSON; refusing to touch it. Merge the lens-coverage hook in by hand -- see hooks/lens-coverage/ in code-quality-atlas.\n' "$settings_file" >&2
      return 1
    fi
  fi

  # This whole function is called as a BARE statement in main() (no `if`,
  # no `|| exit 1`) specifically so `set -e` applies normally to every
  # command in it, including the plain mkdir/cp/chmod above and the mv
  # below -- calling it any other way suspends errexit for the function's
  # entire body, which is exactly what let an internal jq failure here
  # previously go uncaught, silently continue to `> "$settings_file"`, and
  # print a false success message (Copilot review, PR #398, confirmed by
  # reproduction: a settings.json with a non-array `.hooks.PostToolUse`
  # shape made the merge jq error, and the unguarded write truncated the
  # target to an EMPTY file before jq could report that error -- real data
  # loss). A round-3 follow-up review found that first fix incomplete: it
  # added explicit checks around the merge/write below, but the mkdir/cp/
  # chmod block above and the mv below were still unguarded and still hit
  # the identical silent-false-success failure mode on their own (confirmed
  # by reproduction: an obstructed hook_dest made five commands fail while
  # the run still reported success and wrote full hook wiring into
  # settings.json for scripts that were never copied) -- calling the
  # function bare, as it is now, closes every such gap at once rather than
  # requiring a guard at each site; the explicit checks below stay because
  # they give a clear, specific error message instead of a bare abort.
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
  if ! mv "$tmp_settings" "$settings_file"; then
    rm -f "$tmp_settings"
    printf 'Error: failed to move the merged settings JSON into place at %s.\n' "$settings_file" >&2
    return 1
  fi

  # The tracker writes one state file per session under this directory
  # (never meant to be committed); append the ignore entry to the target's
  # own .gitignore, idempotently, same as this repo's own (round-1 review on
  # PR #398 -- nothing previously ignored this path here or in a vendored
  # target). Non-fatal on failure, deliberately: settings_file (the part
  # that actually makes the gate enforce anything) is already written and
  # correct by this point, so a .gitignore hiccup is a hygiene nit, not a
  # reason to report the whole run as failed.
  local gitignore_file="$abs_target/.gitignore" ignore_line=".claude/.atlas-lens-coverage/"
  if [ ! -f "$gitignore_file" ] || ! grep -Fxq "$ignore_line" "$gitignore_file"; then
    # Decide the leading newline BEFORE opening the redirect below -- doing
    # the `-s` check inside the same `{ ... } >> "$gitignore_file"` block
    # reads and writes the same file in one pipeline (shellcheck SC2094);
    # computing it into a plain variable first sidesteps that entirely.
    local leading_newline=""
    [ -s "$gitignore_file" ] && leading_newline=1
    if ! {
      [ -n "$leading_newline" ] && printf '\n'
      printf '# Per-session lens-coverage state (code-quality-atlas hooks/lens-coverage/) -- ephemeral, never committed\n%s\n' "$ignore_line"
    } >> "$gitignore_file"; then
      printf 'Warning: could not update %s to ignore .claude/.atlas-lens-coverage/ -- add it by hand.\n' "$gitignore_file" >&2
    fi
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
  check_target_git_state "$abs_target" "$SUBDIR"
  # #377: --dry-run must not create so much as an empty directory.
  [ "$DRY_RUN" -eq 1 ] || mkdir -p "$dest_root"

  # Previously-vendored names (for safe prune), from the marker if present.
  # #377: only a bare skill name (is_bare_skill_name) is trusted -- anything
  # else is a malformed or maliciously-planted line (e.g. "../../victim")
  # and must never reach OLD_NAMES, since OLD_NAMES feeds both the --prune
  # `rm -rf` below and vendor_one's collision check.
  OLD_NAMES=()
  local skipped_invalid_marker_lines=0
  local marker_format=""
  if [ -f "$marker" ]; then
    local line
    while IFS= read -r line; do
      case "$line" in
        '# format='*) marker_format=${line#'# format='} ;;
        '#'*) ;;     # comment/header
        '') ;;       # blank
        *)
          if is_bare_skill_name "$line"; then
            OLD_NAMES+=("$line")
          else
            printf 'Warning: ignoring malformed marker line in %s (not a bare skill name -- expected only a-z, 0-9, -): %s\n' \
              "$marker" "$line" >&2
            skipped_invalid_marker_lines=$((skipped_invalid_marker_lines + 1))
          fi
          ;;
      esac
    done <"$marker"
    if [ -n "$marker_format" ] && [ "$marker_format" != "$MARKER_FORMAT" ]; then
      printf 'Warning: %s declares format=%s; this tool understands format=%s. Proceeding -- unrecognized lines are dropped above, never treated as skill names -- but the marker may carry fields this version does not know about.\n' \
        "$marker" "$marker_format" "$MARKER_FORMAT" >&2
    fi
  fi

  local sha
  sha=$(git rev-parse --short HEAD 2>/dev/null || printf 'unknown')
  if [ "$sha" = "unknown" ]; then
    printf 'Warning: could not resolve a git commit SHA (no .git found?) -- every\n' >&2
    printf '  NOTICE.md will pin a dead license link to .../blob/unknown/LICENSE-CC-BY-4.0\n' >&2
  fi
  check_source_repo_provenance "$sha"

  # Populated by vendor_one when it skips a name it doesn't own (#175).
  SKIPPED_COLLISIONS=()

  local name
  for name in "${SKILL_NAMES[@]}"; do
    vendor_one "$name" "$dest_root"
  done
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '(dry-run) would vendor %s skill(s) -> %s\n' \
      "$((${#SKILL_NAMES[@]} - ${#SKIPPED_COLLISIONS[@]}))" "$dest_root"
  else
    write_attribution "$dest_root" "$sha"
    printf 'Vendored %s skill(s) -> %s\n' \
      "$((${#SKILL_NAMES[@]} - ${#SKIPPED_COLLISIONS[@]}))" "$dest_root"
  fi

  if [ "$WITH_LENS_COVERAGE_HOOK" -eq 1 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      # #377: --dry-run's whole point is touching nothing -- the hook
      # vendoring writes real files and merges into the target's own
      # settings.json, so it must not run for real here.
      printf '(dry-run) would vendor the lens-coverage hook -> %s (and merge wiring into %s/.claude/settings.json)\n' \
        "$abs_target/$HOOK_SUBDIR" "$abs_target"
    else
      # Called as a bare statement, deliberately -- see the function's own
      # header for why testing its exit status here (an `if`, or `|| exit 1`
      # as this line previously read) would suspend `set -e` for the ENTIRE
      # function body, not just this call. Left untested, a failure inside
      # the function (an explicit `return 1`, or any unguarded command) exits
      # this whole script immediately with that same status, exactly like an
      # ordinary top-level command failing under `set -e` -- no explicit
      # check needed here at all.
      vendor_lens_coverage_hook "$abs_target"
    fi
  fi

  # #377: names present in the old marker but no longer in this run's
  # SKILL_NAMES -- computed once and shared by the --prune loop below and
  # the stale-names notice (previously only reachable via --prune's own
  # inline check, so a refresh with no --prune silently left withdrawn
  # lenses on disk with no indication anything was stale).
  local stale_names=()
  if [ "${#OLD_NAMES[@]}" -gt 0 ]; then
    local old
    for old in "${OLD_NAMES[@]}"; do
      contains "$old" "${SKILL_NAMES[@]}" || stale_names+=("$old")
    done
  fi

  local pruned=0
  if [ "$PRUNE" -eq 1 ] && [ "${#stale_names[@]}" -gt 0 ]; then
    local old target
    for old in "${stale_names[@]}"; do
      target="${dest_root:?}/$old"
      if [ "$DRY_RUN" -eq 1 ]; then
        printf '  - (dry-run) would prune stale: %s\n' "$old"
      else
        # #377: defense in depth beyond is_bare_skill_name above -- refuse
        # to delete anything whose resolved parent isn't actually dest_root.
        confirm_child_of_dest_root "$target" "$dest_root" || exit 1
        rm -rf "$target"
        printf '  - pruned stale: %s\n' "$old"
      fi
      pruned=$((pruned + 1))
    done
  elif [ "$PRUNE" -ne 1 ] && [ "${#stale_names[@]}" -gt 0 ]; then
    # #377: previously silent -- a refresh with no --prune kept re-listing
    # withdrawn lenses in the marker forever with no indication anything
    # was stale or that --prune would remove them.
    printf 'Note: %s previously-vendored skill(s) are no longer in the suite and were left in place: %s -- re-run with --prune to remove them.\n' \
      "${#stale_names[@]}" "${stale_names[*]}"
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    printf '(dry-run) no files were written, deleted, or overwritten. Re-run without --dry-run to apply.\n'
  else
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
    if [ "${#stale_names[@]}" -gt 0 ] && [ "$PRUNE" -ne 1 ]; then
      # Still stale, not pruned this run: keep them recorded so a later
      # --prune (or the notice above) can still find them.
      local old
      for old in "${stale_names[@]}"; do
        marker_names+=("$old")
      done
    fi

    {
      printf '# code-quality-atlas vendored skills — do not hand-edit; regenerate with tooling/vendor-skills.sh\n'
      printf '# format=%s\n' "$MARKER_FORMAT"
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
  fi

  if [ "$skipped_invalid_marker_lines" -gt 0 ]; then
    printf 'Ignored %s malformed marker line(s) in %s -- see the warning(s) above.\n' \
      "$skipped_invalid_marker_lines" "$marker" >&2
  fi

  if [ "${#SKIPPED_COLLISIONS[@]}" -gt 0 ]; then
    printf 'Skipped %s skill(s) due to a pre-existing, non-tool-managed directory: %s\n' \
      "${#SKIPPED_COLLISIONS[@]}" "${SKIPPED_COLLISIONS[*]}" >&2
    return 1
  fi
}

main "$@"
