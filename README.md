# code-quality-atlas

**A composable suite of code-review skills, built from first principles** — map
*everything* that factors into code quality, then distill it into focused,
single-purpose review lenses an AI coding agent can run.

It ships as a **Claude Code plugin**, but the skills are plain `SKILL.md` files with
no Claude-specific dependencies, so the suite **also runs in any coding agent that
supports the `SKILL.md` format** (Cursor, Windsurf, Copilot, …). The plugin wrapper
— commands, hooks, marketplace metadata — is additive.

**Jump to:** [Install](#install) · [Wire it into your repo](#wire-it-into-your-repo)
· [Use it](#use-it) · [Automate PR review](#automate-pr-review) ·
[How it was built](#how-it-was-built)

## What you get

**28 review skills**, generated from a researched taxonomy and refined against eval
scenarios:

- **26 review lenses** — each a narrow, self-contained reviewer (correctness,
  naming & readability, module design, concurrency, migrations & data safety,
  security, performance, tests, API contracts, accessibility & i18n, observability,
  LLM-integration, resilience, plus repo-shaped audits for architecture,
  dependencies, config/build, docs, compliance, infrastructure-as-code, …). Each
  leads with a one-line tagline and an explicit *Skip when…* clause, runs on its
  own, and carries its full checklist in `reference/heuristics.md`.
- **`choosing-review-lenses`** — a router that maps a change to the 2-4 lenses worth
  running, so you don't have to know the catalog.
- **`synthesizing-review-findings`** — merges multiple lenses (and any other
  reviewer) into one deduplicated, severity-ranked, single-verdict report.

The catalog lives in [`skills/manifest.yaml`](skills/manifest.yaml). For Claude
Code, the plugin also adds slash commands, a side-effect-free `SessionStart` routing
hook, and routing templates.

The point of the suite is to **supersede the generic built-in `/code-review`** (and
framework reviews like BMAD) as the *primary* review path — with deeper,
research-derived coverage — while still folding their findings in through the
synthesizer rather than picking only one.

## Install

Both paths install the same skills; the Claude Code plugin adds commands and hooks
on top. **Update mechanics, web-session setup, and keeping current are in
[`docs/install.md`](docs/install.md).**

**Any `SKILL.md` agent — via [Skulto](https://github.com/asteroid-belt/skulto)**
(recommended cross-platform path; syncs to Claude Code, Cursor, Windsurf, Copilot,
and 25+ more):

```bash
brew install asteroid-belt/tap/skulto
skulto add brandondees/code-quality-atlas
skulto install brandondees/code-quality-atlas -y
```

**Claude Code (plugin):**

```text
/plugin marketplace add brandondees/code-quality-atlas
/plugin install code-quality-atlas@code-quality-atlas
```

For Claude Code **web sessions** and always-fresh installs, commit a marketplace
snippet to `.claude/settings.json` instead — see [`docs/install.md`](docs/install.md).

## Wire it into your repo

Installing the suite makes it *available*; it doesn't guarantee an agent *reaches
for it*. On a plain "review this," the shorter-named built-in `code-review` can win
the keyword race. The deterministic fix is a **routing block in the repo's
`CLAUDE.md` / `AGENTS.md`** — agents read it at session start, and it outranks
keyword matching.

In a Claude Code session **inside the repo you want reviewed**:

```text
/code-quality-atlas:atlas-init
```

It writes an idempotent routing block into both `CLAUDE.md` and `AGENTS.md` (different
agents read different files), telling them to prefer the atlas suite over
`/code-review` and framework reviews — combined non-exclusively. Not on Claude Code?
Paste [`templates/agents-routing-snippet.md`](templates/agents-routing-snippet.md) by
hand.

The plugin also ships a `SessionStart` hook that nudges agents toward the suite each
session — a backstop for when skill descriptions get budgeted out of context. Details
in [`docs/install.md`](docs/install.md).

## Use it

| Situation | Reach for |
|---|---|
| A whole PR | `/atlas-review-pr` |
| Local changes with no PR (working tree, or a pushed branch) | `/atlas-code-review` |
| By hand, unsure which lenses apply | `choosing-review-lenses` (maps the change to 2-4 lenses) |
| The relevant lens is obvious | call it directly (async change → `reviewing-concurrency-and-async`) |
| You ran more than one lens | finish with `synthesizing-review-findings` |
| Many repos at once | the [multi-repo audit runbook](docs/runbooks/multi-repo-audit.md) |

Every lens runs on its own; its `SKILL.md` is self-sufficient for a first pass and
`reference/heuristics.md` holds the full checklist.

## Automate PR review

The plugin turns the suite into a **hands-off pull-request loop on Claude Code on the
web**: a GitHub-event **reviewer** that re-reviews each push and quiets down as it
converges, plus a scheduled **poller** that rebases stale PRs and pokes conflicts
(the gap GitHub webhooks don't cover). Convergence rules — a severity floor that
settles at Major, comments only for genuinely-new findings, approve-on-clean, and a
round cap — keep the reviewer and a build/auto-fix session from ping-ponging forever.

The commands ship with the plugin; the routines are account-side config you create
once. **Step-by-step setup:
[`docs/runbooks/pr-review-automation.md`](docs/runbooks/pr-review-automation.md).**
Copy [`templates/REVIEW.md`](templates/REVIEW.md) into the reviewed repo to tune the
convergence policy.

## How it was built

Built fresh from **first principles**, treating existing skills, linters, and review
tools as prior art to learn from — not constraints. Docs are the source of truth;
skills are *generated* from [`skills/manifest.yaml`](skills/manifest.yaml) with
provenance hashes, a drift-checker, and eval-first refinement. The underlying map is
**6 clusters / 31 categories / ~95 factors** (taxonomy v0.3). Ongoing work is the
compounding loop: critique the research, let drift flag affected skills, regenerate,
re-gate.

- Project intent, scope, phases, principles → [`docs/overview.md`](docs/overview.md)
- The master map → [`docs/taxonomy.md`](docs/taxonomy.md); per-cluster research → [`docs/research/`](docs/research/)
- Architecture & generation → [`docs/phase-2-skill-suite-design.md`](docs/phase-2-skill-suite-design.md); [regenerating skills](docs/runbooks/regenerating-skills.md)
- Decisions & history → [`docs/open-questions.md`](docs/open-questions.md); [`docs/session-log.md`](docs/session-log.md)
- Prior art surveyed → [`docs/prior-art.md`](docs/prior-art.md)

## Repo layout

| Path | What's in it |
|---|---|
| [`skills/`](skills/) | The 26 lenses + `choosing-review-lenses` (router) + `synthesizing-review-findings` (synthesizer) |
| [`commands/`](commands/) | Slash commands: `/atlas-review-pr`, `/atlas-code-review`, `/atlas-init`, `/atlas-rebase-stale` |
| [`hooks/`](hooks/) | `SessionStart` routing hook (side-effect-free) |
| [`templates/`](templates/) | `REVIEW.md` convergence policy + `agents-routing-snippet.md` routing block |
| [`tooling/`](tooling/) | The pipeline: generator, drift-checker, eval validator, cross-model runner |
| [`docs/`](docs/) | Research, taxonomy, design, runbooks, install guide, decision log |

## License

Dual-licensed by content type: the research atlas and skills (`docs/`, `skills/`,
this README) are [CC BY 4.0](LICENSE-CC-BY-4.0) — reuse freely with attribution; the
pipeline code (`tooling/`, `tests/`, CI/config) is [MIT](LICENSE-MIT). Details in
[LICENSE](LICENSE).
