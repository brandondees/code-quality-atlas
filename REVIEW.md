# REVIEW.md — convergence policy for the atlas PR reviewer

Copy this file to the **root of the repo you want reviewed**. The
`/atlas-review-pr` command reads it to decide how aggressive each review round
should be, and when to stop. Without it, the command falls back to these same
defaults. The repo's own copy always wins, so tune the numbers per project.

The point of this policy is convergence: the reviewer and the build (auto-fix)
session react to each other, and a `synchronize`-triggered reviewer re-runs on
every push. An escalating severity floor plus a hard round cap is what turns that
mutual reaction into a loop that *settles* instead of one that ping-pongs forever.

## Severity floor per round

Each round, drop every finding below the floor. The floor rises as rounds
accumulate, so later rounds only interrupt for things that actually matter.

| Round | Post findings of severity… | Rationale |
|---|---|---|
| 1 | Nit and above (everything) | First pass — say it all once. |
| 2 | Major and above | Nits and minors were the reviewer's chance; now focus on substance and on flaws in the round-1 fixes. |
| 3+ | Blocker only | Near convergence — interrupt only for correctness/security/data-loss regressions. |

Dropping a finding *below the floor* means it is not posted as an **inline review
comment** — those are the actionable items that drive the fix loop. It does **not**
mean the finding disappears: every round, the below-floor findings are still
reported as a short **non-blocking advisory list** in the review summary (see
[Non-blocking findings](#non-blocking-findings-advisory)), the way Copilot and
CodeRabbit surface non-blocking notes — so the author can dig deeper and tidy up
without re-opening the convergence loop.

## Non-blocking findings (advisory)

Findings below the current round's floor are reported as an advisory list in the
**review summary body only** — never as inline threads, and never `resolve`d or
re-raised thread-to-thread. They are informational: the build / auto-fix session
**may** optionally address them but is not required to; they do **not** block, do
**not** count as actionable for convergence, and do **not** on their own earn a new
round. Keep each to one line — *severity · location · one-clause description*. This
keeps the actionable surface (inline, at/above floor — "what must change") cleanly
separate from the advisory surface (summary, below floor — "what could be tidied").

## Round cap

- **Hard cap: 4 rounds.** Beyond it, post no new inline comments and run no new
  round — but the cap note is **not silent**: post a one-line "cap reached" notice
  that also re-surfaces the **outstanding non-blocking findings** (carry forward the
  advisory list from the last round's summary), so the human taking over sees
  exactly what is left below the floor. A PR still churning after four review rounds
  needs a human, not another machine round.

## Approve-on-clean (the terminal state)

- When a round produces **no findings at or above its floor**, submit a single
  `APPROVE` review saying so — and if any below-floor findings exist, include them
  as the non-blocking advisory list so they stay visible for optional polish. The
  build session then sees no actionable (inline) comments and quiesces — that is how
  the loop ends, not by running out of rounds.

## Scope discipline

- Review only the files in the PR's diff, never the whole repo (that's what the
  `auditing-*` skills and scheduled audits are for).
- Severity vocabulary is the atlas synthesizer's own (`synthesizing-review-findings`),
  ranked **Blocker > Major > Minor > Nit**: **Blocker** (block: correctness,
  security, data loss), **Major** (should fix before merge), **Minor** / **Nit**
  (polish). A single Blocker blocks; only nits left means approve.
