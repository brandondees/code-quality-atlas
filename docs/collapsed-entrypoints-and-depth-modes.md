# Collapsed entrypoints + depth modes — design

*Status: design approved 2026-06-25, build pending. Resolves **Q20** (top-level
skill-count vs. context budget) and **D16** (review-depth modes). Refines **D10**
(router) and **D12** (synthesizer).*

## Problem

Two costs scale with the **count** of top-level skills, not their quality:

1. **Cloud onboarding.** The only repo-independent cloud channel is claude.ai
   account skills, uploaded **one zip per skill** (the GUI rejects multi-skill
   bundles) — 35 tedious, error-prone uploads. See
   [`distribution.md`](distribution.md).
2. **CLI context budget.** Claude Code budgets the installed-skill *listing* to
   ~1% of context and drops descriptions beyond it; with 35 top-level lenses the
   suite is easily overlooked on a plain "review this" (the reason the
   `SessionStart` routing hook exists). See [`install.md`](install.md).

A third, independent flaw surfaced in the same discussion and is folded in here:
the router **caps** lens selection at 2–4, conflating *relevance* (which lenses
apply) with *breadth* (how many to run). The effect is the one D16 named — a few
lenses fire nearly every time and the long tail never runs, so soft findings
(readability-class) never surface. Users frequently want "review this thoroughly
with **all** relevant lenses," up to the full set at repo scope, and cannot get it.

## Decisions

- **D-Q20-1 — Dual-emit.** The manifest + `built_from` research sections stay the
  single source. `generate.py` emits **two forms** from the same lens content, so
  they cannot drift (D6): the existing **standalone** 35 skills (unchanged) and a
  new **collapsed** form.
- **D-Q20-2 — Collapsed form = 4 entrypoints by review shape.** `reviewing-a-change`
  (diff), `auditing-a-repository` (repo/cron), `reviewing-a-decision`,
  `reviewing-an-artifact`. Each bundles its shape's lens *bodies* as on-demand
  files and absorbs the router + synthesizer (so the collapsed form is genuinely
  4 skills, not 6).
- **D-Q20-3 — Both forms committed and marketplace-installable.** The collapsed
  form is generated-but-committed (like `skills/`) under `collapsed/`, with its own
  `.claude-plugin/plugin.json`; `marketplace.json` gains a second plugin so either
  form installs and auto-updates via the marketplace. CI drift-checks both trees.
- **D-Q20-4 — Relevance ranking replaces the cap; breadth becomes a mode axis.**
  Routing emits a relevance-**ranked** list of every applicable lens; a breadth
  selector decides how far down to run. Applies to **both** forms (one manifest
  generation). This is D16's relevance/depth separation.
