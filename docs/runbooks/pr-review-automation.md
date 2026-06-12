# Runbook — Hands-off PR review automation

This wires the atlas suite into a self-driving pull-request loop on **Claude Code
on the web** (cloud sandbox sessions): a build session opens a PR and auto-fixes
feedback, an event-triggered reviewer posts findings and re-reviews each push, and a
scheduled poller covers the merge-conflict gap that webhooks don't. It replaces a
manually spun-up second review session, and it isn't budget/rate-limited the way the
CodeRabbit/Copilot PR integrations are.

## What's in the plugin vs. what you wire up

The plugin ships the **behavior**; the **triggers** are account/cloud-side config
you create once in the web app. A plugin manifest installs skills, commands, and
hooks into a Claude Code installation — it cannot provision routines or triggers
in your Anthropic account, and there is no `routines` key in the manifest schema.
So:

| Piece | Where it lives | Provisioned by |
|---|---|---|
| `/atlas-review-pr` command | this plugin (`commands/`) | plugin install |
| `/atlas-rebase-stale` command | this plugin (`commands/`) | plugin install |
| `REVIEW.md` convergence policy | the **reviewed repo's** root | you copy `templates/REVIEW.md` |
| Reviewer routine (GitHub trigger + watch instructions) | Claude Code web app | you, once (below) |
| Poller routine (schedule trigger) | Claude Code web app | you, once (below) |
| Build + auto-fix session | a live web session | you start it / your existing flow |

## The three moving parts

```
                 PR opened (GitHub trigger)
build+autofix ──────────────────────────►  reviewer routine
  session     ◄──── inline findings ───────  one session: first review, then
     ▲                                        subscribes & re-reviews each push
     │  reacts to review comments / CI
     │
     └──── poller routine (hourly/daily) ── rebases "behind" PRs, pokes conflicts
```

1. **Build + auto-fix session** — your existing flow. One web session opens the PR
   and watches it via PR-activity subscription (the `/autofix-pr` / "watch this PR"
   mechanism), reacting to **new review comments and CI failures**. Nothing new here.
