# code-quality-atlas

**A composable suite of code-review skills, built from first principles** — map
*everything* that factors into code quality, then distill that map into focused,
single-purpose review lenses an AI coding agent can actually run.

It ships as a **Claude Code plugin**, but the skills are plain `SKILL.md` files
with no Claude-specific dependencies, so the suite **also runs in any coding agent
that supports the `SKILL.md` format** (Cursor, Windsurf, Copilot, and others — see
[Install](#install)). The plugin wrapper — commands, hooks, marketplace metadata —
is purely additive on top of harness-agnostic skills.

> **New here?** Jump to [Install](#install) → [Wire it into your repo](#wire-routing-into-claudemd--agentsmd-recommended)
> → [Use it](#using-the-suite). To automate PR review, see
> [Automating PR review](#automating-pr-review-with-claude-routines).

## What you get

**28 review skills**, generated from a researched taxonomy and refined against
eval scenarios:

- **26 review lenses** — each a narrow, self-contained reviewer (correctness &
  invariants, naming & readability, module design, concurrency & async, migration
  & data safety, security, performance, test quality, API-contract safety,
  accessibility & i18n, observability, LLM-integration, resilience & scalability,
  plus repo-shaped audits for architecture, dependencies & supply chain, config &
  build hygiene, docs health, compliance & provenance, infrastructure-as-code, …).
  Every lens leads with a one-line "what am I for" tagline and an explicit *Skip
  when…* clause, runs on its own, and carries its full checklist in
  `reference/heuristics.md`.
- **`choosing-review-lenses`** — a router that maps a change ("bug fix",
  "migration", "async code", "API change", "design doc", "repo audit") to the 2-4
  lenses worth running, so you don't have to know the catalog.
- **`synthesizing-review-findings`** — merges multiple lenses' output into one
  deduplicated, severity-ranked report with a single verdict, reconciling tensions
  (e.g. restraint vs. coverage) between reviewers.

Plus, for Claude Code: slash **commands** (`/atlas-review-pr`,
`/atlas-code-review`, `/atlas-init`, `/atlas-rebase-stale`), a side-effect-free
`SessionStart` **hook** that nudges agents toward the suite, and routing
**templates** you wire into a consuming repo.

The point of the suite is to **supersede the generic built-in `/code-review`** (and
framework reviews like BMAD) as the *primary* review path — with deeper,
research-derived coverage — while still letting you fold those other methods'
findings in through the synthesizer rather than picking only one.

## Install

Pick the path that matches your agent. Both install the same skills; the Claude
Code plugin path adds the commands and hooks on top.

### Recommended: any `SKILL.md` agent, via Skulto

[Skulto](https://github.com/asteroid-belt/skulto) is a cross-platform skill
manager that syncs `SKILL.md` skills to Claude Code, Cursor, Windsurf, Copilot,
and 25+ other agent tools. Because every lens is a standard `SKILL.md`, this is the
recommended install for anything other than (or in addition to) a Claude Code
plugin:

```bash
brew install asteroid-belt/tap/skulto
skulto add brandondees/code-quality-atlas        # register the repo and sync it
skulto install brandondees/code-quality-atlas -y # install all skills (drop -y to pick interactively)
```

Skulto installs are snapshots — run `skulto pull` (or `skulto update`, which adds
a security re-scan and change report) to refresh to the latest merged commit. To
pin a project's skill set for teammates, `skulto save` writes the current installs
to a `skulto.json` manifest that `skulto sync` reproduces.

### Claude Code (plugin)

In an interactive Claude Code session (terminal CLI, desktop app, or IDE
extension):

```text
/plugin marketplace add brandondees/code-quality-atlas
/plugin install code-quality-atlas@code-quality-atlas
```

Or from a plain shell, non-interactively (add `--scope project` to scope to one
repo):

```bash
claude plugin marketplace add brandondees/code-quality-atlas
claude plugin install code-quality-atlas@code-quality-atlas
```

Or per-repo via settings — commit this to a project's `.claude/settings.json` and
anyone who trusts the folder gets the suite, **including Claude Code web sessions**
(which don't expose the interactive `/plugin` command, and which this path keeps
fresh — it reinstalls at session start, so it's never stale):

```json
{
  "extraKnownMarketplaces": {
    "code-quality-atlas": {
      "source": { "source": "github", "repo": "brandondees/code-quality-atlas" }
    }
  },
  "enabledPlugins": {
    "code-quality-atlas@code-quality-atlas": true
  }
}
```

> **Note:** if installing from a private copy/fork of this repo, the installing
> machine needs git credentials that can read it (`gh` auth or SSH keys; web
> sessions clone with your GitHub credentials).

All 28 skills load with provenance intact, and updates ship with every merged
commit (commit-SHA versioning — no version bumps). **How updates reach you depends
on the install path:**

- **Settings-based installs** (the `.claude/settings.json` snippet above,
  including web sessions) install fresh at session start — every new session
  already has the latest merged commit, nothing to do.
- **Interactive installs** (`/plugin install` on CLI/desktop/IDE) cache the plugin
  and do **not** auto-refresh by default. Either pull manually with
  `/plugin marketplace update code-quality-atlas`, or enable auto-update once
  (`/plugin` → **Marketplaces** → `code-quality-atlas` → **Enable auto-update**).

> **Stale-install gotcha (esp. for routines).** An interactive cached install with
> auto-update *off* stays pinned to whatever commit it was installed at and can
> silently run a months-old copy — the tell is a session reporting that
> `commands/atlas-review-pr.md` or `REVIEW.md` is *"not in the repo or its
> history."* For any repo a routine reviews, prefer the **settings-based install**
> (always fresh per session) or **enable auto-update**. To keep an interactive
> install current across all scopes automatically, see the opt-in
> [`tooling/keep-plugin-current.sh`](tooling/keep-plugin-current.sh) helper
> ([details below](#keeping-an-interactive-install-current-opt-in)).

## Wire routing into CLAUDE.md / AGENTS.md (recommended)

Installing the suite makes it *available*; it does not guarantee an agent *reaches
for it*. On a plain "code review this" or "review PR #50" request, the model does
keyword matching over the skills it can see, and the shorter-named built-in
`code-review` skill (or a framework review like BMAD) can win that race over the
atlas entrypoints — even though the atlas coverage is deeper. **The deterministic
fix is a routing block in the consuming repo's memory files**, which agents read at
session start and which outranks keyword matching.

Make this a default step of setup. In a Claude Code session **inside the repo you
want reviewed**, run:

```text
/code-quality-atlas:atlas-init
```

It writes a marked routing block into that repo's `CLAUDE.md` **and** `AGENTS.md`
(both, because different agents read different files), creating either if missing
and refreshing the block in place if it's already there — idempotent, so re-run it
after a plugin update to pick up routing changes. The block tells agents the atlas
suite is the **primary path** for any code/quality/PR review, to **prefer it over
the built-in `code-review` skill and over framework reviews (e.g. BMAD)** — and,
crucially, to **combine them non-exclusively**: still run those other methods if
you like, but fold every finding through `synthesizing-review-findings` for one
ranked verdict rather than picking only one.

Not on Claude Code? The canonical text lives in
[`templates/agents-routing-snippet.md`](templates/agents-routing-snippet.md) —
paste the marked block into your repo's `CLAUDE.md`/`AGENTS.md` (or your agent's
equivalent memory file) by hand.

### Automatic routing (SessionStart hook)

For Claude Code, the plugin also ships a `SessionStart` hook
([`hooks/hooks.json`](hooks/hooks.json) → [`hooks/route.sh`](hooks/route.sh)) so
the suite is used as designed without you having to name a skill first. On each
session it injects one line of routing guidance into context. This exists because,
with 28+ skills, individual skill **descriptions** can be dropped from the model's
skill listing (budgeted to ~1% of context, not re-injected after `/compact`),
which makes the lenses easy to overlook on a plain "review this" request; the
hook's `additionalContext` is injected verbatim before the first prompt, so it's
reliable where the listing isn't. The hook is **side-effect-free** — it only prints
to stdout and writes nothing to your repo.

The hook is a per-session *nudge* that works even before a repo is wired; the
committed routing block from `/atlas-init` is the durable, deterministic override.
The two pair together.

> **Cold-first-session caveat.** The hook can only fire once the plugin itself is
> loaded. On the very first session right after install — while a marketplace
> plugin is still being fetched and indexed — both the skill listing *and* this
> hook may arrive after your first message. Every subsequent session, the plugin is
> cached and the hook fires at startup as intended. If a first session misses it,
> just re-send your request or invoke `choosing-review-lenses` directly.

## Using the suite

For a whole PR, the fastest entrypoint is **`/atlas-review-pr`**; for ad-hoc local
changes with no PR (a working tree, or a branch pushed without a PR), use
**`/atlas-code-review`**. Both lead with the atlas lenses and combine
non-exclusively with other review methods.

Working a change by hand, start with **`choosing-review-lenses`** when you're
unsure which lenses apply — it maps the change shape to the right 2-4 lenses and
carries a one-line catalog of all of them. When the relevant lenses are obvious (an
async change → `reviewing-concurrency-and-async`), call them directly; every lens
runs on its own and leads with a one-line summary plus explicit *Skip when…*
guidance. Each lens's `SKILL.md` is self-sufficient for a first pass; its
`reference/heuristics.md` holds the full checklist. When you've run more than one
lens, finish with **`synthesizing-review-findings`** to fold their findings into
one deduplicated, ranked, single-verdict review. To fan the suite across **many
repos** at once, see the [multi-repo audit runbook](docs/runbooks/multi-repo-audit.md).

## Automating PR review with Claude routines

Beyond running lenses by hand, the plugin turns the suite into a **hands-off
pull-request loop on Claude Code on the web** (cloud sandbox sessions): a
GitHub-event **reviewer** re-reviews each push — posting inline findings when a
push introduces them, going quiet when it doesn't — until it converges, and a cheap
scheduled **poller** rebases stale PRs and pokes conflicts (the gap GitHub webhooks
don't cover). It replaces a manually spun-up second review session and isn't
budget/rate-limited the way the CodeRabbit/Copilot PR integrations are.

- [`commands/atlas-review-pr.md`](commands/atlas-review-pr.md) — `/atlas-review-pr`
- [`commands/atlas-rebase-stale.md`](commands/atlas-rebase-stale.md) — `/atlas-rebase-stale`
- [`templates/REVIEW.md`](templates/REVIEW.md) — convergence policy you copy into the reviewed repo
- **[`docs/runbooks/pr-review-automation.md`](docs/runbooks/pr-review-automation.md) — the recommended setup: how to wire the two routines in the web app, step by step.**

The commands install with the plugin; the routines/triggers are account-side config
you create once (the runbook walks through it, including the Claude GitHub App and
trigger setup). What stops the reviewer and a build/auto-fix session from
ping-ponging forever is **convergence**, tuned in `REVIEW.md`: a severity floor that
settles at Major, comments only for genuinely-new findings (quiet on no news),
approve-on-clean, and a hard round cap.

### Keeping an interactive install current (opt-in)

If you stay on an interactive Claude Code install and don't want to enable
auto-update, [`tooling/keep-plugin-current.sh`](tooling/keep-plugin-current.sh)
refreshes the marketplace clone and re-pins **every** scope (user + each project)
to the latest commit. It reads the scopes from
`~/.claude/plugins/installed_plugins.json`, so new projects are picked up
automatically. A Claude restart still applies the staged update — the script only
stages it for the next session.

```bash
tooling/keep-plugin-current.sh                       # this plugin, all scopes
tooling/keep-plugin-current.sh --user-only           # skip project scopes
tooling/keep-plugin-current.sh other@some-marketplace # any plugin
```

To self-heal every session, add a throttled (once-a-day) `SessionStart` hook to
your **personal** `~/.claude/settings.json` (not committed to any repo),
backgrounded so it never blocks startup:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "lf=\"$HOME/.claude/.keep-plugin-current-last\"; ts=$(date +%s); { [ -f \"$lf\" ] && [ $((ts-$(cat \"$lf\"))) -lt 86400 ]; } && exit 0; echo \"$ts\" > \"$lf\"; nohup bash /abs/path/to/code-quality-atlas/tooling/keep-plugin-current.sh >/dev/null 2>&1 &",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The leading timestamp guard runs the updater at most once a day, so most session
starts exit immediately without a git fetch. Drop the guard to run it every
session.

## How it was built

Built fresh from **first principles**. Existing skills, plugins, linters, and
review tools (Anthropic's, the community's, the author's own) are treated as
**prior art to learn from and borrow from** — not as constraints (catalog in
[`docs/prior-art.md`](docs/prior-art.md)). The docs are the source of truth; skills
are *generated* from [`skills/manifest.yaml`](skills/manifest.yaml) with provenance
hashes, a drift-checker, and eval-first refinement.

Three phases, all complete:

1. **Research & taxonomy** → a maximal map of code quality: **6 clusters / 31
   categories / ~95 factors** (taxonomy v0.3), each cluster web-verified for
   references, static-analysis rules, and reviewable heuristics →
   [`docs/taxonomy.md`](docs/taxonomy.md), [`docs/research/`](docs/research/).
2. **Skill-suite architecture** → behaviors mapped over the categories, single
   owner per category enforced by the manifest validator, built in waves →
   [`docs/phase-2-skill-suite-design.md`](docs/phase-2-skill-suite-design.md).
3. **Build the skills** → the lenses, generated and refined with examples + ≥3 eval
   scenarios each, cross-model-tested down to small local models →
   [`docs/runbooks/regenerating-skills.md`](docs/runbooks/regenerating-skills.md).

Ongoing work is the compounding loop: critique the research, let drift flag
affected skills, regenerate, re-gate. Dogfooding has driven the discoverability
work above — self-sufficient `SKILL.md` first passes, the `choosing-review-lenses`
router, the `synthesizing-review-findings` synthesizer, *Skip when…* clauses on
narrow lenses, and the routing block. The full chronology lives in
[`docs/session-log.md`](docs/session-log.md) and the decision record in
[`docs/open-questions.md`](docs/open-questions.md).

## Map of this repo

| File | What's in it |
|---|---|
| [`docs/overview.md`](docs/overview.md) | Project intent, scope decision, phase plan, working principles |
| [`docs/taxonomy.md`](docs/taxonomy.md) | The master map: clusters → categories → factors |
| [`docs/references.md`](docs/references.md) | Annotated references by cluster — the active research surface |
| [`docs/prior-art.md`](docs/prior-art.md) | Existing skills / tools that already cover parts of the map |
| [`docs/research/`](docs/research/) | Per-cluster research: references, tooling rules, reviewable heuristics |
| [`docs/map-gaps.md`](docs/map-gaps.md) | Cross-cutting structural findings feeding phase-2 |
| [`docs/open-questions.md`](docs/open-questions.md) | Decisions made + unresolved questions |
| [`docs/plans/`](docs/plans/) | Implementation plans (e.g. the wave-1 pipeline build) |
| [`docs/runbooks/`](docs/runbooks/) | Operational guides: PR-review automation, multi-repo audit, regenerating skills |
| [`docs/session-log.md`](docs/session-log.md) | Chronological record of how this evolved |
| [`skills/`](skills/) | The 26 generated lenses **+ `choosing-review-lenses` (router) + `synthesizing-review-findings` (synthesizer)** (see `manifest.yaml`) |
| [`commands/`](commands/) | Slash commands: `/atlas-review-pr`, `/atlas-code-review`, `/atlas-init`, `/atlas-rebase-stale` |
| [`hooks/`](hooks/) | `SessionStart` hook that injects routing guidance (side-effect-free) |
| [`templates/`](templates/) | `REVIEW.md` convergence policy + `agents-routing-snippet.md` (the CLAUDE.md/AGENTS.md routing block) |
| [`tooling/`](tooling/) | The pipeline: generator, drift-checker, eval validator, cross-model runner |

## License

Dual-licensed by content type: the research atlas and skills (`docs/`, `skills/`,
this README) are [CC BY 4.0](LICENSE-CC-BY-4.0) — reuse freely with attribution;
the pipeline code (`tooling/`, `tests/`, CI/config) is [MIT](LICENSE-MIT). Details
in [LICENSE](LICENSE).
</content>
</invoke>
