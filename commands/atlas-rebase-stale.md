---
description: Sweep open PRs for ones that have fallen behind, hit a merge conflict, or slipped past a resident reviewer's watch, and poke or re-trigger as needed — the polling complement that webhooks can't cover. Cheap-model friendly.
argument-hint: "[label or author to filter by — omit to sweep all open PRs]"
allowed-tools: mcp__github__list_pull_requests, mcp__github__pull_request_read, mcp__github__get_commit, mcp__github__update_pull_request_branch, mcp__github__update_pull_request, mcp__github__add_comment_to_pending_review, mcp__github__pull_request_review_write, mcp__github__add_issue_comment
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
**Don't just flag a lapse — retrigger it** (§3): re-requesting review is a real
GitHub event a companion routine can wake on, not only a comment a human has to
notice.

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

A round review is identified by a `## Round N — ...` heading as the body's
first line, falling back to the redundant `<!-- atlas-review round:N -->`
marker only where the heading is absent — `pull_request_read` has been
observed stripping HTML comments from returned review bodies entirely
(#354/#355), so the marker alone is not a reliable presence/absence signal.
Likewise, an ack is either the `<!-- atlas-review-ack -->` marker or the
visible "👀 atlas reviewer engaged" text.

**Precondition: only run this check when the PR has at least one posted round
review** (per the definition above). An ack comment with **zero** round
reviews behind it (e.g. the reviewer crashed right after posting the ack, or
is still mid-flight on round 1) has no baseline commit to
compare HEAD against — "moved past every posted round" is vacuously true over an
empty set and would false-positive on a PR that's simply still being reviewed.
Skip those PRs in this step entirely; don't poke them.

For each open PR that has **at least one** posted round review, compare the HEAD
commit SHA (`mcp__github__pull_request_read`) against the commit the
**most recent** round review was posted against
(`mcp__github__get_commit` / the review's `commit_id`).

**What counts as "already addressed" — defined precisely, because a plain issue
comment carries no GitHub-native resolved state** (unlike the conflict-poke
review thread, which has a real `isResolved`/`isOutdated` signal): a
`<!-- atlas-coverage-poke -->` comment is addressed once a round review has
been **posted after it** — compare
the poke comment's `created_at` against the most recent round review's
`submitted_at`. A poke with **no** later round review is still outstanding;
skip escalating again while one is outstanding. A poke that **does** have a
later round review behind it already did its job (it got a fresh round), so it
no longer counts as outstanding — if HEAD has since moved past *that* round too,
this is a **new** lapse, not a repeat of the old one, and escalates again. Don't
use bare presence as the check: since an issue comment never resolves itself, a
presence-only reading would treat the PR's first-ever poke as "already there"
forever and permanently disable this escalation for the rest of the PR's life.

If HEAD has moved past the most recent round with no outstanding coverage-poke
(by the definition above), the reviewer's watch has lapsed on this push (missed
subscription wakeup, or the resident session was reclaimed) — escalate in two
ways, not one:

1. Post a single issue comment marked `<!-- atlas-coverage-poke -->` that says
   review coverage may have lapsed for this push and a fresh review is needed —
   a human-visible record, kept even when nothing automated is wired to act on it.
2. **Re-request review from the same login that posted the most recent round
   review** (read it off that review's author, no hardcoded identity —
   `mcp__github__update_pull_request`, passing **only** `owner`, `repo`,
   `pullNumber`, and `reviewers: [<that login>]` — never `state`, `base`,
   `title`, `body`, or `draft`, even though the tool schema permits them; this
   command is unattended, scheduled, and swept across every attached repo, so
   its tool grant stays load-bearing only for what this step actually needs).
   This fires a real GitHub `review_requested` event. If the reviewer has a
   companion routine on that trigger (see
   `docs/runbooks/pr-review-automation.md` §1a), this is what actually
   retriggers a fresh review session, independent of whether the original
   resident session or its subscription survived — GitHub delivers this event
   regardless. Without that companion routine wired up it's still a correct,
   harmless signal (a human sees a pending review request either way), just not
   a self-healing one.

Do **not** attempt the review yourself in either case. A PR with no ack comment
yet has simply not been picked up (e.g. the reviewer routine hasn't fired) —
leave it to its own trigger, this step only covers a **lapsed** watch with an
established baseline, not a missing or still-in-flight one.

## 4. Stay idempotent

Mark every conflict poke with `<!-- atlas-rebase-poke -->` (review-comment body)
and every coverage poke with `<!-- atlas-coverage-poke -->` (issue-comment body).
Before posting either, list the PR's existing review threads / issue comments and
skip if an **outstanding** poke of that kind from you is already there — this
command runs often and must never spam. For the conflict-poke, "outstanding"
means the review thread isn't resolved (GitHub's own `isResolved`). For the
coverage-poke, use §3's precise definition (a later round review clears it) —
never a bare presence check, which would silently and permanently disable the
coverage escalation after the PR's first-ever lapse. Branch updates are
naturally idempotent (an up-to-date branch reports as up to date and is
skipped).

## 5. Report

End with a one-line summary: how many PRs were updated, conflict-poked,
coverage-poked, and skipped. Post nothing to GitHub beyond the pokes above.
