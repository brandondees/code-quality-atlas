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
- **D15 — Artifact-scoped lenses get their own `shape: artifact`; G11 factor lands at #30 (Q18 resolved).** *(user, 2026-06-12)* Chose option (b): a fourth review shape **`artifact`** (sibling to diff / repo / decision), hosted as **one entry-point lens** that presence-detects an artifact and loads the matching rubric from a bundled file, driven by a manifest `artifacts:` table (artifact → detector glob → rubric source). Chosen over the minimal one-off lens (a) because it *generalizes* the whole §3 artifact-standard catalog at one always-on description's cost — the foundational pattern the owner asked to strengthen — and over retrieval-routed (c) because (c) breaks D7 plain-markdown portability (a longer-horizon harness bet, parked). The **G11 authoring-quality factor lands at #30** (meta-artifacts), keeping #32 cleanly about *runtime* agent safety; `SKILL.md`-authoring is the first instance (highest-confidence rubric — we already enforce it on ourselves via the generator/validator). Borrows presence-based activation from the linter world (MegaLinter activate-on-file, ESLint glob `overrides`, Spectral rulesets-by-type) and gives Q14 its cleanest relevance signal (file presence). Research: [`research/artifact-scoped-lenses.md`](research/artifact-scoped-lenses.md). **Not built** — the build phase adds the `shape: artifact` capability to `manifest.py`/`generate.py`, an `artifacts:` table, the `SKILL.md` rubric (mined from the Anthropic authoring guide), evals, and a #30 research subsection. Open at build time: detector reliability for embedded/non-standard-path artifacts; whether the shape subsumes or sits alongside the implicit artifact lenses (#20/#31/#19 — likely alongside).
- **D14 — Promote agentic/tool-use safety to its own category #32 (Q16 resolved).** *(user, 2026-06-12)* Agentic action-safety leaves #25 to become **#32 Agentic & tool-use safety**, scoped to the **action/tool surface** (tool least-privilege, approval gates & step budgets, tool-metadata-as-untrusted-input, confused-deputy/token-audience, inter-agent auth, sandboxed exec, memory hygiene, audit trail, excessive agency). Chosen over the cheaper "sharpen #25's trigger" middle path because the trigger gap is the decider — the highest-risk agent codebases (tool defs, MCP servers, autonomous loops) may not read as "LLM integration," so #25's trigger can miss them — plus G1 cross-cutting ownership (#13/#14/#24/#25) wants a single owner, and OWASP's *separate* Agentic Top 10 (ASI01–ASI10) is standards-grade external validation. **#25↔#32 boundary:** model-call concerns stay #25; action/tool concerns → #32; the **lethal-trifecta framing** stays in #25 but its exfil/action-leg mitigations are #32 (#25 references #32, no double-report). Build defaults (reversible): lens `reviewing-agentic-safety` (`shape: diff`, `built_from #32`, skip-clause "no tools/agents/MCP/autonomous loops"); a repo-shaped whole-agent-system audit arm is a noted follow-up. **`taxonomy.md` updated (#32 added, G2/Q16 marked resolved); skill not yet built** — the build phase moves the 9 agentic heuristics from cluster-4 #25 into a new #32 research section + manifest entry + generated skill/evals + router/synthesizer wiring + `taxonomy_version` bump, then cross-model re-gate. 32 categories.
- **D13 — Taxonomy v0.3 (round-2 gap hunt): four promoted categories + a third review shape.** *(user, 2026-06-12; "full v0.3 draft")* Promoted **#28 Operational & resilience design**, **#29 Decision lifecycle**, **#30 Enforcement apparatus & meta-artifacts**, **#31 Infrastructure-as-code**; added factors to #16/#17/#19/#20/#22/#25/#27; named **decision-time** as a third review shape alongside diff and repo/cron ([`decision-time-review-shape.md`](decision-time-review-shape.md), Q15). Resolves the G9 #12 drops (→ #28) and the G10 framing gap (→ #30). Decision-time is modelled as a **mode orthogonal to topic** (formalizing the existing `design:` flag) plus a few decision-native lenses — **not** a 7th cluster (would re-create G1 double-booking). Governance slices (build-vs-buy TCO, deep fairness, DevEx-as-a-system) held **out-of-scope** via the G8 detect-and-escalate boundary. Disposition: [`taxonomy.md`](taxonomy.md#candidate-additions--resolved-v03). 31 categories (D14 later added #32 → 32). **v0.3 build complete (2026-06-12):** all four promoted categories now ship skills — `reviewing-decision-lifecycle` (#29), `auditing-enforcement-and-meta-artifacts` (#30), `reviewing-resilience-and-scalability` (#28), and `auditing-infrastructure-as-code` (#31) — each with research section, manifest entry, examples, evals, and a cross-model gate on the 7-8B tier (qwen2.5:7b + llama3.1:8b). The add-factor regenerations landed earlier (drift clean). 26 lens skills + router + synthesizer. **(#32 from D14 and the `shape: artifact` lens from D15 remain unbuilt — the next build phase.)**

