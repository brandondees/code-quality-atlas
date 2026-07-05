# REVIEW.md — convergence policy for the atlas PR reviewer

Copy this file to the **root of the repo you want reviewed**. The
`/atlas-review-pr` command reads it to decide how aggressive each review round
should be, and when to stop. Without it, the command falls back to these same
defaults. The repo's own copy always wins, so tune the numbers per project.

The point of this policy is convergence: the reviewer and the build (auto-fix)
session react to each other, and a `synchronize`-triggered reviewer re-runs on
every push. The brakes that keep that mutual reaction from ping-ponging forever
are: a severity floor that rises once and then **plateaus at Major** (so later
rounds are low-noise but still catch real problems), a rule that **only
genuinely-new findings earn a comment** (quiet pushes stay quiet), and a hard
round cap as a backstop.

## Reviewer ACK (start-of-review notice)

On the **first round** for a PR, before running any lenses, post one short issue
comment marked `<!-- atlas-review-ack -->` — e.g. "👀 atlas reviewer engaged —
running lenses, hold for findings." This is an acknowledgment, not a finding: it
lets the author (or their auto-fix session) know immediately that a reviewer is
attached and worth waiting for, since the lens run itself takes a while. Post it
**once per PR** (round 1 only); later rounds don't repeat it — the author already
knows the reviewer is live. Keep it to one line; never attach findings to the ACK.

## Severity floor per round

