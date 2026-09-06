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
# dev-only material is excluded (evals/). Each skill is CC BY 4.0 licensed, so a
# generated NOTICE.md plus a vendored copy of LICENSE-CC-BY-4.0 ship alongside
# its SKILL.md in every ZIP — mirrors tooling/vendor-skills.sh's write_attribution().
# Want the whole suite together instead of one ZIP per skill? Use
# tooling/vendor-skills.sh to put it inside a repo — this script previously also
# had a --bundle mode for a single-archive-of-everything, removed (issue #449)
# once nothing actually consumed it: the claude.ai GUI, the only real consumer
# named anywhere in this repo, rejects a multi-skill ZIP outright (confirmed,
# docs/distribution.md "One skill per zip"), no doc pointed at the bundle as a
# real workflow, and only this script's own test exercised the path.
#
# Usage:
#   tooling/package-account-zips.sh                 # one ZIP per skill -> dist/account-skills/
#   tooling/package-account-zips.sh --collapsed     # the 4 collapsed entrypoints instead of the 44 skills
#   tooling/package-account-zips.sh --out DIR        # write ZIPs to DIR
#
# bash 3.2 compatible (macOS default).

set -euo pipefail

# check_requirements/repo_root/collect_skill_names (issue #392).
# shellcheck source=lib/skills-common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/skills-common.sh"

REQUIRED_PROGRAMS=("zip")

OUT_DIR="dist/account-skills"
# Which tree to package: the 44 standalone skills (default) or the 4 collapsed
# entrypoints (--collapsed). Both live under the repo root.
SKILLS_SUBDIR="skills"

usage() {
  cat <<'EOF'
Usage: tooling/package-account-zips.sh [--collapsed] [--out DIR]

Packages skills/<name>/ into upload-ready ZIPs for the claude.ai Skills GUI.
Each per-skill ZIP holds <name>/SKILL.md plus reference/ and examples.md;
evals/ is excluded. Run from anywhere inside the repo.

Options:
  --collapsed    Package the 4 collapsed entrypoints (collapsed/skills/) instead
                 of the 44 standalone skills (skills/)
  --out DIR      Output directory (default: dist/account-skills)
  -h, --help     Show this help

External tools:
  zip

Examples:
  tooling/package-account-zips.sh
  tooling/package-account-zips.sh --collapsed --out /tmp/atlas-zips
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --collapsed) SKILLS_SUBDIR="collapsed/skills" ;;
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
      --bundle | --bundle-only)
        # Removed (#449): the claude.ai Skills GUI rejects a multi-skill ZIP
        # outright, so the archive this used to build had no real consumer.
        # Named explicitly here (unlike the generic unknown-argument case
        # below) so a caller who remembers this flag is pointed at the
        # actual replacement instead of a bare "unknown argument".
        printf 'Error: %s was removed (#449) -- the claude.ai GUI never accepted a multi-skill\n' "$1" >&2
        printf '  ZIP anyway. Use tooling/vendor-skills.sh instead to put the whole suite inside a repo.\n\n' >&2
        usage >&2
        exit 1
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

# repo_root and collect_skill_names come from lib/skills-common.sh (sourced
# above).

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

# Stage a skill's runtime files (SKILL.md, examples.md, reference/) under
# $stage_root/$name/ — dev-only evals/ is deliberately not copied. Mirrors
# vendor-skills.sh's vendor_one() so both distribution channels ship the same
# runtime surface.
stage_skill() {
  local name=$1 stage_root=$2
  local src="$SKILLS_SUBDIR/$name"
  local dest="$stage_root/$name"
  rm -rf "${dest:?}"
  mkdir -p "$dest"
  cp "$src/SKILL.md" "$dest/SKILL.md"
  [ -f "$src/examples.md" ] && cp "$src/examples.md" "$dest/examples.md"
  [ -d "$src/reference" ] && cp -R "$src/reference" "$dest/reference"
  return 0
}

# The skill content staged by stage_skill is CC BY 4.0 (LICENSE-CC-BY-4.0),
# which requires attribution on redistribution. Vendor the actual license
# text alongside the notice -- not just a link to it -- so an uploaded ZIP is
# self-contained: extracted into a claude.ai account skill, it has no ongoing
# relationship to this git repo at all, so a dead or unreachable link would
# be the *only* copy of the license terms that skill will ever have (issue
# #351). Mirrors vendor-skills.sh's write_attribution() so both distribution
# channels for this same content carry the same notice.
write_attribution() {
  local dest=$1 sha=$2
  cp "LICENSE-CC-BY-4.0" "$dest/LICENSE-CC-BY-4.0"
  cat >"$dest/NOTICE.md" <<EOF
# Attribution notice

This skill was packaged from
[brandondees/code-quality-atlas](https://github.com/brandondees/code-quality-atlas)
(commit \`$sha\`) by \`tooling/package-account-zips.sh\`.

It is licensed under CC BY 4.0. The full license text is vendored alongside
this notice as \`LICENSE-CC-BY-4.0\`, copied verbatim from the source
repository at the commit above (see also
[LICENSE-CC-BY-4.0](https://github.com/brandondees/code-quality-atlas/blob/$sha/LICENSE-CC-BY-4.0)
in the source repository, pinned to the same commit so the linked text
matches what was actually packaged). This notice satisfies the attribution
requirement for this copy; do not remove either file while the content
remains here.
EOF
}

zip_one() {
  local name=$1 dest=$2 stage_root=$3
  rm -f "$dest"
  # Zip from within the stage dir so the archive root is <name>/… as the GUI
  # expects.
  (cd "$stage_root" && zip -q -r -X "$dest" "$name")
}

main() {
  parse_args "$@"
  check_requirements || exit 1

  local root
  root=$(repo_root) || exit 1
  cd "$root"

  collect_skill_names || exit 1

  mkdir -p "$OUT_DIR"
  local abs_out
  abs_out=$(cd "$OUT_DIR" && pwd)

  local stage_root
  stage_root=$(mktemp -d) || { printf 'Error: mktemp -d failed\n' >&2; exit 1; }
  # Double-quoted so $stage_root is substituted now, at registration time —
  # it's a `local` inside main() and would be out of scope (unbound under
  # set -u) by the time an EXIT trap on a single-quoted command fires later.
  # shellcheck disable=SC2064
  trap "rm -rf '$stage_root'" EXIT

  local sha
  sha=$(git rev-parse --short HEAD 2>/dev/null || printf 'unknown')
  if [ "$sha" = "unknown" ]; then
    printf '  ! warning: could not resolve a git commit SHA (no .git found?) — every\n' >&2
    printf '    NOTICE.md will pin a dead license link to .../blob/unknown/LICENSE-CC-BY-4.0\n' >&2
  fi

  local count="${#SKILL_NAMES[@]}"
  local name

  for name in "${SKILL_NAMES[@]}"; do
    warn_on_name_mismatch "$name"
    stage_skill "$name" "$stage_root"
    write_attribution "$stage_root/$name" "$sha"
  done

  printf 'Packaging %s per-skill ZIP(s) -> %s\n' "$count" "$abs_out"
  for name in "${SKILL_NAMES[@]}"; do
    zip_one "$name" "$abs_out/$name.zip" "$stage_root"
    printf '  + %s.zip\n' "$name"
  done

  printf 'Done.\n'
}

main "$@"
