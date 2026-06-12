# code-quality-atlas

A from-first-principles research project — and, eventually, a **standalone agent skill suite for code review and maintenance.**

The goal is two-part:

1. Map *everything* that factors into code quality, as comprehensively as possible.
2. Distill that map into a coherent set of composable agent skills that help **review** and **maintain** code.

All three phases are complete — the suite is built and installable (see Install below). Ongoing work is the compounding loop: critique the research, let drift flag affected skills, regenerate, re-gate.

## Status

**Phase 1 — Research & taxonomy (complete, 2026-06-09)**

- [x] Scope decision: **maximal** — intrinsic code properties **plus** all cross-cutting concerns (security, performance, tests, deps, build/CI, data, docs, accessibility, observability, …).
- [x] Taxonomy v0.2 (pressure-tested): **6 clusters / 27 categories / ~80 factors** → [`docs/taxonomy.md`](docs/taxonomy.md)
- [x] **Per-cluster research — all 6 clusters written & web-verified:** references, static-analysis tool rules, reviewable heuristics → [`docs/research/`](docs/research/)
- [x] Prior-art survey → [`docs/prior-art.md`](docs/prior-art.md); cross-cutting findings → [`docs/map-gaps.md`](docs/map-gaps.md)

**Phase 2 — Skill-suite architecture (complete, 2026-06-09)** → [`docs/phase-2-skill-suite-design.md`](docs/phase-2-skill-suite-design.md): docs are the source of truth; skills are generated from [`skills/manifest.yaml`](skills/manifest.yaml) with provenance hashes, a drift-checker, and eval-first refinement. 22 behaviors mapped over the 27 categories, built in waves.

**Phase 3 — Build the skills (complete, 2026-06-10)**

- [x] **Wave 1 — the 6 ★ skills** (LLM-judgment-heavy, highest unique value) → [`skills/`](skills/): generated, refined with examples + ≥3 eval scenarios each, cross-model-tested down to small local models (see [`docs/runbooks/regenerating-skills.md`](docs/runbooks/regenerating-skills.md)).
- [x] **Wave 2 — high-stakes triage** (5 skills): security sweep, migration & data safety, performance & efficiency, test quality, accessibility & i18n — same refine-and-eval loop; small-model gaps + linter pairings documented in the runbook.
- [x] **Wave 3 — remainder + repo/cron-shaped audits** (11 skills): tracing correctness, concurrency & async, idioms & consistency, API contract safety, observability & operability, PR & process hygiene; plus repo-shaped audits for architecture conformance, dependencies & supply chain, config & build hygiene, documentation health, and compliance & provenance.
- [x] **G1 single-owner enforcement:** the manifest validator rejects a category with two primary owners; double-booked categories carry explicit `cross_ref` markers.
- [x] **Q12 packaging:** the repo is itself a Claude Code plugin + marketplace (commit-SHA versioned) → see Install below.

All **22 behaviors / 27 categories** from the [phase-2 design](docs/phase-2-skill-suite-design.md) are built.

**First dogfood cycle (2026-06-11)** — real-usage feedback drove five packaging fixes (D10): every `SKILL.md` now inlines its top ~8 checks (self-sufficient first pass, no second fetch); a 23rd skill, [`choosing-review-lenses`](skills/choosing-review-lenses/SKILL.md), routes "what am I reviewing" → the 2-4 lenses worth running; design-capable lenses are explicitly marked (◆); skills sharing a research category name the primary owner so findings aren't double-reported; and reference links say when each file is actually needed.

**Composition completed (2026-06-12, D12)** — the back half of Q7: a 24th skill, [`synthesizing-review-findings`](skills/synthesizing-review-findings/SKILL.md), merges the lenses' output into one report — deduplicated, lens tensions reconciled (e.g. restraint vs. coverage), severity-ranked, single verdict. Fan-out stays advisory by default but ships a fixed finding contract so an orchestrating harness can mechanize the same merge.

**Second feedback cycle (2026-06-12)** — discoverability refinements from a dogfood session that reached for ad-hoc agents over the suite: (1) the narrowly-scoped lenses now carry explicit **Skip when…** clauses (no accessibility lens on a CLI repo, no LLM lens on code with no model call) so direct invocation doesn't misfire; (2) each lens surfaces its one-line **picker as a scannable tagline** at the top of its `SKILL.md`, so the catalog is readable at a glance, not only via the router; (3) the router keeps a terse listing `description` separate from a richer `body` (reconciling PR #30 into the generator); and (4) a [multi-repo audit runbook](docs/runbooks/multi-repo-audit.md) shows how to fan the suite across many repos with background agents and aggregate findings through the synthesizer's contract.

## Using the suite

