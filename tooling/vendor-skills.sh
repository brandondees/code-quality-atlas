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
# Usage:
#   tooling/vendor-skills.sh <target-repo-dir>            # vendor/refresh
#   tooling/vendor-skills.sh <target-repo-dir> --prune    # also drop stale vendored skills
#
# After running, review and commit the .claude/skills/ changes in the target repo.
#
# bash 3.2 compatible (macOS default).

set -euo pipefail

REQUIRED_PROGRAMS=("git")

TARGET=""
PRUNE=0
SUBDIR=".claude/skills"
MARKER_NAME=".atlas-vendored"
# Which tree to vendor: the 37 standalone skills (default) or the 4 collapsed
# entrypoints (--collapsed).
SRC_SUBDIR="skills"

usage() {
  cat <<'EOF'
Usage: tooling/vendor-skills.sh <target-repo-dir> [--collapsed] [--prune]

Copies skills/<name>/{SKILL.md, reference/, examples.md} (no evals/) into
<target-repo-dir>/.claude/skills/<name>/. Run the script from inside the
code-quality-atlas clone; pass the OTHER repo as the argument.

Arguments:
  target-repo-dir   Repo to vendor the suite into (its .claude/skills/ is written)

Options:
  --collapsed   Vendor the 4 collapsed entrypoints (collapsed/skills/) instead of
                the 37 standalone skills (skills/)
  --prune       Remove skills previously vendored by this tool that are no longer
                in the suite (safe: only touches names recorded in the marker)
  -h, --help    Show this help

External tools:
  git

Examples:
  tooling/vendor-skills.sh ~/code/my-service
  tooling/vendor-skills.sh ~/code/my-service --prune
EOF
}

check_requirements() {
  local missing=0
  local program
  for program in "${REQUIRED_PROGRAMS[@]}"; do
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

vendor_one() {
  local name=$1 dest_root=$2
  local src="$SRC_SUBDIR/$name"
  local dest="$dest_root/$name"
  rm -rf "$dest"
  mkdir -p "$dest"
  cp "$src/SKILL.md" "$dest/SKILL.md"
  [ -f "$src/examples.md" ] && cp "$src/examples.md" "$dest/examples.md"
  [ -d "$src/reference" ] && cp -R "$src/reference" "$dest/reference"
  return 0
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

  local name
  for name in "${SKILL_NAMES[@]}"; do
    vendor_one "$name" "$dest_root"
  done
  printf 'Vendored %s skill(s) -> %s\n' "${#SKILL_NAMES[@]}" "$dest_root"

  local pruned=0
  if [ "$PRUNE" -eq 1 ] && [ "${#OLD_NAMES[@]}" -gt 0 ]; then
    local old
    for old in "${OLD_NAMES[@]}"; do
      if ! contains "$old" "${SKILL_NAMES[@]}"; then
        rm -rf "$dest_root/$old"
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
  local marker_names=("${SKILL_NAMES[@]}")
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
    for name in "${marker_names[@]}"; do
      printf '%s\n' "$name"
    done
  } >"$marker"

  printf 'Source: code-quality-atlas@%s' "$sha"
  [ "$pruned" -gt 0 ] && printf ' (pruned %s)' "$pruned"
  printf '\nNext: review and commit %s in the target repo.\n' "$SUBDIR"
}

main "$@"