2. **Reviewer routine** — a routine with a **GitHub trigger** on `Pull request
   opened`. Fires within seconds of a PR opening, spins up one session that runs
   `/atlas-review-pr`, then **stays resident and watches the PR**, re-reviewing each
   push in the same session. A routine can carry only **one GitHub event** (see
   [Setup §1](#1-reviewer-routine-event-driven-no-cron-lag)), so `synchronize` can't
   be a second trigger here — the in-session subscription covers re-review instead.
   The watch behavior lives in the routine's prompt, not the command, so it's set up
   per-routine.
3. **Poller routine** — a **scheduled** routine on a cheap fast model running
   `/atlas-rebase-stale`. Catches PRs that fell **behind or into conflict**, which
   GitHub never delivers as a webhook, so neither (1) nor (2) can see them.

## Setup

### 0. Prerequisites

- The plugin installed in the reviewed repo via `.claude/settings.json` (see the
  README "Install" section) so **web sessions** load it at startup.
- The **Claude GitHub App** installed on the repo (required for GitHub triggers).
  The trigger setup prompts you to install it if it isn't already; if configuring
  the trigger never prompts, it's already installed. Note that `/web-setup` grants
  clone access but does **not** install the App or enable webhook delivery.
- `cp templates/REVIEW.md REVIEW.md` in the reviewed repo, tune the floors/cap,
  commit it.

### 1. Reviewer routine (event-driven, no cron lag)

In the Claude Code web app → **Routines** → **New routine**:

- **Name:** e.g. `Atlas PR reviewer`.
- **Repository:** the reviewed repo. Selecting it is what **unlocks** the GitHub
  trigger (it's greyed out until a repo is chosen).
- **Model:** a strong model (review quality matters here).
- **Trigger:** **GitHub event** → **`Pull request opened`**.
  - A routine allows **one GitHub event per trigger**, and **Add another trigger**
    only offers Schedule/API — so you *cannot* put `opened` + `synchronize` on one
    routine, and "Custom"/multi-select isn't available. Pick `opened` and let the
    session watch for pushes itself (next bullet), or see the `synchronize`
    alternative under [Known boundaries](#known-boundaries).
  - Optionally add a **filter** (e.g. *Is draft = false*, or *Head branch contains
    `claude/`*) so the reviewer only fires on PRs you actually want reviewed — each
    fire is a run (see [Usage and run limits](#usage-and-run-limits)).
- **Prompt / Instructions:** `/atlas-review-pr`, followed by an in-session **watch
  block** so a single `opened`-triggered session re-reviews subsequent pushes
  instead of exiting after the first pass. The command itself is written for the
  per-push-trigger model (it counts prior reviews via `<!-- atlas-review round:N -->`
  markers); the watch block is what adapts it to one resident session:

  ```text
  /atlas-review-pr

  After that first review, do not exit — stay resident and watch this PR until it
  is merged or closed. Subscribe to its activity and re-run the review on each new
  push, in this same session. Keep the round count and the findings you have already
  raised in memory across pushes: resolve threads that later pushes addressed, and
  never re-litigate ones that still stand. Each round, apply REVIEW.md's convergence
  policy — raise the severity floor as rounds accumulate (round 1: all; round 2:
  Major+; round 3+: Blocker-only), and post a single APPROVE when nothing meets the
  floor. Approving does NOT end your watch: stay subscribed and keep reviewing later
  pushes, so a change pushed after you approved still gets reviewed. After an
  approval, only speak again if a later push introduces a finding at or above the
  floor — don't re-post APPROVE on every subsequent quiet push. Stop watching only
  when the PR is merged or closed, or the hard round cap is reached. Note: a bare
  push with no CI or comment activity may not wake the subscription; if you suspect
  you missed pushes, re-fetch the PR head before deciding you are done.
  ```

- **Connectors:** the form attaches **all your account connectors by default** and
  warns they can be used (including writes) without per-call approval during a run.
  The reviewer only needs GitHub — which comes from the selected repo's GitHub App,
  **not** a connector — so **remove every connector** before saving. Gotcha: if you
  clear them on the Connectors tab and then click **Create**, the defaults can
  **reappear** on the saved routine; re-open it with **Edit**, remove them again,
  and **Save** — that edit sticks.
- **Permissions:** leave **Allow unrestricted branch pushes** *off*. The reviewer
  only posts reviews/comments via the GitHub API; it never pushes commits.

### 2. Poller routine (the conflict/stale backstop)

A second routine on the same repo:

- **Trigger:** **Schedule**. The web presets are **hourly / daily / weekdays /
  weekly**, and the minimum interval is **one hour** — sub-hour schedules are
  rejected, and a custom interval (e.g. every 4 hours) needs `/schedule update` in
  the CLI. (An earlier draft of this runbook said "~15 min"; that isn't achievable,
  and would be cap-expensive anyway since every fire is a run.)
- **Cadence:** pick the loosest cadence that still catches stale PRs in time —
  **hourly** for an active repo (≈24 runs/day, so mind the shared daily cap), or
  **daily** for a low-traffic one.
- **Model:** a cheap, fast model (e.g. Haiku) — this job is mechanical.
- **Connectors:** none needed (same as the reviewer — strip the defaults).
- **Prompt:** `/atlas-rebase-stale`

### 3. (Optional) merge gate

If you already run a scheduled "merge PRs meeting criteria" routine, point its
criteria at the reviewer's terminal state: an approval from the atlas reviewer
carrying `<!-- atlas-review round:N -->` plus green CI is a clean "ready" signal.

**Match the approval in the review *body*, not the GitHub review *state*.** GitHub
forbids approving your own PR, so when the reviewer runs as the **same identity
that opened the PR** — the common case here, where your build sessions open PRs as
you and the reviewer routine also runs as you — it **cannot** emit an `APPROVE`
review state. It falls back to a `COMMENT` whose body says it approves (observed:
`## Round N — APPROVE (own-PR, posted as comment)`). A gate keyed on
`reviewDecision == APPROVED` therefore never fires on your own PRs; key it on the
`<!-- atlas-review round:N -->` marker plus an `APPROVE` token in the review body
instead. (On PRs opened by a *different* identity, the reviewer posts a real
`APPROVE` state and either signal works.)

## Why it converges instead of looping forever

Two autonomous sessions reacting to each other will ping-pong without a brake.
The brakes live in `REVIEW.md` and are enforced by `/atlas-review-pr`:

- **Escalating severity floor** — round 1 posts everything; later rounds post only
  Major+, then Blocker-only. Fewer comments each round ⇒ fewer fixes ⇒ fewer pushes.
- **Approve-on-clean** — a round with nothing above its floor posts a single
  `APPROVE`. The build session then has no actionable comments and goes quiet. This
  is the real terminal state.
- **Hard round cap** — a backstop (default 4) that hands a still-churning PR to a
  human rather than burning another machine round. The cap is enforced by the
  instructions, not the platform — the reviewer decides each round whether a push
  warrants a new round, so it won't burn a round on a no-op event.

## Usage and run limits

Routines draw down two separate meters: ordinary **subscription usage** (the
token-based session/weekly limits) and a **daily included-run cap** (15/day on Max
at the time of writing — read your real number at `claude.ai/settings/usage` or
`claude.ai/code/routines`). The cap is **per account, shared across every routine**
you own, and resets daily.

- Each GitHub event that matches a trigger starts its **own session** — there's no
  session reuse across events. With an `opened`-only reviewer that's **one run per
  PR opened**; the in-session watch re-reviews subsequent pushes inside that
  already-counted session, so pushes don't each cost a run. (A `synchronize` trigger
  would cost one run *per push* — the reason we don't use it.)
- Exactly what increments the included-run counter is **not documented and observed
  to be fuzzy**: in testing, ~10 scheduled fires in a day did not increment it 1:1
  (the counter read 0/15 just after a reset, and ~7/15 by end of a prior day). Treat
  the number as soft guidance and watch `claude.ai/settings/usage` rather than
  budgeting against a strict per-fire count.
- With **usage credits** enabled, runs past the daily cap continue on metered
  overage (bounded by your monthly spend limit) rather than failing — so the loop
  doesn't silently starve; heavy days just cost credits.
- Trigger **filters** are the lever to conserve runs: scope the reviewer to the PRs
  you actually care about, and prefer the loosest poller cadence that still works.

## Known boundaries

- **Per-account hourly caps** on GitHub-triggered sessions (research preview). A PR
  that pushes many times an hour can starve the trigger; the escalating floor keeps
  push volume down.
- **Merge conflicts have no webhook** — only the poller catches them; it pokes (it
  does **not** auto-resolve, since that's a code judgment).
- **CI *success* and bare pushes** aren't reliably delivered to a PR-activity
  subscription. Because the reviewer triggers on `opened` and then *watches* via
  subscription (rather than a `synchronize` trigger), a bare push with no CI/comment
  activity can be **missed** — the watch block tells the session to re-fetch the PR
  head as a guard. If closing this gap matters more than the per-push run cost, swap
  the trigger to **`Pull request synchronize`** (one run per push), or add a second
  reviewer routine triggered on `synchronize` alongside the `opened` one.
- A subscription/routine can't share context with the build session — they're
  separate sessions communicating only through the PR (comments, reviews, commits).
