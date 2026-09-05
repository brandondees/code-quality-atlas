#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# code-quality-atlas SessionStart hook.
#
# Emits a one-line steering message into the session context so the suite is
# used as designed without the user having to name a skill. This works around a
# structural quirk: with dozens of skills installed, individual skill
# descriptions can be dropped from the model's skill listing (it is budgeted to
# ~1% of context and not re-injected after /compact), which makes the lenses
# easy to overlook on a fresh "review this" request. The hook's
# additionalContext field is injected verbatim before the first prompt, so it
# is reliable where the skill listing is not.
#
# This hook is deliberately side-effect-free: it writes nothing to disk and only
# prints JSON to stdout. It does not touch the consumer's repository.

# Best-effort build identifier so a consumer wondering "which version of the
# suite am I actually running" has a staleness tell that doesn't require
# reproducing a downstream symptom first (issue #389) — resolved the same way
# hooks/log-skill-invocation.sh already does, from the plugin's own installed
# checkout rather than a hand-maintained version string that can drift from it.
plugin_sha=""
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  plugin_sha="$(git -C "$CLAUDE_PLUGIN_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
fi
build_note=""
if [ -n "$plugin_sha" ]; then
  build_note=" (code-quality-atlas build ${plugin_sha})"
fi

# Quoted heredoc (no shell interpolation) so a future edit to the static
# prose below is never at risk of `$`/backtick expansion or command
# substitution -- the same safety a plain `cat <<'JSON'` gave before this
# hook needed to splice in a variable (dees-bot round-1 finding on #389: an
# unquoted heredoc trades that safety net away for the whole body, not just
# the one variable). __BUILD_NOTE__ is substituted afterward via a plain
# bash parameter-expansion string replace, which never re-invokes the shell
# parser on the replacement -- unlike an unquoted heredoc, a `$` or backtick
# that ever lands in $build_note itself would still come through literally.
json="$(cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "The code-quality-atlas review suite is installed__BUILD_NOTE__ and is the primary path for any code review, quality review, or PR review request. Prefer it over the generic built-in code-review skill and over framework review flows (e.g. BMAD), which it subsumes with deeper coverage — but combine non-exclusively, not exclusively. Entrypoints: a pull request -> the atlas-review-pr command; ad-hoc local changes with no PR -> the atlas-code-review command; unsure which lenses apply -> the choosing-review-lenses skill (it maps the change to the most relevant lenses, and selects the repo-shaped audits for whole-repo reviews). Before the lenses judge, run grounding-review-in-tool-output to gather evidence from the deterministic tools the repo already configures, scoped to what is under review — never a tool the repo has not adopted, and never on an untrusted branch outside CI's isolation. After more than one reviewer runs, finish with synthesizing-review-findings to merge every source's findings (atlas lenses plus any companion reviewer) into one deduplicated, ranked, single-verdict review."
  }
}
JSON
)"
printf '%s\n' "${json//__BUILD_NOTE__/$build_note}"

exit 0