Everything below applies to the default **review** depth mode — the one
`/atlas-review-pr` runs unless the request asks for a different depth. See
[Depth modes](#depth-modes) for **triage** and **comprehensive**, which use a
fixed floor instead of the round-based escalation described here.

Each round, drop every finding below the floor. The floor rises once after the
first pass, then holds at **Major** — high enough to stay quiet on polish, low
enough that any real problem (including one introduced by a fix) still gets
surfaced no matter how many rounds in.

| Round | Post findings of severity… | Rationale |
|---|---|---|
| 1 | Nit and above (everything) | First pass — say it all once. |
| 2+ | Major and above | Nits and minors were the reviewer's one chance; from here on interrupt only for substance — but **keep** interrupting for it, since a Major-only stream is already low-noise. |

## Depth modes

The reviewer picks a depth mode from the request (see
`choosing-review-lenses/SKILL.md`'s Depth modes table for the exact trigger
phrases) and applies that mode's floor **instead of** the round-based table
above:

| Mode | Floor | Escalates by round? |
|---|---|---|
| **triage** | Major, every round | No — pinned at Major from round 1 |
| **review** (default) | round-based (table above) | Yes — Nit at round 1, Major at round 2+ |
| **comprehensive** | Nit, every round | No — pinned at Nit so long-tail findings never get trimmed |

Triage and comprehensive still use the rest of this policy unchanged — only-new-
findings, the round cap, and approve-on-clean all still apply; just the floor
itself is fixed instead of escalating.

Earlier versions of this policy climbed to **Blocker-only** at round 3+. That
suppressed real Major regressions (e.g. a bug introduced by a late fix) just
because the PR had taken a few rounds. The floor now **plateaus at Major**: once
the noise is gone, there's little cost to surfacing each further Major and real
downside to hiding it. Convergence comes instead from the *only-new-findings*
rule below, not from raising the floor out of reach.

Dropping a finding *below the floor* means it is not posted as an **inline review
comment** — those are the actionable items that drive the fix loop. It does **not**
mean the finding disappears: below-floor findings are still reported as a short
**non-blocking advisory list** in the review summary (see
[Non-blocking findings](#non-blocking-findings-advisory)) — the way Copilot and
CodeRabbit surface non-blocking notes — so the author can dig deeper and tidy up
without re-opening the convergence loop.

## Only new findings earn a comment (quiet on no news)

A push earns inline comments only for findings **new this round** — at or above
the floor and not already raised in a still-standing thread from an earlier round.
Re-posting a finding an open thread already records is noise; the original thread
is the record.

When a round surfaces **no new at/above-floor findings**, do not post a fresh
review summary on every push:

- **First time the PR comes clean** (nothing new at/above the floor): post one
  concise terminal note — an `APPROVE` (see
  [Approve-on-clean](#approve-on-clean-the-terminal-state)) carrying the round
  marker and, if any exist, the advisory list.
- **Subsequent quiet pushes** (still nothing new at/above the floor): stay
  silent. Resolve any threads the new push addressed, but post **no** new
  summary — there is no news. Don't re-emit `APPROVE`, and don't re-dump the
  advisory list verbatim each push.
- **A push that does bring new at/above-floor findings** re-opens the loop: post
  those inline as usual. Speak again after a quiet spell only when there's
  genuinely something new.

Keep every comment proportional to what changed since your last round. In a round
with no new findings, a single concise line — or silence — beats restating the
standing list.

## Non-blocking findings (advisory)

Findings below the current round's floor are reported as an advisory list in the
**review summary body only** — never as inline threads, and never `resolve`d or
re-raised thread-to-thread. They are informational: the build / auto-fix session
**may** optionally address them but is not required to; they do **not** block, do
**not** count as actionable for convergence, and do **not** on their own earn a new
round. Keep each to one line — *severity · location · one-clause description*. To stay
concise, include the list **only in a summary you're already posting** — the first
approve, the cap notice, or a round you're posting because of new at/above-floor
findings — and within those, refresh it when it has changed rather than re-dumping
an unchanged list. **Refresh vs. carry is decided by whether the lenses ran this
round:** when they ran (the first approve, or a new-findings round), recompute the
below-floor set and post the refreshed list; when they did **not** run (the cap
notice — see [Round cap](#round-cap)), you cannot recompute it, so carry the last
lens-running round's advisory list forward **verbatim**. A changed advisory list is
**never on its own** a reason to post on an otherwise-quiet push.
This keeps the actionable surface (inline, at/above floor — "what must change")
cleanly separate from the advisory surface (summary, below floor — "what could be
tidied").

## Round cap

- **Hard cap: 10 rounds.** Beyond it, post no new inline comments and run no new
  round — but the cap note is **not silent**: post a one-line "cap reached" notice
  that also re-surfaces the **outstanding non-blocking findings** (carry forward the
  advisory list from the last round's summary), so the human taking over sees
  exactly what is left below the floor. A PR still churning after ten review rounds
  needs a human, not another machine round.
- The cap is a backstop, not the usual exit — most PRs settle earlier via
  approve-on-clean, and the quiet-on-no-news rule means the extra headroom costs
  nothing on rounds where there's nothing new to say. Ten gives a Major-only stream
  room to keep surfacing genuine regressions across a long-lived PR; lower it if
  your PRs are short, raise it if they run long.

## Approve-on-clean (the terminal state)

- When a round produces **no new findings at or above its floor**, submit a single
  `APPROVE` review saying so — and if any below-floor findings exist, include them
  as the non-blocking advisory list so they stay visible for optional polish. The
  build session then sees no actionable (inline) comments and quiesces — that is how
  the loop ends, not by running out of rounds.
- Approving does **not** end the watch. A later push that introduces a new
  at/above-floor finding re-opens the loop (post it inline); a later push with
  nothing new stays quiet per
  [Only new findings earn a comment](#only-new-findings-earn-a-comment-quiet-on-no-news).
  Don't re-emit `APPROVE` on every subsequent quiet push.

## Scope discipline

- Review only the files in the PR's diff, never the whole repo (that's what the
  `auditing-*` skills and scheduled audits are for).
- Severity vocabulary is the atlas synthesizer's own (`synthesizing-review-findings`),
  ranked **Blocker > Major > Minor > Nit**: **Blocker** (block: correctness,
  security, data loss), **Major** (should fix before merge), **Minor** / **Nit**
  (polish). A single Blocker blocks; once only below-floor findings remain, approve.
