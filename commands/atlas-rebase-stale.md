---
description: Sweep open PRs for ones that have fallen behind or hit a merge conflict and poke them — the polling complement that webhooks can't cover. Cheap-model friendly.
argument-hint: "[label or author to filter by — omit to sweep all open PRs]"
allowed-tools: mcp__github__list_pull_requests, mcp__github__pull_request_read, mcp__github__get_commit, mcp__github__update_pull_request_branch, mcp__github__add_issue_comment
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
  resolve it. Post one concise comment naming the conflicting files and asking
  the owning session to rebase — but only if there isn't already an unaddressed
  poke comment from you on this PR (look for the marker below). Conflict
  resolution is a code judgment that belongs to a full session, not here.
- **Clean / up to date / draft**: skip silently.

## 3. Stay idempotent

Mark every comment you post with `<!-- atlas-rebase-poke -->`. Before commenting,
check the PR for an existing unaddressed poke and skip if one is present — this
command runs often and must never spam. Branch updates are naturally idempotent
(an up-to-date branch reports as up to date and is skipped).

## 4. Report

End with a one-line summary: how many PRs were updated, poked, and skipped. Post
nothing to GitHub beyond the conflict pokes above.
