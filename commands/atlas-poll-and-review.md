---
description: >-
  Poll-driven alternative to the event-triggered reviewer: one scheduled sweep
  does rebase/conflict polling AND the actual round-1 and re-review work
  itself, delegating the cheap listing pass to a fast/cheap model subagent and
  the judgment-heavy review pass to a stronger one. No GitHub-event trigger
  (`Pull request opened` / `Pull request review requested`) needed at all —
  only a schedule. Trades the event-triggered design's near-instant latency
  for zero dependency on PR-activity subscriptions, self-nudge chains, or a
  webhook trigger surviving. See `docs/runbooks/pr-review-automation.md`
  ("Model B") for when to pick this over the event-triggered design.
argument-hint: "[repo, or label/author filter — omit to sweep every attached repo's open PRs]"
allowed-tools: Task, Skill, Read, Grep, Bash, mcp__github__list_pull_requests, mcp__github__pull_request_read, mcp__github__get_file_contents, mcp__github__get_commit, mcp__github__list_commits, mcp__github__get_me, mcp__github__update_pull_request_branch, mcp__github__add_comment_to_pending_review, mcp__github__pull_request_review_write, mcp__github__add_issue_comment, mcp__github__add_reply_to_pull_request_comment, mcp__github__resolve_review_thread
---

**`allowed-tools` above covers both the top-level sweep and every subagent it
spawns** — a `Task`-spawned subagent inherits this session's tool grants
rather than needing a separate list, which is why it's wider than what steps
1-2 call directly: the review subagent in step 3 needs everything
`atlas-review-pr.md` itself requires (`Skill`, `get_file_contents`, `get_me`,
`resolve_review_thread`, and the rest), inherited from here rather than
granted again per spawn. Nothing here is unused — it's used one level down.

You are the **poller-reviewer**: a single scheduled sweep that replaces both
the event-triggered reviewer routine and the escalation-only poller
(`atlas-rebase-stale.md`) with one mechanism. GitHub emits no webhook for a
base branch advancing past a PR, and a resident reviewer session's watch
(subscription or self-nudge) can silently lapse — this command sidesteps both
by never depending on either: it runs itself, from scratch, on a schedule, and
does the actual review inline rather than escalating to something else that
might also fail to fire. Keep the model split as strict as the split below —
it's what keeps a repo with no open PRs cheap to poll every cycle.

$ARGUMENTS names a repo (`owner/name`) or a label/author filter; omit it to
sweep every repo this session has access to.

## 1. Cheap triage — spawn a fast/cheap-model subagent

Spawn one subagent (the `Task` tool, requesting the fastest/cheapest model
your platform offers — e.g. Haiku) per repo being swept. Its job is purely
mechanical listing, not judgment, so keep it off the stronger tier entirely:
list every open PR (`mcp__github__list_pull_requests`, paginate fully,
applying `$ARGUMENTS`'s filter if a label/author was given — not a repo name),
and for each PR report back: PR number, `draft` (true/false),
`mergeable_state`, HEAD commit SHA, whether an `<!-- atlas-review-ack -->`
issue comment exists (and its `created_at` if so), whether any
`<!-- atlas-review round:N -->` review exists (and if so the **highest**
round number, that review's `commit_id`, and its author's login), and whether
an unresolved `<!-- atlas-rebase-poke -->` review thread exists. One line per
PR, nothing else — this report is the only thing the calling session reads
before acting, so keep it structured and compact.

## 2. Mechanical actions — no subagent, no judgment

From the triage report, for each non-draft PR:

- **`mergeable_state` = `behind`, no conflicts**: bring it up to date with
  `mcp__github__update_pull_request_branch` (no comment — this is silent and
  routine).
- **`mergeable_state` = `dirty`**: if no unresolved `<!-- atlas-rebase-poke -->`
  review thread already exists, post one — read the diff
  (`mcp__github__pull_request_read`, files method), anchor an inline comment to
  a line on the `RIGHT` side, submit as a `COMMENT` review
  (`mcp__github__add_comment_to_pending_review` then
  `mcp__github__pull_request_review_write`) whose body is unambiguous that this
  is a **whole-PR conflict notice**, not a line-level issue: rebase onto base
  and resolve, don't attempt the resolution yourself — that's a code judgment
  this step never makes.
- **Clean / up to date**: nothing.

**Draft PRs never reach this step or step 3** — leave them alone entirely
until marked ready for review.

## 3. The review itself — spawn a stronger-model subagent, per PR that needs one

For each non-draft PR needing a review, first **re-verify immediately before
acting** — re-run `mcp__github__pull_request_read` (`get_comments`,
`get_reviews`) for that one PR, not trusting the triage report as current.
This sweep may not be the only thing capable of reviewing this PR (a repo
could also run an event-triggered reviewer routine alongside this one) —
treat a state that already changed as "someone else got there first," not an
error.

- **No ack yet** — round 1. Post the `<!-- atlas-review-ack -->` issue comment
  **yourself, in this session, immediately** — this is the lock, and it has to
  happen before anything else for this PR so the race window stays as short as
  one API call. Do this for every PR needing round 1 *before* spawning any
  review subagent, then spawn one review subagent per PR (below).
- **Has ack, zero round reviews, ack younger than ~90 minutes**: skip —
  plausibly a review subagent (this cycle's or an earlier one) still running.
  Never spawn a second attempt while one might be in flight.
- **Has ack, zero round reviews, ack 90+ minutes old**: the earlier attempt
  crashed or was lost — this is not "in progress," it's stuck. Spawn a review
  subagent (below). Don't re-post the ack; one already exists and
  `atlas-review-pr.md` checks for it before posting its own.
- **Has ack + at least one round review, HEAD has moved past the most recent
  round's commit**: re-review — spawn a review subagent (below).
- **HEAD matches the most recent round's commit**: nothing to do.

**Review subagent** (`Task` tool, the strongest model your platform offers,
one per PR): tell it to read and follow
`commands/atlas-review-pr.md` exactly for that specific PR, and — critically —
to **re-derive the round and ack status itself from GitHub**, not trust
anything the calling session reports, since the triage pass may be stale by
the time it runs. It runs the lenses, posts that round's review, and stops —
no resident watch, no subscription, no self-nudge chain to arm. The next
scheduled sweep is what picks up the next push, by design.

**Concurrency cap: at most 5 review subagents in flight at once, across every
repo in this sweep combined.** A sweep over many attached repos could
plausibly have review work due on several PRs at the same tick — batch
review-subagent spawns in groups of 5 (wait for each batch before starting
the next) rather than firing all of them at once, so a busy sweep can't
silently fan out into an unbounded number of concurrent strong-model
subagents each posting to GitHub simultaneously. This is a starting number,
not a hard platform limit — raise or lower it per the account's actual
concurrency/rate-limit headroom.

## 4. Idempotency

Never spawn two review subagents for the same PR in one sweep. Never post a
second ack for a PR that already has one — re-check immediately before
posting, per step 3. Conflict-poke idempotency: skip while an unresolved
`<!-- atlas-rebase-poke -->` thread already exists. Branch updates are
naturally idempotent.

## 5. Report

End with one line per repo swept: counts of updated (rebased), conflict-poked,
round-1-reviewed, re-reviewed, and skipped. Nothing else goes to GitHub beyond
the actions above.