Start with **`choosing-review-lenses`** when you are unsure which lenses apply — it maps the change shape (bug fix, migration, async code, API change, design doc, repo audit, …) to the right 2-4 lenses and carries a one-line catalog of all of them. When the relevant lenses are already obvious (an async change → `reviewing-concurrency-and-async`), call them directly; every lens is built to run on its own and now leads with a one-line summary and explicit *Skip when…* guidance. Each lens's `SKILL.md` is self-sufficient for a first pass; its `reference/heuristics.md` holds the full checklist. When you've run more than one lens, finish with **`synthesizing-review-findings`** to fold their findings into one deduplicated, ranked, single-verdict review — and to fan the suite across **many repos** at once, see the [multi-repo audit runbook](docs/runbooks/multi-repo-audit.md).

## Install

### Claude Code (plugin)

In an interactive Claude Code session on your machine (terminal CLI, desktop app, or IDE extension):

```
/plugin marketplace add brandondees/code-quality-atlas
/plugin install code-quality-atlas@code-quality-atlas
```

Or from a plain shell, non-interactively (add `--scope project` to scope to one repo):

```bash
claude plugin marketplace add brandondees/code-quality-atlas
claude plugin install code-quality-atlas@code-quality-atlas
```

Or per-repo via settings — commit this to a project's `.claude/settings.json` and
anyone who trusts the folder gets the suite, **including Claude Code web sessions**
(which don't expose the interactive `/plugin` command):

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

All 24 skills load with provenance intact; updates ship with every merged commit
(commit-SHA versioning — no version bumps needed). How updates reach you depends
on the install path:

- **Interactive installs** (`/plugin install` on CLI/desktop/IDE) cache the plugin
  and do **not** auto-refresh by default. Either pull manually with
  `/plugin marketplace update code-quality-atlas`, or enable auto-update once
  (`/plugin` → **Marketplaces** → select `code-quality-atlas` → **Enable
  auto-update**) and it refreshes at startup from then on.
- **Settings-based installs** (the `.claude/settings.json` snippet above,
  including Claude Code web sessions) install fresh at session start, so every
  new session already has the latest merged commit — nothing to do.

> **Stale-install gotcha (esp. for routines).** An interactive cached install
> with auto-update *off* stays pinned to whatever commit it was installed at and
> can silently run a months-old copy — the tell is a session reporting that
> `commands/atlas-review-pr.md` or `REVIEW.md` is *"not in the repo or its
> history"* (those files simply post-date the pinned commit). For any repo a
> routine reviews, prefer the **settings-based install** (always fresh per
> session) or **enable auto-update** on the interactive install. To keep an
> interactive install current across all scopes without the manual `/plugin
> marketplace update`, see the opt-in
> [`tooling/keep-plugin-current.sh`](tooling/keep-plugin-current.sh) helper below.

#### Keeping an interactive install current (opt-in)

If you stay on an interactive install and don't want to enable auto-update,
[`tooling/keep-plugin-current.sh`](tooling/keep-plugin-current.sh) refreshes the
marketplace clone and re-pins **every** scope (user + each project) to the latest
commit. It reads the scopes from `~/.claude/plugins/installed_plugins.json`, so
new projects are picked up automatically. A Claude restart still applies the
staged update — the script only stages it for the next session.

```bash
tooling/keep-plugin-current.sh                       # this plugin, all scopes
tooling/keep-plugin-current.sh --user-only           # skip project scopes
tooling/keep-plugin-current.sh other@some-marketplace # any plugin
```

It is **not** wired to run automatically — it issues `claude plugin update`
commands, so when and where it runs is left to you. To self-heal every session,
add a throttled `SessionStart` hook to your **personal** `~/.claude/settings.json`
(not committed to any repo), backgrounded so it never blocks startup:

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

The `command` is self-contained: the leading timestamp guard (`$lf` / 86400s)
runs the updater at most once a day, so most session starts exit immediately
without a git fetch. Drop the guard if you want it to run every session.

#### Automatic routing (SessionStart hook)

The plugin ships a `SessionStart` hook ([`hooks/hooks.json`](hooks/hooks.json) →
[`hooks/route.sh`](hooks/route.sh)) so the suite is used as designed without you
having to name a skill first. On each session it injects one line of guidance —
*"for a review or audit, start with `choosing-review-lenses`, then finish with
`synthesizing-review-findings`"* — directly into context.

This exists because, with 24+ skills, individual skill **descriptions** can be
dropped from the model's skill listing (it is budgeted to ~1% of context and is
not re-injected after `/compact`), which makes the lenses easy to overlook on a
plain "review this" request. The hook's `additionalContext` is injected verbatim
before the first prompt, so it is reliable where the listing is not. The hook is
**side-effect-free**: it only prints to stdout and writes nothing to your repo.

