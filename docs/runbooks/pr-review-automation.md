# Runbook — Hands-off PR review automation

This wires the atlas suite into a self-driving pull-request loop on **Claude Code
on the web** (cloud sandbox sessions): a build session opens a PR and auto-fixes
feedback, an event-triggered reviewer posts findings on every push, and a frequent
poller covers the merge-conflict gap that webhooks don't. It replaces a manually
spun-up second review session, and it isn't budget/rate-limited the way the
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
| Reviewer routine (GitHub trigger) | Claude Code web app | you, once (below) |
| Poller routine (schedule trigger) | Claude Code web app | you, once (below) |
| Build + auto-fix session | a live web session | you start it / your existing flow |

## The three moving parts

```
                 push / synchronize
build+autofix ───────────────────────►  reviewer routine  ── posts inline findings ─┐
  session     ◄───────────────────────────────────────────────────────────────────┘
     ▲   reacts to review comments (auto-fix)                                         
     │                                                                                
     └──── poller routine (every ~15 min) ── rebases "behind" PRs, pokes conflicts ───
```

1. **Build + auto-fix session** — your existing flow. One web session opens the PR
   and watches it via PR-activity subscription (the `/autofix-pr` / "watch this PR"
   mechanism), reacting to **new review comments and CI failures**. Nothing new here.
2. **Reviewer routine** — a routine with a **GitHub trigger**, the event-driven
   (non-cron) trigger type. Fires within seconds of `opened`/`synchronize`, spins
   up a fresh session, runs `/atlas-review-pr`. Because every push emits
   `synchronize`, the re-review loop is automatic.
3. **Poller routine** — a **scheduled** routine on a cheap fast model running
   `/atlas-rebase-stale`. Catches PRs that fell **behind or into conflict**, which
   GitHub never delivers as a webhook, so neither (1) nor (2) can see them.

## Setup

### 0. Prerequisites

- The plugin installed in the reviewed repo via `.claude/settings.json` (see the
  README "Install" section) so **web sessions** load it at startup.
- The GitHub App installed on the repo (required for GitHub triggers).
- `cp templates/REVIEW.md REVIEW.md` in the reviewed repo, tune the floors/cap,
  commit it.

### 1. Reviewer routine (event-driven, no cron lag)

In the Claude Code web app → **Routines** → new routine:

- **Repository:** the reviewed repo.
- **Trigger:** **GitHub** → events **`opened`** and **`synchronize`** (add
  `reopened` if you reopen PRs). *Not* a schedule — the GitHub trigger is the
  webhook-immediate one.
- **Model:** a strong model (review quality matters here).
- **Prompt:** `/atlas-review-pr`

### 2. Poller routine (the conflict/stale backstop)

A second routine on the same repo:

- **Trigger:** **Schedule** → every ~15 min (tighten/loosen to taste).
- **Model:** a cheap, fast model (e.g. Haiku) — this job is mechanical.
- **Prompt:** `/atlas-rebase-stale`

### 3. (Optional) merge gate

If you already run a scheduled "merge PRs meeting criteria" routine, point its
criteria at the reviewer's terminal state: an `APPROVE` from the atlas reviewer
carrying `<!-- atlas-review round:N -->` plus green CI is a clean "ready" signal.

## Why it converges instead of looping forever

Two autonomous sessions reacting to each other will ping-pong without a brake.
The brakes live in `REVIEW.md` and are enforced by `/atlas-review-pr`:

- **Escalating severity floor** — round 1 posts everything; later rounds post only
  Major+, then Blocker-only. Fewer comments each round ⇒ fewer fixes ⇒ fewer pushes.
- **Approve-on-clean** — a round with nothing above its floor posts a single
  `APPROVE`. The build session then has no actionable comments and goes quiet. This
  is the real terminal state.
- **Hard round cap** — a backstop (default 4) that hands a still-churning PR to a
  human rather than burning another machine round.

## Known boundaries

- **Per-account hourly caps** on GitHub-triggered sessions (research preview). A PR
  that pushes many times an hour can starve the trigger; the escalating floor keeps
  push volume down.
- **Merge conflicts have no webhook** — only the poller catches them; it pokes (it
  does **not** auto-resolve, since that's a code judgment).
- **CI *success* and bare pushes** aren't delivered to a PR-activity subscription;
  the reviewer routine sidesteps that by triggering on `synchronize` directly.
- A subscription/routine can't share context with the build session — they're
  separate sessions communicating only through the PR (comments, reviews, commits).
