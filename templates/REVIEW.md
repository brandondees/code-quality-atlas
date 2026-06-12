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

## Round cap

- **Hard cap: 4 rounds.** Beyond it, post nothing but a one-line note that the cap
  was reached and stop. A PR still churning after four review rounds needs a human,
  not another machine round.

## Approve-on-clean (the terminal state)

- When a round produces **no findings at or above its floor**, submit a single
  `APPROVE` review saying so. The build session then sees no actionable comments
  and quiesces — that is how the loop ends, not by running out of rounds.

## Scope discipline

- Review only the files in the PR's diff, never the whole repo (that's what the
  `auditing-*` skills and scheduled audits are for).
- Severity vocabulary is the atlas synthesizer's own (`synthesizing-review-findings`),
  ranked **Blocker > Major > Minor > Nit**: **Blocker** (block: correctness,
  security, data loss), **Major** (should fix before merge), **Minor** / **Nit**
  (polish). A single Blocker blocks; only nits left means approve.