> **Cold-first-session caveat.** The hook can only fire once the plugin itself is
> loaded. On the very first session right after install — while a marketplace
> plugin is still being fetched and indexed — both the skill listing *and* this
> hook may arrive after your first message (you may watch the skills appear
> mid-session). Every subsequent session, the plugin is cached and the hook fires
> at startup as intended. If a first session misses it, just re-send your request
> or invoke `choosing-review-lenses` directly.

### Other harnesses (Skulto)

The skills are plain markdown and remain harness-agnostic; the plugin wrapper is
additive (D9 in [`docs/open-questions.md`](docs/open-questions.md)). Because each
lens is a standard `SKILL.md`, the suite also installs via
[Skulto](https://github.com/asteroid-belt/skulto), a cross-platform skill manager
that syncs skills to Claude Code, Cursor, Windsurf, Copilot, and 25+ other agent
tools (`brew install asteroid-belt/tap/skulto`):

```bash
skulto add brandondees/code-quality-atlas        # register the repo and sync it
skulto install brandondees/code-quality-atlas -y # install all skills (drop -y to pick interactively)
```

Skulto installs are snapshots — run `skulto pull` (or `skulto update`, which adds
a security re-scan and change report) to refresh to the latest merged commit.
To pin a project's skill set for teammates, `skulto save` writes the current
installs to a `skulto.json` manifest that `skulto sync` reproduces.

## Automating PR review (Claude Code on the web)

Beyond running lenses by hand, the plugin ships two slash commands that turn the
suite into a hands-off pull-request loop on cloud sandbox sessions: a GitHub-event
**reviewer** that posts inline findings on every push and re-reviews until it
converges, and a cheap scheduled **poller** that rebases stale PRs and pokes
conflicts (the gap GitHub webhooks don't cover).

- [`commands/atlas-review-pr.md`](commands/atlas-review-pr.md) — `/atlas-review-pr`
- [`commands/atlas-rebase-stale.md`](commands/atlas-rebase-stale.md) — `/atlas-rebase-stale`
- [`templates/REVIEW.md`](templates/REVIEW.md) — convergence policy you copy into the reviewed repo
- [`docs/runbooks/pr-review-automation.md`](docs/runbooks/pr-review-automation.md) — **how to wire the two routines** in the web app

The commands install with the plugin; the routines/triggers are account-side config
you create once (the runbook walks through it). Convergence — escalating severity
floor, approve-on-clean, round cap — is what stops the reviewer and a build/auto-fix
session from ping-ponging forever.

## Approach

Built fresh from **first principles**. Existing skills, plugins, linters, and review tools (Anthropic's, the community's, the author's own) are treated as **prior art to learn from and borrow from** — not as constraints. The catalog lives in [`docs/prior-art.md`](docs/prior-art.md).

## Map of this repo

| File | What's in it |
|---|---|
| [`docs/overview.md`](docs/overview.md) | Project intent, scope decision, phase plan, working principles |
| [`docs/taxonomy.md`](docs/taxonomy.md) | The master map: clusters → categories → factors |
| [`docs/references.md`](docs/references.md) | Annotated references by cluster — the active research surface |
| [`docs/prior-art.md`](docs/prior-art.md) | Existing skills / tools that already cover parts of the map |
| [`docs/research/`](docs/research/) | Per-cluster research: references, tooling rules, reviewable heuristics |
| [`docs/map-gaps.md`](docs/map-gaps.md) | Cross-cutting structural findings feeding phase-2 (double-booked concerns, decomposition tension, etc.) |
| [`docs/open-questions.md`](docs/open-questions.md) | Decisions made + unresolved questions |
| [`docs/plans/`](docs/plans/) | Implementation plans (e.g. the wave-1 pipeline build) |
| [`docs/session-log.md`](docs/session-log.md) | Chronological record of how this evolved |
| [`skills/`](skills/) | The 22 generated + refined lenses **+ the `choosing-review-lenses` router** (see `manifest.yaml`) |
| [`commands/`](commands/) | Slash commands for hands-off PR review automation (`/atlas-review-pr`, `/atlas-rebase-stale`) |
| [`hooks/`](hooks/) | `SessionStart` hook that injects routing guidance so the suite is used without naming a skill (side-effect-free) |
| [`templates/`](templates/) | `REVIEW.md` convergence policy to copy into a reviewed repo |
| [`tooling/`](tooling/) | The pipeline: generator, drift-checker, eval validator, cross-model runner |

## License

Dual-licensed by content type: the research atlas and skills (`docs/`, `skills/`, this README) are [CC BY 4.0](LICENSE-CC-BY-4.0) — reuse freely with attribution; the pipeline code (`tooling/`, `tests/`, CI/config) is [MIT](LICENSE-MIT). Details in [LICENSE](LICENSE).
