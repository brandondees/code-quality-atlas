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
- **D9 — Packaging (Q12 resolved): the repo is itself a Claude Code plugin + marketplace.** `.claude-plugin/plugin.json` + `marketplace.json` at the repo root; `skills/` is already the plugin-default skill layout, so no restructuring. Install: `/plugin marketplace add brandondees/code-quality-atlas` then `/plugin install code-quality-atlas@code-quality-atlas`. **Versioning: commit-SHA** (no `version` field) — every merged commit ships, matching the regeneration loop; switch to pinned semver if/when the suite stabilizes for external users. Skill-level provenance still carries `taxonomy_version`. Validated with `claude plugin validate` and a local end-to-end install (22/22 skills discovered). *(2026-06-10)*

## Open questions

### Q2 — Candidate additions  → RESOLVED (see D5)
Disposition table lives in [`taxonomy.md`](taxonomy.md#candidate-additions--resolved-v02). Residual low-priority candidates still open: cloud cost / FinOps (factor-note in #15); SLO/error-budget (factor-note in #16, overlaps #24); telemetry/analytics privacy (across #16 and #27). Revisit only if any proves to need its own review behavior.

### Q9 — Compliance scope boundary *(new, from D5)*
Where does #27 (compliance/licensing/provenance) stop being "engineering quality" and become legal/governance that's out of scope for a code-review skill? Likely keep only the parts a reviewer can see in a diff (license headers, dep licenses, PII in code/logs, AI-provenance markers); push the rest to humans.

---

## Phase 2 design questions *(opened 2026-06-09, gating the skill-suite architecture)*

### Q10 — Regeneration model (the D6 mechanism)
How do docs→skills stay linked so improving research rebuilds/refines skills? Options: (a) **generated** — a generator reads taxonomy+research and emits skills; regen = re-run; (b) **authored-with-provenance** — hand-authored skills carry frontmatter linking to source categories/sections + content hashes; a drift-checker flags stale skills; (c) **hybrid** — generator emits a structured first draft + provenance, humans/agents refine, drift-checker compares recorded source-hashes vs current docs and proposes updates. (Leaning hybrid.) Blocks the whole pipeline design.

### Q11 — Async-critique integration
The research docs will be critiqued/refined continuously and in parallel. How does a doc change surface the skills it affects? (Provenance map + drift report; CI check; a "docs changed → which skills to rebuild" command.) Tied to Q10.

### Q1 (revisited) — Granularity, now constrained by D6
Granularity isn't just "how many skills" — it's "what unit of the research does one skill correspond to," because that mapping IS the regeneration link. A clean category→skill (or cluster→skill, or behavior→skill) mapping makes regeneration tractable; a fuzzy one makes it impossible. Resolve Q1 and Q10 together.

### Q12 — Packaging & where skills live  → RESOLVED (see D9)
In-repo `skills/` dir? A Claude Code plugin? How are they versioned relative to the docs (so a skill records which doc version it was built from)?

### Q1 — Granularity (the big one, blocks phase 2)
24 categories is too many for 24 skills; several would be thin. How do categories collapse into a buildable, composable set? Options to weigh later:
- **By cluster** (~6 skills) — coarse, each skill covers a whole cluster.
- **By review behavior** — group by *what the reviewer does* (e.g. "trace correctness", "hunt silent failures", "check the blast radius") rather than by topic. May cut across clusters.
- **By altitude** — line/function → module → architecture → system. Maps to how reviews actually zoom.
- **Hybrid** — a few broad "lens" skills + a handful of sharp single-behavior skills (security scan, migration safety, N+1) where prior art shows crisp triggers work.
- **Decision criterion:** a skill should have a coherent trigger, fit in working context, and produce findings a human/agent can act on without re-deriving the rest of the map.

### Q2 — Candidate additions (from taxonomy.md)
Promote any of these to first-class categories? config management; logging-as-first-class; i18n money/units; licensing/compliance/provenance; **AI/LLM-specific code quality**; internal-API DX/ergonomics; portability & environment assumptions. *(AI/LLM-specific feels most likely to be genuinely under-served by all prior art.)*

### Q3 — Review vs. maintenance split
"Review" (assess a diff) and "maintenance" (improve existing code over time) are different activities that touch the same categories differently. Should skills be dual-mode, or should we have a review-facing and a maintenance-facing variant per area?

### Q4 — Findings vs. scores
Do skills emit only findings (actionable, located), or also quantitative scores per dimension (à la `type-design-analyzer`)? Scores aid trend-tracking but invite gaming/vanity-metric failure modes.

### Q5 — Counterweight enforcement
How do we make the "restraint" counterweights (premature abstraction, premature optimization) structurally present so the suite doesn't just nag for *more* — more tests, more abstraction, more defensive code? Possibly a dedicated "is this change *too much*?" lens.

### Q6 — Language/ecosystem strategy
Universal-but-shallow vs. ecosystem-specific-and-deep (the `dhh-rails` / `kieran-*` model). Likely a layered answer: language-agnostic core + opt-in idiom packs.

### Q7 — Composition & orchestration
When multiple skills apply to one review, how do they fan out and synthesize without drowning the user in overlapping findings? (Prior-art multi-agent review toolkits are the reference.)

### Q8 — Scope of "maintenance"
Does maintenance include proactive hygiene (dead-code sweeps, dependency bumps, doc staleness) on a schedule, not just review-time? If so, some skills are *cron-shaped*, not *diff-shaped*.
