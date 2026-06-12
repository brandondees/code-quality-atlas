---
description: Sweep open PRs for ones that have fallen behind or hit a merge conflict and poke them — the polling complement that webhooks can't cover. Cheap-model friendly.
argument-hint: "[label or author to filter by — omit to sweep all open PRs]"
allowed-tools: mcp__github__list_pull_requests, mcp__github__pull_request_read, mcp__github__get_commit, mcp__github__update_pull_request_branch, mcp__github__add_comment_to_pending_review, mcp__github__pull_request_review_write
---

You are the **stale-PR poker**. GitHub emits no webhook when a base branch
advances and leaves a PR behind or in conflict, so neither an auto-fix
subscription nor a `synchronize`-triggered review will ever notice. This command
is the polling backstop — run it on a **frequent schedule** with a cheap, fast
model (see `docs/runbooks/pr-review-automation.md`). Keep it mechanical; it makes
no code judgments.

## 1. List candidates

List open PRs with `mcp__github__list_pull_requests` (apply the `$ARGUMENTS`
label/author filter if given). For each, read its mergeable state via
`mcp__github__pull_request_read`.

## 2. Classify each PR

- **Behind but auto-mergeable** (`mergeable_state` = `behind`, no conflicts):
  bring it up to date with `mcp__github__update_pull_request_branch`. This emits
  a `synchronize` event, which re-triggers the reviewer and any auto-fix session
  naturally — no comment needed.
- **Conflicted** (`mergeable_state` = `dirty`/`conflicting`): do **not** try to
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

## 3. Stay idempotent

Mark every poke with `<!-- atlas-rebase-poke -->` in the review-comment body. Before
posting, list the PR's existing **review threads** (`mcp__github__pull_request_read`,
review-comments method) and skip if an unaddressed poke from you is already there —
this command runs often and must never spam. Branch updates are naturally idempotent
(an up-to-date branch reports as up to date and is skipped).

## 4. Report

End with a one-line summary: how many PRs were updated, poked, and skipped. Post
nothing to GitHub beyond the conflict pokes above.