- **D-Q20-5 — Three depth modes with per-mode severity floors.**
  **triage** (critical tier only — correctness/security/data/concurrency — floor
  Major+), **review** (default; top 2–4 by relevance; today's escalating floor),
  **comprehensive** (all relevant lenses, uncapped; floor pinned at Nit so
  long-tail findings actually surface). The floor policy lives in the synthesizer.
- **D-Q20-6 — Non-goal:** removing the standalone 35. Dual-emit keeps them for
  filesystem / Skulto / other-agent installs and direct per-lens auto-triggering.
- **Revisit trigger.** Reopen the dual-emit decision if **both** original pains go
  away: the claude.ai GUI gains multi-skill-bundle upload (removing the ~35-upload
  cost) **and** the CLI skill-listing context budget stops truncating descriptions
  (e.g. a larger listing budget or on-demand skill discovery). If both hold, the
  collapsed form's maintenance + repo-size overhead may no longer be justified —
  re-evaluate collapsing back to the standalone form alone.

## Architecture

### Emission model

```text
skills/manifest.yaml  +  docs/**/built_from sections        (single source — D6)
        │
        ├── generate_skill()      → skills/<lens>/            (standalone, 35; unchanged)
        │                           + skills/{router,synthesizer}/
        └── generate_collapsed()  → collapsed/skills/<entrypoint>/   (new, 4)
                                    + collapsed/.claude-plugin/plugin.json
```

Both trees are committed. The collapsed lens bodies are a *repackaging* of the
same generated content — no lens prose is authored twice.

### Collapsed entrypoint structure

```text
collapsed/skills/reviewing-a-change/
├── SKILL.md                      # shape-scoped trigger + relevance routing + mode rules + "load lens, synthesize"
└── reference/
    ├── lenses/<lens>/
    │   ├── body.md               # when-to-use + full heuristics + examples — the review content (what the entrypoint Reads)
    │   ├── tool-rules.md         # static-analysis rules — deeper level, linked from body.md, opened on demand
    │   └── sources.md            # research provenance — deeper level, linked from body.md, opened on demand
    └── synthesis.md              # synthesizer procedure incl. the per-mode severity-floor policy
```

- **Lens membership** is derived from each skill's existing `shape` and `design`
  fields: diff lenses → `reviewing-a-change`; the 8 audits → `auditing-a-repository`;
  `reviewing-decision-lifecycle` + design-capable (◆) lenses → `reviewing-a-decision`;
  `reviewing-artifact-conventions` + its rubrics → `reviewing-an-artifact`. A
  design-capable lens is bundled in more than one entrypoint — duplication in
  bundled files has no context cost until read.
- **Progressive disclosure is preserved per lens.** `body.md` (composed from the
  same `built_from` `heuristics` + `examples` the standalone lens uses) is what the
  entrypoint loads when a lens is selected. `tool-rules.md` and `sources.md` are a
  *further* level down — **linked from `body.md`, tightly folded, zero context cost
  until the agent or user calls for deeper provenance/tooling**. This mirrors the
  standalone lens's `SKILL.md → reference/*` disclosure, just nested under the
  entrypoint, so content parity is structural.

### Agent flow (collapsed form)

1. User: "review this PR" → `reviewing-a-change` triggers (its description carries
   the diff-review trigger surface).
2. Its SKILL.md ranks the applicable lenses by relevance to the change's scope and
   selects per the active **mode** (default **review** = top 2–4).
3. Agent **`Read`s** `reference/lenses/<lens>/body.md` for each selected lens and
   applies it — `Read` replaces the Skill-invocation; no new mechanism (skills
   already point at `reference/*.md`).
4. Agent merges findings via `reference/synthesis.md`, applying the mode's severity
   floor, to one ranked verdict.

The standalone form keeps today's flow (router skill → lens skills → synthesizer
skill) but the router/synthesizer **gain the same relevance-ranking + mode logic**,
generated from the manifest so both forms behave identically.

### Marketplace / distribution

- `collapsed/.claude-plugin/plugin.json` defines `code-quality-atlas-collapsed`;
  `marketplace.json` lists it as a second plugin (`source: ./collapsed`). Install:
  `/plugin install code-quality-atlas-collapsed@code-quality-atlas`. Auto-updates
  via the same marketplace-clone refresh.
- `tooling/package-account-zips.sh --collapsed` zips the 4 entrypoints (4 uploads,
  not 35) for the claude.ai GUI.
- `tooling/vendor-skills.sh <repo> --collapsed` vendors the 4 entrypoints into a
  repo's `.claude/skills/`.
- **Install one form, not both** — both would double-register/trigger. Documented
  in `distribution.md` (which form for which surface) and `install.md`.

## Routing & depth model

The router (`built_from: []`) and the 4 entrypoints share generated routing logic:

- **Relevance ranking.** For a change, produce an ordered list of every lens whose
  scope the change touches (from the existing route table, now emitting a ranked
  list rather than a 2–4 slice). `reviewing-pr-and-process-hygiene` stays additive.
- **Modes (breadth × floor):**

  | Mode | Lenses run | Severity floor | Typical trigger |
  |---|---|---|---|
  | **triage** | critical tier only (correctness, security, data-safety, concurrency) | Major+ | pre-merge gate; "quick/triage review" |
  | **review** *(default)* | top 2–4 by relevance (escalating floor as today) | round-based | "review this PR" |
  | **comprehensive** | **all** relevant lenses, uncapped (full audit set at repo scope) | pinned at Nit | "thorough review", "use all relevant lenses", "comprehensive" |

