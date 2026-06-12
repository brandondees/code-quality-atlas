# Map gaps & cross-cutting findings

Surfaced during the phase-1 research pass (2026-06-08). These are **structural** observations about the taxonomy that feed **phase 2 (skill-suite architecture)** — especially the granularity decision (Q1). Kept separate from `open-questions.md` because each is a concrete design constraint, not an open question.

## G1 — Concerns that are double/triple-booked → each needs ONE canonical owner

Several factors legitimately appear under multiple categories. For the *map* that's fine (it's a graph). For *skills* it's a hazard: two skills flagging the same issue produces duplicate, possibly-conflicting findings. Each concern below needs one owning skill; the others reference it.

| Concern | Appears in | Proposed owner (TBD phase 2) |
|---|---|---|
| Dependency / CVE / supply-chain | #14 security, #18 deps, #25 (LLM03) | #18, with #14 deferring to it |
| PII / sensitive-data handling | #14 security, #16 logging, #27 compliance | #27 detects, #14/#16 enforce at their boundary |
| Feature-flag hygiene & lifecycle | #12 arch, #16 operability, #26 config | #26 (lifecycle/cleanup), #12 (architecture only) |
| Graceful startup/shutdown | #16, #26 | #16 |
| Money / units / measurement | #4 correctness, #23 i18n | split: value-correctness → #4, formatting → #23 |
| AI-generated code provenance | #25, #27 | #27 |
| Doc-drift vs comment-rot | #22 (doc drift), #7 (comment rot) | boundary: in-code comments → #7, external docs → #22 |

**Principle to adopt:** detection has a single owner; other categories may *enforce* at their boundary but don't re-report.

## G2 — Candidate promotion: "Excessive Agency" / agentic tool-use safety

OWASP LLM Top 10 **LLM06 (Excessive Agency)** + Simon Willison's **"lethal trifecta"** (private-data access + untrusted-content exposure + exfiltration/action ability) may be big enough to pull out of #25 into its own category. It cross-cuts #14 (security) and #13 (API/contract design, since it's about what actions a tool surface permits). Decision deferred; flagged as the most likely *next* promotion after the v0.2 three.

**Update (2026-06-12) — external validation landed.** OWASP now treats agentic risk as its own discipline: a dedicated **Top 10 for Agentic Applications** (ASI01–ASI10, released 2025-12-09) separate from the LLM-app list, with the **Agentic AI: Threats and Mitigations** (v1.0, 2025-02) companion; the **MCP spec** ships its own security-best-practices page (confused deputy, token passthrough, tool poisoning). The references + nine agentic heuristics are filed under #25 in [`research/cluster-4-runtime.md`](research/cluster-4-runtime.md) regardless of the promotion call, so no research is blocked on it.

**Resolved (2026-06-12, D14 / Q16):** **promoted to category #32 — Agentic & tool-use safety** (cross-cutting #13/#14/#24/#25), scoped to the action/tool surface with a model-call↔action G1 boundary (lethal-trifecta framing stays in #25). `taxonomy.md` carries #32; the owning lens `reviewing-agentic-safety` is pending the build phase (move the 9 heuristics from cluster-4 #25 → a new #32 research section + manifest + generated skill/evals). The trigger gap (agent-heavy repos that don't read as "LLM integration") was the decider over the cheaper "sharpen #25's trigger" path.

## G3 — Decomposition tension the suite MUST take a stance on

#6 (local readability, Clean-Code lineage: *extract aggressively, many small functions*) directly conflicts with #11/#9 (Ousterhout: *deep modules, don't over-decompose; shallow wrappers are negative-value*). A "split this up" reviewer and a "stop over-abstracting" reviewer will contradict each other on the same diff. The suite needs an explicit **altitude/decomposition policy** before either skill ships. Relates to counterweight enforcement (Q5).

## G4 — Readability coverage seam