## Open questions

**Live state (2026-06-12).** Most of the questions below were answered by what
shipped across phases 2–3 and are now marked `→ RESOLVED` in place (with a
pointer to the decision or skill that closed them). A **decision sweep
(2026-06-12)** closed three more: **Q16 → D14** (promote agentic safety → #32),
**Q18 → D15** (the `artifact` shape; G11 factor → #30), and **Q13** (design
approved, build deferred) — all three are *decided* but **not yet built** (a
build backlog, batched). **Genuinely still open (undecided):**
Q17 (self-improving loop — design exploration written, awaiting review),
Q13 (team preferences overlay — designed, not yet built),
Q14 (router intent / matching-and-ranking / review-depth modes — new),
Q15 (a decision-time review shape — new, the round-2 gap-hunt headline),
Q19 (ship the latent tool-mechanization nudge + close the deterministic-tooling
presence holes — new), Q3 (review-vs-maintenance modes), Q4 (findings-vs-scores),
Q6 (idiom packs),
Q8 (proactive/cron-shaped maintenance — partially built as the repo audits),
and the Q2 residual low-priority candidates. Two new framing-class gaps were
also logged this pass ([`map-gaps.md`](map-gaps.md) **G12** validation-vs-verification /
stakeholder-intent — disposition: in-scope; **G13** *Tidy First?* economics &
proactive tidying mode — disposition open). A **round-3 gap hunt** (2026-06-14,
[`research/taxonomy-gap-hunt-round-3.md`](research/taxonomy-gap-hunt-round-3.md))
then added **G14–G19** via gap-finding methods that reason from outside the map
(external completeness model, stakeholder-vantage rotation, substrate sweep,
shape-axis extrapolation): G14 AI-authored-code defects, G15 production-evidence
review (a candidate 5th shape), G16 ethical/responsible-design, G17
data-engineering & data-contracts, G18 the two unowned ISO-25010:2023
characteristics (interoperability, safety), G19 review-coverage transparency, and
G20 the codebase/repo as a working environment for AI maintainers (the agent
vantage — a cluster-II rotation, mirror of G14; the agent-as-*operator* role is
mostly already mapped via #24/#32/#30), G21 operational time-bombs & exhaustion
classes (a failure-grounded sweep — cert/credential expiry & rotation, calendar/
clock time-bombs; add-factors), and G22 diff-isolation blindness (interaction /
composition defects — a missing change-set *unit*) — all **provisional,
owner-gated**, web-verified. A scope re-audit (2026-06-14, owner) then added
**G23** (detect-and-route: surfacing ≠ deciding — generalize G8; product/UX/value
findings are surfaced and routed to the right decider, not excluded) and **G24**
(candidate **Cluster VII — Product, Experience & Value**: usability, perceived
quality, UX consistency/content, inclusion, value/outcome instrumentation, trust/
transparency, conceptual integrity, i18n-of-experience, feature-value lifecycle —
[`research/product-experience-value-cluster.md`](research/product-experience-value-cluster.md)),
**G25** (re-audit of the rest of the exclusion pile — most exclusions held on the
no-artifact axis; sustainability + FinOps upgraded to routed #15 factors), and
**G26** (detect-and-suggest ≠ apply, defect ≠ improvement — the suite is
defect-only by a guard in every lens; improvement-suggestion is review-time;
refines Q3, narrows Q8). The recurring meta-lesson: reviewability is orthogonal
to authority (G23), reader identity (G20), and application-timing/valence (G26). A
**cross-discipline review-analog sweep** (importing mature review *practices* from
audit / science / manufacturing / clinical / aviation —
[`research/cross-discipline-review-analogs.md`](research/cross-discipline-review-analogs.md))
then added **G27** (segregation-of-duties / maker-checker dual-control in authz —
add-factor #14), **G28** (claims-vs-evidence verification, generalized from the
perf lens), and **G29** (root-cause vs symptom / band-aid detection); plus
feeds-existing notes (materiality → Q14; differential-diagnosis → G19;
safety-margin → #28/G21). The sweep mostly *confirmed* the atlas (poka-yoke maps
to #9/#10; checklists ≡ the whole form), so it yielded add-factors, not a new
cluster. Re-running shape-extrapolation on *security* and auditing the
synthesizer's own apparatus then added **G30** (threat modeling — STRIDE / DFD /
trust boundaries / abuse cases — as a *design-time* security discipline, distinct
from #14's diff-time vuln sweep; a strong instance of the Q15 decision shape) and
**G31** (the synthesizer's tension table is restraint-centric; enrich it with
cross-quality pairs like observability↔privacy, security↔usability). A final
**deliberate conflation audit** (enumerate every axis `X` for which
reviewability⊥X) then returned one net-new gap, **G32** (reviewability ⊥
*attribution* — pre-existing defects in touched code suppressed by the diff-only
filter; the Boy-Scout / opportunistic-surfacing principle, detect-and-route,
scope-bounded), and otherwise **confirmed the prior axes are covered** — a closure
signal that the framing seam is largely mined and the bottleneck is shifting from
finding to deciding. The pile is now consolidated into a ranked, dependency-
sequenced **synthesis** ([`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md))
— four build waves (foundations → add-factors → new lenses → bigger bets), with
the G23/G26 primitives and Q13/Q14/Q15 flagged as the upstream enablers most of
the high-value lenses depend on. A factor-level coverage audit
([`map-gaps.md`](map-gaps.md) G9) also found ~10 categories only partially
surfaced at the factor level — fixable through the manifest/research, with the
router half tracked as Q14. Everything else here is historical context kept for
provenance.

**Pending follow-up → RESOLVED (2026-06-12, local re-gate).** The cross-model
eval re-gate for the research-expansion additions ran on a laptop with Ollama.
All six skills whose heuristics changed since the expansion
(`reviewing-llm-integration`, `reviewing-decision-lifecycle`,
`auditing-enforcement-and-meta-artifacts`, `auditing-config-and-build-hygiene`,
`auditing-documentation-health`, `reviewing-pr-and-process-hygiene`) **pass** on
the 7-8B tier (`qwen2.5:7b`); the two new v0.3 skills were cross-confirmed on a
second family (`llama3.1:8b`). Every clean/healthy scenario correctly returned
"No findings" — no over-flagging regression. The only gaps observed are the
already-documented 7B ceilings (top-findings-only recall on dense audit scans;
cosmetic format-leak on qwen — a trailing "No findings:" sentence after real
findings, absent on llama). Per the runbook these are model-capability limits,
not heuristic regressions, so no tuning was applied. See the session-log entry
of the same date.

### Q18 — Artifact-scoped lens hosting: many per-artifact lenses without context bloat *(new, 2026-06-12)*

**Trigger.** Owner asked whether we review artifacts against published authoring standards — starting
from Anthropic's Agent Skill best-practices guide ([`map-gaps.md`](map-gaps.md) **G11**). We hold
*ourselves* to that guide (D7, enforced in the generator/validator) but have **no lens that reviews
someone else's `SKILL.md`** — and that's one instance of a broad class (Dockerfiles, Terraform, K8s
manifests, CI workflows, OpenAPI specs, ADRs, changelogs, `AGENTS.md`, model cards, datasheets), each
with its own canonical "well-formed X" standard and dedicated linter. Research:
[`research/artifact-scoped-lenses.md`](research/artifact-scoped-lenses.md).

**The question.** Adding a peer lens per artifact type would pile N always-on `description`s into the
skill budget — the §2 context tax (every skill's metadata is pre-loaded; "too many tools degrade
selection"; lost-in-the-middle / context rot make even a catalog that *fits* a reasoning tax; RAG-MCP
shows retrieval-narrowed tool sets >3× selection accuracy). So: **how do we host an open-ended set of
artifact-scoped lenses at near-zero idle cost?**

**Candidate directions (no decision yet; full detail in the research doc §6):**

1. **Minimal** — one new lens with a tight "skip when artifact absent" clause. Closes G11; doesn't
   generalize; +1 always-on description.
2. **An `artifact` shape** *(recommended)* — promote `shape: artifact` (sibling to diff / repo /
   decision): one entry-point lens that detects an artifact and loads the matching rubric from a
   bundled file, driven by a manifest `artifacts:` table (artifact → detector glob → rubric source).
   Breadth lives in on-demand rubrics; top-level cost is one description. Borrows the linter world's
   **presence-based activation** (MegaLinter activate-on-file, ESLint glob `overrides`, Spectral
   rulesets-by-type) and serves Q14's relevance-vs-depth split (file-presence is a clean relevance
   signal — Q14 candidate-3 with the cleanest possible signal).
3. **Retrieval-routed lenses** — full RAG-MCP: index every lens, retrieve per change, carry none at
   the top level. Highest leverage on the tax but breaks D7 portability (needs a retrieval step, not
   plain markdown). Longer-horizon.

**Open sub-questions.**

- Taxonomy placement of the *factor* (artifact-authoring quality): #30 meta-artifact vs #22/#24 vs a
  promoted Q16 category. Lean #30 (G11's table).
- Does the `artifact` shape subsume the existing implicit artifact lenses (#20 migrations, #31 IaC,
  #19 CI) or sit alongside them? (Likely alongside — those carry topic judgment beyond conformance.)
- Detector reliability: file-presence vs content-sniffing for embedded specs / non-standard paths.
- New behavior ⇒ cross-model eval re-gate before ship (compounds the pending re-gate above).

**Relation to prior decisions.** Refines D7 (we become a reviewer of the standard we author to),
D10/D12 (router/synthesizer), and Q14 (the cleanest signal-based-matching case). Evidence: G11 +
the research doc. **Status: RESOLVED (D15) — option (b), the `artifact` shape; G11 factor → #30. Build pending.**

### Q19 — Ship the latent tool-mechanization nudge + close the deterministic-tooling presence holes *(new, 2026-06-14)*

**Trigger.** Owner expected the suite to flag gaps in *deterministic* tooling — linters, complexity
scoring, coverage reporting, performance benchmarking, security scans — and hadn't seen it come up.
Audit confirms the state is **mixed, not "left to the repo owner":**

- `auditing-config-and-build-hygiene` **already** flags missing/disabled gates — *"Does CI run the
  full gate — lint, format-check, type-check, tests, dep/security scan — and is passing **required**
  to merge?"* plus soft-fail detection (`continue-on-error` / `|| true` / `allow_failure`)
  (`auditing-config-and-build-hygiene/SKILL.md:38,41`). So "no linter / no security scan in CI" **is**
  caught — by that one repo-shaped audit, when it's run.
- **coverage reporting** and **performance benchmarking** are **not** in that gate list, and
  complexity scoring / perf benchmarks have **no presence check anywhere**.
- the cross-lens nudge — **G10 item 1**'s `mechanize-with:` line (*"you detect this by hand; tool X
  gates it in CI, consider wiring it up"*), appended to each lens's finding contract from its existing
  `reference/tool-rules.md` — was **decided as an action but never built**: zero `SKILL.md` files carry
  it and it is absent from `tooling/generate.py` (parked in [`session-log.md`](session-log.md):272 and
  [`research/taxonomy-gap-hunt-round-2.md`](research/taxonomy-gap-hunt-round-2.md):153). Today
  `tool-rules.md` is positioned as a *wiring aid* ("for wiring up linters, not needed for the judgment
  review itself"), not a finding source — which is why the suite leaves this judgment to the owner by
  default: not by design decision, but because the `mechanize-with:` feature was never built.

**The question.** Two small, advisory builds: **(a)** ship the `mechanize-with:` generator pass (G10
item 1) so every lens surfaces its tool-mechanization as advisory output; **(b)** extend
`auditing-config-and-build-hygiene`'s gate list with **coverage-reporting** and **perf-benchmark**
presence (and **complexity-scoring**, if it earns a check).

**Open sub-questions.**

- Is *"the repo has no coverage gate / no perf benchmark"* a finding the owner wants, or noise on repos
  that deliberately skip it? Ties to the **Q13** team-preferences overlay (a preference-tier finding the
  team can tune/suppress, not a floor-tier one).
- Does `mechanize-with:` belong in **every** lens's finding contract, or only the repo audits?
- New advisory output ⇒ a light cross-model eval pass before ship (no over-flagging regression on clean
  repos).

**Relation to prior decisions.** Implements the unbuilt half of **G10 item 1**; refines D12 (the finding
contract) and D10 (the generator). **Status: open — decided-in-spirit (G10) but unbuilt; the
coverage/perf/complexity presence holes are newly named here.**

### Q17 — Self-improving loop: usage signals → learnings → research edits *(new, 2026-06-12)*

Make the suite self-improving: agents running the skills reflect on how the review process worked, detect routing misses / false positives / escapes / coverage gaps, and propagate learnings back to this repo — opt-in for consumers, mostly automated. Key insight: the **back half already exists** (D6/D8: research edit → drift → regenerate → evals → ship); what's missing is signal collection, distillation, and consented transport. Design exploration: [`self-improvement-loop.md`](self-improvement-loop.md) — a signal taxonomy (S1–S8, with taste S7 firewalled to the Q13 overlay, never upstreamed), the mechanism substrate (plugin hooks incl. a `PostToolUse` Skill-matcher invocation logger, a generated synthesizer "Process notes" appendix via a manifest `feedback:` section, `/atlas-retro` transcript digestion, a GitHub **outcome-auditor** routine joining reviews to merges/reverts as ground truth, an eval-first intake routine here), a **learning contract** mirroring D12's finding contract (stamped with the plugin commit SHA, enabling champion/challenger measurement across regenerations), four opt-in tiers (`off`/`local`/`draft`/`auto`) with the privacy boundary at record *creation* (abstracted evidence, never raw code), and the meta-loop's own failure modes (heuristic bloat, self-report bias, taste laundering, poisoned reports) countered by evidence thresholds + the eval-first ratchet as immune system. Staged rollout (§7): process-notes + local log first; full automation keeps exactly two human gates (consumer filing approval, atlas merge). Feeds Q14 (the invocation log is the missing lens-usage evidence) and depends on Q13. Status: **brainstorm captured, awaiting user review.**

### Q16 — Promote agentic/tool-use safety to its own category?  → RESOLVED (see D14: promoted → #32)

Map-gaps G2's candidate now has standards-grade external backing: OWASP released a dedicated **Top 10 for Agentic Applications** (ASI01–ASI10, 2025-12-09) separate from the LLM Top 10, alongside the Agentic AI Threats & Mitigations companion and the MCP spec's security-best-practices page (confused deputy / token passthrough / tool poisoning). The research-expansion pass (2026-06-12) filed the references + nine agentic heuristics under **#25** in cluster-4, so the suite reviews this material today either way. The open call: promote to a new category **#32** (cross-cutting #13 tool contracts, #14 authz, #24 agent process) — clearer ownership and a sharper lens trigger for agent-heavy codebases, at the cost of taxonomy churn and skill re-mapping — or keep it a #25 facet.
**Resolved (user, 2026-06-12) — promoted to #32 (D14).** The trigger gap was the decider (agent-heavy repos that don't read as "LLM integration" can slip #25's trigger); G1 cross-cutting ownership and OWASP's separate Agentic Top 10 sealed it. Scoped to the action/tool surface with a model-call↔action boundary; the lethal-trifecta framing stays in #25. `taxonomy.md` carries #32; the skill is pending the build phase. The cheaper "sharpen #25's trigger only" middle path was considered and rejected (leaves G1 ownership unresolved, keeps the bundled-budget crowding).

### Q13 — Team preferences overlay *(new, 2026-06-12)*

The suite pushes research-derived "objectively better" defaults but has no home for the **codebase owner's / team's considered opinion** (only `checking-idioms-and-consistency` bends, and only to linter configs). Design write-up: [`team-preferences-overlay.md`](team-preferences-overlay.md). Decisions captured from the user this session: **(a) tiered precedence** — preference-tier findings (taste/thresholds/idioms) the team may tune or silently suppress; floor-tier findings (security, correctness, data/migration safety, concurrency) can never be silently dropped, only `acknowledge`d with a recorded rationale that still surfaces; **(b) bootstrap = template + inference, but inference is proposal-only** — it emits a ratification *interview*, never writes the overlay, and never runs by accident, so a haphazard/vibe-coded repo can't launder unconsidered "approve-click" patterns into ratified standards. Overlay lives in the *reviewed* repo (`.code-quality-atlas/preferences.md`), is read at review time by the router, and stays out of generated-skill provenance (D6). Status: **design APPROVED (user, 2026-06-12) as the implementation basis; build DEFERRED** — sequenced after the v0.3 / #32 builds rather than next, so the keystone unblock of Q17/Q18/Q14 waits. The genuinely-open §9 residuals (tier-tag granularity — per-check vs per-lens; overlay-vs-linter-config precedence; monorepo discovery; `acknowledge` expiry) are **left to implementation-planning** when the build is picked up. **Extended (user, 2026-06-14, G26):** the overlay also carries an **improvement-valence verbosity** dial (§4.6 — the defect-only guard is a team preference, default strict) plus a built-in **anti-churn / convergence** discipline (§4a) it cannot relax; this is where G26's valence policy lives.

### Q14 — Router intent, matching/ranking, and review-depth modes *(new, 2026-06-12)*

**Trigger.** A factor-level coverage audit ([`map-gaps.md`](map-gaps.md) G9) **observed** the router's 2-4-lens cap acting as a *coverage suppressor*: capping each change to 2-4 lenses leaves the soft lenses (naming/readability, observability, restraint) unfired on most change shapes, so their factors never produce findings — the suite emits no naming findings in practice despite #5 being owned. **The cap is working exactly as documented** — `choosing-review-lenses/SKILL.md` (and `tooling/generate.py`) specify "run 2-4 content lenses per change" (D10), and that contract stands. The tension is that the contract was written to *improve unprompted, relevant skill activation* — a discovery aid so an agent/harness fires the right lenses without knowing the whole catalog — **not to gate total coverage**. The original intent was the full suite run **together, in parallel, for an extremely comprehensive review**; the router was meant to be the on-ramp to that, not a turnstile in front of it. Q14 asks whether that contract should be re-scoped — separating relevance from depth (below) — not whether the router is violating it.

**The conflation to undo.** Today's router collapses two independent axes onto one 2-4 list:

- **Relevance** — which lenses *apply* to this change (a bug fix needn't run a11y).
- **Depth / budget** — *how much* to run right now (quick triage vs. full audit).

The 2-4 cap is really a *depth* choice wearing a *relevance* mask. Separating the two axes is the core of this question.

**Candidate directions (to weigh — no decision yet):**

1. **Review-depth modes / tiers** — make depth an explicit selectable axis:
   - *Critical-only triage* — correctness, security, data-safety, concurrency; fast/cheap, gate-shaped (pre-merge smoke).
   - *PR-level review* — the relevance-routed set (today's behavior), tuned per change shape.
   - *Comprehensive all-lens audit* — the original vision: every applicable lens in parallel; run periodically / on-demand / on high-risk diffs, not every push.
   This reframes the six repo audits as the *repo* arm of the comprehensive tier and adds a *diff* arm.
2. **Expand what the router exposes** — always surface the full ranked catalog rather than a hard 2-4 cut, so no lens is invisible; the cap becomes a *default depth*, overridable.
3. **Change matching & ranking** — move from the hand-authored `when → lenses` table toward signal-based matching (changed paths, languages, diff features) yielding a relevance *score* per lens, with a depth threshold deciding how far down the ranked list to go. Soft lenses stay reachable at higher depth instead of being absent.
4. **Progressive-phase routing** — phase the review: gate-critical first (block fast on blockers), then structural/design, then readability/idiom/docs as polish — each phase a depth step a reviewer (human or scheduled) can stop at. Pairs with the synthesizer's severity floor.

**Open sub-questions.**

- Where does *mode* live — a router argument, distinct commands (`/atlas-review-pr` exists; add `/atlas-audit-comprehensive` and `/atlas-triage`?), or a manifest `modes:` section the router generates from?
- Does the 2-4 cap survive as the *PR-mode default*, or is it dropped for relevance-ranked-to-a-budget?
- Interaction with the synthesizer (D12) and `REVIEW.md`'s round-based severity floor: that escalating floor is *precisely* what silences Nit/Minor (readability-class) findings after round 1, so comprehensive mode would need to **lower** the floor — keep it at Nit regardless of round count, or bypass the per-round escalation entirely for full-suite runs — to keep those findings alive. (A *higher* floor drops more, not fewer.)
- Cost/latency: comprehensive-in-parallel is the expensive path — on-demand only, or scheduled like the repo audits?
- Does the team-preferences overlay (Q13) set the default mode and the critical-tier floor per repo?

**Relation to prior decisions.** Refines D10 (router) and D12 (synthesizer / advisory fan-out); "all lenses in parallel" is consistent with D12's finding contract a harness can mechanize. Evidence: G9. **Status: open — framing captured, no decisions yet.**

### Q15 — A decision-time review shape *(new, 2026-06-12; the round-2 gap-hunt headline)*

The round-2 gap hunt ([`research/taxonomy-gap-hunt-round-2.md`](research/taxonomy-gap-hunt-round-2.md)) found that the strongest, most-recurring gap is not a topic but a **shape**. The suite reviews *diffs* (diff-lenses) and *repo state* (cron audits), but never a **decision as it is made** — an ADR, RFC, adoption PR, deprecation plan, rollout plan, capacity/DR design. Axis C (adopt / revisit-ADR / retire) is *entirely* this shape; much of axis E (DR, capacity, resilience, progressive-delivery) is RFC-shaped; so are B3 (model adoption) and D2 (privacy-by-design). Many of round 2's strongest gaps are invisible to a diff **and** to a repo scan because they live in the decision, not the artifact.

The router has a thin "design doc / RFC" route today, but no lens *family* built for decision-record review — which asks different questions: *is the rationale recorded? are the assumptions stated and still valid? is there a revisit-trigger? what's the exit / rollback / sunset?* **Resolved (design pass + D13):** decision-time is a **mode orthogonal to topic** — formalized as a `shape: decision` capability (promoting the existing `design:` flag) carrying a shared decision-record checklist, *plus* a few decision-native lenses (adoption-&-exit, decision-record audit, operational-design) — **not** a 7th cluster. #29 (decision lifecycle) is the *topic* whose natural shape this is; topic and shape are orthogonal axes (like #21's `repo` shape). Design write-up: [`decision-time-review-shape.md`](decision-time-review-shape.md); its §6 sub-questions stay open, and the decision-native lenses are pending the v0.3 build phase. **Status: shape resolved; lenses pending build.**

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
**Refined by [`map-gaps.md`](map-gaps.md) G26 (2026-06-14):** the split is largely a *valence toggle at review time*, not a separate mode. Improvement *detection + suggestion* (tidyings, dead code, stale deps) is review-time and detect-and-route (route: implementer); it is currently suppressed only by the defect-only reviewer-discipline guard, not by a missing mode. The genuinely separate "maintenance" activity is just auto-*application* (Q8) and proactive *scanning* (the repo audits). Resolution proposed in G26: refine the guard + add a `valence: defect | improvement` axis to the finding contract.

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
**Narrowed by [`map-gaps.md`](map-gaps.md) G26 (2026-06-14):** the "fixing half" is *only auto-application*, and is partly served already by the broader `simplify` / `code-review --fix` skills. *Suggesting* the fix (apply/defer/ignore to the implementer) is review-time, not part of this residual — it's gated by the defect-only guard (G26), not by missing capability.
