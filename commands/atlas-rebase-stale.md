---
description: Sweep open PRs for ones that have fallen behind, hit a merge conflict, or slipped past a resident reviewer's watch, and poke or re-trigger as needed — the polling complement that webhooks can't cover. Cheap-model friendly.
argument-hint: "[label or author to filter by — omit to sweep all open PRs]"
allowed-tools: mcp__github__list_pull_requests, mcp__github__pull_request_read, mcp__github__get_commit, mcp__github__update_pull_request_branch, mcp__github__add_comment_to_pending_review, mcp__github__pull_request_review_write, mcp__github__add_issue_comment
---

You are the **stale-PR poker**. GitHub emits no webhook when a base branch
advances and leaves a PR behind or in conflict, so neither an auto-fix
subscription nor a `synchronize`-triggered review will ever notice. A resident
reviewer session watching a PR can also just disappear — a bare push with no
CI/comment activity may not wake its subscription, and the session itself can be
reclaimed after a period of inactivity, silently ending the watch with no one
told coverage lapsed. This command is the polling backstop for both gaps — run
it on a **frequent schedule** with a cheap, fast model (see
`docs/runbooks/pr-review-automation.md`). Keep it mechanical; it makes no code
judgments, and re-triggering a review is a delegation, not a review itself.

## 1. List candidates

List open PRs with `mcp__github__list_pull_requests` (apply the `$ARGUMENTS`
label/author filter if given). For each, read its mergeable state via
`mcp__github__pull_request_read`.

## 2. Classify each PR

- **Behind but auto-mergeable** (`mergeable_state` = `behind`, no conflicts):
  bring it up to date with `mcp__github__update_pull_request_branch`. This emits
  a `synchronize` event, which re-triggers the reviewer and any auto-fix session
  naturally — no comment needed.
- **Conflicted** (`mergeable_state` = `dirty`): do **not** try to
  resolve it — that's a code judgment for a full session. Flag it where the PR
  author's auto-fix subscription will actually see it: that subscription reads
  **review threads**, not issue comments, so post the poke as an **inline review
  comment**. Read the PR's files (`mcp__github__pull_request_read`, files method) to
  get the diff, anchor the comment to a line that appears in the diff (`side: RIGHT`),
  and submit it as a `COMMENT` review (`mcp__github__add_comment_to_pending_review`
  then `mcp__github__pull_request_review_write`). Make the body unambiguous that it is
  a **whole-PR conflict notice, not a line-level issue**: the PR conflicts with its
  base branch — rebase onto the base, resolve the conflicts, and push. Leave *how* to
  resolve to the owning session. Post only if there isn't already an unaddressed poke
  from you (see the marker below).
- **Clean / up to date / draft**: skip silently.

## 3. Check reviewer coverage of the current HEAD

**Precondition: only run this check when the PR has at least one posted
`<!-- atlas-review round:N -->` review.** An `<!-- atlas-review-ack -->` comment
with **zero** round reviews behind it (e.g. the reviewer crashed right after
posting the ack, or is still mid-flight on round 1) has no baseline commit to
compare HEAD against — "moved past every posted round" is vacuously true over an
empty set and would false-positive on a PR that's simply still being reviewed.
Skip those PRs in this step entirely; don't poke them.

For each open PR that has **at least one** posted round review, compare the HEAD
commit SHA (`mcp__github__pull_request_read`) against the commit the
**most recent** `<!-- atlas-review round:N -->` review was posted against
(`mcp__github__get_commit` / the review's `commit_id`). If HEAD has moved past
that round with no unaddressed `<!-- atlas-coverage-poke -->` from you already on
the PR, the reviewer's watch has lapsed on this push (missed subscription
wakeup, or the resident session was reclaimed) — post a single issue comment
marked `<!-- atlas-coverage-poke -->` that says review coverage may have lapsed
for this push and a fresh review is needed; do **not** attempt the review
yourself. A PR with no ack comment yet has simply not been picked up (e.g. the
reviewer routine hasn't fired) — leave it to its own trigger, this step only
covers a **lapsed** watch with an established baseline, not a missing or
still-in-flight one.

## 4. Stay idempotent

Mark every conflict poke with `<!-- atlas-rebase-poke -->` (review-comment body)
and every coverage poke with `<!-- atlas-coverage-poke -->` (issue-comment body).
Before posting either, list the PR's existing review threads / issue comments and
skip if an unaddressed poke of that kind from you is already there — this command
runs often and must never spam. Branch updates are naturally idempotent (an
up-to-date branch reports as up to date and is skipped).

## 5. Report

End with a one-line summary: how many PRs were updated, conflict-poked,
coverage-poked, and skipped. Post nothing to GitHub beyond the pokes above.