#5 (naming = intention-revealing *meaning*) and #8 (consistency = *uniformity*, casing/convention) overlap on naming rules. Split cleanly: **meaning → #5, uniformity → #8.**

## G5 — Where LLM judgment is the ONLY tool (build here first)

These factors have little or no static-analysis coverage, so an LLM reviewer adds unique, non-redundant value — and they should be prioritized in phase 2 *because* tools don't already do them:
- altitude/abstraction-level mixing (#6)
- symmetry of expression (#6)
- premature abstraction / the wrong abstraction (#11) — counterweight
- premature optimization (#15) — counterweight
- naming *quality* beyond casing (#5)
- agent-native parity (#24)
- caller ergonomics / "pit of success" (#9)

Corollary: where mature linters already cover a category well (formatting, basic complexity, many security/a11y rules), the skill's job is to *orchestrate/triage tool output*, not re-implement it.

## G6 — #8 is probably a *family*, not a skill

Idiom/consistency is inherently per-ecosystem (the `dhh-rails` / `kieran-*` prior-art pattern). #8 likely becomes a language-agnostic core + opt-in idiom packs rather than one generic skill. Drives the language strategy question (Q6).

## G7 — Some skills need git history, not just the diff

#21 (maintainability) is meaningfully **VCS-history-aware**: churn × complexity hotspots, change-coupling, bus factor (CodeScene / Adam Tornhill's *Your Code as a Crime Scene*). These can't be assessed from a single diff. Implies a class of **repo/history-shaped** skills distinct from **diff-shaped** ones (relates to Q8: are some skills cron-shaped?).

## G8 — Detection vs. adjudication boundary (esp. #27)

Several #27 checks (regulatory interpretation, license-law compatibility) should **escalate to a human**, not be adjudicated by the agent. The agent's job is *detection + flagging with evidence*, not legal judgment. Generalize: every skill should know which findings it can resolve vs. which it must escalate. Matches Q9.

## G9 — Factor-level propagation gap: category ownership is complete, factor *surfacing* leaks

Full taxonomy-vs-skills sweep (2026-06-12). **All 27 categories have an owning skill** — no orphaned research, no un-skilled area. But ~10 categories are only *partially* surfaced at the **factor** level: a factor lives in `taxonomy.md` (often also in the skill's `heuristics.md`) yet never reaches a top-level inlined check, so it almost never produces a finding. The originating observation was that the suite emits **no naming findings** in practice despite #5 being owned.

Three mechanisms drive the leak:

1. **Router under-selection.** A lens only fires when `choosing-review-lenses` picks it, and the 2-4 cap means soft lenses run on few change shapes — `reviewing-naming-and-readability` appears in just **3 of ~20 routes** (feature, refactor, UI). On bug fixes, migrations, async, API, security, perf, LLM, config, and every repo audit it is never invoked. *(This is the router-intent problem — see Q14.)*
2. **Bundle + ~8-check budget.** Multi-category skills split a single ~8-check inlined budget, crowding out the junior category's factors: `#5 naming + #6 readability + #7 comments`, `#9 module + #10 type-modeling`, `#19 build + #26 config/portability`, `#18 deps + #27 compliance`.
3. **Severity trimming.** The synthesizer (D12) floats correctness/security to the top and ranks `Nit` last, so the readability class sinks and gets trimmed from the merged report even when produced.

**Dropped** (absent even from `heuristics.md`): `#12` scalability-of-the-design; `#12` feature-flag *architecture* (runtime flags are in #16; flag *design* is nowhere); `#15` cloud-cost / FinOps *(residual candidate)*; `#16`/`#27` telemetry-analytics privacy *(residual candidate)*.

**Thin** (heuristics-only or a single passing line, not a surfaced check): `#26` portability / environment assumptions (OS/arch, hardcoded paths, locale/encoding/timezone); `#16` SLO / error-budget instrumentation; `#6` symmetry of expression & altitude mixing; `#21` change-amplification & onboarding cost; `#24` agent-native parity & CODEOWNERS; `#9` caller ergonomics ("pit of success") & composition-vs-inheritance; `#4` numeric overflow / counter wraparound.

**Irony vs. G5.** Several of the thin factors — altitude, symmetry, naming quality beyond casing, agent-native parity, caller ergonomics — are *exactly* the ones G5 flagged as **build-here-first** because LLM judgment is the only tool that covers them. The propagation gap hit the highest-unique-value factors hardest: the parts of the map that most justify an LLM reviewer are the parts most likely to go silent.

**Fix surface** (spans three layers): the **manifest** (promote dropped/thin factors into inlined checks; rebalance the bundled-category budgets), the **research docs** (the two genuinely-missing #12 factors need research before they can be a check), and the **router** (stop the under-selection — Q14). Diff-shaped factors regenerate from the manifest; #12 scalability/feature-flag-design need a research pass first.

## G10 — The enforcement apparatus (and the meta-layer generally) was never framed as a reviewable surface

Surfaced 2026-06-12 chasing "where would *set up a vuln scanner* or *tidy up linter ignores* live?" The answer split three ways and exposed a **framing**-level gap deeper than G9's propagation gap:

1. **Tool-mechanization nudge — trivial, already latent.** Every lens carries `reference/tool-rules.md`; surfacing *"you detect this by hand — tool X gates it in CI, consider wiring it up"* is additive output and **advisory (not the Q8 fixing-mode)**. `auditing-config-and-build-hygiene` already does a version of it (*"fix it or swap in a maintained equivalent"*, `SKILL.md:39`). Action: a generator pass appends an optional `mechanize-with:` line to each lens's finding contract.
2. **Gate / enforcement health — already covered.** *"Is a quality gate disabled or soft-failed (`continue-on-error` / `|| true` / `allow_failure` / a skipped check)?"* is in the corpus (`cluster-5-verification.md` §19) **and** shipped (`auditing-config-and-build-hygiene/SKILL.md:39` + an eval; reinforced by `cluster-2:145` "presence and enforcement is itself the control" and `cluster-6:175` actionlint/required-checks). The "re-enable / provision the missing scanner" case is live.
3. **In-code suppression rot — a genuine research-corpus hole.** `# noqa` / `eslint-disable` / `# type: ignore` accumulation, blanket-disabled rules, growing lint baselines, suppressions with no rationale or expiry: **absent from `docs/research/` entirely**, owned by no skill. Falls between #8 (config conformance), #19 (gate config), and #21 (debt) — and because no category was shaped to attract it, it was never written.

**The structural lesson (the reason this matters beyond the example).** The map covers *artifacts*, their *properties*, and *mistake-detection*. It never framed **the enforcement apparatus itself** — the gates, suppressions, and tooling config wrapped around the code — as a first-class reviewable surface. Gate-health landed only because it fell incidentally inside #19; the code-level suppression residue had no home, so it went unresearched. Generalize:

> **A missing category does not yield a *thin* heuristic you can spot by auditing the skills (that is G9). It yields a *silent* hole — the factor is never written at all.** G9-class gaps are findable by diffing taxonomy ↔ skills; **framing-class gaps are invisible to that diff** and only surface by asking *"what kind of reviewable thing did we never put on the map?"*

This is precisely why a taxonomy-vs-skills audit can't be the gap-hunting method for framing gaps. It motivates a second from-first-principles research pass over *kinds of reviewable surface* — the **round-2 gap hunt** ([`research/taxonomy-gap-hunt-round-2.md`](research/taxonomy-gap-hunt-round-2.md)), seeded by the meta-layer and decision-lifecycle omissions this finding exposed (enforcement apparatus; documentation-as-designed-system; binary/generated artifacts; dependency *selection & exit* vs. mere patching; …).

**Resolved (2026-06-12, taxonomy v0.3 / D13):** the enforcement apparatus is now a first-class category — **#30 Enforcement apparatus & meta-artifacts** (suppression hygiene, monitoring-config-as-artifact, codegen↔source drift) — owned by the repo-shaped audit `auditing-enforcement-and-meta-artifacts` (research in [`research/cluster-5-verification.md`](research/cluster-5-verification.md) #30). The framing hole this finding named is closed.

## G11 — Artifact-authoring quality is a reviewable surface we hold ourselves to but never review

Surfaced 2026-06-12 (owner question: *do we have anything correlating to Anthropic's Agent Skill authoring best-practices guide?*). The answer split two ways and exposed a framing-class gap (the G10 kind — a *silent* hole, not a thin heuristic):

1. **As authors — fully covered.** The best-practices guide *is* **D7**, transcribed into our building standard and **enforced in the pipeline**: `tooling/manifest.py` validates `description` ≤1024 chars; `tooling/generate.py` inlines top checks (progressive disclosure), emits gerund names, one-level-deep bundled files, no time-sensitive text. The suite is a reference *implementation* of the guide.
2. **As a review lens — unowned.** Nothing reviews **someone else's** `SKILL.md` / agent definition *against* that standard. The two nearest touchpoints miss it: #24 "agent-native parity" is about the *product* exposing agent-reachable actions; #22/#24's `AGENTS.md`-as-doc-artifact (added 2026-06-12) covers only *drift* (is it still true?), not *authoring quality*.

**The generalization (the reason this matters beyond the example).** "Is this `SKILL.md` well-authored?" is one instance of a broad class: files that are **not application source** but carry their own canonical "well-formed X" standard and dedicated linter — Dockerfiles (hadolint), Terraform (tflint/Checkov), K8s manifests (kube-linter), CI workflows (actionlint/zizmor), OpenAPI specs (Spectral/Zally), ADRs, changelogs, `AGENTS.md`, model cards, datasheets, `SKILL.md`. The atlas *touches* several of these but always **folded into a topic cluster** (migrations→#20, IaC→#31, CI→#19, API specs→#13), never as a declared **artifact-scoped review shape** with presence-based activation. That missing slot is why the `SKILL.md` case had nowhere to land.

> **Generalize G10's lesson once more:** the map frames artifacts → properties → mistake-detection, and #30 framed the *enforcement apparatus* as reviewable — but neither framed **"is this artifact well-formed per its own published standard"** as a first-class, presence-activated review behavior spanning artifact *types*.

**Three distinct agent-surfaces** (this gap clarified that they're separate, which informs the Q16 call): runtime agent **security** (tool least-privilege, lethal trifecta) → Q16/#25; agent-facing **docs drift** (`AGENTS.md` stays true) → #22/#24; agent-artifact **authoring quality** (`SKILL.md` built to the guide) → **this gap, unowned.** Bundling authoring under a Q16 *security* category would blur the trigger.

**Disposition (resolved 2026-06-12).**

| Concern | Decision |
|---|---|
| "Is this artifact well-formed per its standard?" (the factor) | **→ #30 meta-artifact factor** (D15) — keeps #32 = runtime agent safety, #22/#24 = doc-drift; three distinct agent-surfaces stay separate. |
| *How* to host many artifact lenses without top-level context bloat (the pattern) | **→ a new `shape: artifact`** (D15, Q18 option b) — one entry-point lens + manifest `artifacts:` table + bundled on-demand rubrics; `SKILL.md`-authoring is the first instance. |

Full research — the artifact-standard catalog (the references beyond the one guide), the context-cost evidence (lost-in-the-middle, context rot, RAG-MCP, the 128-tool ceiling), the presence-based-activation prior art (MegaLinter/ESLint-overrides/Spectral), and the three hosting options — is in [`research/artifact-scoped-lenses.md`](research/artifact-scoped-lenses.md). **Status: gap logged + researched; both decisions made (D15, Q18 RESOLVED); build pending.**
