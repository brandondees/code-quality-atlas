# shellcheck shell=bash
# SPDX-License-Identifier: MIT
# tooling/lib/skills-common.sh
#
# Shared helpers for tooling/vendor-skills.sh and tooling/package-account-zips.sh
# (issue #392): both scripts operate on the same skills/ (or collapsed/skills/)
# tree from the repo root and previously carried their own byte-for-byte
# copies of check_requirements/repo_root/collect_skill_names, with two
# different global names for the same "which tree" concept (SRC_SUBDIR vs
# SKILLS_SUBDIR) and two different messages for the same repo-root failure.
# Sourced, not executed directly -- has no shebang-invokable behavior of its
# own.
#
# Callers must, before sourcing this file:
#   - set REQUIRED_PROGRAMS to an array of external binaries this run needs
#   - set SKILLS_SUBDIR to "skills" or "collapsed/skills"
#   - define their own usage() (check_requirements calls it on failure; not
#     required to exist yet at source time, only by the time a caller
#     actually invokes check_requirements)
#
# bash 3.2 compatible (macOS default), matching both callers.

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

# Echo the repo root (directory containing skills/), or fail. $0 here
# resolves against the CALLING script's path, not this sourced file's --
# sourcing a file into a shell does not change its $0.
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
  printf 'Error: could not locate the repo root (no skills/ directory found here or at this script'"'"'s location).\n' >&2
  return 1
}

# A skill directory is any immediate child of $SKILLS_SUBDIR that holds a
# SKILL.md. Sets the global SKILL_NAMES array (bash 3.2: no mapfile).
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
