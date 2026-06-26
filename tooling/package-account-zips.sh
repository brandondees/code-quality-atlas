#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# tooling/package-account-zips.sh
#
# Package the suite's skills as upload-ready ZIPs for the claude.ai Skills GUI
# (Settings -> Capabilities/Skills -> "+" -> Upload a skill). Account-enabled
# skills are the documented, repo-independent way to make the suite available in
# Claude Code web/cloud sessions on ANY repo (see docs/distribution.md). Marketplace
# plugins do NOT load in cloud, which is why this exists.
#
# Each ZIP contains one skill as a top-level folder (<name>/SKILL.md), the layout
# the GUI requires — it rejects a ZIP with more than one top-level folder, so it's
# one upload per skill. Runtime resources ship (SKILL.md, reference/, examples.md);
# dev-only material is excluded (evals/). The whole-suite --bundle mode produces a
# single archive for convenience only; the claude.ai GUI will NOT accept it (use
# tooling/vendor-skills.sh if you want the suite inside a repo instead).
#
# Usage:
#   tooling/package-account-zips.sh                 # one ZIP per skill -> dist/account-skills/
#   tooling/package-account-zips.sh --collapsed     # the 4 collapsed entrypoints instead of the 35 skills
#   tooling/package-account-zips.sh --bundle        # also a single all-skills archive (NOT GUI-uploadable)
#   tooling/package-account-zips.sh --bundle-only   # only that archive
#   tooling/package-account-zips.sh --out DIR        # write ZIPs to DIR
#
# bash 3.2 compatible (macOS default).

set -euo pipefail

REQUIRED_PROGRAMS=("zip")

# Dev-only directories never shipped to an end user's session.
EXCLUDE_GLOBS=("*/evals/*")

OUT_DIR="dist/account-skills"
EMIT_PER_SKILL=1
EMIT_BUNDLE=0
BUNDLE_NAME="code-quality-atlas-skills.zip"
# Which tree to package: the 35 standalone skills (default) or the 4 collapsed
# entrypoints (--collapsed). Both live under the repo root.
SKILLS_SUBDIR="skills"

usage() {
  cat <<'EOF'
Usage: tooling/package-account-zips.sh [--bundle | --bundle-only] [--out DIR]

Packages skills/<name>/ into upload-ready ZIPs for the claude.ai Skills GUI.
Each per-skill ZIP holds <name>/SKILL.md plus reference/ and examples.md;
evals/ is excluded. Run from anywhere inside the repo.

Options:
  --collapsed    Package the 4 collapsed entrypoints (collapsed/skills/) instead
                 of the 35 standalone skills (skills/)
  --bundle       Also emit a single all-skills archive (convenience; the
                 claude.ai GUI will NOT accept a multi-skill ZIP)
  --bundle-only  Emit ONLY that archive, no per-skill ZIPs
  --out DIR      Output directory (default: dist/account-skills)
  -h, --help     Show this help

External tools:
  zip

Examples:
  tooling/package-account-zips.sh
  tooling/package-account-zips.sh --bundle --out /tmp/atlas-zips
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
      --collapsed) SKILLS_SUBDIR="collapsed/skills" ;;
      --bundle) EMIT_BUNDLE=1 ;;
      --bundle-only)
        EMIT_BUNDLE=1
        EMIT_PER_SKILL=0
        ;;
      --out)
        shift
        OUT_DIR=${1:-}
        if [ -z "$OUT_DIR" ]; then
          printf 'Error: --out requires a directory argument.\n\n' >&2
          usage >&2
          exit 1
        fi
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        printf 'Error: Unknown argument: %s\n\n' "$1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done
}

# Echo the repo root (directory containing skills/), or fail.
repo_root() {
  local root
  if root=$(git rev-parse --show-toplevel 2>/dev/null) && [ -d "$root/skills" ]; then
    printf '%s\n' "$root"
    return 0
  fi
  # Fallback: walk up from this script's location.
  local here
  here=$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)
  if [ -n "$here" ] && [ -d "$here/skills" ]; then
    printf '%s\n' "$here"
    return 0
  fi
  printf 'Error: could not locate the repo root (no skills/ directory found).\n' >&2
  return 1
}

# A skill directory is any immediate child of skills/ that holds a SKILL.md.
# Sets the global SKILL_NAMES array (bash 3.2: no mapfile).
collect_skill_names() {
  SKILL_NAMES=()
  local md name
  for md in "$SKILLS_SUBDIR"/*/SKILL.md; do
    [ -e "$md" ] || continue
    name=$(basename "$(dirname "$md")")
    SKILL_NAMES+=("$name")
  done
  if [ "${#SKILL_NAMES[@]}" -eq 0 ]; then
    printf 'Error: no %s/*/SKILL.md found under %s\n' "$SKILLS_SUBDIR" "$(pwd)" >&2
    return 1
  fi
}

# Warn (do not fail) when a skill's frontmatter name does not match its folder —
# the GUI keys on the folder, and a mismatch is usually a packaging mistake.
warn_on_name_mismatch() {
  local name=$1
  local declared
  declared=$(grep -m1 '^name:' "$SKILLS_SUBDIR/$name/SKILL.md" 2>/dev/null | sed 's/^name:[[:space:]]*//; s/[[:space:]]*$//; s/^["'\'']//; s/["'\'']$//' || true)
  if [ -n "$declared" ] && [ "$declared" != "$name" ]; then
    printf '  ! warning: %s/SKILL.md declares name: "%s" (folder differs)\n' "$name" "$declared" >&2
  fi
}

zip_one() {
  local name=$1 dest=$2
  rm -f "$dest"
  # Zip from within the skills source dir so the archive root is <name>/… as the
  # GUI expects.
  (cd "$SKILLS_SUBDIR" && zip -q -r -X "$dest" "$name" -x "${EXCLUDE_GLOBS[@]}")
}

main() {
  parse_args "$@"
  check_requirements || exit 1

  local root
  root=$(repo_root) || exit 1
  cd "$root"

  collect_skill_names || exit 1

  # zip's -x patterns are matched against the paths as written; resolve OUT_DIR to
  # an absolute path so the (cd skills && zip …) subshell writes to the right place.
  mkdir -p "$OUT_DIR"
  local abs_out
  abs_out=$(cd "$OUT_DIR" && pwd)

  local count="${#SKILL_NAMES[@]}"
  local name

  if [ "$EMIT_PER_SKILL" -eq 1 ]; then
    printf 'Packaging %s per-skill ZIP(s) -> %s\n' "$count" "$abs_out"
    for name in "${SKILL_NAMES[@]}"; do
      warn_on_name_mismatch "$name"
      zip_one "$name" "$abs_out/$name.zip"
      printf '  + %s.zip\n' "$name"
    done
  fi

  if [ "$EMIT_BUNDLE" -eq 1 ]; then
    local bundle="$abs_out/$BUNDLE_NAME"
    rm -f "$bundle"
    printf 'Packaging all-skills bundle -> %s\n' "$bundle"
    (cd "$SKILLS_SUBDIR" && zip -q -r -X "$bundle" "${SKILL_NAMES[@]}" -x "${EXCLUDE_GLOBS[@]}")
    printf '  + %s\n' "$BUNDLE_NAME"
    printf 'Note: the claude.ai GUI REJECTS a multi-skill ZIP (one top-level folder only).\n'
    printf '      This bundle is a convenience archive, not for GUI upload; upload the\n'
    printf '      %s per-skill zips, or use tooling/vendor-skills.sh for a repo.\n' "$count"
  fi

  printf 'Done.\n'
}

main "$@"
