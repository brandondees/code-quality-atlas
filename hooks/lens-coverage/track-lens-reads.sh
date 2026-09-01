#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# code-quality-atlas PostToolUse(Read) hook -- lens-coverage tracker (#357, Q23).
#
# Records, per session, which lens bundles have actually been Read this run --
# .../reference/lenses/<lens>/body.md (a collapsed entrypoint's on-demand
# load) or .../skills/<lens>/SKILL.md (the standalone form, vendored or
# account-enabled). This is the evidence half of the gate: gate-lens-coverage.sh
# (its PreToolUse companion) blocks a review post that attributes a finding to
# a lens this file never recorded as read -- the mechanical version of #357's
# fix, checked by the harness instead of trusted from the reviewer's own
# self-report.
#
# Registered with matcher "Read", so it fires once per Read call and receives
# that call's hook JSON on stdin: {session_id, tool_name, tool_input:
# {file_path, ...}, ...}.
#
# Scope, stated plainly: this only sees local filesystem reads. A session
# using the cross-repo GitHub-API-fetch fallback (docs/runbooks/
# pr-review-automation.md -- when a repo has neither vendored skills nor
# account skills enabled) fetches lens content via a different tool
# (mcp__github__get_file_contents), which this hook does not match --
# gate-lens-coverage.sh fails open in that case (see its own header). Covering
# that path is a follow-up: match this hook on that tool too, keyed on its
# path argument instead of tool_input.file_path.
#
# Always exits 0 -- this hook only records evidence, it never blocks. A
# missing jq, an unwritable state dir, or malformed input degrades to "don't
# record this one," same discipline as ../log-skill-invocation.sh.
#
# bash 3.2 compatible (macOS default), matching tooling/keep-plugin-current.sh.

set -u

input="$(cat)"   # drain stdin unconditionally so the caller never blocks on a full pipe

command -v jq >/dev/null 2>&1 || exit 0

session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
[ -n "$session_id" ] || exit 0

file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)"
[ -n "$file_path" ] || exit 0

# Match either shape a lens bundle can be Read from:
#   .../reference/lenses/<lens>/body.md   -- collapsed entrypoint, on-demand load
#   .../skills/<lens>/SKILL.md            -- standalone, vendored or account skill
lens=""
case "$file_path" in
  # Both branches need a no-prefix variant too: a path can legitimately start
  # at "reference/lenses/..." or "skills/..." with nothing before it (e.g.
  # this repo's own top-level skills/<lens>/SKILL.md), not only nested under
  # some other prefix like .claude/ or collapsed/skills/<entrypoint>/.
  reference/lenses/*/body.md | */reference/lenses/*/body.md)
    lens="${file_path%/body.md}"
    lens="${lens##*/reference/lenses/}"
    lens="${lens#reference/lenses/}"
    ;;
  skills/*/SKILL.md | */skills/*/SKILL.md)
    lens="${file_path%/SKILL.md}"
    lens="${lens##*/skills/}"
    lens="${lens#skills/}"
    ;;
  *)
    exit 0   # not a lens file -- nothing to record
    ;;
esac
[ -n "$lens" ] || exit 0

state_dir=".claude/.atlas-lens-coverage"
mkdir -p "$state_dir" 2>/dev/null || exit 0
state_file="$state_dir/$session_id.txt"

# One lens slug per line; dedupe on write so the gate hook stays a plain
# `grep -Fxq` with no need to de-duplicate on read.
if ! grep -Fxq "$lens" "$state_file" 2>/dev/null; then
  printf '%s\n' "$lens" >> "$state_file" 2>/dev/null
fi

exit 0
