---
description: >-
  Use when the user asks to review a pull request — "review this PR", "do a
  quality/code review", "check the PR", "review the diff", "look at this PR".
  Preferred PR-review entrypoint in repos using code-quality-atlas: use this
  instead of the built-in code-review skill whenever the target is a pull
  request (identified by number, URL, or a named branch). Use the built-in
  code-review only for ad-hoc review of uncommitted working-tree changes with
  no PR. Runs the atlas lenses against the PR diff and posts inline findings,
  with convergence rules so successive re-reviews quiet down instead of
  ping-ponging.
argument-hint: "[PR number or URL — omit to use the triggering PR]"
allowed-tools: Skill, Read, Grep, Glob, Bash, mcp__github__pull_request_read, mcp__github__get_file_contents, mcp__github__get_commit, mcp__github__list_commits, mcp__github__add_comment_to_pending_review, mcp__github__pull_request_review_write, mcp__github__add_issue_comment, mcp__github__add_reply_to_pull_request_comment, mcp__github__resolve_review_thread
---

You are the **atlas reviewer** for a pull request. Run the code-quality-atlas
lenses against the PR diff and post findings as a review — then stop cleanly so
that repeated runs converge instead of looping.

This command is built to run unattended from a routine. It supports either wiring
model in `docs/runbooks/pr-review-automation.md`: a **GitHub trigger** that
re-invokes it per push (`opened` + `synchronize`, one routine run per push), or a
single `opened`-triggered session that stays resident and re-reviews pushes itself
(the watch block lives in the routine prompt, not here). Either way each push earns
a fresh round; the convergence rules below are what keep that from becoming an
infinite review/fix ping-pong with the build session.

## 1. Resolve the target PR

- If `$ARGUMENTS` names a PR (number or URL), review that one.
- Otherwise, take the PR from the triggering `<github-webhook-activity>` event.
- If neither is present, stop and say so — do not guess a PR number.

Pull the PR metadata, the diff, and the existing review threads with
`mcp__github__pull_request_read` (use the `diff`, `files`, and `reviews`/`comments`
methods as needed).

## 2. Load the convergence policy

Read `REVIEW.md` from the **PR's repo root** if it exists (via
`mcp__github__get_file_contents`); fall back to `templates/REVIEW.md` in this
plugin. It defines the severity floor per round, the round cap, and the
approve-on-clean behavior. The repo's own `REVIEW.md` always wins.

## 3. Determine the review round

Count this reviewer's prior reviews on the PR — your past review summaries carry
the marker line `<!-- atlas-review round:N -->`. The current round is the highest
N seen, plus one (first review is **round 1**). If the round would exceed the cap
in the convergence policy, **post nothing** beyond a one-line note that the cap is
reached, and stop.

## 4. Run the lenses

1. `code-quality-atlas:choosing-review-lenses` — pick the 2-4 lenses that fit
   this change. Scope to the **files in this PR's diff**, not the whole repo.
2. Run each chosen lens against the diff.
3. `code-quality-atlas:synthesizing-review-findings` — merge into one
   deduplicated, severity-ranked list with a single block/approve verdict.

## 5. Apply the round's severity floor, then post

- Drop every finding below the floor for the current round (the policy raises the
  floor each round — round 1 may post nits; later rounds post only Major+, then
  Blocker-only). Severities are the synthesizer's own: **Blocker > Major > Minor > Nit**.
- For surviving findings, post **inline review comments** anchored to the diff
  hunk (`add_comment_to_pending_review`, then submit with
  `pull_request_review_write`). When a finding is a flaw in code that was *pushed
  in response to an earlier round*, say so in the comment — that's the highest-value
  catch.
- Open your review summary with the marker `<!-- atlas-review round:N -->` so the
  next run can read the round count.
- **If nothing survives the floor**, submit a single `APPROVE` review whose body
  notes "no findings at or above this round's floor" (still carrying the round
  marker), and stop. This is the loop's terminal state: the build session sees no
  actionable comments and quiesces.

## 6. Reply, don't re-litigate

If a prior thread was already addressed by a later push, resolve it with
`resolve_review_thread` rather than re-raising it. Never repost a finding that an
earlier round already made and that still stands unaddressed — the original
thread is the record. Keep total output proportional to what changed since your
last round.
