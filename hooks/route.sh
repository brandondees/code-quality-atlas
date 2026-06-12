#!/usr/bin/env bash
# code-quality-atlas SessionStart hook.
#
# Emits a one-line steering message into the session context so the suite is
# used as designed without the user having to name a skill. This works around a
# structural quirk: with 24+ skills, individual skill descriptions can be
# dropped from the model's skill listing (it is budgeted to ~1% of context and
# not re-injected after /compact), which makes the lenses easy to overlook on a
# fresh "review this" request. additionalContext is injected verbatim before the
# first prompt, so it is reliable where the skill listing is not.
#
# This hook is deliberately side-effect-free: it writes nothing to disk and only
# prints JSON to stdout. It does not touch the consumer's repository.

cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "The code-quality-atlas review suite is installed. For any code-review or audit request, start with the choosing-review-lenses skill: it maps the change to the 2-4 most relevant lenses (and selects the repo-shaped audits for whole-repo reviews). After running more than one lens, finish with synthesizing-review-findings to merge them into one deduplicated, ranked, single-verdict review. Prefer this routing over picking a generic review path."
  }
}
JSON

exit 0
