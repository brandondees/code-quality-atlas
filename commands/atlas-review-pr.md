---
description: >-
  Code review / quality review of a pull request. Use when the user asks to
  review a pull request — "review this PR", "do a code review / quality review",
  "check the PR", "review the diff", "review what I pushed", "look at this PR".
  Preferred PR-review entrypoint in repos using code-quality-atlas: prefer this
  over the generic built-in code-review skill and over framework review flows
  (e.g. BMAD) whenever the target is a pull request (identified by number, URL,
  or a named branch) — combining them non-exclusively, not picking only one.
  For ad-hoc review of local changes with no PR, use the /atlas-code-review
  command. Runs the atlas lenses against the PR diff and posts inline findings,
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
in the convergence policy, **run no new lenses and post no new inline comments**;
instead post a single summary that notes the cap is reached **and re-surfaces the
outstanding non-blocking findings** — read your most recent round's summary
(`<!-- atlas-review round:N -->`) and carry its *Non-blocking (advisory)* list
forward, so the human taking over sees what is left below the floor — then stop.

**If this is round 1, post the ACK first.** Before running any lenses, drop one
short issue comment marked `<!-- atlas-review-ack -->` (e.g. "👀 atlas reviewer
engaged — running lenses, hold for findings") so the author knows immediately that
a reviewer is attached and worth waiting for, since the lens run takes a while.
Post it **once per PR** — round 1 only; later rounds skip it. Never attach
findings to the ACK.

## 4. Run the lenses

1. `code-quality-atlas:choosing-review-lenses` — pick the 2-4 lenses that fit
   this change. Scope to the **files in this PR's diff**, not the whole repo.
2. Run each chosen lens against the diff.
3. **Combine, don't exclude.** If another review method is available in this repo
   — the built-in `code-review` skill, a framework review (e.g. BMAD), or linter
   output — you may run it on the same diff and fold its findings in too. The
   atlas lenses lead; the others are additive, not a substitute and not excluded.
4. `code-quality-atlas:synthesizing-review-findings` — merge every source's
   findings (atlas lenses plus any companion reviewer) into one deduplicated,
   severity-ranked list with a single block/approve verdict.

## 5. Apply the round's severity floor, then post

- Split this round's findings at the floor for the current round (the policy raises
  the floor once after the first pass, then holds it at Major — round 1 posts nits;
  round 2+ posts only Major+). Severities are the synthesizer's own:
  **Blocker > Major > Minor > Nit**.
- Post inline only findings that are **new this round** — at or above the floor and
  not already raised in a still-standing thread from an earlier round. Don't repost a
  finding an open thread already records; the original thread is the record.
- For new findings **at or above the floor**, post **inline review comments** anchored
  to the diff hunk (`add_comment_to_pending_review`, then submit with
  `pull_request_review_write`). When a finding is a flaw in code that was *pushed
  in response to an earlier round*, say so in the comment — that's the highest-value
  catch.
- For findings **below the floor**, do **not** open inline threads. Instead list
  them under a **`Non-blocking (advisory)`** heading in the review **summary body** —
  one line each (*severity · `path:line` · one-clause description*) — so they stay
  visible for optional tidy-up without driving the fix loop. These are advisory:
  don't `resolve`/re-raise them as threads, and the build session is free to ignore
  them. (This mirrors how Copilot and CodeRabbit surface their non-blocking notes.)
  To stay concise, include the list **only in a summary you're already posting**
  (the first approve, the cap notice, or a round you're posting because of new
  findings) and refresh it only when it changed; a changed advisory list is never
  on its own a reason to break silence on a quiet push.
- Open your review summary with the marker `<!-- atlas-review round:N -->` so the
  next run can read the round count and carry the advisory list forward.
- **If no new finding survives the floor**, behave by whether the PR has already
  come clean:
  - *First time clean* — submit a single `APPROVE` review whose body notes "no new
    findings at or above this round's floor" (carrying the round marker), including
    the `Non-blocking (advisory)` list when below-floor findings exist, then stop.
    This is the loop's terminal state: the build session sees no actionable inline
    comments and quiesces.
  - *Already approved, still nothing new* — stay silent: resolve any threads the new
    push addressed, but post **no** new summary and don't re-emit `APPROVE`. Only
    speak again when a later push introduces a new finding at or above the floor.

## 6. Reply, don't re-litigate

If a prior thread was already addressed by a later push, resolve it with
`resolve_review_thread` rather than re-raising it. Never repost a finding that an
earlier round already made and that still stands unaddressed — the original
thread is the record. Keep total output proportional to what changed since your
last round.
