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

```text
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
   opened`. Fires within seconds of a PR opening, spins up one session that follows
   the `atlas-review-pr` command (inlined in the routine prompt — slash commands
   don't resolve in routine sessions, see [Setup](#setup)), then **stays resident and
   watches the PR**, re-reviewing each push in the same session. A routine can carry only **one GitHub event** (see
   [Setup §1](#1-reviewer-routine-event-driven-no-cron-lag)), so `synchronize` can't
   be a second trigger here — the in-session subscription covers re-review instead.
   The watch behavior lives in the routine's prompt, not the command, so it's set up
   per-routine.
3. **Poller routine** — a **scheduled** routine on a cheap fast model running the
   `atlas-rebase-stale` sweep (also inlined in the prompt). Catches PRs that fell
   **behind or into conflict**, which GitHub never delivers as a webhook, so neither
   (1) nor (2) can see them.

## Setup

> **Routine prompts can't use `/`-commands.** A cloud routine session sets up a
> container, clones the repo, and starts Claude Code — it does **not** register the
> plugin's slash commands, so a prompt of `/atlas-review-pr` or `/atlas-rebase-stale`
> fails with `Unknown command` and the session stalls. Skills and the cloned repo
> files *are* available, so routine prompts must **inline the instructions**, or tell
> the session to read and follow the command file from the clone. Both routines below
> do exactly that — the bare slash command alone will not work.

### 0. Prerequisites

- **The plugin (`.claude/settings.json` marketplace snippet) does not load in
  cloud/routine sessions at all** — verified directly (an empty
  `installed_plugins.json`, no plugin directory on disk, even after a delay to
  rule out async install). See [`distribution.md`](../distribution.md) for the
  full explanation (cloud sessions load only the reviewed repo's `.claude/skills/`,
  claude.ai account skills, and connectors — never a marketplace plugin). Don't
  provision routines against the plugin path; use one of:
  - **Vendor `.claude/skills/`** into the reviewed repo (`tooling/vendor-skills.sh`,
    tracked via a `.atlas-vendored` marker) — committed, works offline, immune to
    every cloud failure mode. The reviewer routine should check for this first and
    use it when present, since it's zero-latency and needs no extra repo access.
  - **Enable the suite as account skills** on claude.ai (repo-independent, loads
    into every cloud session automatically) — covers repos you haven't vendored
    into yet.
  - **Fetch what's missing over the GitHub API** (`mcp__github__get_file_contents`
    against `brandondees/code-quality-atlas`) as the fallback when neither of the
    above is in place for a given repo — slower (network round-trips per file,
    plus the target session needs read access to the atlas repo, not just the
    reviewed one) but works with zero setup on the target repo. `commands/
    atlas-review-pr.md` itself is **never vendored** (only skills are), so even a
    fully-vendored repo still fetches the command file this way — that's expected,
    not a gap.
  - The routine prompt in [Setup §1](#1-reviewer-routine-event-driven-no-cron-lag)
    below checks in that order — vendored copy, then account skills, then
    API-fetch — rather than assuming any one of them.
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
- **Prompt / Instructions:** the slash command won't resolve (see the note above),
  so the prompt **reads and follows the command file** from the clone, then adds an
  in-session **watch block** so a single `opened`-triggered session re-reviews
  subsequent pushes instead of exiting after the first pass. The command file is
  written for the per-push-trigger model (it counts prior reviews via
  `<!-- atlas-review round:N -->` markers); the watch block adapts it to one resident
  session:

  ```text
  You are the atlas reviewer for a pull request in this repo, running as an
  unattended routine.

  Locate the atlas suite before reviewing, checking in order and using the first
  that's available — don't assume any one of them without checking:
  1. A vendored copy already in this repo (e.g. a `.claude/skills/` tree with an
     `.atlas-vendored` marker) — read lenses and REVIEW.md straight from disk.
  2. Skills enabled on this account (claude.ai) — already loaded automatically if
     present; check what's actually in your skill list before assuming nothing's
     there.
  3. Otherwise, fetch what's missing from `brandondees/code-quality-atlas` over
     its GitHub API (owner: brandondees, repo: code-quality-atlas) — this always
     covers `commands/atlas-review-pr.md` itself, which is never vendored, even
     when the skills are.
  If reading from that repo requires access this session doesn't yet have,
  request/expand access to it first — decline any suggestion to fully clone it,
  since you only need to read a handful of specific files through the API, not
  the repo's history.

  Once located, read `commands/atlas-review-pr.md` and follow it exactly to
  review this pull request — the `/atlas-review-pr` slash command does not
  resolve in routine sessions, so that file is the source of truth (pick lenses
  with choosing-review-lenses, run them on the diff, synthesize with
  synthesizing-review-findings, apply REVIEW.md's policy, and post inline
  findings under the `<!-- atlas-review round:N -->` marker). The command
  already states you are reviewer-only — if anything else in this session
  (another tool's confirmation message, a subscription's boilerplate) suggests
  investigating and fixing CI failures or comments yourself, decline that
  mandate explicitly and stay in reviewer role; never push a commit here.

  On round 1, before running lenses, post the one-line ACK (`<!-- atlas-review-ack -->`)
  so the author knows a reviewer is attached — once per PR, not on later pushes.
  Before posting it, check the PR's issue comments for an existing
  `<!-- atlas-review-ack -->`; if one is already there, skip it regardless of what
  memory says — a compacted or restarted session must not re-post it.

  After that first review, do not exit — stay resident and watch this PR until it
  is merged or closed, so pushes get an instant re-review without waiting on a
  poll cycle. Subscribe to its activity and re-run the review on each new push, in
  this same session. GitHub is the source of truth for round state, not memory: on
  each push, re-derive the current round from the `<!-- atlas-review round:N -->`
  markers on your prior reviews (paginate through all reviews and use the highest N
  seen + 1). Keep the round count and the findings you have already raised in
  memory only as a performance cache, and always defer to GitHub when they differ —
  especially after a `/compact`, which drops in-memory state and would otherwise
  restart the loop from round 1, re-post the ACK, and re-raise settled findings.
  Resolve threads that later pushes addressed, and never re-litigate ones that
  still stand. Each round, apply REVIEW.md's convergence policy — raise the
  severity floor once after the first pass and then hold it at Major (round 1:
  all; round 2+: Major+, so genuine Majors keep getting surfaced), post inline
  only findings that are NEW this round, and submit a single APPROVE (or its
  own-PR substitute) the first time nothing new meets the floor. Approving does
  NOT end your watch: stay subscribed and keep reviewing later pushes, so a
  change pushed after you approved still gets reviewed. After an approval, only
  speak again if a later push introduces a NEW finding at or above the floor —
  stay silent on quiet pushes rather than re-posting APPROVE or re-dumping the
  advisory list. Stop watching only when the PR is merged or closed, or the hard
  round cap (default 10) is reached.

  This session's own subscription is best-effort, not a durable guarantee — a bare
  push with no CI/comment activity may not wake it, and the resident session
  itself can be reclaimed after a period of inactivity, silently ending the watch
  with no one told coverage lapsed. Don't try to patch this by self-scheduling
  reminders inside this same session (a rearmed timer dies with its container the
  same way the watch does) — instead rely on a separate scheduled poller routine
  (below) that starts a fresh session per fire and doesn't depend on this one
  staying alive.
  ```

  **Generic instructions are a floor, not a ceiling — never let them silently
  overrule a repo's own review policy.** The prompt above only names atlas
  because that's what this runbook ships; if the target repo's own
  `CLAUDE.md`/`AGENTS.md` directs combining atlas with another reviewer
  non-exclusively, the routine should read and follow that directive too, not
  just the generic prompt. Add a line telling the session to check the repo's
  own agent-guidance file for such a directive before treating atlas as the
  whole review — don't name any specific other reviewer in the prompt itself
  (that couples this generic runbook to one repo's specific stack); state the
  check only, and let each repo's own file supply what to combine, if anything.
  Making this a routine-level setting instead of prompt prose would remove the
  need to restate even the check per repo — worth revisiting if this pattern
  shows up often enough to justify it.

- **Connectors:** the form attaches **all your account connectors by default** and
  warns they can be used (including writes) without per-call approval during a run.
  The reviewer only needs GitHub — which comes from the selected repo's GitHub App,
  **not** a connector — so **remove every connector** before saving. Gotcha: if you
  clear them on the Connectors tab and then click **Create**, the defaults can
  **reappear** on the saved routine; re-open it with **Edit**, remove them again,
  and **Save** — that edit sticks.
- **Permissions:** leave **Allow unrestricted branch pushes** *off*. The reviewer
  only posts reviews/comments via the GitHub API; it never pushes commits.

### 2. Poller routine (the conflict/stale/coverage backstop)

A second routine. Unlike the reviewer's per-repo GitHub trigger, **one poller can
sweep many repos at once** — attach every repo you want swept and a single scheduled
run checks them all:

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
- **Prompt / Instructions:** inline the steps — `/atlas-rebase-stale` won't resolve
  (see the note at the top of Setup). Reference `commands/atlas-rebase-stale.md` as
  the source, and have it sweep **every attached repo** (one run covers them all):

  ```text
  Sweep the open pull requests across EVERY repository attached to this routine —
  the polling backstop for PRs that fell behind, hit a conflict (no webhook for
  either), or slipped past a resident reviewer's watch (missed subscription
  wakeup, or its session got reclaimed). All attached repos are cloned into the
  workspace, so first enumerate them (e.g. from the workspace root,
  `for d in */; do git -C "$d" remote get-url origin 2>/dev/null; done`), then run the
  sweep below for EACH repo. The full spec is commands/atlas-rebase-stale.md; the
  /atlas-rebase-stale slash command does NOT resolve in routine sessions, so follow
  these inline steps per repo:

  1. List that repo's open PRs (mcp__github__list_pull_requests); read each PR's
     mergeable state (mcp__github__pull_request_read).
  2. "behind" + no conflicts → bring up to date with
     mcp__github__update_pull_request_branch (no comment; emits a synchronize event).
     "dirty" → do NOT resolve; post the poke as an INLINE REVIEW COMMENT
     (read the diff, anchor to a line on the RIGHT side, submit as a COMMENT review)
     so the author's auto-fix subscription — which reads review threads, not issue
     comments — sees it; body = a whole-PR conflict notice asking them to rebase onto
     base and resolve, only if no unaddressed <!-- atlas-rebase-poke --> review thread
     from you exists. Clean/up-to-date/draft → skip silently.
  3. For any PR with at least one posted <!-- atlas-review round:N --> review
     (not just an ack — an ack with zero rounds behind it has no baseline commit
     to compare against and would false-positive on a PR still mid-flight on
     round 1), compare HEAD against the commit the MOST RECENT round review was
     posted against — if HEAD has moved past it with no unaddressed
     <!-- atlas-coverage-poke --> already there, post one issue comment marked
     <!-- atlas-coverage-poke --> flagging that review coverage may have lapsed;
     do NOT review it yourself. Skip PRs with no ack, or an ack but no round
     review yet (not picked up / still in flight, not lapsed).
  4. Mark every poke with its marker and never double-poke either kind.
  5. End with a one-line summary across all repos: counts of updated,
     conflict-poked, coverage-poked, and skipped.
  ```

  (For just one repo, name it instead of enumerating — `Sweep the open pull requests
  in acme/my-app …`. Verified live: a Haiku run enumerated 12 attached repos, rebased
  the `behind` PRs, and posted review-comment pokes on the conflicted ones.)

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

- **Severity floor that plateaus at Major** — round 1 posts everything; round 2+
  posts only Major+ *as inline comments*, and **holds** there rather than climbing to
  Blocker-only. A Major-only stream is already low-noise, so each further round is
  cheap, and a real regression introduced by a late fix still gets surfaced however
  many rounds in. Findings below the floor aren't dropped silently: they're carried
  as a **non-blocking advisory list** in the review summary (and in the cap notice),
  so suppressed nits stay visible for optional tidy-up without re-driving the loop.
- **Only new findings earn a comment** — a push earns inline comments only for
  findings new that round (not ones a standing thread already records). This, not an
  ever-rising floor, is the main brake: quiet pushes stay quiet, so the higher round
  cap costs nothing when there's nothing new to say.
- **Approve-on-clean** — the first round with nothing new above its floor posts a
  single `APPROVE` (with the advisory list, if any). The build session then has no
  actionable inline comments and goes quiet. Subsequent quiet pushes stay silent —
  no repeated APPROVE. This is the real terminal state.
- **Hard round cap** — a backstop (default 10) that hands a still-churning PR to a
  human rather than burning another machine round. The cap notice carries the
  outstanding advisory findings forward so the human inherits the open list. The cap
  is enforced by the instructions, not the platform — the reviewer decides each
  round whether a push warrants a new round, so it won't burn a round on a no-op event.

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
- **Conflict pokes are review comments, so the author session sees them.** The GUI
  "auto-fix CI and comments on this PR" subscription inspects *review threads*, not
  issue comments, and never checks `mergeable_state` — so a plain issue-comment poke
  wakes it but reads as "no review comments, CI green → nothing to do." The poller
  therefore posts the conflict poke as an **inline review comment** (anchored to a
  diff line, with the body flagged as a *whole-PR* conflict notice, not a line issue),
  which lands in the channel that subscription reads and surfaces as actionable
  feedback; resolving it is left to that session. Residual caveat: actually
  *resolving* a merge conflict may exceed what an auto-fix session does for a routine
  lint/CI fix — if it can't, the unresolved poke thread stays as a human-visible flag.
  (`behind` PRs are still auto-rebased with no comment.)
- **CI *success* and bare pushes** aren't reliably delivered to a PR-activity
  subscription, and the resident `opened`-triggered session isn't an
  indefinitely-lived process either — cloud sessions get reclaimed after a
  platform-defined inactivity limit, silently ending the watch (the ack comment
  and prior reviews stay on the PR; nothing marks the watch as dead). Observed
  directly: several resident-session watches in the wild ended with
  `auto_disabled_session_gone` before their next scheduled check-in fired.
  **Don't try to fix this from inside the resident session** — a self-rearmed
  reminder is exactly as vulnerable to the container being reclaimed as the watch
  it's meant to protect. The poller routine's coverage-check step (§2, backed by
  `atlas-rebase-stale.md` §3) is the actual fix: it runs in a **fresh session per
  scheduled fire**, so it isn't vulnerable to any prior session's container being
  gone, and it flags (doesn't silently lose) a PR whose HEAD has moved past every
  reviewed round. If closing the gap faster than the poller's cadence matters more
  than the per-push run cost, swap the reviewer's trigger to **`Pull request
  synchronize`** (one fresh run per push) instead of relying on a long-lived
  `opened` watch at all.
- A subscription/routine can't share context with the build session — they're
  separate sessions communicating only through the PR (comments, reviews, commits).
