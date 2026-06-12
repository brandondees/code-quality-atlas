# Open Questions & Decisions

## Decisions made

- **D1 — Project framing.** Build a *standalone, first-principles* skill suite for code review & maintenance. Existing skills/tools are prior art, not constraints. *(2026-06-08)*
- **D2 — Scope.** Maximal: intrinsic code properties **plus** all cross-cutting concerns. *(2026-06-08)*
- **D3 — Sequence.** Map first, then design the skill suite. Research/reference-gathering happens against the map before any skill design. *(2026-06-08)*
- **D4 — Repo.** `code-quality-atlas`, private, under `~/code/`. Name provisional. *(2026-06-08)*
- **D5 — Map pressure-test → taxonomy v0.2.** Resolved the candidate additions: **promoted** AI/LLM-integration (#25), Configuration & environment (#26), Compliance/licensing/provenance (#27); **broadened** #3 (distributed correctness) and #9 (caller ergonomics / internal-API DX); **cross-linked** money/units #4 ↔ #23; **kept folded** logging in #16. Now 27 categories. Reversible. *(2026-06-08)*
- **D6 — Docs are the source of truth; skills are derived, traceable & regenerable.** *(user, 2026-06-09)* The taxonomy + per-cluster research are canonical. Every skill must trace back to the categories/research sections it's built from, and be **rebuildable/refinable** as those docs improve. Research critique/refinement runs **async and in parallel** with skill-building — the architecture must let improving docs flow into improving skills over time (a compounding loop), never a one-shot generation that then drifts. This makes phase-2 partly a *pipeline* design, not just a set of skills.
- **D7 — Skills follow Anthropic's Agent Skills best practices; optimize for progressive disclosure, auto-trigger descriptions, and model portability.** *(user, 2026-06-09; ref https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)* `SKILL.md` is a lean entry point (**<500 lines**, aim ≪) with frontmatter (gerund `name`; specific third-person `description` ≤1024 chars carrying explicit trigger keywords; provenance) + when-to-use + a lean checklist; detailed heuristics / tool-rules / references / examples live in **one-level-deep bundled files** loaded on demand (no context cost until read; >100-line files get a ToC). **Do not assume the model is Claude** — target portability down to ~8B local models: bundled files are explicit, concrete, checklist-style (low ambiguity), with concrete good/bad examples and a single default approach (no option-menus). Plain markdown+files = harness/model-agnostic. Forward-slash paths; no time-sensitive text; consistent terminology.
- **D8 — Eval-first.** Each skill ships **≥3 evaluation scenarios** (query + expected_behavior, with a no-skill baseline). Evals are the **regression net for regeneration**: docs change → drift-check flags affected skills → regenerate/refine → re-run evals to confirm no behavioral regression. Write evals before skill prose.
- **D10 — First-dogfood packaging fixes (Q7 partially resolved): self-sufficient SKILL.md + a router skill.** *(from in-session user feedback, 2026-06-11)* Five changes, all driven through the manifest/generator so regeneration stays clean: **(1)** every `SKILL.md` inlines its **top ~8 checks** (head of the source heuristics; cross_ref categories capped at 2) so the first disclosure level is reviewable without a second fetch; **(2)** a manifest `router:` section generates `choosing-review-lenses` — the composition layer mapping "what am I reviewing" → 2-4 lenses, with a one-line `picker` differentiator per lens (selection sharpness without touching the eval-tuned trigger `description`s); **(3)** a `design: true` flag marks which diff lenses also work on design docs/plans (◆ in the router catalog), and every SKILL.md states its shape explicitly; **(4)** skills with `cross_ref` categories carry a **dedupe note** naming the category's primary owner (G1, surfaced at review time, not just validation time); **(5)** the reference-file links say when each is actually needed (tool-rules/sources are not part of the judgment review). The router has `built_from: []` — it derives from the manifest, so docs drift never flags it; manifest edits regenerate it.
- **D12 — Composition back half (Q7 resolved): a synthesizer skill + advisory-by-default fan-out.** *(2026-06-12)* The router (D10) picks the lenses; a 24th skill, `synthesizing-review-findings`, merges their output into one report — **collect → dedupe → reconcile → rank → verdict**. Dedup reuses the existing G1 primary-owner attribution (shared findings reported once, under the owner); reconciliation uses a manifest `synthesizer.tensions:` table of known opposing lens pairs (restraint ↔ module-design / performance / test-quality / api-contract; performance ↔ readability) each with a default resolution; ranking uses a `severity_order` scale (Blocker > Major > Minor > Nit) with correctness/security/data-loss floated to the top; the verdict is one of block / approve-with-changes / approve. **Fan-out is advisory by default** (the agent runs the router's lenses, then applies the merge) — chosen over automated orchestration to honor D7 portability (plain markdown, no Claude/harness assumption) — but the skill ships a fixed **finding contract** (location/severity/lens/finding/fix) so a capable harness can *mechanize* the same deterministic merge. Generated from the manifest like the router (`built_from: []`, no docs drift); validator checks tensions name two distinct known lenses and `severity_order` is non-trivial. A `reviewer discipline` guard forbids inflating the merged report beyond the union of real lens findings.
- **D11 — License for public release: dual MIT (code) + CC BY 4.0 (content).** *(user, 2026-06-11)* The research atlas and skills (`docs/`, `skills/`, README) carry CC BY 4.0 — prose is the project's main value and CC BY is built for it; the pipeline (`tooling/`, `tests/`, CI/config) carries MIT. Python sources get `SPDX-License-Identifier: MIT` headers (dogfooding #27's per-file-header check); the plugin manifest declares `MIT AND CC-BY-4.0`. Root `LICENSE` is the explainer, full texts in `LICENSE-MIT` / `LICENSE-CC-BY-4.0`. Chosen over single-MIT for content-license fit, over copyleft to keep plugin adoption unencumbered. Unblocks flipping the repo public.
- **D9 — Packaging (Q12 resolved): the repo is itself a Claude Code plugin + marketplace.** `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (both inside the repo-root `.claude-plugin/` directory); `skills/` is already the plugin-default skill layout, so no restructuring. Install: `/plugin marketplace add brandondees/code-quality-atlas` then `/plugin install code-quality-atlas@code-quality-atlas`. **Versioning: commit-SHA** (no `version` field) — every merged commit ships, matching the regeneration loop; switch to pinned semver if/when the suite stabilizes for external users. Skill-level provenance still carries `taxonomy_version`. Validated with `claude plugin validate` and a local end-to-end install (22/22 skills discovered). *(2026-06-10)*

## Open questions

**Live state (2026-06-12).** Most of the questions below were answered by what
shipped across phases 2–3 and are now marked `→ RESOLVED` in place (with a
pointer to the decision or skill that closed them). **Genuinely still open:**
Q14 (promote agentic/tool-use safety to its own category),
Q13 (team preferences overlay — designed, not yet built),
Q3 (review-vs-maintenance modes), Q4 (findings-vs-scores), Q6 (idiom packs),
Q8 (proactive/cron-shaped maintenance — partially built as the repo audits),
and the Q2 residual low-priority candidates. Everything else here is historical
context kept for provenance.

### Q14 — Promote agentic/tool-use safety to its own category? *(new, 2026-06-12)*
Map-gaps G2's candidate now has standards-grade external backing: OWASP released a dedicated **Top 10 for Agentic Applications** (ASI01–ASI10, 2025-12-09) separate from the LLM Top 10, alongside the Agentic AI Threats & Mitigations companion and the MCP spec's security-best-practices page (confused deputy / token passthrough / tool poisoning). The research-expansion pass (2026-06-12) filed the references + nine agentic heuristics under **#25** in cluster-4, so the suite reviews this material today either way. The open call: promote to a category **#28** (cross-cutting #13 tool contracts, #14 authz, #24 agent process) — clearer ownership and a sharper lens trigger for agent-heavy codebases, at the cost of taxonomy churn and skill re-mapping — or keep it a #25 facet. D5-style taxonomy decision: **awaiting user.**

### Q13 — Team preferences overlay *(new, 2026-06-12)*
The suite pushes research-derived "objectively better" defaults but has no home for the **codebase owner's / team's considered opinion** (only `checking-idioms-and-consistency` bends, and only to linter configs). Design write-up: [`team-preferences-overlay.md`](team-preferences-overlay.md). Decisions captured from the user this session: **(a) tiered precedence** — preference-tier findings (taste/thresholds/idioms) the team may tune or silently suppress; floor-tier findings (security, correctness, data/migration safety, concurrency) can never be silently dropped, only `acknowledge`d with a recorded rationale that still surfaces; **(b) bootstrap = template + inference, but inference is proposal-only** — it emits a ratification *interview*, never writes the overlay, and never runs by accident, so a haphazard/vibe-coded repo can't launder unconsidered "approve-click" patterns into ratified standards. Overlay lives in the *reviewed* repo (`.code-quality-atlas/preferences.md`), is read at review time by the router, and stays out of generated-skill provenance (D6). Status: **design, awaiting review before implementation planning.** Open sub-questions live in the write-up (§9).

### Q2 — Candidate additions  → RESOLVED (see D5)

Disposition table lives in [`taxonomy.md`](taxonomy.md#candidate-additions--resolved-v02). Residual low-priority candidates still open: cloud cost / FinOps (factor-note in #15); SLO/error-budget (factor-note in #16, overlaps #24); telemetry/analytics privacy (across #16 and #27). Revisit only if any proves to need its own review behavior.

### Q9 — Compliance scope boundary *(new, from D5)*  → RESOLVED (built: `auditing-compliance-and-provenance`)

Where does #27 (compliance/licensing/provenance) stop being "engineering quality" and become legal/governance that's out of scope for a code-review skill? Likely keep only the parts a reviewer can see in a diff (license headers, dep licenses, PII in code/logs, AI-provenance markers); push the rest to humans.
**Resolved exactly as proposed:** the `auditing-compliance-and-provenance` lens reviews only what's visible in a diff/repo (license headers, dep licenses, PII in code/logs, AI-provenance markers, SBOM currency) and **detects-and-escalates to humans rather than deciding legal questions** — the legal/governance call stays with people.

---

## Phase 2 design questions *(opened 2026-06-09, gating the skill-suite architecture)*

### Q10 — Regeneration model (the D6 mechanism)  → RESOLVED (hybrid; built)

How do docs→skills stay linked so improving research rebuilds/refines skills? Options: (a) **generated** — a generator reads taxonomy+research and emits skills; regen = re-run; (b) **authored-with-provenance** — hand-authored skills carry frontmatter linking to source categories/sections + content hashes; a drift-checker flags stale skills; (c) **hybrid** — generator emits a structured first draft + provenance, humans/agents refine, drift-checker compares recorded source-hashes vs current docs and proposes updates. (Leaning hybrid.) Blocks the whole pipeline design.
**Resolved as (c) hybrid:** [`skills/manifest.yaml`](../skills/manifest.yaml) maps each skill to its source categories; [`tooling/generate.py`](../tooling/generate.py) emits `SKILL.md` + reference files + per-section provenance hashes from the research; hand-refined `examples.md`/`evals` are preserved across regen; [`tooling/drift.py`](../tooling/drift.py) compares recorded hashes vs current docs. Regen = `python -m tooling.cli generate`. See the [regeneration runbook](runbooks/regenerating-skills.md).

### Q11 — Async-critique integration  → RESOLVED (built: drift report + CI gate)

The research docs will be critiqued/refined continuously and in parallel. How does a doc change surface the skills it affects? (Provenance map + drift report; CI check; a "docs changed → which skills to rebuild" command.) Tied to Q10.
**Resolved:** the per-section provenance hashes + `python -m tooling.cli drift` are the "docs changed → which skills are stale" report, gated in CI. Editing a research section flags exactly the skills `built_from` it; the two composition skills (`built_from: []`) are regenerated by manifest edits instead.

### Q1 (revisited) — Granularity, now constrained by D6  → RESOLVED (see phase-2 design; built)

Granularity isn't just "how many skills" — it's "what unit of the research does one skill correspond to," because that mapping IS the regeneration link. A clean category→skill (or cluster→skill, or behavior→skill) mapping makes regeneration tractable; a fuzzy one makes it impossible. Resolve Q1 and Q10 together.
**Resolved as behavior-based, manifest-mapped:** the unit is a *review behavior* (22 behaviors over the 27 categories), each skill's `built_from` naming the exact research sections it derives from — so the regeneration link (Q10) is the manifest. See [`docs/phase-2-skill-suite-design.md`](phase-2-skill-suite-design.md).

### Q12 — Packaging & where skills live  → RESOLVED (see D9)

In-repo `skills/` dir? A Claude Code plugin? How are they versioned relative to the docs (so a skill records which doc version it was built from)?

### Q1 — Granularity (the big one, blocks phase 2)  → RESOLVED (behavior-based + hybrid; built)

*(Original framing kept for provenance; resolved together with Q1-revisited above.)* The suite collapsed the categories along the **By review behavior** + **Hybrid** options below — broad lens skills plus sharp single-behavior ones (security sweep, migration safety, …) — meeting the decision criterion (coherent trigger, fits working context, actionable findings without re-deriving the map).
24 categories is too many for 24 skills; several would be thin. How do categories collapse into a buildable, composable set? Options to weigh later:
- **By cluster** (~6 skills) — coarse, each skill covers a whole cluster.
- **By review behavior** — group by *what the reviewer does* (e.g. "trace correctness", "hunt silent failures", "check the blast radius") rather than by topic. May cut across clusters.
- **By altitude** — line/function → module → architecture → system. Maps to how reviews actually zoom.
- **Hybrid** — a few broad "lens" skills + a handful of sharp single-behavior skills (security scan, migration safety, N+1) where prior art shows crisp triggers work.
- **Decision criterion:** a skill should have a coherent trigger, fit in working context, and produce findings a human/agent can act on without re-deriving the rest of the map.

### Q2 — Candidate additions (from taxonomy.md)  → RESOLVED (see D5; duplicate of the Q2 above)

*(Earlier verbatim copy of Q2; resolved by D5 — promoted AI/LLM-integration #25, config #26, compliance #27; the rest folded. Residual low-priority candidates tracked under the resolved Q2 at the top.)*
Promote any of these to first-class categories? config management; logging-as-first-class; i18n money/units; licensing/compliance/provenance; **AI/LLM-specific code quality**; internal-API DX/ergonomics; portability & environment assumptions. *(AI/LLM-specific feels most likely to be genuinely under-served by all prior art.)*

### Q3 — Review vs. maintenance split

"Review" (assess a diff) and "maintenance" (improve existing code over time) are different activities that touch the same categories differently. Should skills be dual-mode, or should we have a review-facing and a maintenance-facing variant per area?

### Q4 — Findings vs. scores

Do skills emit only findings (actionable, located), or also quantitative scores per dimension (à la `type-design-analyzer`)? Scores aid trend-tracking but invite gaming/vanity-metric failure modes.

### Q5 — Counterweight enforcement  → RESOLVED (built: `checking-restraint` + synthesizer tensions)

How do we make the "restraint" counterweights (premature abstraction, premature optimization) structurally present so the suite doesn't just nag for *more* — more tests, more abstraction, more defensive code? Possibly a dedicated "is this change *too much*?" lens.
**Resolved exactly as proposed** — a dedicated "is this change too much?" lens: `checking-restraint`, wired into the feature, refactor, performance, LLM, and dependency routes so restraint is structurally present, not optional. D12's synthesizer `tensions` table then forces restraint to be weighed against the "more" lenses (module-design, performance, test-quality, api-contract) at merge time, with restraint winning absent evidence.

### Q6 — Language/ecosystem strategy

Universal-but-shallow vs. ecosystem-specific-and-deep (the `dhh-rails` / `kieran-*` model). Likely a layered answer: language-agnostic core + opt-in idiom packs.

### Q7 — Composition & orchestration  → RESOLVED (see D10 + D12)

When multiple skills apply to one review, how do they fan out and synthesize without drowning the user in overlapping findings? (Prior-art multi-agent review toolkits are the reference.)
First answer shipped (D10): the `choosing-review-lenses` router (situation → lenses, 2-4 cap, design-capability markers) plus per-skill dedupe notes naming each shared category's primary owner. Back half shipped (D12): `synthesizing-review-findings` merges multi-lens output into one deduplicated, tension-reconciled, severity-ranked report with a single verdict; **fan-out is advisory by default** (portability over orchestration, per D7) but ships a finding contract a harness can mechanize. Both halves are generated from the manifest. Residual future work folds into the compounding loop — tuning the tension table and severity calls as dogfooding surfaces new conflicts.

### Q8 — Scope of "maintenance"  → PARTIALLY RESOLVED (detection built; fixing still open)

Does maintenance include proactive hygiene (dead-code sweeps, dependency bumps, doc staleness) on a schedule, not just review-time? If so, some skills are *cron-shaped*, not *diff-shaped*.
**Yes, and the cron shape is built for detection:** the six repo-shaped audits + `finding-maintainability-hotspots` are scheduled, whole-repo *detectors* (dead-code/debt, dep CVEs, doc staleness, …). **Still open:** the *fixing* half — skills that don't just flag but apply the change (sweep the dead code, bump the dep, refresh the stale doc). That residual is the same gap as Q3 (a maintenance/fixing mode vs. review/detection mode).