- **Severity-floor policy** lives in the synthesizer / `synthesis.md`: the floor is
  a function of mode. This is the actual fix for the long-tail-never-surfaces
  effect — comprehensive must both *run* the soft lenses and *not trim* their
  findings.
- **Trigger surface (D7-portable):** natural language the entrypoint/router body
  interprets (phrasing → mode). CLI installs may add command sugar
  (`/atlas-review --depth comprehensive`, `/atlas-triage`); the account-skill/cloud
  form relies on phrasing since it has no commands. Mode is orthogonal to shape.

## Manifest & generator changes

- **`entrypoints:` section** (new, generated like `router:`): 4 entries — name,
  shape(s) covered, trigger description, lens-membership rule. `built_from: []`.
- **`modes:` section** (new): the three modes — name, lens-tier selector
  (critical-tier list for triage; top-N for review; all-relevant for comprehensive),
  and severity-floor policy. Generated; `built_from: []`. (This is D16's `modes:`.)
- **Generator additions:**
  - `build_entrypoint_md(manifest, entrypoint)` and `generate_collapsed(manifest)` —
    emit the 4 folders, each with bundled `reference/lenses/*.md` and
    `reference/synthesis.md`, plus `collapsed/.claude-plugin/plugin.json`.
  - Router (`build_router_md`) and synthesizer generation extended with the
    relevance-ranking + mode/floor logic, so the standalone form matches.
  - `marketplace.json` updated to list the second plugin (manifest- or
    script-driven so it stays in sync).

## Evals

- **Per-lens behavioral evals (D8):** unchanged — lens content is byte-identical,
  only relocated.
- **Per-entrypoint routing evals (new):** query → expected ranked lenses + that the
  trigger fires and the right `reference/lenses/*.md` are loaded. ~3 per entrypoint.
- **Per-mode evals (new):** the same change under triage / review / comprehensive
  yields the expected lens breadth *and* the expected severity floor (e.g. a
  readability-class finding is absent under review but present under comprehensive).

## CI / drift

- The existing drift check runs against `skills/`; extend it to **rebuild and diff
  `collapsed/`** too, so a manifest/content change that isn't regenerated fails CI.
- `claude plugin validate` runs for both plugin manifests.

## Coexistence & migration

- New entrypoint names (`reviewing-a-change`, …) don't collide with the 35 lens
  names. A user installs the standalone **or** the collapsed plugin, not both.
- No data migration; this is additive generation + routing-logic changes. Existing
  consumers of the standalone form see only the routing/mode upgrade.

## Scope & phasing

**This build:** dual-emit (`generate_collapsed`, committed `collapsed/` tree, second
marketplace plugin, CI drift) + relevance-ranking + the three modes + per-mode
severity floors + routing/mode/entrypoint evals + `--collapsed` distribution flags +
doc updates. Resolves Q20 and D16.

**Explicit non-goals / later:** removing the standalone form; per-repo default-mode
selection (Q13 team-preferences overlay sets it when built); content-sniffing
artifact detection (unchanged from D15).

## Resolved sub-questions

- **Lens-bundle composition (resolved):** `body.md` = when-to-use + heuristics +
  examples; `tool-rules.md` and `sources.md` ship as a deeper, tightly-folded
  disclosure level linked from `body.md` — reachable when deeper context is called
  for, zero overhead until then. (Not omitted.)
- **Collapsed `plugin.json` (resolved):** generated from a single source alongside
  `marketplace.json` (not hand-kept), to avoid drift.

## Open implementation sub-questions

- Command sugar naming for CLI installs (`/atlas-triage`, `/atlas-review --depth`,
  `/atlas-audit-comprehensive`) — finalize in the implementation plan.

## Cross-references

- Supersedes the build-deferred portion of [D16](review-depth-modes.md) (relevance/
  depth separation, three modes, per-mode floors) — mark D16 resolved-by-build.
- Refines D10 (router gains ranked relevance + mode axis) and D12 (synthesizer
  gains the per-mode floor policy). See [`open-questions.md`](open-questions.md) Q20.
