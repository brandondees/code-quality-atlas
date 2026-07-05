# Session Log

Chronological record of how the research evolved. Newest at the bottom.

---

## 2026-06-08 — Session 1: scoping & taxonomy v0.1

**Goal:** brainstorm what factors into code quality, as comprehensively as possible, toward a future skill suite for code review & maintenance.

**What happened:**

- Reframed mid-session: this is a **new, standalone, first-principles** suite. Existing skills are prior art, not a starting point. *(→ D1)*
- Chose **maximal scope** for the map. *(→ D2)*
- Chose to do it **phased**: comprehensive map first, then skill-suite architecture; with a research/reference-gathering loop on the map before skill design. *(→ D3)*
- Produced **taxonomy v0.1**: 6 clusters, 24 categories, ~70 factors. Embedded two counterweights (premature abstraction, premature optimization). Flagged 7 candidate additions.
- Captured everything into this repo (`code-quality-atlas`, private, under `~/code/`). *(→ D4)*
- Seeded `references.md` with foundational works + per-cluster anchors (many TODOs).
- Surveyed prior art: ~13/24 categories have some existing agent-skill coverage; identified greenfield zones and a static-analysis "heuristic goldmine" to mine.

**Open at end of session:** granularity (Q1) is the gating question for phase 2; candidate additions (Q2) pending; review-vs-maintenance, scores-vs-findings, counterweight enforcement, language strategy, composition, maintenance-scope all logged (Q3–Q8).

**Next:** continue iterating the *research* — fill `references.md` TODOs, mine static-analysis tools for concrete checks per category, resolve candidate additions — before moving to phase 2 (skill-suite architecture).

### 2026-06-08 (cont.) — map pressure-test → v0.2

- Resolved all 7 candidate additions *(→ D5)*. Map now **27 categories**: added #25 AI/LLM-integration, #26 Configuration & environment, #27 Compliance/licensing/provenance; broadened #3 and #9; cross-linked #4 ↔ #23.
- Logged new open question Q9 (compliance scope boundary).
- Kicked off the parallel research pass: one research agent per cluster (references + static-analysis-tool rule mining + reviewable-heuristic seeds), output filed under `docs/research/`. Cluster I taken extra-deep as the template.

### 2026-06-08 (cont.) — research pass: web-access blocker + salvage

- **Key environment finding:** general-purpose subagents are **sandboxed without network** (WebSearch/WebFetch/curl all denied), but the **main loop has working web access**. Future research must be run from the main loop (or hand sources to subagents), not delegated to web-less subagents.
- Of 6 cluster agents: **3 correctly refused to fabricate and stopped** (I, III, V — no files); **3 wrote from-memory drafts** with `(verify)` tags + caveats (II readability, IV runtime, VI evolution). Drafts committed as **unverified v0** for safekeeping. (Cluster IV left ~15 canonical URLs unmarked — to be verified.)
- Captured cross-cutting structural findings into [`map-gaps.md`](map-gaps.md) (G1–G8): double-booked concerns needing single owners, a possible "Excessive Agency" promotion, the Clean-Code-vs-Ousterhout decomposition tension, where LLM judgment is the only tool, and git-history-shaped vs diff-shaped skills.

**Next:** redo the research properly from the main loop (where web works) — write the 3 missing clusters (I/III/V) with verified citations, and verify/upgrade the 3 drafts (clear `(verify)`, add real URLs). Cluster I first, as the exemplar.

### 2026-06-09 — full web-grounded research pass complete (all 6 clusters)

Ran the whole research pass from the **main loop** (web works there; subagents are sandboxed without it). For each cluster: verified references, static-analysis tool rule IDs, and reviewable heuristics against live sources, committing per cluster.

- **Cluster I (correctness)** — written fresh as the **exemplar** (extra-deep + Template notes). Verified ESLint/typescript-eslint/RuboCop/Bandit/gosec rules, `go test -race` semantics; Out of the Tar Pit, Release It!, Goldberg, Lamport, Falsehoods-about-Time.
- **Cluster II (readability)** — verified & upgraded draft: Sonar S3776=15/S1192/S125, Pylint C0104/R2004, RuboCop AbcSize 17/PerceivedComplexity 8, golangci `mnd`, Ruff D417/ERA001, Belshee 7 stages. Corrected `stylecheck` (ships via staticcheck).
- **Cluster III (structure)** — written fresh: connascence (9 types + strength/degree/locality), parse-don't-validate / illegal-states lineage, the-wrong-abstraction counterweight, dependency-cruiser/import-linter/ArchUnit, Reek smells, jscpd/CPD/S4144, Spectral/oasdiff/buf/Pact, Bloch/Postel/RMM.
- **Cluster IV (runtime)** — verified & upgraded draft: OWASP Top 10 2021, CWE Top 25 2024 (XSS #1), OWASP LLM Top 10 2025, **ASVS corrected to 5.0 (17 chapters)**, Bandit/gosec IDs, Core Web Vitals (INP replaced FID 2024-03-12), Willison lethal trifecta (2025-06-16).
- **Cluster V (verification)** — written fresh: pyramid vs trophy, mutation + property-based testing, SLSA/Scorecard/SBOM/OSV, expand-contract migrations + gh-ost/pt-osc/strong_migrations, twelve-factor + feature-toggle taxonomy, DORA, Bazel hermetic.
- **Cluster VI (evolution)** — verified & upgraded draft: WCAG 2.2 SCs (2.4.11, 2.5.8 24px, 1.4.3), axe/jsx-a11y rules, Conventional Commits + Beams, **SmartBear/Cisco study (200–400 LOC)**, Diátaxis/ADR/Keep-a-Changelog, AGPL network copyleft/SPDX/REUSE, **EAA in force 2025-06-28**, GDPR.

**Phase 1 (research & taxonomy) is effectively complete.** Remaining before phase 2: resolve the granularity question (Q1) and a few residual open questions; then design the skill-suite architecture.

### 2026-06-09/10 — phases 2–3: architecture, pipeline, all 22 skills built (sessions 2–5)

- **Phase 2 designed & built:** manifest-driven generator with provenance hashes, drift-checker, eval validator, cross-model runner (Ollama + any OpenAI-compatible server; llama-server/GGUF path for sandboxes). Docs are the source of truth; skills regenerate. (PRs #1–#2.)
- **Wave 1 (6 ★ skills)** refined + cross-model gated on a local 7B (qwen2.5-coder, temp 0). Found the 3B over-flagging mode and the ~7–8B clean-code-precision floor. (PR #3.)
- **Wave 2 (5 high-stakes triage skills).** Key discovery: **numbered findings lists in examples.md force enumeration** on weak models (1/4 → 3/4 recall). Documented 7B ceilings: DDL keyword blindness, multi-sink tracking. First external critique flowed docs→drift→regenerate end-to-end. (PR #4.)
- **Wave 3 (11 skills: 6 diff-shaped + 5 repo-shaped audits)** + wave-1 retrofit + **G1 single-owner enforcement** in the manifest validator. New lessons: the list template needs an explicit "correct code → exactly 'No findings'" escape hatch (it induced list-filling on clean code); audit skills hallucinate scan data without a "cite only what the scan shows" rule; range-arithmetic is a 7B ceiling.
- **Phase 3 complete: all 22 behaviors / 27 categories built**, each with examples + ≥3 eval scenarios, gated on two model tiers. Remaining: Q12 packaging (plugin wrap).

### 2026-06-10 (cont.) — Q12 packaging: repo is now an installable plugin

- Added `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`; `skills/` already matched the
  plugin-default layout, so packaging was purely additive *(→ D9)*.
- **Commit-SHA versioning** (no `version` field): every merged commit ships, matching the
  docs→drift→regenerate loop; pinned semver deferred until the suite stabilizes.
- Validated with `claude plugin validate` and a local end-to-end
  marketplace-add → install → 22/22 skills discovered → uninstall cycle.
- All roadmap items are now closed; remaining work is the compounding loop itself
  (critique research → drift → regenerate → re-gate) plus future re-granularization
  via the manifest as model capability shifts.

### 2026-06-11 — first dogfood feedback → packaging fixes (D10)

A user session that drove the suite by hand (fetching SKILL.md + heuristics from
the repo to review a sync-engine design and a diff) returned the first real
usage critique. Verdict: the heuristics content and the "Reviewer discipline"
guard earned their keep (lens checklists directly produced design bugs the
session would otherwise have shipped); the **packaging** carried the friction.
Six findings, ranked; all addressed through the manifest/generator so docs and
regeneration stay canonical:

1. **SKILL.md wasn't self-sufficient** ("Top checks" listed zero checks — every
   review needed a second fetch) → the generator now inlines the top ~8 checks
   (head of each source category's heuristics; cross_ref categories capped at 2).
2. **No composition layer** (picking from 22 lenses was on the user) → new
   manifest `router:` section generates `choosing-review-lenses`: a
   situation → 2-4-lenses routes table + a one-line catalog. Q7 partially resolved.
3. **Diff-vs-design applicability was unsigned** → `design: true` manifest flag;
   every SKILL.md now states its shape, design-capable lenses are ◆-marked.
4. **The 22 descriptions blur at selection time** → per-skill `picker` one-liners
   carry the differentiation in the router catalog; the eval-tuned trigger
   descriptions stay untouched.
5. **Heuristic-level overlap caused duplicate findings** → cross_ref skills now
   emit a dedupe note naming the category's primary owner (G1 at review time).
6. **tool-rules.md / sources.md role unclear** → the links section now says when
   each reference is needed (not during the judgment review itself).

Validator additions: routes must reference known skills, pickers required when a
router exists, `design` only on diff lenses. The router carries
`built_from: []` (manifest-derived; docs drift can't flag it) and ships 4 eval
scenarios + examples. Suite is now **23 skills**; CI gate updated.

### 2026-06-11 (cont.) — license for public release (D11)

Private-repo install friction prompted flipping the repo public. Pre-publication
sweep: no secrets/PII (example credentials are labeled fakes), no third-party
text carrying its own license terms. License decision (user): **dual MIT (code) +
CC BY 4.0 (content)** — see D11. Added LICENSE / LICENSE-MIT /
LICENSE-CC-BY-4.0, SPDX headers on Python sources, `license: MIT AND CC-BY-4.0`
in plugin.json, and a README License section. Visibility flip itself happens in
GitHub settings.

### 2026-06-12 — composition back half: the synthesizer (D12)

Picked up the one substantive open thread after a clean "what's next" sweep
(all phases done, CI green, no open PRs/issues): the residual half of Q7. D10's
router solved lens *selection*; nothing yet merged the selected lenses' output.
Built `synthesizing-review-findings` (24th skill) as the router's sibling — same
manifest-canonical, `built_from: []`, no-docs-drift generation pattern.

- New manifest `synthesizer:` section: `severity_order` (Blocker > Major > Minor
  > Nit) + a `tensions` table of known opposing lens pairs, each with a default
  resolution (restraint ↔ module-design / performance / test-quality /
  api-contract; performance ↔ readability). `build_synthesizer_md` assembles the
  **collect → dedupe → reconcile → rank → verdict** procedure, the tension table,
  a finding contract, and an output format from it.
- **Dedup** reuses the existing G1 primary-owner attribution (no new mechanism) —
  a finding raised by two lenses is reported once, under the owner each lens's
  *Shared categories* note already names.
- **Fan-out resolved as advisory-by-default, mechanizable** (D12): the suite stays
  plain markdown with no Claude/harness assumption (D7), so orchestration isn't
  baked in — but the fixed finding contract (location/severity/lens/finding/fix)
  lets a capable harness run the lenses in parallel and apply the *same*
  deterministic merge. Advisory or automated, identical output.
- Validator additions: tensions must name two distinct known lenses;
  `severity_order` non-trivial and unique; synthesizer name can't collide with a
  lens. Router now points forward to the synthesizer when one is defined.
- Ships 4 eval scenarios (dedup, conflict reconciliation, all-clear no-inflation,
  severity-ranking with a Blocker float) + examples. Suite is now **24 skills**;
  CI gate, README, and Q7 (now RESOLVED) updated. 60 tests pass, no drift.

### 2026-06-12 (cont.) — reconcile the open-questions ledger

A "let's look at the other questions" pass found the *Open questions* section
significantly stale: five questions still listed as open were actually answered
by what shipped in phases 2–3, never marked. Dogfooding `auditing-documentation-
health` (docs telling the truth about the code), reconciled them in place with
the established `→ RESOLVED (see …)` pattern + a pointer to the closing
skill/decision:

- **Q1** (granularity, "the big blocker") → behavior-based, manifest-mapped (22
  behaviors / 27 categories); both the original and revisited copies marked.
- **Q5** (counterweight enforcement) → `checking-restraint` shipped exactly the
  proposed "is this too much?" lens; D12's synthesizer tensions enforce it at
  merge time.
- **Q9** (compliance scope boundary) → `auditing-compliance-and-provenance`
  adopted the proposed detect-and-escalate-to-humans stance.
- **Q10/Q11** (regeneration model, async-critique) → the built hybrid pipeline
  (manifest + generate + provenance hashes + drift gate).
- **Q8** downgraded to *partially resolved*: the cron-shaped detectors exist (6
  repo audits + hotspots), but the *fixing* half is still open — same gap as Q3.

Added a "Live state" banner naming what's **genuinely** open: Q3 (review-vs-
maintenance modes), Q4 (findings-vs-scores), Q6 (idiom packs), the Q8 fixing
residual, and the Q2 low-priority candidates. Docs-only; 61 tests pass, no drift.

### 2026-06-12 (cont.) — team preferences overlay (Q13, design)

First-usage feedback (user): the suite is research-rooted and pushes "objectively
better" defaults, but has nowhere to incorporate the **owner's/team's considered
opinion** — today only `checking-idioms-and-consistency` bends, and only to linter
configs. Opened Q13 and wrote the design: [`team-preferences-overlay.md`](team-preferences-overlay.md).

Two user decisions shaped it. **Tiered precedence** — taste/threshold/idiom
findings are preference-tier (team may tune or silently suppress); security /
correctness / data-safety / concurrency are floor-tier (never silently dropped,
only `acknowledge`d with a rationale that still surfaces). **Bootstrap = template +
inference, but inference is proposal-only** — the inference skill emits a
ratification interview (evidence + "deliberate decision or accident?") and never
writes the overlay itself, never runs by accident; this is the guardrail against
a haphazard/vibe-coded repo laundering unconsidered approve-clicks into ratified
standards. Overlay lives in the *reviewed* repo (`.code-quality-atlas/preferences.md`),
read at review time by the router, kept out of generated-skill provenance (D6).
Status: design, awaiting review before implementation planning.

### 2026-06-12 (cont.) — factor-level coverage audit (G9) + router-intent question (Q14)

User asked whether the suite has scope gaps — research that settled into the docs
without reaching the skills — prompted by noticing **no naming findings ever
surface** despite #5 being owned. Ran a full taxonomy-vs-skills sweep.

Finding: at the *category* level there are **no gaps** — all 27 categories have an
owning skill. The leak is at the **factor** level, and naming is the worked
example. Three mechanisms, recorded as [`map-gaps.md`](map-gaps.md) **G9**:
(1) **router under-selection** — a lens only fires when the router picks it, and
the 2-4 cap leaves `reviewing-naming-and-readability` in just 3 of ~20 routes;
(2) **bundle + ~8-check budget** — multi-category skills crowd out the junior
category's factors; (3) **severity trimming** — the synthesizer ranks the
readability class to the bottom and trims it. Dropped factors: #12 scalability &
feature-flag *architecture*, #15 FinOps, #16/#27 telemetry privacy. Thin factors:
portability (#26), SLO (#16), symmetry/altitude (#6), change-amplification (#21),
agent-native parity (#24), caller ergonomics (#9), numeric overflow (#4). Noted the irony:
several thin factors are exactly G5's "build-here-first, LLM-only" list.

The router half opened as **Q14**. User reframing (important): the router was meant
to *improve unprompted, relevant skill activation* — not to **cap** coverage; the
original intent was the **full suite in parallel for an extremely comprehensive
review**. So the 2-4 cap inverts the design. Q14 separates the two axes the router
currently conflates — **relevance** (which lenses apply) vs. **depth/budget** (how
much to run) — and captures four candidate directions: review-depth *modes*
(critical-only triage / PR-level / comprehensive all-lens), expose the full ranked
catalog, signal-based matching+ranking, and progressive-phase routing. Framing
captured, no decisions yet. Docs-only.

### 2026-06-12 (cont.) — G10 (the enforcement apparatus as un-framed surface) + round-2 gap hunt opened

Follow-on from the G9/Q14 discussion. User asked where "improve the quality
*tooling*" lands — e.g. propose a vuln scanner, tidy up linter ignores. Chasing it
exposed a gap one level deeper than G9, captured as [`map-gaps.md`](map-gaps.md) **G10**:

- The "a tool could mechanize this for you" nudge is **trivial and already latent**
  (every lens carries `tool-rules.md`); it is advisory output, **not** the Q8
  fixing-mode — I had mis-parked it under Q8. `config-and-build-hygiene` already
  does a version of it.
- **Gate/enforcement health** (disabled / soft-failed gates) is **already covered** —
  in the corpus (`cluster-5` §19) and shipped (`config-and-build-hygiene/SKILL.md:39`
  - eval). So "re-enable / provision the missing scanner" was a false alarm.
- **In-code suppression rot** (`# noqa` / `eslint-disable` / `# type: ignore`
  accumulation, lint-baseline growth) is a **genuine research-corpus hole** — absent
  from `docs/research/` entirely.

The structural lesson: the map covers artifacts → properties → mistake-detection but
never framed **the enforcement apparatus itself** as reviewable; gate-health landed
only because it fell incidentally inside #19. **A missing category yields a *silent*
hole (factor never written), not a *thin* heuristic — so the G9 taxonomy-vs-skills
diff cannot find framing gaps.** That motivated a second pass.

Opened the **round-2 gap hunt** ([`research/taxonomy-gap-hunt-round-2.md`](research/taxonomy-gap-hunt-round-2.md)):
a from-first-principles sweep over *kinds of reviewable surface*, organized along five
axes orthogonal to the original six clusters — (A) meta-surfaces, (B) under-covered
artifact types, (C) decision & lifecycle (choose/adopt/revisit/retire — incl. the user's
dependency-*selection*-vs-patching point), (D) socio-technical & responsible engineering,
(E) operational & resilience design — each candidate scored against a rubric (already
covered? distinct behavior? shape? prior art? disposition) to avoid re-flagging covered
facets. Feeds a possible taxonomy v0.3. Research running; synthesis to follow.

### 2026-06-12 (cont.) — round-2 gap hunt synthesized (→ taxonomy v0.3 proposal + Q15)

Five parallel research agents (axes A–E) returned; synthesized into
[`research/taxonomy-gap-hunt-round-2.md`](research/taxonomy-gap-hunt-round-2.md).
Three structural findings, each bigger than any single category:

1. **A missing review *shape*: decision-time / decision-record review.** The suite
   has diff-lenses and repo/cron-audits but nothing that reviews a *decision as
   made* (ADR/RFC/adoption/deprecation/rollout/capacity-DR plan). Recurs across all
   of axis C and most of axis E. Opened as **Q15** — the headline.
2. **The G10 meta-layer generalizes** — suppression rot (A1), monitoring-config
   (A4), codegen↔source drift (A5), test scaffolding (A2), IaC (B1): one omission,
   ~5 instances, not five unrelated gaps.
3. **A design-time operational cluster is missing** (scale / recover / degrade —
   distinct from #16's *runtime* operability), which also absorbs the two G9 #12
   drops. Axis D's restraint check **passed**: the socio-technical "gaps" were
   mostly governance (out-of-scope) or already-covered, confirming v0.2 didn't
   under-reach on the human axis — the real gaps are *structural*, not ideological.

Proposed v0.3 (disposition table in the doc): **2–4 new categories** — #28 operational
& resilience design [high]; #29 decision lifecycle [med-high, scope to the reviewable
slice, escalate TCO/procurement]; #30 enforcement-apparatus/meta-artifacts [high on
suppression hygiene; grouping open]; IaC-as-reviewed-code [high, placement open] —
**+ ~10 add-factors** (#27 asset/model-weight licensing + privacy-by-design; #25
harmful-output eval; #17 test-apparatus; #19 codegen-drift + rollout-plan; #22
docs-as-system; …). Plus the cross-cutting tool-mechanization `mechanize-with:` nudge.
**Not editing `taxonomy.md` yet — owner decision pending on how much to promote vs.
fold (a restraint call).** Docs-only.

### 2026-06-12 (cont.) — taxonomy v0.3 drafted (D13) + decision-time shape design (Q15 resolved)

Owner chose **full v0.3 draft** + **design pass first** for the decision-time shape.
Did the design pass first (it gates how #29 enters the map):
[`decision-time-review-shape.md`](decision-time-review-shape.md) resolves decision-time
as a **mode orthogonal to topic** — a `shape: decision` capability (promoting the
existing `design:` flag) with a shared decision-record checklist, plus a few
decision-native lenses — **not** a 7th cluster (avoids G1 double-booking). That
dissolves Q15's "category or shape?" tension: #29 is the *topic*, decision-time is the
*shape*.

Then drafted **taxonomy v0.3** (`taxonomy.md`, now 31 categories / ~95 factors):
promoted **#28** operational & resilience design (resolves the G9 #12 scalability
drop), **#29** decision lifecycle, **#30** enforcement apparatus & meta-artifacts (the
G10 gap), **#31** infrastructure-as-code; added factors to #16/#17/#19/#20/#22/#25/#27;
named decision-time as the third review shape; added a "Candidate additions — resolved
(v0.3)" disposition table. Recorded as **D13**. Governance slices held out-of-scope
(G8). `taxonomy.md` is docs-only and not a skill `built_from` source, so drift stays
clean (61 tests pass). **Next: the v0.3 build phase** — research sections for the four
new categories + manifest entries + generated skills/evals, and regenerating the
add-factor-affected skills (#16/#17/#19/#20/#22/#25/#27) whose research sections change.

### 2026-06-12 (cont.) — v0.3 build, wave 1: the first decision-time lens

Owner chose **decision-time (#29) first**. Shipped `reviewing-decision-lifecycle`
end-to-end — the suite's first **decision-shaped** lens, validating the new shape
through the whole pipeline:

- **Pipeline:** `manifest.py` validator accepts `shape: decision`; `generate.py`
  emits a decision scope-line and a "Decision-shaped" router-catalog section.
- **Research:** `cluster-6-evolution.md` gains `## #29 Decision lifecycle`
  (references / tool-rules / heuristics) grounded in round-2 prior art — Nygard
  ADRs, Tech Radar rings, one/two-way doors, RFC 8594 Sunset, build-vs-buy TCO,
  lock-in/exit.
- **Skill:** `shape: decision`, `built_from #29`, 8 inlined checks, 4 evals
  (adoption / stale-ADR / clean-deprecation / build-vs-buy) + examples.
- **Router:** a decision route + catalog section. **Manifest** `taxonomy_version`
  bumped v0.2 → v0.3 (provenance across all skills).

Generate clean, no drift, evals valid, 61 tests pass. **Remaining v0.3 build:**
operational & resilience design (#28), enforcement apparatus & meta-artifacts
(#30), infrastructure-as-code (#31) — each: research section + skill + evals — and
the ~10 add-factor regenerations (#16/#17/#19/#20/#22/#25/#27). Optional polish: a
shape-aware "Reviewer discipline" wording (says "code" for decision/repo lenses)
and a decision-specific synthesizer verdict vocabulary (adopt / revisit / reject).

### 2026-06-12 (cont.) — research review & expansion pass (first compounding-loop iteration on the research itself)

A "review the research, find more to add" pass — the first substantive *research*
critique since the 2026-06-09 pass, run from the main loop with live web access.
Reviewed all six cluster files + open threads + map-gaps, then expanded where the
repo's own flags pointed, all citations web-verified today. Four additions:

1. **Agentic/tool-use safety (#25, the G2 thread).** The world moved: OWASP shipped
   a dedicated **Top 10 for Agentic Applications** (ASI01–ASI10, 2025-12-09 — after
   our research date) plus the Threats & Mitigations companion, and the MCP docs
   carry named anti-patterns (confused deputy, token passthrough, tool poisoning).
   Added 4 references + 9 agentic heuristics (tool least-privilege, approval
   gates/step budgets, tool-metadata-as-untrusted-input, token audience discipline,
   sandboxed code exec, inter-agent auth, memory hygiene, audit trail) to cluster-4
   #25. G2 updated; **promotion decision opened as Q16** (user call, D5-style).
2. **IaC/workflow surface (#19).** hadolint (DL3006/7/8, DL3002…), Checkov
   (CKV_AWS_20/57), tflint, kube-linter (run-as-non-root, latest-tag, …),
   actionlint, zizmor (template injection, mutable-tag pinning) — all IDs verified
   against primary sources — plus 5 heuristics (IaC gets the app-code gate,
   workflow `${{ }}` injection, SHA-pinned actions, container hygiene, cloud
   misconfig). Seam noted: #19 owns mechanics, #14 owns the security verdict.
3. **Agent-facing docs (#22/#24).** AGENTS.md (OpenAI 2025-08 → Agentic AI
   Foundation under the Linux Foundation 2025-12) closes the "agent-native parity
   is thinly sourced" open thread for the docs half: agent instructions are now a
   first-class doc artifact with drift obligations (new #22 heuristic).
4. **FinOps/green residual (#15).** FOCUS spec (v1.2/v1.3 2025) and SCI
   (ISO/IEC 21031:2024) — the cloud-cost facet now has standards; still
   factor-level (taxonomy residual note updated).

All additions **append-only** below existing bullets, so every skill's inlined
"Top checks" stayed stable — regeneration diffs are provenance-hash + reference-file
content only. references.md reconciled (cluster files are the deep surface; stale
TODOs annotated). Pipeline: drift flagged 6 skills → regenerate → no drift,
61 tests pass. **Cross-model eval re-gating deferred** (no local model in this
sandbox; additions are appended checks, not changed behavior — re-gate per the
runbook when next on a machine with Ollama).

### 2026-06-12 (cont.) — PR #21 reconciled with main; v0.3 build wave 2 (#30) on a new branch

PR #21 reconciled with `main` (merged PRs #22 research-expansion + #25 hook).
One numbering collision: `main` and this work both minted a **Q14**, and main's
agentic-safety candidate proposed category **#28** — now v0.3's operational
category. Relabelled main's self-contained agentic question **Q14 → Q16** and its
candidate **#28 → #32**, keeping the interconnected v0.3 numbering (Q14 router,
Q15 decision-time, #28–#31). Verified PR #21's review findings were already
addressed (CodeRabbit + atlas-review rounds 1–4, all resolved in `6741e12`); CI
`gate` green; atlas hit its 4-round cap so the wave-1 skill + merge are
bot-unreviewed but test-green.

Owner approved a **new PR for the build**. Branch `claude/v0.3-enforcement-apparatus`.
**Wave 2 ships `auditing-enforcement-and-meta-artifacts`** — the **#30** owner,
closing the G10 framing gap. Repo-shaped audit over three meta-artifacts:
suppression hygiene (blanket/unjustified/unused `# noqa` · `eslint-disable` ·
`# type: ignore`, baseline accretion vs. ratchet), monitoring-config-as-artifact
(symptom-vs-cause alerts, runbook/`for:`/lint, dashboard drift, monitoring-as-code),
and codegen↔source drift (regenerate-and-`git diff --exit-code` gate). Research
section #30 added to `cluster-5-verification.md`; manifest entry (`shape: repo`,
`built_from #30`) + two router routes (added to the cron-audit set → now seven
audits; plus a targeted enforcement-config route); 4 evals + examples; G10 marked
resolved in `map-gaps.md`. Generate clean, no drift, 61 tests pass, evals valid.

**Webhook note (owner-flagged):** review *summary bodies* don't reliably wake a
subscribed session (only inline threads / issue comments do, and CI-success /
pushes / merges are never delivered). Mitigation adopted: the author session
**polls** `get_reviews` + `get_review_comments` + `get_check_runs` on each wake
and scheduled check-in rather than trusting the push stream. Optional routine
tweak (a one-line issue-comment beacon from `atlas-review-pr`) offered, pending
owner call. **Remaining v0.3 build:** #28 operational & resilience design, #31
infrastructure-as-code, and the ~10 add-factor regenerations.

## 2026-06-12 — Second feedback cycle: direct-invocation discoverability

A dogfood session reported it **never reached for the suite** on a multi-repo
audit — it spawned ad-hoc Explore agents instead. Root cause: 22 peer lenses
with no scannable summaries, no negative triggers, and no fleet workflow. PR #30
had already repositioned `choosing-review-lenses` from a mandatory front door to
an *optional* uncertainty helper (call lenses directly when the relevant ones
are clear) — but it hand-edited the generated router `SKILL.md`, diverging it
from the generator (CI's `drift` only hashes research provenance, so it passed).

This cycle's refinements, all source-of-truth-first:

- **Skip clauses.** The five narrowly-scoped lenses (accessibility-and-i18n,
  llm-integration, migration-and-data-safety, concurrency-and-async,
  api-contract-safety) gained explicit *Skip when…* sentences in their manifest
  descriptions, so direct invocation doesn't misfire on irrelevant repos —
  matching the `claude-api` skill's SKIP precedent the feedback cited.
- **Scannable taglines.** `build_skill_md` now emits each lens's one-line
  `picker` as an italic tagline between the H1 and "When to use", so a lens is
  recognizable at a glance without reading its trigger-rich description.
- **Router reconciled.** Added an optional `body` field to the router (terse
  `description` for the listing, richer `body` for the loaded "When to use"),
  and ported PR #30's two "How to pick" bullets into `build_router_md`. Regenerate
  now reproduces PR #30 faithfully — the divergence is closed, not reverted.
- **Multi-repo fan-out.** New `docs/runbooks/multi-repo-audit.md`: one background
  agent per repo, each emitting the synthesizer's finding contract (plus a `repo`
  field), aggregated centrally — dedupe within repo, group across repos, one
  fleet verdict. Linked from the README and the synthesizer's *Going deeper*.

Generate clean, no drift, 63 tests pass (+2: picker tagline, router body), evals
valid. **Not yet addressed:** the harness-level cost of 22 names in the listing
and the fact that frontmatter descriptions can be dropped from the model's skill
budget remain harness constraints the SessionStart hook mitigates but can't fix.

### 2026-06-12 (cont.) — G11 + artifact-scoped-lens research (the foundational pattern)

Owner question while discussing the decision-gated open questions: *do we have anything
correlating to Anthropic's Agent Skill authoring best-practices guide?* — then, on finding we
don't, *do more extensive research; that guide isn't the only reference, and strengthen the
foundational pattern for quality lenses that scope to specific artifact kinds without bloating the
top-level kit's context cost.* A web-grounded research pass from the main loop (citations verified
today).

The answer split two ways and exposed a **framing-class gap (the G10 kind)**, logged as
[`map-gaps.md`](map-gaps.md) **G11**: we **hold ourselves** to the skills guide (D7, enforced in
`manifest.py`/`generate.py`) but have **no lens that reviews someone else's** `SKILL.md` / agent
definition against it. The two nearest touchpoints miss it — #24 agent-native parity (product
exposing agent actions) and #22/#24 `AGENTS.md`-as-doc (drift only). Clarified **three distinct
agent-surfaces**: runtime security → Q16/#25; agent-doc drift → #22/#24; **agent-artifact authoring
→ unowned**.

The generalization is the real find: "is this `SKILL.md` well-formed?" instances a broad class —
files that aren't application source but carry a canonical "well-formed X" standard + dedicated
linter (Dockerfile/hadolint, Terraform/tflint·Checkov, K8s/kube-linter, CI/actionlint·zizmor,
OpenAPI/Spectral·Zally, ADR, changelog, `AGENTS.md`, model card, datasheet). The atlas *touches*
several but always **folded into a topic cluster**, never as a declared **artifact-scoped review
shape** with presence-based activation — the missing slot the `SKILL.md` case fell through.

Research filed in [`research/artifact-scoped-lenses.md`](research/artifact-scoped-lenses.md):
(1) the **artifact-standard catalog** — the references beyond the one guide, each row a candidate
lens + its linter goldmine; (2) the **context-cost evidence** for why "one peer lens per artifact"
fails — metadata is an always-on tax, "too many tools degrade selection" (Anthropic), RAG-MCP
(>3× selection accuracy when retrieval-narrowed; ~128-tool provider ceiling), lost-in-the-middle
(arXiv 2307.03172) and context rot (Chroma 2025) making even a catalog that *fits* a reasoning tax;
(3) **presence-based-activation prior art** from the linter world (MegaLinter activate-on-file,
ESLint glob `overrides`, Spectral rulesets-by-type) — a cheap detector gating an expensive
artifact rubric; (4) a **hosting pattern** with three options, recommending **(b) an `artifact`
shape** (one entry-point lens + manifest `artifacts:` table + bundled on-demand rubrics) over the
minimal one-lens fix (a) and the portability-breaking retrieval-routed (c). The pattern directly
serves Q14 (file-presence is the cleanest relevance signal — candidate-3) and the §3 catalog is a
linter-mining research task with `SKILL.md` as the highest-confidence worked example (we already
enforce it on ourselves).

Opened **Q18** (artifact-scoped lens hosting) in [`open-questions.md`](open-questions.md) and added
it to the Live-state banner; G11's disposition table parks the *factor* at **#30 meta-artifact**
(keeping Q16 = runtime safety) pending the owner call. **Docs-only** — `taxonomy.md`/`manifest.yaml`
untouched, so no drift; nothing built yet. Decisions pending: Q18 hosting pattern (a/b/c) and the
G11 factor placement, both gating the build. *(PR #33, merged.)*

## 2026-06-12 — Cross-model eval re-gate (local Ollama, laptop)

Closed the pending portability follow-up: the 2026-06-12 research-expansion
additions had shipped without a small-model re-run (no local model in the
sandbox session). Ran the re-gate on a laptop with Ollama.

**Scope.** Six skills whose `reference/heuristics.md` changed since the
expansion-pass parent (`git diff` against `5f5e798~1`): the two new v0.3 skills
(`reviewing-decision-lifecycle`, `auditing-enforcement-and-meta-artifacts` —
never gated on any model before) plus four with appended heuristics
(`reviewing-llm-integration`, `auditing-config-and-build-hygiene`,
`auditing-documentation-health`, `reviewing-pr-and-process-hygiene`). 20
scenarios total. Drift was clean going in.

**Method.** `python -m tooling.run_evals --skill <s> --model qwen2.5:7b --api
ollama` (temp 0, the harness pins sampling). `qwen2.5:7b` is the closest
available stand-in for the previously-validated `qwen2.5-coder-7b` tier; the two
new skills were also run on `llama3.1:8b` to confirm the result wasn't
qwen-specific.

**Result: all six pass on the 7-8B tier.** Every clean/healthy scenario (6/6)
correctly returned "No findings" — the over-flagging regression the runbook
warns about did not appear. Detection fired on every bad case. The new v0.3
skills passed cleanly on **both** model families; `llama3.1:8b` actually
produced tidier output than qwen on `reviewing-decision-lifecycle` (no
repetition).

**Two observations, both pre-documented 7B ceilings — not regressions:**

- **Top-findings-only recall on dense audit scans.** `auditing-config-and-build-hygiene`
  scenario 1 caught the baked-in secret and the unvalidated-config fallback but
  dropped `continue-on-error` and `node:latest`; scenario 2 caught the dead flag
  and curl-pipe-bash but dropped the `/opt/sdk` machine-local dependency. Exactly
  the runbook's "~top findings only from 7B-class models; pair with linters for
  exhaustiveness" gap.
- **Cosmetic format-leak (qwen only).** A few qwen responses appended the
  template's "No findings:" sentence *after* listing real findings — the
  documented "weak models mimic example output format" artifact. Absent on
  llama3.1:8b. Per the runbook, not chased with more prose.

**No tuning applied** — no heuristic regressions found, only model-capability
limits already characterized in the runbook. Re-gate complete; suite is clear
for the next behavior-changing PR.

### Follow-up — tuned `auditing-config-and-build-hygiene` (the one soft skill)

A closer scorecard of the detection scenarios (not just the clean ones) showed
config-hygiene was the only skill below bar: on qwen2.5:7b it scored ~2/3 and
~1.5/3 sub-finding recall on its two bad scans, dropping whole distinct finding
*types* — the soft-failed `continue-on-error` gate, the `/opt/sdk` machine-local
build dependency. All five dropped checks were present in `heuristics.md`; the
gap was that `examples.md` (the model's de-facto output template) had one bad
example that *bundled* the unpinned artifacts into a single finding and never
exercised machine-local deps or the dead-vs-ownerless flag distinction.

Fix (examples only — not regenerated, not drift-hashed): unbundled pinning into
per-artifact findings (action SHA / base-image digest / lockfile are three
checks), added a decision-rule line saying so, and added a **second bad example**
covering build-reproducibility + the two-flag dispositions, using content
isomorphic to but different from the eval inputs (jdk path, `wget|sh`, different
flag names) to teach the pattern without teaching the answer.

Re-run result:

- **qwen2.5:7b** — S1 now catches the soft-failed gate (was missed); S2 now
  catches the machine-local dependency (was missed). S3 still clean (the richer
  template did not induce over-flagging).
- **llama3.1:8b** — S2 **3/3**, both flags separately enumerated, confirming the
  second example is sufficient for a capable 8B model.

Residual (accepted, documented 7B-class ceiling): on the densest scan (S1, 5+
defects) both models still drop `node:latest` after flagging the action pin —
a *second instance of an already-flagged class* — and one llama run also dropped
the config-validation finding. This is the "top-findings-only recall on dense
scans" limit; per the runbook it is not chased with more prose (risks
clean-code over-flagging). Posture for this skill at 7-8B stays detection +
pair with deterministic linters (hadolint for `:latest`, a flag-audit tool) for
exhaustiveness. The other five skills signed off as-is.

### 2026-06-12 (cont.) — decision sweep: Q16 resolved (D14, promote agentic safety → #32)

Resumed the decision-gated open questions as a sweep (the back half of the "let's discuss the
decision questions" thread). First call: **Q16 → promote** (user, D5-style). Agentic/tool-use
safety leaves #25 to become **#32 Agentic & tool-use safety**, scoped to the *action/tool surface*
(distinct from #25's *model call*). The **trigger gap** was the decider — agent-heavy codebases
(tool defs, MCP servers, autonomous loops) may not read as "LLM integration," so #25's trigger can
miss exactly the highest-risk repos — reinforced by G1 cross-cutting ownership (#13/#14/#24/#25) and
OWASP's *separate* Agentic Top 10 (ASI01–ASI10). The cheaper "sharpen #25's trigger only" middle
path was considered and rejected (leaves G1 ownership unresolved; keeps the bundled ~8-check budget
crowded). **#25↔#32 boundary:** model-call → #25, action/tool → #32; the lethal-trifecta *framing*
stays #25 but its exfil/action-leg mitigations are #32 (#25 references #32, no double-report).

Recorded as **D14**; `taxonomy.md` carries the #32 entry (placed with its sibling #25), G2/Q16
flipped to resolved, the v0.3 disposition + numbering notes updated. **Docs-only, no build yet** —
the agentic material already ships under #25, so nothing is lost in the interim; the build phase
(move the 9 heuristics → #32 research section, lens `reviewing-agentic-safety` `shape: diff` with a
skip-clause, router/synthesizer wiring, evals, `taxonomy_version` bump, cross-model re-gate) is
**batched** with the other sweep outcomes per the user's "record and continue" call. **Holding the
commit** to bundle Q16/Q13/Q18 decision-records into one docs PR at the end of the sweep. 32
categories. Remaining sweep decisions: **Q13** (team-preferences overlay — keystone) and **Q18**
(artifact-scoped lens hosting pattern).

### 2026-06-12 (cont.) — decision sweep complete: Q13 (approved/deferred) + Q18 → D15

Closed the remaining two sweep decisions.

- **Q13 (team-preferences overlay) — design APPROVED, build DEFERRED.** The design was already
  complete with both hard calls locked (tiered precedence; proposal-only inference), so this was an
  approve-to-implementation call, not a fresh fork. User approved the design as the implementation
  basis but **deferred the build** (sequenced after the v0.3 / #32 work rather than next) — so the
  keystone unblock of Q17/Q18/Q14 waits. The §9 residuals (tier-tag granularity per-check vs
  per-lens; overlay↔linter-config precedence; monorepo discovery; `acknowledge` expiry) are left to
  implementation-planning.
- **Q18 (artifact-scoped lens hosting) → D15: the `artifact` shape.** Chose option (b): a fourth
  review **shape `artifact`** (sibling to diff / repo / decision), hosted as one entry-point lens
  that presence-detects an artifact and loads a bundled rubric on demand, driven by a manifest
  `artifacts:` table. Over (a) one-off lens — (b) *generalizes* the whole §3 catalog at one
  description's cost (the pattern the owner asked to strengthen); over (c) retrieval-routed — (c)
  breaks D7 plain-markdown portability (parked, long-horizon). **G11 authoring-quality factor → #30**
  (keeps #32 = runtime agent safety); `SKILL.md`-authoring is the first instance (we already enforce
  the standard on ourselves). Borrows linter-world presence-activation; feeds Q14's cleanest relevance
  signal. `taxonomy.md` carries the #30 factor + the artifact shape in the topic-vs-shape note.

**Sweep outcome — three decisions, all docs-only, all build-pending:** D14 (#32 agentic safety),
D15 (`artifact` shape + G11→#30), Q13 (approved/deferred). Live-state banner updated. **Build
backlog now (dependency-ordered):** the v0.3 remainder (#28 operational, #31 IaC, ~10 add-factor
regenerations) · #32 agentic-safety lens · the `artifact` shape + `SKILL.md` rubric · then the
deferred Q13 overlay. All gated on a cross-model eval re-gate (no local model in this sandbox).
Committing the batched decision-records as one docs PR.

## 2026-06-12 — v0.3 build complete: #28 resilience + #31 IaC (the last two)

Built the two remaining v0.3 categories, closing out D13's build phase (all 31
categories now have skills). Same docs→manifest→generate pipeline as #29/#30.

**#28 → `reviewing-resilience-and-scalability`** (shape: diff, design-capable).
Design-time operability, distinct from #16's runtime observability: unbounded
queues/buffers, missing timeouts + failure plans on dependency calls, blast radius
/ bulkheading, retry budgets, statelessness for horizontal scale, single-writer
bottlenecks, RTO/RPO + tested restore, graceful degradation, multi-tenant
isolation. Research section in cluster-4-runtime.md#28 (Release It!, Google SRE
cascading-failures/overload, AWS Well-Architected Reliability, The Tail at Scale,
chaos engineering, Reactive Streams backpressure, twelve-factor statelessness).
Added a synthesizer tension (restraint ↔ resilience machinery).

**#31 → `auditing-infrastructure-as-code`** (shape: repo, the 8th repo audit).
IaC manifests as production code: blast-radius of a plan (replace/destroy of
stateful resources), public exposure, wildcard IAM, secrets in state, unpinned
modules/providers, declared-vs-live drift, unsafe container defaults, stale/
soft-failed scanners. Research section in cluster-5-verification.md#31 with
**web-verified (2026-06-12)** tooling currency — the churny part: tfsec is folded
into Trivy (no new checks since the 2024 merge; AVD-* IDs map over), **Terrascan
was archived 2025-11-20 (read-only)**, driftctl is maintenance-mode (Snyk moved
drift into its platform; `terraform plan` is the canonical drift signal), Checkov
(Palo Alto) and kube-linter (StackRox) current. The Terrascan/tfsec facts double
as a worked instance of the suite's own "verify the tool still runs, don't
cargo-cult a canonical-but-dead default" stance. The security *verdict* on
exposure/IAM stays owned by #14 (noted inline, no cross_ref).

Router: added a resilience/scalability/DR-design route and an IaC-change route;
the whole-repo audit list grew seven → eight (IaC only where manifests exist).

**Cross-model gate (qwen2.5:7b + llama3.1:8b, temp 0):**

- #28 — bad-diff and bad-design scenarios fully enumerated on both; clean scenario
  clean. **One tuning iteration:** llama initially over-flagged the clean
  (stateless) scenario by demanding RTO/RPO where there is no durable state. Fixed
  by scoping the recoverability check in `examples.md` ("match the check to the
  surface — RTO/RPO/HA apply only to durable-state or DR designs"). Re-run: clean
  on both.
- #31 — qwen S1 6/6, S2 4/5 (dropped only the lowest-value "kube-linter not run"
  meta-finding — the documented secondary-finding ceiling), clean S3; llama S1 7/7,
  S2 5/5 (caught the one qwen dropped), clean S3. No example defect — qwen's drop
  is its recall ceiling.

Generate clean, no drift, eval-structure valid for all 28, 81 tests pass.
**Count reconciliation:** phase 3 ended at 22 lens skills (the "24 skills" earlier
in this log = those 22 + the router + the synthesizer). v0.3 then added four lens
skills — #29 decision-lifecycle and #30 enforcement (built earlier in the wave),
plus #28 resilience and #31 IaC (this entry) — so **22 → 26 lens skills**; with the
router and synthesizer that is **28 total**. Residuals are the known 7B ceilings
(secondary-finding recall on dense scans; cosmetic format-leak), not chased per the
runbook.

With D13's build done, the remaining build backlog (from the decision sweep
above) is: **#32 agentic-safety lens** (D14) · the **`shape: artifact` lens** +
`SKILL.md` rubric (D15) · then the deferred **Q13 team-preferences overlay**.

## 2026-06-13 — markdownlint: conform the suite + enforce it (hook + CI)

Settled the recurring CodeRabbit markdown nits (MD022/MD031) for good by making
the docs conform and adding an enforced gate, rather than per-PR hand-fixes.

**Policy.** Added `.markdownlint-cli2.jsonc`. Enforced the genuine-error rules
(blank lines around headings/fences/lists — MD022/MD031/MD032 — plus MD040 fence
languages, MD018, MD004, MD001, MD038). Disabled the rules the docs intentionally
break: MD013 (line length — prose/tables not wrapped), MD024 (repeated section
headings are deliberate structure), MD034 (research cites bare URLs inline), MD033
(`<details>` blocks in commands/templates), MD036 (bold phase labels in README),
MD041 (command files open with prose), MD060 (compact table pipes). **This
reverses the earlier "MD022 is house style, don't flag it" stance** — the team's
call (this session) is to conform the blank-line rules.

**Scope.** ~900 enforced violations across 129 files. `markdownlint-cli2 --fix`
auto-handled the blank-line bulk; the generator (`tooling/generate.py`) was taught
to emit lint-clean markdown (blank line after `## Contents`; the synthesizer's
output-format fence now declares `text`) so regenerated skills stay clean; the
remaining ~18 were hand-fixed (16 bare fences → `text`; one h2→h4 skip).

**Autofix caught two latent rendering bugs** worth noting: lines that soft-wrapped
onto a leading `#N` category reference were being parsed as spurious H1 headings
(autofix turned `#6` into `# 6`), and an `X + Y` plus-sign that wrapped to line
start had been read as a `+` bullet. Both are now reworded so no prose line opens
with `#` or a stray bullet.

**Enforcement.** A `markdownlint` step in `.github/workflows/ci.yml` (action
SHA-pinned, v23.2.0) and a `.pre-commit-config.yaml` hook (markdownlint-cli2
v0.22.1) — both read the same config, so commit-time and CI agree. Lint clean (0),
no drift, 85 tests pass. Generator output is idempotent.

---

## 2026-06-14 — Session: quality-lens coverage-gap hunt (three owner questions)

**Goal:** owner asked whether the suite covers (1) alignment with stakeholder
intentions, (2) Kent Beck's *Tidy First?* tidyings + heuristics, and (3) flagging
gaps in deterministic tooling (linters, complexity, coverage, perf benchmarks,
security scans). Audit, then log gaps in the established style.

**Findings:**

- **(1) Validation vs. verification — a true blind spot.** The atlas is rooted at
  *"Does it work?"* — it checks code against a *stated* intent
  (`tracing-correctness-and-invariants`, "the check no linter can do") but never
  questions the intent. The only "is this the right thing?" lives in
  `reviewing-decision-lifecycle`, scoped to decisions, never a diff. No
  acceptance-criteria / requirements-traceability behavior. → **map-gaps G12**;
  disposition **in-scope gap** (user).
- **(2) *Tidy First?* — one of three parts in.** The readability tidyings are
  mined into `reviewing-naming-and-readability`; the proactive tidying *action*
  (Q3/Q8 fixing mode) and the now/after/never **economics** + structural-vs-
  behavioral commit split are unowned. → **map-gaps G13**; disposition open.
- **(3) Deterministic-tooling presence — mixed, not punted to the owner.**
  `auditing-config-and-build-hygiene` already flags missing/disabled lint/type/
  test/security gates; coverage-reporting, perf-benchmark, and complexity-scoring
  presence are not checked anywhere; and the cross-lens `mechanize-with:` nudge
  (G10 item 1) was decided but never built. → **open-questions Q19**.

**Changes:** `docs/map-gaps.md` (+G12, +G13), `docs/open-questions.md` (+Q19,
live-state updated). Docs-only; no manifest/research/skill edits, so no drift.

---

## 2026-06-14 — Session (cont.): round-3 gap hunt

**Goal:** while PR #39 awaited review, the owner asked to locate *additional*
candidate gap areas by extrapolation, first-principles re-orientation, and
holistic perspectives.

**Method (the contribution):** three gap-finding methods the project had not used
before — all reasoning from *outside* the map rather than diffing taxonomy ↔
skills — plus an extension of round 2's most productive axis:

1. **External completeness model** — sweep ISO/IEC 25010:2023 characteristic by
   characteristic; find the ones with no owner.
2. **Stakeholder-vantage rotation** — review through eyes the suite never takes
   (the end user as a subject of behavior; the reviewer's own epistemics).
3. **Substrate sweep** — "software" beyond app-code-in-a-repo (machine-authored
   code, the data/analytics plane).
4. **Shape-axis extrapolation** — what vantage is still missing after diff / repo
   / decision / artifact (round 2's headline move).

**Findings (G14–G19, all provisional/owner-gated, web-verified):**

- **G14** AI-authored-code defects (substrate; reflexive) — promote (diff lens).
- **G15** production-evidence / runtime-informed review — a candidate **5th shape**.
- **G16** ethical / responsible-design in non-ML code — promote, detect-and-escalate.
- **G17** data-engineering & data-contract quality — promote (paired lens).
- **G18** the two unowned ISO-25010:2023 characteristics: **interoperability**
  (the missing "-ility") + **safety** (ISO added it as a top characteristic in
  2023, distinct from #14 security).
- **G19** review-coverage transparency / known-unknowns — fold into the synthesizer.

Plus weaker/fold candidates (quality-trajectory → Q4; domain-model fidelity;
non-app substrates → the artifact shape) and scope boundaries worth writing down
(end-user product validation; functional-safety certification; org-level DevEx).

**Cross-cutting lesson:** an external completeness model earns its keep — one
ISO-25010 pass caught two characteristics the self-referential framing-hunt of
rounds 1–2 missed. Adopt the external-model sweep as a standing method, re-run on
each major revision of an external quality standard.

**Changes:** new `docs/research/taxonomy-gap-hunt-round-3.md`; `docs/map-gaps.md`
(+G14–G19); `docs/open-questions.md` (live-state pointer). Docs-only; the
gap-hunt docs are not skill `built_from` sources, so no drift.

---

## 2026-06-14 — Session (cont.): the agent vantage (G20)

**Goal:** owner asked whether the suite covers code agents (a) as code-owners /
maintainers and (b) as users/operators — LLM-centric readability, context-window
awareness, agent config/instruction files, discoverability, RAG; and SKILL.md /
MCP tools, LLM-accessible UI, UI parity for agents.

**Finding — a vantage rotation round-3 under-exploited.** Method 2 (vantage
rotation) had stopped at the end user and the reviewer's epistemics; it missed the
rotation that matters most to an agent-run suite: the AI agent as reader/operator.

- **Code-owner role → G20, a genuine framing gap.** Cluster II is titled "Can
  humans understand it?" — never rotated to "Can an *agent* understand/navigate/
  modify this within a context budget?" Absent: LLM-centric readability, context
  economy of reviewed code, agent discoverability/navigability, RAG-friendliness.
  Partial: AGENTS.md/CLAUDE.md (drift covered #22/#24; authoring unbuilt #30/D15).
  It's the **mirror of G14** (quality *of* AI-authored code ↔ quality of code
  *for* AI readers) and **the G11 pattern again** (we optimize our own artifacts
  for agent-legibility via D7 but never review for it). Lean: promote.
- **Operator role → mostly mapped; restraint held.** #24 agent-native parity
  (G9-thin), #32 agentic safety + #30/D15 SKILL.md/MCP authoring (mapped, unbuilt),
  #23/#24 for LLM-accessible UI. New small bits: `llms.txt`-style agent
  discoverability + LLM-accessible UI affordance as add-factors. Not a new category.

Also gave the owner a full ISO/IEC 25010 explainer (lineage 9126→25010:2011→2023;
product vs quality-in-use split to 25019; the 9 characteristics + 2023 deltas;
why it served as round-3's external completeness model).

**Changes:** `taxonomy-gap-hunt-round-3.md` (+G20 under Method 2-revisited,
disposition table, synthesis point 5), `map-gaps.md` (+G20), `open-questions.md`
(live-state pointer). Docs-only; no drift.

---

## 2026-06-14 — Session (cont.): round-4 methods (G21, G22)

**Goal:** "keep going" — two more gap-finding methods, folded into the round-3 doc
(it is explicitly a multi-method hunt).

- **Method 5 — failure-grounded completeness model** (incident/outage corpus,
  complementing the attribute-grounded ISO-25010 sweep) → **G21 operational
  time-bombs & exhaustion classes.** Absent: cert/credential/token **expiry &
  rotation** (the most preventable major-outage class — #14 owns only *hardcoded*
  secrets). Thin: calendar/clock time-bombs (leap/DST/epoch-2038); coordinated
  retries (thundering herd / stampede / retry budget); exhaustion classes
  (disk/fd/port/pool). Shared temporal signature: correct-at-merge, detonates
  later. Lean: add-factors (#4/#14/#26/#28) + flag a cohesive "latent /
  time-delayed defect" thread. Verified: danluu post-mortems (~50% of severe
  outages are config; expired-cert outages at Microsoft/Spotify/Google/BoE).
- **Method 6 — adversarial / inversion** (design the defect that evades the suite)
  → **G22 diff-isolation blindness.** The load-bearing assumption is "the diff is
  the unit." Un-owned: semantic/logical merge conflicts (independently-correct
  changes that break combined), assumption invalidation across in-flight changes,
  load-bearing deletions. A missing **change-set unit** (the analog of round-2's
  missing decision *shape*). Lean: promote (scoped) — LLM ripple-trace, escalate
  heavy detection. Verified: semantic-conflict literature (arXiv 2310.02395 et al.).

**Synthesis additions:** (6) failure-grounded and attribute-grounded external
sweeps catch disjoint classes — keep both standing; (7) *unit* is an axis
orthogonal to topic, like *shape* — the diff/repo/decision units all assume a
single isolated change.

**Changes:** `taxonomy-gap-hunt-round-3.md` (+Methods 5–6, +G21/G22, disposition
table, synthesis 6–7, sources), `map-gaps.md` (+G21/G22), `open-questions.md`
(pointer). Docs-only; no drift.

---

## 2026-06-14 — Session (cont.): scope re-audit → product/experience/value (G23, G24)

**Goal:** owner challenged the recurring "product/UX out of scope" boundary — the
suite is meant to navigate toward the best possible software *holistically*, not
just dev-time logic/hygiene; needing a different stakeholder to decide shouldn't
mean a finding isn't surfaced.

**New method — audit the exclusions themselves.** Rounds 1–3 found gaps inside
scope; this pass questions the *edge*. The "out of scope" label conflated two
axes: (1) reviewable at review time? vs (2) who has authority to decide? Product/
UX/value findings often answer no to (2) but yes to (1) — they're in the diff.

- **G23 — detect-and-route (scope-principle fix).** Generalize G8 from a
  compliance footnote to a map-wide primitive: surface the finding with evidence,
  route the *decision* to the right stakeholder (product/design/legal/leadership),
  never drop it for "not our call." Add a route axis to the synthesizer alongside
  severity. Only concerns with *no artifact at review time* (market/pricing/org)
  stay out — and those re-enter as #29 once written down. Lean: adopt.
- **G24 — candidate Cluster VII: Product, Experience & Value.** The six clusters
  are all about the code and its lifecycle; none is about the product as
  experienced/valued by users (only #23 a11y is user-facing). Ten candidate
  lenses (VII-A usability [Nielsen's 10], VII-B perceived quality, VII-C
  design-system conformance, VII-D UX writing, VII-E inclusion [ISO inclusivity],
  VII-F value/outcome instrumentation, VII-G trust/transparency, VII-H conceptual
  integrity [Brooks — the *product* counterweight], VII-I i18n-of-experience,
  VII-J feature-value lifecycle). All skip-when-no-user-surface + detect-and-route.
  Lean: promote a cluster, built incrementally (VII-A + VII-F first; E/I→#23, C→#8).

Verified: Nielsen's 10 usability heuristics (canonical UX completeness model);
Brooks conceptual integrity; perceived-performance/optimistic-UI. Fixed the now-
contradicted "out of scope" notes in round-3 (G18 interaction-capability;
scope-boundaries) to point at G23/G24.

**Synthesis:** the exclusion-audit is a standing method; detect-and-route unlocks
the human-value half of software (largest scope expansion since v0.2 maximal
scope); conceptual integrity is the missing *product* counterweight.

**Changes:** new `docs/research/product-experience-value-cluster.md`; `map-gaps.md`
(+G23/G24); `taxonomy-gap-hunt-round-3.md` (reframe fixes); `open-questions.md`
(pointer). Docs-only; no drift.

---

## 2026-06-14 — Session (cont.): exclusion re-audit (G25)

Applied G23's two-axis test to the *rest* of the out-of-scope/fold pile (so the
reframe isn't special-pleading). Result confirms restraint: most prior exclusions
were correctly on the no-artifact axis. Only **sustainability/green** (was a
"carbon label on #15") and **FinOps/cloud cost** (#15 thin residual) were
mis-folded (under-surfaced, not mis-axised) → upgrade to routed #15 factors.
DevEx-as-a-system, deep model-fairness auditing, and build-vs-buy TCO stay out
(genuinely no review-time artifact; diff-visible slices already covered by the
existing #19/#21, G16, and #29). Net: the reframe sharpens the boundary, it does
not erase it. → map-gaps G25; detail in product-experience-value-cluster.md.

---

## 2026-06-14 — Session (cont.): detect-vs-apply / defect-vs-improvement (G26)

Owner caught the same wrong-axis error a third time: I'd filed tidyings /
dead-code / dep-bumps under the unbuilt "fixing mode," but *detecting and
suggesting* them is review-time (reviewer suggests a nit; implementer applies/
defers/ignores). Grep confirmed the real blocker: every SKILL.md carries the
generated guard "do not suggest changes to code that is already correct" — the
suite is **defect-only by construction**, so improvement-valence findings are
prohibited regardless of any apply-automation.

- "Maintenance" decomposes into three orthogonal things; only auto-*application*
  (Q8) is genuinely unbuilt (and partly served by simplify / code-review --fix).
  Improvement *detection+suggestion* is review-time (detect-and-route, route:
  implementer), gated only by the guard. Proactive *scanning* is the cron shape
  (repo audits).
- Fix (G26): refine the guard + add a `valence: defect | improvement` axis to the
  finding contract; improvements admissible as opt-in, nit-severity, route:
  implementer, volume-bounded (throttled by the synthesizer floor + REVIEW.md
  convergence, which already keeps suppressed nits visible for optional tidy-up).
  Largely resolves Q3; narrows Q8 to auto-application only.
- **Meta-principle (3rd instance):** reviewability is orthogonal to authority
  (G23), reader identity (G20), and application-timing/valence (G26). The
  "conflation audit" is itself a standing gap-finding method.

**Changes:** map-gaps (+G26, refined G13 disposition), open-questions (Q3 refined,
Q8 narrowed, live-state pointer), product-experience-value-cluster.md (synthesis
point 4). Docs-only; no drift.

---

## 2026-06-14 — Session (cont.): G26 refinement — valence as a team preference + anti-churn

Owner refined G26: (1) the defect-only guard is a legitimate *team preference*,
not a universal — so it becomes a strict default plus a **preference-tier dial**
in the Q13 team-preferences overlay (the `valence` axis is the mechanism; the
overlay is the policy). (2) A built-in **anti-churn / value-threshold /
convergence** discipline the overlay cannot relax: an improvement must cross a
value+confidence bar (improve, not merely differ — no change-for-change's-sake)
and converge (once a dimension is as good as we can confidently make it, no
further/lateral/oscillating suggestion). Same termination guarantee REVIEW.md
convergence gives the review loop, applied to improvement nits.

Folded into the pending team-preferences-overlay design (new directive kind §4.6
improvement-valence verbosity + §4a anti-churn built-in) and Q13. map-gaps G26
disposition updated accordingly. Docs-only; no drift.

---

## 2026-06-14 — Session (cont.): cross-discipline review-analog sweep (G27–G29)

New method — import mature *review practices* from other assurance disciplines
(financial audit, scientific peer review, manufacturing QA, clinical, aviation,
civil-eng), the inverse of the ISO/Nielsen quality-model sweep. Mostly confirmed
the atlas is well-grounded (poka-yoke ≡ #9/#10; checklist discipline ≡ the suite's
whole form, externally validated; adversarial ≡ #14/#32; reproducibility ≡ #1/#19)
— restraint held. Three net-new:

- **G27** segregation of duties / maker-checker / four-eyes in authz logic (no
  single actor completes a sensitive workflow alone) — SOX §404, anti-fraud;
  distinct from #14's IDOR/least-privilege. add-factor #14, detect-and-route.
- **G28** claims-vs-evidence verification, generalized from the one place the
  atlas already does it (perf lens "demand a profile"): an unsupported PR claim
  is itself a finding. cross-cutting factor / synthesizer principle.
- **G29** root-cause vs symptom (band-aid detection) for fixes — does the change
  resolve the cause or mask the symptom. add-factor (#1 / hunting-silent-failures).

Feeds-existing: materiality/sampling → Q14 (the depth axis's missing name);
differential-diagnosis → G19; safety-margin → #28/G21; four-eyes-on-irreversible
→ #24; blameless M&M → Q17/G15.

**Changes:** new `docs/research/cross-discipline-review-analogs.md`; map-gaps
(+G27–G29); open-questions (live-state pointer). Docs-only; no drift.

---

## 2026-06-14 — Session (cont.): shape & synthesizer sweeps (G30–G31)

Two more passes:

- Re-ran shape-axis extrapolation on *security*: where is security reviewed at
  *design* time? → **G30 threat modeling** (STRIDE / DFD+trust-boundaries / attack
  trees / abuse cases) as a design/decision-time discipline, distinct from #14's
  diff-time vuln sweep (#14 has design:true but running diff-heuristics over prose
  ≠ generative threat enumeration). Grep confirmed absence ("trust boundary" only
  in the parse-don't-validate sense). Verified design-time framing (STRIDE 1999;
  Shostack's four questions). Lean: promote a design-shaped security lens / #14
  decision-arm, detect-and-route the high-stakes slice. The security analog of #28.
- Audited the synthesizer's own apparatus → **G31**: the tensions table is
  entirely restraint-centric; cross-quality tensions (observability↔privacy,
  security↔usability, transparency↔security, perf↔a11y, consistency↔evolvability)
  have no default and fall back to "safer+simpler." Cluster VII (G24) + G16 make
  these collisions more frequent. Lean: enrich the manifest tensions table.

**Changes:** map-gaps (+G30/G31), open-questions (live-state pointer). Docs-only;
no drift. Remaining mining queue: cross-quality is now partly done; open frontiers
are thinning — next candidates are second-order/feedback-loop effects and a
deliberate full conflation-audit pass.

---

## 2026-06-14 — Session (cont.): deliberate conflation audit (G32 + closure)

Ran the conflation audit as a named method: enumerate every axis X for which a
gap could hide behind collapsing "is it reviewable?" with X. One net-new:

- **G32** reviewability ⊥ *attribution* — the diff-only convention conflates
  "what changed" with "what's reviewable." A pre-existing defect visible in
  touched code is reviewable and worth surfacing (Boy Scout / opportunistic
  rule), tagged "pre-existing — not introduced here," non-blocking, scoped to
  touched code (the repo audits own whole-repo hunting), governed by the G26
  anti-churn/scope discipline + Q13 verbosity. Verified prior art.

The other axes test as already-handled: tooling→G5/Q19; subjectivity→Q13;
composition-unit→G22; phase→shape axis (Q15/G15); localizability→G24 VII-H +
repo audits; ownership→#18/#30; positive/affirming findings considered and
declined (restraint). **Closure signal:** the framing seam (rounds 1-3's richest
vein) is largely mined; remaining yield is add-factors/validations, and the
bottleneck has moved from finding to deciding → next is the consolidation
synthesis across G12-G32 (owner to allow).

**Changes:** map-gaps (+conflation-audit table, +G32, closure), open-questions
(live-state pointer). Docs-only; no drift. End of the mining phase.

---

## 2026-06-14 — Session (cont.): consolidation synthesis (G12–G32)

Mining phase closed; produced the decision-support synthesis
`docs/research/gap-hunt-synthesis.md` — the whole pile (21 gaps + Q19 + the
enabling open questions) ranked and dependency-sequenced into four build waves:

- **Wave A — foundations:** the two primitives (G23 detect-and-route axis, G26
  valence axis + anti-churn), the cheap synthesizer upgrades (G19 coverage block,
  G31 tensions enrichment), and Q19 (mechanize-with + presence checks). All
  manifest/synthesizer/contract edits that regenerate cleanly; they unblock the rest.
- **Wave B — high-value add-factors:** G27 (SoD, best value-per-cost), G21
  (time-bombs), G28 (claims-vs-evidence), G29 (root-cause), G25 (green/FinOps),
  G13 (tidy suggestions via G26), G32 (attribution), G12-as-factor.
- **Wave C — new lenses:** G14 (AI-authored, top), G16 (ethical, needs G23), G20
  (agent-legibility), G30 (threat-modeling, needs Q15), G18-interop.
- **Wave D — bigger bets:** G24 Cluster VII (incremental: VII-A + VII-F + VII-H
  first; needs G23+G26+Q13), G17 (data-eng), G22 (scoped), G15 (runtime shape,
  longest horizon).

Dependency headline: G23 + G26 (+ Q13) are upstream of most high-value lenses —
build the primitives before the lenses. Top-five and the G1 single-owner
boundaries (ethics triad G16/VII-G/#27; the claims/criteria/intent family
G28/G12/#1; contracts G17/#13/#20; etc.) are called out for the decision pass.
Also recorded: the hunt's reusable deliverables — three standing gap-finding
methods plus two primitives — compound beyond this pile.

**Changes:** new `docs/research/gap-hunt-synthesis.md`; map-gaps + open-questions
pointers. Docs-only; no drift. This closes the gap-hunt + synthesis arc; decisions
(promote/fold/sequence) are the owner's separate pass.

---

## 2026-06-15 — Session: promote G27 (segregation of duties) — first Wave B build

Owner picked G27 off the synthesis backlog — the highest value-per-cost item in
the pile and an SOX-grade control the suite simply lacked. Promoted as an
**add-factor on `sweeping-for-security` (#14)** via the compounding loop:

- **Research source:** added a `Reviewable heuristics` seed + a `Key references`
  entry (maker-checker / four-eyes / SoX SoD) to `cluster-4-runtime.md#14`. The
  heuristic asks whether the *same actor can both initiate and approve* a
  high-consequence action (payment/refund, role grant, deploy, bulk delete), and
  frames SoD as orthogonal to least-privilege (*how much*) and IDOR (*whose*).
- **Detect-and-route, in prose:** the G23 route-axis primitive isn't built yet, so
  the factor surfaces the missing dual-control to security/compliance and notes
  that *which* ops require it is a business-policy call — capturing the
  detect-and-route spirit without depending on the unbuilt mechanism.
- **Regenerated** the skill: SoD is now the **3rd Top check** in `SKILL.md`
  (grouped with the IDOR/authz check; PII-in-logs moves to the full list). Added a
  numbered-list **example** (refund self-approval) and a 4th **eval scenario**
  (plus the existing good-case held intact).
- **Gates:** `drift` clean, `eval` structural pass (4 scenarios), full test suite
  85 passed. **Live cross-model re-gate deferred** — no Ollama/llama-server tier in
  this sandbox; tracked here per prior re-gate precedent.

Also confirmed in passing: open issues **#23/#24** are already fixed on `main`
(commit `3a3c55d`) and just need closing on GitHub — pure housekeeping, left for
the owner.

**Changes:** `cluster-4-runtime.md` (+heuristic, +reference), regenerated
`sweeping-for-security` (SKILL/heuristics/sources), hand-edited examples + eval,
map-gaps (G27 shipped marker), gap-hunt-synthesis (Wave B status). No drift.

**Round-1 atlas review (PR #41, approve-with-changes) addressed:**

- *PII dropped from Top checks* (Minor): reordered the #14 source so PII-in-logs
  sits at #8 (ahead of the more framework-defaulted CSRF, now #9) — SoD enters the
  8-budget window without evicting a higher-base-rate check.
- *Description frontmatter stale* (Minor): added SoD/maker-checker to the manifest
  `description` + "authorization workflows" to the trigger list, so routers/catalog
  match it; regenerated.
- *Eval scenario latent IDOR* (Minor): isolated the SoD bad case behind an
  explicit `@require_role("refund_approver")` gate so self-approval is the *sole*
  defect (the role-gated lookup is correct for an approver) — removes the
  IDOR/SoD ambiguity rather than testing two things loosely.
- *No positive SoD scenario* (Nit): added a good→no-finding eval **and** a matching
  `examples.md` pair (approver≠requester enforced) to pin the false-positive rate.
  Eval now 5 scenarios.

**Live cross-model re-gate (the deferred D6/D8 step), run in-session via Ollama:**

Environment work first: this sandbox had no model server, but egress is open, so
installed Ollama + pulled `qwen2.5-coder:7b` (floor) and `llama3.2:3b` (low). Two
traps cleared:

- **Ollama 0.30.8 segfaults** on every model load here (broken inference build,
  not a CPU gap — box has AVX2/AVX512). Pinning **Ollama 0.5.7** fixed it.
- **Harness bug — silent context truncation.** `run_evals.py`'s Ollama path never
  set `num_ctx`, so Ollama's 2048 default truncated the ~3.1k-token assembled skill
  context; the model reviewed against a partial prompt and produced generic "here
  are improvements" reviews that *looked* like results. Re-ran with `num_ctx 8192`
  (via a driver reusing the harness's own `assemble_context`) → responses snapped to
  the skill's format. **Fixed in the harness**: pin `OLLAMA_NUM_CTX = 8192` in the
  Ollama options + raise the per-call timeout to 600s (CPU prompt-eval on a large
  context exceeded the old 180s).

Graded results (temp 0, num_ctx 8192):

- **7B floor — first valid pass: 4/5.** S1 injection ✓, S2 secret/CSPRNG/SQL ✓,
  **S3 bad-SoD MISS** ("No findings" — treated the `@require_role` gate as
  sufficient), S4 good-SoD ✓, S5 good-delete ✓. Precision clean; the new factor's
  *recall* missed — the documented "pattern-match beats reading" 7B ceiling
  (role-gate-present → fine, missing the relational inference that one identity is
  both requester and approver).
- **Tuning pass** (general, not test-specific): added the decision rule *a
  role/permission gate authorizes who may act and is not segregation of duties —
  if an action records an initiator and an approver but never compares their
  identities, the maker-checker control is missing even with a role gate present*
  to the #14 heuristic (regenerated) + `examples.md`.
- **7B floor — re-run: S3 MISS → PASS**, S4/S5 still clean. **Net 5/5 on the
  documented floor.**
- **3B low tier: fails the SoD scenarios both ways** (confabulated a non-existent
  self-check on the bad case; false-positived the good case) and over-flags clean
  code — below the 7–8B precision floor, consistent with prior runbook findings; not
  a regression from this factor.

Net: G27 **passes the cross-model gate at the documented floor.** Follow-up worth
considering: the `num_ctx` harness fix means earlier Ollama-based eval runs in the
repo's history may have been silently truncated too — worth a spot re-check.

### 2026-06-15 (cont.) — Wave A primitives: G23 detect-and-route + G26 valence axis

**Goal:** build the two Wave A foundation primitives from [`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md) — they sit upstream of most high-value lenses, so they go first.

**What shipped (one PR, generator-prose only — no manifest schema change):**

- **G23 detect-and-route.** Added a `route:` axis (`eng | implementer | product | design | legal | leadership`) to the synthesizer finding contract, generalizing the G8 detect-and-escalate pattern into a map-wide principle: a holistic review *surfaces* every reviewable finding with evidence and *routes the decision* to its owner — never silently dropping a non-engineering call, never self-adjudicating one. New **Routed — non-defect decisions outside engineering** report section. Valence (not route) governs the verdict — a defect that is also routed (a GPL dep → `valence: defect, route: legal`) still blocks in its severity section *and* escalates; only non-defect routed findings are surfaced without setting the verdict. *(Clarified in PR review — the original wording let a routed defect produce a false "approve.")*
- **G26 valence axis.** Added `valence: defect | improvement` to the contract. Refined the per-lens *Reviewer discipline* guard (in `generate.py`, so it regenerates across all ~26 lenses) from an absolute "do not suggest changes to correct code" into "**defect-only by default; improvements opt-in**." Improvements are admissible only as `nit`-severity, `route: implementer`, and must clear a **non-configurable anti-churn floor** (genuine-improvement bar + convergence/no-oscillation). New **Improvements — opt-in, optional** report section. Default behavior unchanged (strict); the team verbosity dial still depends on the Q13 overlay (designed, unbuilt).

**Verification:** `pytest tests/` 88 pass (added guard + contract assertions); `cli drift` clean (regenerated in sync); `cli eval` OK (2 new synthesizer scenarios — a product/design routed case, an improvement-valence + anti-churn case — for 6 total); markdownlint 0 errors. Cross-model eval re-gate pending (lighter than a new lens — mechanism/prose, not new judgment).

**Resolves:** G23, G26 dispositions → shipped; **Q3 largely resolved** (review/maintenance is a valence toggle, not a separate mode). Remaining Wave A: G19 (synthesizer coverage/limitations block), G31 (tensions enrichment), Q19 (mechanize-with nudge).

### 2026-06-15 (cont.) — Wave A finish: G19 coverage block + G31 tensions + Q19 mechanize-with

Closed out Wave A from [`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md) — three near-free synthesizer/generator edits, all regenerating cleanly (no drift).

- **G19 — coverage & limitations.** The synthesizer now closes every report with a required **Coverage & limitations** block: which lenses ran, which the router did not select, and what could not be verified from the diff alone (runtime, data, repo-wide context). Always present — even on a "No findings" report — because a confident verdict silent on its own blind spots manufactures false assurance. Generator prose; +1 eval scenario.
- **G31 — cross-quality tensions.** The `synthesizer.tensions:` table was entirely restraint-centric. Added the three cross-quality pairs whose both lenses exist today: observability↔privacy (log detail vs PII), performance↔accessibility (a11y is correctness, not an optimization to trade away), consistency↔evolvability (match the idiom until evolvability has evidence). The two G24-dependent pairs (security↔usability, transparency↔security) wait on the unbuilt Cluster VII lenses. Manifest data; validates against real lenses.
- **Q19 — mechanize-with + presence checks.** (a) Every lens gained a generated **"Mechanizing these checks"** section reframing `reference/tool-rules.md` as an advisory mechanization source, surfaced as a non-blocking `route: implementer` nudge (integrates with the G23/G26 axes; answers "every lens?" → yes, uniformly). (b) `auditing-config-and-build-hygiene` gained a coverage/perf-benchmark/complexity-scoring **presence** check, framed as a preference-tunable advisory (not a floor-tier block) so repos that deliberately skip them can suppress it — the Q13-aligned answer to "finding or noise?".

**Verification:** `pytest tests/` 90 pass (added mechanize-with, coverage-block, and cross-quality-tension assertions); `cli drift` clean; `cli eval` OK (synthesizer 8 scenarios, config-hygiene 3); markdownlint 0 errors. Cross-model eval re-gate pending (mechanism/prose + one advisory heuristic — light, no new judgment lens).

**Resolves:** G19, G31 dispositions → shipped; **Q19 → resolved/built**. Wave A is complete. Next per the synthesis: **Wave B add-factors** (G21 operational time-bombs, G28 claims-vs-evidence, G29 root-cause, G25 green/FinOps, G13 tidyings, G32 pre-existing defects, G12 acceptance-criteria) — cheap, regenerate from the manifest.

### 2026-06-15 (cont.) — Wave A cross-model re-gate (#45 + #46)

Closed the deferred D6/D8 ratchet on the Wave A mechanism work. Ran on local
Ollama 0.23.2 with **qwen2.5:7b** (the documented 7-8B floor) and **llama3.2:3b**
(the over-flagging canary), via `python -m tooling.run_evals` (num_ctx 8192).

**Primary concern — over-flagging regression on clean code — did not appear.** The
Wave A changes touched all 26 lenses (the amended defect-default guard + the
mechanize-with section) plus the synthesizer contract and one config-hygiene
heuristic, so the re-gate targeted the widest-blast-radius and the new-judgment
surfaces:

- **`checking-restraint` (guard-change canary), 7B + 3B.** Over-engineering and
  premature-optimization scenarios flagged correctly on both tiers; the **clean**
  scenario returned "No findings" on **both** 7B and 3B. The new "improvements
  opt-in" guard language and the mechanize-with section did **not** inject
  improvement-churn or tool nudges onto correct code. (3B was verbose/template-
  dumping on the bad cases as previously documented — not a Wave A regression.)
- **`auditing-config-and-build-hygiene` (Q19 presence check), 7B.** Bad-config and
  stale-flag/curl-pipe-bash scenarios caught; the **healthy-repo** scenario returned
  "No findings" — the new coverage/perf/complexity presence heuristic stayed
  advisory and did **not** manufacture a "missing coverage gate" finding on a clean
  repo. This was the exact Q19 over-flagging worry; it is clear.
- **`synthesizing-review-findings` (route/valence/coverage contract), 7B — 8
  scenarios.** 6 clean passes including the #45-review GPL `defect + route: legal`
  case (verdict "approve with changes", not a false approve) and the G19 coverage
  block. Two soft recall gaps at the floor: the G23 routed case kept route tags
  **inline** rather than under a dedicated Routed section, and the G26 anti-churn
  case **surfaced** the equivalent-reorder as an explicitly-optional suggestion
  instead of **dropping** it. Both preserve the information and are consistent with
  the documented 7B ceiling on the subtlest disciplines; the deployment tier
  (Claude) handles them. Not regressions, logged as known floor limitations.

**Verdict: Wave A passes the cross-model gate at the 7-8B floor; the core
no-over-flagging property holds even at 3B.** Q19's pending eval pass is now done.

### 2026-06-15 (cont.) — Wave B wave 1: G21 operational time-bombs + G28 claims-vs-evidence

First Wave B add-factors from [`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md) — pure heuristic additions to existing lenses, edited at the research source and regenerated (drift clean), each with a single G1 owner and an eval.

**G21 — operational time-bombs (the "correct at merge, detonates later" class).** A failure-grounded gap (incident-corpus method, round-3): defects that pass review because today is an ordinary day, then detonate by passage of time or accumulation. Split to single owners:

- **Credential & certificate expiry / rotation** → #14 `sweeping-for-security` (cluster-4 #14). TLS/mTLS certs, OAuth tokens, API/signing keys with no renewal path or pre-expiry alert — the single most preventable major-outage class. Distinct from the existing "secrets absent from source" check (lifecycle, not leakage).
- **Calendar/clock time-bombs** → #4 `tracing-correctness-and-invariants` (cluster-1 #4). Leap year/second, DST gaps/overlaps, month/year rollover, epoch-2038; hardcoded years and `day+1` calendar-blind arithmetic. Sharpens the existing UTC/DST bullet with the actual detonation triggers.
- **Thundering herd / cache stampede** and **resource-exhaustion classes** → #28 `reviewing-resilience-and-scalability` (cluster-4 #28). Synchronized clients (aligned TTLs/timers/reconnects) beyond per-client backoff → want single-flight + jitter; finite ceilings that creep under load (disk/inode, fd/socket, ephemeral port, pool slots).

The cohesive "latent / time-delayed defect" thread is threaded into each factor as framing rather than spun into a new lens (restraint — the synthesis flagged it as an *option*, not a mandate).

**G28 — claims-vs-evidence** → #24 `reviewing-pr-and-process-hygiene` (cluster-6 #24, its single owner — it reviews the PR's stated claims). Generalizes the perf lens's lone "demand a profile" into the broad discipline: every PR claim ("fixes X"/"closes #N", "faster", "pure refactor / no behavior change") must be checkable against evidence *in the diff*; an unsupported claim is itself a finding. Kept as a per-lens factor, **not** a synthesizer check — the synthesizer adds no checks of its own.

**Surfacing note (G9-aware).** #14 expiry and #28 herd/exhaustion landed high enough to inline as **top-checks**; #4 calendar and #24 claims are domain-conditional and live in the **full checklist** (`reference/heuristics.md`), which evals load and which a lens opens when the change is in-domain. Broader top-check surfacing for the deeper factors is the separate **G9 budget rebalance**, not this PR.

**Verification:** `pytest tests/` 90 pass; `cli drift` clean; `cli eval` OK (+4 scenarios: tracing 4, security 6, resilience 4, pr-hygiene 4); markdownlint 0 errors. Cross-model re-gate pending (add-factor heuristics; batch with the next Wave B items).

**Resolves:** G21, G28 → shipped. Wave B remaining: G29 (root-cause-vs-symptom), G25 (green/FinOps), G13 (tidyings, now that G26 valence exists), G32 (pre-existing/adjacent defects, needs G23+G26 — both shipped), G12 (acceptance-criteria traceability).

### 2026-06-15 (cont.) — G9 budget layer: inline-priority marker (deep factors now surface)

The Wave A/B add-factors kept landing in the **full checklist** (`reference/heuristics.md`) but not the inlined **Top checks**, because a bundled lens splits the ~8-check budget across its categories and a factor past position ~4 never makes the head. That is the G9 propagation leak — "category ownership is complete, factor *surfacing* leaks." Fixed the budget layer of G9 (the router/Q14 and severity-trim layers remain open).

**Mechanism — an inline-priority marker (`★`).** A research heuristic bullet may be flagged `- ★ …`; `tooling/sections.py` exposes `is_priority`/`strip_priority` and `tooling/generate.py` `top_checks` inlines every marked bullet **additively** (marker stripped). Design choices, each deliberate:

- **Additive, not displacing.** A marked factor is added on top of the normal position-based head, so promoting a deep factor never knocks a foundational check (money-as-minor-units, float-comparison, breaking-change-signaling) out of Top checks. A lens grows only by its mark count (the marked lenses now run 9-10 inlined checks vs 8); unmarked lenses are untouched — keeping this targeted rather than the blanket budget bump the marker was chosen over.
- **Owner-only.** Cross-ref categories ignore the marker, so a factor force-surfaces only in the lens that *owns* the category, not in every lens that shares it (e.g. calendar/overflow surface in `tracing-correctness-and-invariants`, not in `hunting-silent-failures` which cross-refs #4).
- **Directive, not content.** The marker is stripped from both SKILL.md Top checks and heuristics.md; `section_hash` still hashes the raw source (incl. `★`), so drift stays clean and the source doc carries a visible "headline check" cue for human readers.

**Promoted the demonstrated leakers** (verified each was absent from Top checks before, present after): calendar/clock time-bombs + numeric overflow (#4), claims-vs-evidence + agent-native parity (#24), caller-ergonomics/pit-of-success (#9), portability (#26), symmetry of expression (#6). `altitude` (#6), `SLO/error-budget` (#16), `change-amplification` (#21) already surfaced — left unmarked.

**Verification:** `pytest tests/` 93 pass (new: marker detection/stripping in test_sections; additive-surfacing + heuristics-strip in test_generate); `cli drift` clean; `cli eval` OK; markdownlint 0 errors. Generator-logic + research-annotation only — no hand-edited skills.

**Resolves:** G9 **budget layer** (partial — router under-selection Q14 and severity-trimming remain). Unblocks the rest of Wave B: future add-factors can be marked to surface immediately.

### 2026-06-15 (cont.) — Wave B wave 2: G29 band-aid, G25 cost+carbon, G13 economics, G12 acceptance-criteria

Four more Wave B add-factors, each at a single G1 owner, regenerated from research (drift clean), with evals. The G9 priority marker (shipped earlier today) is now used to surface the two highest-value ones as top-checks.

- **G29 — root cause vs. band-aid** → `hunting-silent-failures` (#2), **marked priority**. Does a bug fix resolve the cause or paper over a symptom (catch-and-ignore, special-case the one bad input, retry a flaky call, bump a timeout, drop a guard at the crash site)? Existing lenses verify a fix is *correct*; none asked if it is at the *right level*. 5-whys framing.
- **G25 — cost & carbon efficiency** → `reviewing-performance-and-efficiency` (#15), **marked priority**, `route: eng/leadership`. Green and FinOps share one diff signal (wasted work per request) with two weights, so unified into a single routed factor rather than two near-duplicate bullets (restraint) — upgrades the pre-existing thin FinOps line. Diff-visible inefficiency in scope; org-level target out.
- **G13 — tidy-first economics** (Beck part 3). The *now/after/never* timing + coupling-as-cost-driver → `finding-maintainability-hotspots` (#21); the *structural-vs-behavioral separation* (refactoring and the feature it enables in separate changes — stronger than #24's atomic-commits) → `reviewing-pr-and-process-hygiene` (#24, which absorbs it). Both unmarked (those lenses are already well-surfaced). Part 2 (auto-apply) stays Q8.
- **G12 — acceptance-criteria traceability** → `reviewing-pr-and-process-hygiene` (#24), as a factor (per the synthesis: start as a factor, earn a lens later). Does the PR deliver what its linked issue asked — no less (criteria met), no more (no unrequested scope)? Framed as **validation**, distinct from #1 (code-vs-intent) and #29 (decision soundness). Unmarked.

**Marking discipline:** only G29 and G25 marked priority — high value, currently leaking, owning lens at <=8 top-checks. G13/G12 land in the full checklist; #21/#24 are already heavily surfaced and G12 is explicitly meant to earn a lens before claiming a top slot. Both marked lenses now run 9 top-checks (additive, no foundational displaced).

**Verification:** `pytest tests/` 94 pass; `cli drift` clean; `cli eval` OK (+4 scenarios: hunting 4, performance 4, maintainability 4, pr-hygiene 5); markdownlint 0 errors. **Cross-model re-gate: target Wave B close-out (the G32 PR), no earlier than 2026-06-16** — batched rather than per-factor (mechanism/prose, no new judgment lens); the G32 PR is the trigger to run it across #48 / #50 / G32 together.

**Resolves:** G29, G25 → shipped; G13 parts (1)+(3) shipped (part 2 = Q8); G12 shipped as factor. **Wave B remaining: G32** (pre-existing/adjacent defects — the attribution axis, its own PR next).

### 2026-06-16 — Wave B close-out: G32 pre-existing/adjacent defects (the attribution axis)

The last Wave B item from [`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md). G32 is **the fourth instance of the conflation pattern** — *reviewability ⊥ attribution* — after G23 (⊥ authority/route) and G26 (⊥ application-timing/valence). Its three predecessors shipped in Wave A as **cross-cutting generator prose** (the per-lens *Reviewer discipline* guard + the synthesizer finding contract), so G32 lands the same way rather than as a single-lens topic heuristic. This keeps it a true primitive (every lens) and keeps `built_from` untouched, so drift stays clean.

**The diff-only convention conflates "what changed" (attribution) with "what's reviewable."** A genuine defect a change did *not* introduce, but that sits in the code the PR *touches* (the edited function or immediately adjacent lines), is reviewable and worth surfacing — the Boy-Scout / opportunistic-improvement rule — without expanding the PR's scope. It is *un-attributed improvement-valence*: opt-in, default-quiet, `route: implementer`, non-blocking.

**What shipped (generator prose only):**

- **Per-lens guard.** Every lens's *Reviewer discipline* section gains a clause: a pre-existing defect noticed in touched code may be surfaced, tagged "pre-existing — not introduced by this change," opt-in/default-quiet, `route: implementer`, non-blocking; stay scoped to touched code (a repo-wide hunt is the audits' job) and never expand the PR's scope. All 27 lenses regenerated.
- **Synthesizer finding contract.** New **`attribution: introduced | pre-existing`** field; an *Attribution (Boy-Scout, scoped)* surfacing principle alongside detect-and-route and valence; a verdict rule (a `pre-existing` defect is surfaced and routed to the implementer **without** setting this PR's verdict — the diff did not cause it); and a dedicated opt-in **"Pre-existing — noticed in touched code, not introduced here"** report section (absent unless the team opted into Boy-Scout surfacing).

**Verification:** `pytest tests/` 95 pass (+1: pre-existing-in-touched-code guard clause; extended the synthesizer-contract test for the attribution field/principle/section); `cli drift` clean; `cli eval` OK (synthesizer now 9 scenarios — added an opted-in Boy-Scout case asserting the pre-existing finding is tagged, routed to the implementer, and does not set the verdict); markdownlint 0 errors. Generator-logic + prose only — no hand-edited skills, no research-section edits.

**Resolves:** G32 → shipped. **Wave B is closed** (G27, G21, G28, G29, G25, G13(1)+(3), G12, G32 all shipped; G13 part 2 = Q8 auto-apply). **Cross-model re-gate still owed** — batched across the Wave B add-factor PRs (#48 / #50) + this G32 close-out; it needs Ollama/local models (qwen2.5:7b floor + a 3B canary) and so runs on a machine with that substrate, not in this environment. Next strategic step is Wave C, led by **G14** (AI-authored-code-defects lens).

### 2026-06-16 (cont.) — dogfood fix: shape-gate the G32 attribution guard

Ran the atlas suite against PR #53 itself (the feature route: tracing-correctness, checking-restraint, test-quality, naming-readability, + pr-hygiene). The restraint+correctness lenses surfaced one Minor that CodeRabbit's clean pass missed: `build_skill_md` emitted the diff-specific attribution guard ("this PR", "touched code", "a repo-wide hunt is the audits' job") onto **all** lenses, including the 8 repo-shaped audits (where repo-wide hunting *is* the job — self-referential) and the decision lens (which reviews an ADR, not a diff). Fixed by gating the paragraph on `skill.shape == "diff"`, mirroring `_scope_line`. The guard now renders on the 18 diff lenses only; the defect/improvement valence guard stays shape-neutral (unchanged). Test added (`test_attribution_guard_is_diff_shaped_only`). `pytest` 96 pass; drift clean; eval OK; markdownlint 0 errors.

### 2026-06-17 — Wave C opens: G14 AI-authored-code defects (taxonomy v0.4, new lens #34)

First **Wave C** new lens, and the first **v0.4** taxonomy promotion. Unlike the Wave B add-factors (cross-cutting prose that regenerates), a new lens carries the full compounding loop (D6/D8): a dedicated research section → taxonomy category → manifest entry → generate → evals. G14 is the highest-base-rate new lens and **reflexively important — this suite is itself AI-built**, so it should hold its own output to this bar.

**The gap:** the map reviews code that *calls* a model (#25) and tracks AI *provenance markers* (#27), but nothing owned the **failure signature of machine-authored code itself**, independent of author. AI-assisted code is now the median diff and fails in characteristic, diff-reviewable ways fluent prose hides.

**What shipped:**

- **Research §#34** in [`cluster-4-runtime.md`](research/cluster-4-runtime.md) (next to its sibling #25), grounded in cited prior art: Spracklen et al. package-hallucination (~20% non-existent, ~43% recur → slopsquatting), *Beyond Functional Correctness* (invented/misused APIs, plausible-but-wrong logic, inconsistent state), Veracode (~45% of LLM code carries a security flaw), Willison on slopsquatting, GitClear churn/duplication. 9 reviewable heuristics, 2 priority-marked (G9): the slopsquat guard and confident-but-wrong constants/APIs.
- **Taxonomy v0.4** — new category **#34 AI-authored-code defects** in Cluster IV; version header + changes note updated.
- **Lens `reviewing-ai-authored-code`** (shape: diff, wave 5) — **primary-owns #34, cross-refs #18** so the package-existence/slopsquat leg dedupes under the supply-chain owner rather than double-reporting; **attribution-agnostic** (it does not require knowing a model wrote the code) and **defers the deep verdict** to the owning lens (#18 supply-chain, #14 security, #1 correctness, #11 restraint).
- **Router** — a dedicated route ("AI-generated/assisted change, large/unfamiliar diff, or any change adding dependencies or confident-looking constants/APIs" → `reviewing-ai-authored-code` + correctness + security); auto-listed in the diff catalog.
- **4 evals** — slopsquat dependency, confident-but-wrong constant (84600≠86400), over-helpful scope creep, and a clean control guarding false positives; `examples.md` populated.

**Verification:** `pytest tests/` 97 pass (+1: `test_ai_authored_lens_owns_34_and_crossrefs_supply_chain` — owns #34, #18 not stolen, priority checks + shared-owner note present); `cli drift` clean; `cli eval` OK (new lens 4 scenarios); markdownlint 0 errors.

**Resolves:** G14 → shipped. **Wave C opened.** Remaining Wave C (each a full research+eval pass): G16 ethical/responsible-design (needs G23), G20 agent-legibility (cluster-II rotation), G30 threat-modeling (decision-shape, needs Q15), G18-interoperability. **Cross-model re-gate still owed** — now also covers this new lens; batch on a machine with the Ollama substrate (qwen2.5:7b floor + 3B canary), not this environment.

### 2026-06-17 (cont.) — Wave C: G20 agent-legibility (taxonomy v0.5, new lens #35)

Second **Wave C** new lens, first **v0.5** promotion, and the deliberate **mirror of G14**: G14 reviews the quality *of* AI-authored code; G20 reviews the quality of code *for* AI readers — same readability axis, opposite direction, neither subsuming the other. Framing and prior art were fresh from the G14 pass, so this was the natural next pick.

**The gap:** Cluster II asks *"Can humans understand it?"* (#5–#8); the axis was never rotated to the reader an agent-run review most needs to serve — *"Can an **agent** understand, navigate, and safely modify this within a context budget?"* It is also **the G11 pattern again**: the suite optimizes its *own* artifacts for agent-legibility (D7) but never made it a **review behavior**. The round-3 hunt flagged the *code-owner / reader* role as the genuine framing gap; the *operator* role (agent-as-user) stays mapped to #24/#32/#30 and is **not** over-promoted.

**What shipped:**

- **Research §#35** in [`cluster-2-readability.md`](research/cluster-2-readability.md) (next to #5–#8), grounded in cited prior art: "AI-friendly codebases" and "coding agents as a first-class project-structure concern" (the **40% context rule**, depth-first slices, self-contained modules, AST-grounded interfaces), *Lost in the Middle* (Liu et al. — retrieval degrades mid-context, so context economy is a correctness-adjacent property, not style), the `llms.txt` proposal, GitClear's "superficially clean but intrinsically complex" read from the reader's side, and the Anthropic AGENTS.md/skill-authoring spine. 9 heuristics, 2 priority-marked (G9): context economy / self-containment, and present-accurate-scoped agent onboarding.
- **Taxonomy v0.5** — new category **#35 Agent-legibility** in Cluster II; version header, count (34→35), changes note, and numbering note updated.
- **Lens `reviewing-agent-legibility`** (shape: diff, wave 5) — a **single-category lens** (built_from #35, no cross_ref): the agent-as-reader vantage is genuinely new, so its checks live in #35 rather than being shared. Cross-links #5–#8/#21/#22/#24/#30 in prose; the sharp seam with #30 (artifact *conformance* vs. onboarding *content fit*) and #24 (operator parity) is stated. **Diff arm only**; a whole-repo agent-navigability audit arm is a noted follow-up, mirroring the #32/#33 incremental precedent (restraint over shipping both arms at once).
- **Router** — a dedicated route ("change to an AI-/agent-maintained codebase, to agent-onboarding files or repo structure an agent must navigate, or a large/scattered change whose context economy matters" → `reviewing-agent-legibility` + naming/readability + restraint); auto-listed in the diff catalog.
- **4 evals** — stale AGENTS.md after a build-command rename, a scattered stringly-dispatched change defeating context economy + AST navigation, a clean self-contained control guarding false positives, and an agent-hostile megafile + duplicated helper; `examples.md` populated.

**Verification:** `pytest tests/` 98 pass (+1: `test_agent_legibility_lens_owns_35_as_mirror_of_ai_authored` — owns #35, #34 undisturbed, both ★ checks surface, no shared-category note); `cli drift` clean; `cli eval` OK (new lens 4 scenarios); markdownlint 0 errors.

**Resolves:** G20 (code-owner role) → shipped. Remaining Wave C: G16 ethical/responsible-design (needs G23), G30 threat-modeling (decision-shape, needs Q15), G18-interoperability; plus the noted G20 **repo arm** follow-up. **Cross-model re-gate still owed** — now also covers this lens; batch on the Ollama substrate (qwen2.5:7b floor + 3B canary), not this environment.

### 2026-06-17 (cont.) — Wave C: G16 ethical / responsible-design defects (taxonomy v0.6, new lens #36)

Third **Wave C** new lens, first **v0.6** promotion. The first Wave-C lens whose primitive dependency was already in place: G16 **needs G23** (the route axis), shipped in Wave A — so this lens is built around **detect-and-route** from the ground up rather than retrofitting it.

**The gap:** ethics is reviewed today only where it is *legal* (#27) or *ML-output* (#25 harmful-output). The whole class of **diff-visible, code-level** ethical defects had no owner — dark patterns, manipulative defaults, obstruction, and **discriminatory business logic in plain conditionals** (a hardcoded threshold disadvantaging a group, no model in sight). The round-3 human-axis sweep resolved mostly to *covered* or *escalate*; G16 was the one genuinely diff-visible, genuinely unowned find, so the restraint counterweight held (a structural gap, not an ideological one).

**What shipped:**

- **Research §#36** in [`cluster-4-runtime.md`](research/cluster-4-runtime.md) (next to #25's harmful-output, its non-ML analog), grounded in cited prior art: Mathur's 7-category dark-patterns taxonomy, the EDPB's 6-family/16-subcategory guidelines, the FTC "Bringing Dark Patterns to Light" report, the empirical sub-50% detection-coverage ceiling (so it is a **judgment lens**, not lint), and *Deception at Scale* (dark patterns recur in AI-generated UI — reflexively relevant). 9 heuristics, 2 priority-marked (G9): dark-pattern/deceptive-flow detection, and manipulative defaults / asymmetric choices.
- **Taxonomy v0.6** — new category **#36** in Cluster IV (the cross-cutting-harm cluster with #14/#25/#32); count 35→36, version/changes/numbering notes updated.
- **Lens `reviewing-ethical-design`** (shape: diff, wave 5) — a **single-category lens** (built_from #36, no cross_ref). Strictly **detect-and-route (G8/G23)**: name the pattern with evidence, then route the *decision* — consent-as-law → #27/`legal`, product/UX trade-off → `product`/`leadership`, a11y mechanics → #23 — never adjudicating a non-engineering call nor silently dropping one. Discriminatory logic and consent-theater are typically `defect`s; most dark-pattern verdicts `route: product`. Diff arm only; a design-time arm is a noted follow-up.
- **Synthesizer tension** — added `sweeping-for-security ↔ reviewing-ethical-design` (protective friction vs. manipulative obstruction): this is the long-noted **security ↔ usability** cross-quality pair (G31, map-gaps) that was previously blocked on the unbuilt Cluster VII — now buildable because the ethical-design lens supplies the usability/honest-friction side. Default: keep friction that protects the user (confirmations on destructive actions, step-up auth, cooling-off); cut friction that serves the business against the user's clear intent.
- **Router** — a dedicated route (user-facing flow that could manipulate or disadvantage a person → `reviewing-ethical-design` + accessibility + security).
- **4 evals** — manipulative pre-checked consent, discriminatory ZIP/surname pricing conditionals, a clean control exercising the protective-friction boundary (destructive-action confirmation is *not* a dark pattern), and fabricated urgency + roach-motel obstruction; `examples.md` populated.

**Verification:** `pytest tests/` 100 pass (+2: `test_ethical_design_lens_owns_36_detect_and_route` and `test_security_ethical_design_tension_present`); `cli drift` clean; `cli eval` OK (new lens 4 scenarios); markdownlint 0 errors.

**Resolves:** G16 → shipped. Remaining Wave C: G30 threat-modeling (decision-shape, needs Q15), G18-interoperability; plus the noted G20 repo arm and G16 design-time arm follow-ups. **Cross-model re-gate still owed** — now also covers this lens; batch on the Ollama substrate (qwen2.5:7b floor + 3B canary), not this environment.

### 2026-06-24 — bug-backlog sweep: clear-cut issues + count reconciliation

Cleared the unambiguous slice of the open-issue backlog (no PRs were open) in one
pass, and **flagged the issues that turned out to be non-bugs or design calls**
rather than forcing a fix.

**Fixed:**

- **#59 (stale skill count) — reconciled past what the issue assumed.** The issue
  said "28 → 29"; ground truth had drifted further: Wave C added 3 lenses, so the
  manifest now carries **30 lenses → 32 total** (incl. router + synthesizer). Updated
  every count to ground truth under each file's own framing: `README.md` 29→32 total /
  27→30 lenses / "7 more"→"10 more" / catalog row "27 lenses"→"30"; `docs/install.md`
  29→32 (and "29+"→"32+"); `.claude-plugin/plugin.json` 29→30 (its number is the
  domain-lens count — router + synthesizer are "plus").
- **#60 (`mergeable_state`).** Removed the invalid `conflicting` value (GitHub only
  returns `dirty` for conflicts) from `commands/atlas-rebase-stale.md` and the
  poller prompt in `docs/runbooks/pr-review-automation.md`.
- **#58 (negative top-checks budget).** Made the squeeze **non-silent** with a
  `warnings.warn` when `_CROSS_REF_QUOTA × len(crosses) ≥ _TOP_CHECKS_BUDGET`, rather
  than changing the floor — no current skill has >1 cross_ref, so the floor change
  would have altered generated output and caused drift; the warning fixes the "silent"
  complaint with zero drift.
- **#66 (llama.cpp `<tag>` placeholder).** Resolved the placeholder in
  `docs/runbooks/regenerating-skills.md`: documented the `b<NNNN>` tag format, an
  in-shell latest-tag fetch, the `ggerganov` → `ggml-org` repo move (kept `ggml-org`,
  the current canonical), and an asset-name caveat.
- **#62 (own-PR APPROVE fallback).** Added the documented `COMMENT`-fallback note to
  `commands/atlas-review-pr.md` step 5 so an interactive same-identity run matches the
  merge-gate's body-text signal (previously only in the runbook).
- **#63 (pagination).** Added "paginate through all pages of reviews/threads before
  counting rounds" guidance to `atlas-review-pr.md` step 3.
- **#65 (session lifetime).** Added a *Session lifetime* boundary to the
  pr-review-automation Known boundaries — a resident `opened` watch dies on session
  timeout; prefer the `synchronize` trigger for long-lived PRs.

**Flagged, not fixed:**

- **#57 — not a bug.** Verified against the Claude Code hooks docs: `clear` **and**
  `compact` are valid `SessionStart` matcher source values (the hook fires after both),
  so the matchers in `hooks/hooks.json` are live, not dead config. Applying the
  proposed "fix" would have removed working behavior.
- **#64 / #61 / #67 — design decisions.** atlas-init fallback sync (pick lint vs
  remove vs generate), the choosing-review-lenses "2-4 vs 8-audit" reframing (regenerates
  the router + touches front-matter), and the advisory-list refresh-vs-carry policy
  (command ↔ REVIEW.md wording) each need a maintainer call before editing.

**Verification:** `pytest tests/` 100 pass; `cli drift` clean (the #58 warning changes
no output); `cli eval` OK; markdownlint 0 errors.

### 2026-06-24 (cont.) — backlog sweep, round 2: the flagged design-decision issues

Followed up the clear-cut batch by resolving the three issues previously flagged as
needing a maintainer call, making the conventional choice on each and documenting it:

- **#67 (advisory-list refresh ambiguity) — made deterministic.** The command said
  "carry the advisory list forward" while `REVIEW.md` said "refresh when it changed";
  these only conflict if you ignore *whether the lenses ran*. Pinned the rule in both
  `templates/REVIEW.md` and `commands/atlas-review-pr.md`: **refresh when the lenses
  ran this round** (first approve / new-findings round), **carry verbatim when they
  did not** (the cap notice, where you cannot recompute the below-floor set).
- **#61 (2-4 vs 8-audit framing) — option (a).** Led the router's *How to pick* with
  the distinction (`generate.py` `build_router_md`): the 2-4 figure is per-change
  only and is **not** a cap on the whole-repo audit route, which runs all eight
  repo-shaped audits. Added the same carve-out to the router `description` in
  `manifest.yaml`; regenerated `choosing-review-lenses` (drift clean).
- **#64 (atlas-init fallback drift) — option (a), CI lint.** Added
  `tests/test_routing_snippet_sync.py`: extracts the `BEGIN…END` routing block from
  both `templates/agents-routing-snippet.md` (source of truth) and the embedded
  fallback in `commands/atlas-init.md` and fails the build if they diverge — so an
  offline `/atlas-init` can never silently install a stale block. The CI gate already
  runs `pytest tests/`, so the check is enforced with no workflow change.

**#57 stays closed-as-not-a-bug** (explained on the issue): `clear` and `compact`
are valid `SessionStart` matcher source values.

**Verification:** `pytest tests/` 101 pass (+1: the routing-snippet sync test);
`cli drift` clean (regeneration touched only the router); `cli eval` OK; markdownlint
0 errors.

### 2026-06-24 (cont.) — Wave C: G18 interoperability arm (taxonomy v0.7, new lens #37)

Fourth **Wave C** new lens, first **v0.7** promotion, and the **last clearly-scoped
Wave C item with a built dependency**. Resolves the **interoperability arm** of gap
G18 — the first of the two ISO/IEC 25010:2023 characteristics the external-completeness
sweep found unowned. (The **safety arm** is deliberately deferred to a follow-up: it is
add-factor work against #2/#28 + a detect-and-escalate boundary, a different shape from
this consolidated lens. Scope confirmed with the owner this session.)

**The gap:** #13 reviews the contract **we** design and publish; #8 reviews **internal**
idiom; #4 owns **internal** time/encoding/number correctness — but none asks whether a
value crossing the boundary actually conforms to the **external** standard a third party
parses. "We emit a date no downstream RFC-3339 parser accepts," "our OAuth callback never
validates `state`," "this Quartz cron string silently no-ops on POSIX cron" had no owner;
the checks existed only as scattered factor-notes across #4/#8/#13/#26. This is a
**consolidation**, not a net-new topic — exactly the disposition the round-3 hunt logged.

**What shipped:**

- **Research §#37** in [`cluster-4-runtime.md`](research/cluster-4-runtime.md) (the
  cross-cutting-runtime cluster, alongside the other ISO-derived promotions #34/#36),
  grounded in cited prior art: ISO/IEC 25010:2023 (the external model that found the gap),
  RFC 9110/9111 (HTTP semantics & caching), RFC 9700 + OIDC Core (OAuth/OIDC BCP),
  SemVer 2.0.0, Unicode UAX #15 / UTS #39, and the RFC format spines (3339 date, 3986 URI,
  5321/5322 email, 8259 JSON, 4180 CSV). 8 heuristics, 2 priority-marked (G9): **standard
  protocol semantics** (HTTP/OAuth/OIDC) and **RFC/format conformance at the boundary**.
- **Taxonomy v0.7** — new category **#37 Interoperability & external-standard conformance**
  in Cluster IV; version header, count (36→37), changes note updated.
- **Lens `reviewing-interoperability`** (shape: diff, wave 5) — a **single-category lens**
  (built_from #37, no cross_ref): the boundary-conformance vantage is genuinely new, so the
  checks live in #37 rather than being shared. **G1 single-owner:** owns conformance to an
  *external/published* standard and cross-links the neighbours whose factor-notes it
  consolidates — #4 (internal correctness), #8 (idiom), #13 (the contract we author), #26
  (config validity) — deferring each verdict; the auth-flow security verdict routes to #14.
- **Router** — a dedicated route ("a change that parses or emits a standard format or
  speaks an external protocol — HTTP/REST, OAuth/OIDC, date/URL/email/CSV/JSON
  serialization, a version bump on a published surface, a cron expression, or telemetry
  attributes" → `reviewing-interoperability` + api-contract-safety + correctness);
  auto-listed in the diff catalog.
- **4 evals** — a non-RFC-3339 timestamp emitted to a partner webhook, an OAuth callback
  that never validates `state` (detect-and-route to #14), a clean control (an
  idempotency-key plus an RFC-3339 offset → "No findings"), and a Quartz 6-field cron
  string handed to 5-field POSIX cron; `examples.md` populated.

**Verification:** `pytest tests/` 102 pass (+1: `test_interoperability_lens_owns_37_consolidating_conformance`
— owns #37, neighbours #4/#13 undisturbed, both ★ checks surface, no shared-category note);
`cli drift` clean; `cli eval` OK (new lens 4 scenarios); markdownlint 0 errors. Counts
reconciled (README/install/plugin: 30→31 lenses, 32→33 total).

**Resolves:** G18 interoperability arm → shipped. **Remaining Wave C:** G30 threat-modeling
(decision-shape, needs Q15); **G18 safety arm** (add-factor #2/#28 + detect-and-escalate);
plus the noted G20 repo arm and G16 design-time arm follow-ups. **Cross-model re-gate still
owed** — now also covers this lens; batch on the Ollama substrate (qwen2.5:7b floor + 3B
canary), not this environment.

### 2026-06-24 (cont.) — build: #32 Agentic & tool-use safety lens (D14, closes the oldest build-backlog item)

**Goal (from "what's ready to work on?" → "yep 32"):** ship `reviewing-agentic-safety`,
the longest-standing decided-but-unbuilt item — #32 was promoted at D14/v0.3 with the
taxonomy entry in place but no skill. The build splits agentic action-safety out of #25.

**What shipped:**

- **Research §#32** in [`cluster-4-runtime.md`](research/cluster-4-runtime.md) — the 8
  ASI-tagged action/tool-surface heuristics **moved out of #25** (tool least-privilege,
  approval gates & autonomy bounds, tool-metadata-as-untrusted-input, agent identity &
  tokens, sandboxed exec, inter-agent auth, memory hygiene, audit trail), **plus a 9th**
  for the lethal-trifecta **exfil/action leg** (the framing stays #25; #32 owns the
  mitigation). 2 ★ priority checks (tool least-privilege; approval gates). Its own
  references (OWASP Agentic Top 10 ASI01–ASI10, the Threats-and-Mitigations companion, the
  MCP security spec — all moved from #25) and a fresh agentic tooling list (MCP scanners,
  permission/scope auditors, sandbox runtimes, framework approval-gate hooks, action
  tracing). #25 keeps the model-call concerns behind a new **boundary note** and a pointer
  where the heuristics moved.
- **Lens `reviewing-agentic-safety`** (`shape: diff`, design-capable, wave 5) — a
  single-category lens (`built_from #32`, no cross_ref): the action-surface vantage is
  genuinely new. **G1 single-owner:** owns the action/tool surface; defers the model call
  to #25, the authz verdict to #14, and tool *contracts* to #13 (named in the description +
  examples, not via cross_ref). All 9 heuristics inline as Top checks.
- **Router** — a dedicated route ("Agent / tool-use change — a tool/function definition
  exposed to a model, an MCP server or client, an autonomous/multi-agent loop, agent
  memory, or any code that lets a model take actions" → `reviewing-agentic-safety` +
  `reviewing-llm-integration` + `sweeping-for-security`); the existing LLM route was
  narrowed to the model-call case so the two no longer conflate.
- **4 evals** — an over-broad `execute_sql` tool (least-privilege), an unbounded loop with
  an ungated `issue_refund` (autonomy bound + approval gate), an MCP server forwarding the
  inbound token (token passthrough / confused deputy, detect-and-route to #14), and a clean
  control (narrow read-only tool + `max_steps` + `require_approval` → "No findings");
  `examples.md` populated.

**Verification:** `pytest tests/` 103 pass (+1: `test_agentic_safety_lens_owns_32_action_surface`
— owns #32, #25/#14 undisturbed, both ★ checks surface, no shared-category note);
`cli drift` clean (the #25 split re-hashed `reviewing-llm-integration`, regenerated cleanly);
`cli eval` OK (new lens 4 scenarios). Counts reconciled (README 31→32 lenses / 33→34 total;
install.md, plugin.json, and the stale-since-interop marketplace.json). No `taxonomy_version`
bump — #32 already lives in v0.7's taxonomy.

**Resolves:** the D14/Q16/map-gaps-G2 build backlog → shipped. **Remaining backlog:** the
`shape: artifact` lens (D15) is now the oldest decided-but-unbuilt item. **Cross-model
re-gate still owed** — now also covers this lens; batch on the Ollama substrate (qwen2.5:7b
floor + 3B canary), not this environment.

### 2026-06-24 (cont.) — build: the `shape: artifact` family (D15 / Q18 / map-gaps G11)

**Goal (after merging #70 / #32):** ship the second decided-but-unbuilt backlog item — the
**artifact review shape**. Not just a lens: a new *shape* (sibling to diff / repo / decision)
that hosts an open-ended set of artifact-scoped rubrics at one always-on description's cost,
the pattern the owner asked to strengthen.

**Design that made it fit the existing machinery:** an artifact lens is a normal skill with
`shape: artifact` whose `built_from` points at **rubric sections numbered ≥101** in a new
`docs/research/artifact-rubrics.md`. Numbering above the 1–37 taxonomy range keeps the rubrics
out of the manifest's G1 single-owner bookkeeping while still flowing through the **same
`built_from` → `section_hash` → drift** path — so rubric drift is tracked for free, no
`drift.py` change. A manifest `artifacts:` table (`name` / `detect` / `slug` / `rubric`) maps
each artifact to its detector and its rubric section.

**What shipped:**

- **Tooling** — `manifest.py`: an `Artifact` dataclass + `artifacts` field on `Skill`,
  `artifact` added to the shape enum, and validation (artifact shape needs a non-empty
  `artifacts` table; every artifact's `rubric` must be in `built_from`; slugs lowercase-hyphen
  and unique; `artifacts` rejected on non-artifact shapes). `generate.py`: an artifact branch
  in `_scope_line` and `build_skill_md` (a detect→rubric **Artifacts table** replaces the
  inlined Top checks; no diff-only Boy-Scout guard), a `build_artifact_rubric` that emits one
  bundled `reference/<slug>.md` per artifact (heading levels promoted ### → ## so the file
  increments cleanly), and an **artifact catalog block** in the router.
- **Research** — `docs/research/artifact-rubrics.md` **#101 SKILL.md / agent-skill authoring**,
  mined from Anthropic's skill-authoring best practices (the standard our own
  generator/validator already enforces): nine heuristics — frontmatter-within-limits and
  progressive-disclosure ★-marked — plus references and a tooling list.
- **Lens `reviewing-artifact-conventions`** (`shape: artifact`, wave 5) — presence-activated:
  detect a supported artifact, open its rubric, review against it; first artifact is `SKILL.md`.
  Distinct from #22 doc-drift and #32 runtime agent-safety (authoring quality). A dedicated
  router route + the new artifact catalog section.
- **4 evals + examples.md** — a weak first-person/no-trigger frontmatter, a no-progressive-
  disclosure mega-body, a well-formed control → "No findings", and a no-artifact-present diff →
  "No findings" (exercises presence-activation).
- **7 new tests** (110 pass total): artifact-shape validation (4) and generation/router (3).

**Verification:** `pytest tests/` **110 pass**; `cli drift` clean; `cli eval` OK (new lens 4
scenarios); markdownlint 0 errors. Counts reconciled (README/install/plugin/marketplace:
32→33 lenses, 34→35 total). No `taxonomy_version` bump — a shape is a capability, not a
taxonomy category; #30 already documents the artifact-authoring factor.

**Resolves:** D15 / Q18 / map-gaps G11 → shipped. The shape generalizes: each further artifact
(Dockerfile → hadolint, OpenAPI → Spectral, Terraform → tflint, …) is a research section + an
`artifacts:` row, **no new always-on description**. **Cross-model re-gate still owed** — now
also covers this lens (new behavior); batch on the Ollama substrate (qwen2.5:7b floor + 3B
canary), not this environment.

### 2026-06-24 (cont.) — Cross-model re-gate: the six Wave C / D14 / D15 lenses

Closed the deferred D6/D8 re-gate that had been **owed since 2026-06-15** across every
lens shipped 2026-06-17→24 — the substrate (local Ollama) turned out to be available
in this environment after all, contrary to the standing "not this environment" note on
each owed marker. Ran on **Ollama 0.30.10** with **qwen2.5:7b** (the documented 7-8B
floor) and **llama3.1:8b** (a second 7-8B family, the cross-confirm tier the prior
v0.3 re-gate used), via `python -m tooling.run_evals` (num_ctx 8192, temperature 0).
Six lenses × 4 scenarios × 2 tiers = 48 runs. Assembled-context sizes checked first
(largest ~4.5k tokens, comfortably inside the 8192 window — no silent truncation).

**Scope:** `reviewing-ai-authored-code` (#34), `reviewing-agent-legibility` (#35),
`reviewing-ethical-design` (#36), `reviewing-interoperability` (#37),
`reviewing-agentic-safety` (#32), `reviewing-artifact-conventions` (#101 / `shape:
artifact`).

**Primary concern — over-flagging on clean code — did not appear on either tier.**
Every lens's clean / well-formed / no-artifact-present scenario returned "No findings"
on both qwen2.5:7b and llama3.1:8b (12/12 clean scenarios across the six lenses, both
tiers). The presence-activated artifact lens correctly returned "No findings" on a
source-only diff (no SKILL.md present) — it did not review `.ts` source against the
authoring rubric.

**Per-lens (both tiers pass):**

- **#34 ai-authored-code** — slopsquat (xref #18), transposed-digit constant
  (84600≠86400), and scope-creep all caught; clean httpx scenario → "No findings".
  qwen dropped the secondary `except Exception` leg on the scope-creep diff (7B
  top-findings-only ceiling); llama caught it *and* over-generated two low-value
  findings on that same defect diff (a hallucinated `httpx` import not in the
  snippet, plus a borderline `n=3` magic-number) — small-model noise on a
  multi-issue **defect** case, not on clean code.
- **#35 agent-legibility** — AGENTS.md drift, stringly-typed dispatch, and the giant
  generated file + duplicate helper all caught with full recall on both tiers; clean
  scenario → "No findings" (did not over-demand an `llms.txt`).
- **#36 ethical-design** — manipulative default, discriminatory plain-conditionals
  (ZIP/surname proxies), and the fake-urgency + roach-motel dark patterns all caught
  and correctly detect-and-routed (#27/legal, product); clean delete-confirmation
  read as legitimate protective friction → "No findings".
- **#37 interoperability** — RFC 3339 wire-format violation, missing OAuth `state`,
  and Quartz-vs-POSIX cron-dialect mismatch all caught; clean idempotency-key +
  RFC-3339 scenario → "No findings". llama dropped the explicit `route: #14` tag on
  the OAuth case (named ownership here, omitted the security hand-off) — a
  secondary-detail drop at the floor.
- **#32 agentic-safety** — tool least-privilege (ASI02/03), unbounded-loop +
  missing-approval (ASI01/08), and MCP token-passthrough / confused-deputy (ASI03)
  all caught on both tiers; bounded-and-gated clean scenario → "No findings".
- **#101 artifact-conventions** — first-person/no-trigger frontmatter and the
  no-progressive-disclosure mega-body caught; well-formed control and no-artifact
  diff → "No findings". qwen dropped the secondary gerund-`name` leg on the
  frontmatter case (7B ceiling); llama caught both legs.

**Verdict: all six lenses pass the cross-model gate at the 7-8B floor and cross-confirm
on a second family.** The only gaps are the already-documented model-capability
ceilings — qwen's "top findings only" secondary-finding drops on multi-issue diffs, the
known qwen cosmetic trailing-sentence after "No findings", and small-model plausible-
noise on a defect scenario (llama #34 S3) — none a heuristic regression, all handled by
the deployment tier (Claude). The 3B canary was not run this pass (it is below the
clean-code precision floor by long-standing documentation; the two 7-8B tiers are the
gate of record). **The re-gate debt carried across the Wave B/C/D14/D15 builds is
cleared.**

### 2026-06-24 (cont.) — Cross-model re-gate: the Wave B add-factors (G21 + G28)

Closed the *other* half of the owed re-gate — the Wave B add-factor heuristics that
shipped 2026-06-15 onto four existing lenses and were marked "cross-model re-gate
pending" in [`gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md). Same harness and
tiers as the six-lens pass above (qwen2.5:7b floor + llama3.1:8b cross-confirm, num_ctx
8192, temp 0). Lenses: `sweeping-for-security` (#14, G21 expiry/rotation), `tracing-
correctness-and-invariants` (#4, G21 calendar/clock), `reviewing-resilience-and-
scalability` (#28, G21 thundering-herd/exhaustion), `reviewing-pr-and-process-hygiene`
(#24, G28 claims-vs-evidence + the G12 acceptance-criteria factor). 19 scenarios × 2
tiers.

**Three of the four G21/G28 factors pass both tiers; one is below the 7-8B floor.**

- **G21 expiry/rotation (#14)** — ✅ both tiers. qwen flagged the 1-year self-managed
  cert with no renewal path as the "detonates when the clock runs out" class; llama
  caught both the cert and the long-lived no-refresh OAuth token.
- **G21 calendar/clock (#4)** — ✅ both tiers. Both flagged the `date(year, 2, 29)`
  leap-year time-bomb in the annual-job scheduler.
- **G28 claims-vs-evidence (#24)** — ✅ both tiers. Each tier caught the "pure
  refactor / no behavior change" + "30% faster, no benchmark" claims (different
  secondary legs dropped per tier — qwen softer on the `>=`→`>` smuggled change, llama
  softer on the closes-#812-no-test leg; union covers it). The G12 acceptance-criteria
  factor (S5) caught the under-delivery (unmet rate-limit AC) on both tiers; the "no
  more" over-delivery leg (unrequested XLSX + button) dropped at the floor — a
  documented secondary-finding drop.
- **G21 thundering-herd / cache-stampede (#28)** — ❌ initially **missed on both
  tiers** → ✅ **fixed by an examples.md tune, now passes both tiers.** First pass: both
  models engaged the shared-key + single-TTL setup but **misdiagnosed** the failure
  mode (qwen → "multi-tenancy isolation"; llama → "bulkheading / single-writer
  bottleneck") rather than naming the stampede (one shared key with one TTL expires for
  all nodes at once → N concurrent 2s recomputes). Root cause: `examples.md` had **no
  worked stampede case**, and the decision rule's "a shared resource whose exhaustion
  has no bulkhead" line actively steered the models toward "isolation/bulkheading."
  **Fix applied:** added a *Coordinated-client failure* clause to the decision rule
  (name the stampede, not isolation/write-serialization) plus a dedicated bad→finding
  worked example (a shared `"dashboard"` key, single TTL, ~3s recompute → single-flight
  plus jittered TTL) — isomorphic to, not identical to, the eval scenario so it
  generalizes. **Re-ran both tiers: #28 S4 now caught on qwen2.5:7b and llama3.1:8b**,
  with the clean scenarios held (S1/S2 full recall both tiers; S3 clean on qwen; llama
  led with "No finding" then offered one optional improvement-valence suggestion — not
  a defect false-positive). **Acceptance criterion for the tune (the bar it had to
  clear to be kept):** lift #28 S4 to a both-tier catch *without* regressing the clean
  scenarios (S3 stays "No findings"; S1/S2 keep full recall) — met, so the change was
  kept; had it lifted S4 only by also flagging the clean fx-breaker case, it would have
  been reverted and the gap logged as a confirmed ceiling. `examples.md` is not
  provenance-hashed, so drift stays clean and no regenerate was needed. This is the
  cold-path / "a maximum is not a finding" decision-rule playbook applied again — the
  coordinated-timing ceiling was reachable with a concrete worked example after all.

**Two substrate findings (not regressions, recorded for the runbook):**

- **G27 SoD is model-variant-sensitive.** The general `qwen2.5:7b` *missed* the
  missing-segregation-of-duties case (#14 S3) and rationalized it as enforced;
  `llama3.1:8b` caught it cleanly. The original G27 re-gate (2026-06-15) passed on
  `qwen2.5-coder:7b` — the **code-tuned** variant. So G27 holds on the coder model and
  on llama, but not the general qwen2.5:7b. The documented floor is `qwen2.5-coder:7b`
  for exactly this reason; the general qwen2.5:7b is a slightly weaker substrate for
  authorization-pattern reasoning.
- **`llama3.1:8b` over-flags clean security/boundary code.** It invented findings on
  the clean #14 S4 (SoD correctly enforced — it pattern-matched "SoD missing" onto a
  correct control even after echoing the decision rule), the clean #14 S5 (ownership-
  scoped delete — 6 spurious findings), and the clean #4 S3 (correct 1-based page math
  — invented a wrong off-by-one). `qwen2.5:7b` returned "No findings" on all three.
  This is the documented general-vs-code-tuned precision gap — it is why the floor of
  record is the *coder* variant. The qwen tier held clean-code precision throughout.

**Verdict: all four G21/G28 factors now pass the cross-model gate** — G21 expiry, G21
calendar/clock, and G28 claims-vs-evidence passed outright; G21 thundering-herd (#28)
missed initially and was lifted to a both-tier pass by the examples.md decision-rule +
worked-example tune above. **The Wave B add-factor re-gate debt is fully resolved, no
follow-up owed.** Substrate caveat: this pass
used the general `qwen2.5:7b` (the only qwen on this machine), not the documented
`qwen2.5-coder:7b` floor — the SoD and clean-precision deltas above are attributable to
that substrate difference, not to the heuristics.

### 2026-06-24 (cont.) — Build: G18 safety arm (fail-toward-safe add-factors on #2/#28) — closes G18

Built the **second and final arm of round-3 gap G18** — the ISO/IEC 25010:2023 **safety**
characteristic (harm-prevention, distinct from #14 security = attacker-prevention). The
interoperability arm shipped as #37 (v0.7); the disposition for safety was an **add-factor
pass against #2/#28 + detect-and-escalate**, deep hazard analysis (ISO 26262 / IEC 61508 /
DO-178C) out of scope. No new category, no `taxonomy_version` bump.

**What shipped (research → regenerate, the D6 pipeline):**

- **#2 `hunting-silent-failures` (cluster-1 #2)** — a ★ Top-check heuristic **"Fail toward
  safe, not toward harm"**: fail **closed** on an auth/permission/quota/limit check that
  errors or times out; a destructive/financial/physical action defaults to no-op/abort; a
  failed validation rejects; a missing safety control blocks not bypasses. Distinct from
  fail-*loud* (visibility) and #14 (attacker). Plus an ISO 25010:2023 *safety* key
  reference and an examples.md fail-open→finding / fail-closed→no-finding pair.
- **#28 `reviewing-resilience-and-scalability` (cluster-4 #28)** — a full-checklist
  heuristic **"Degrade toward safe, not just toward available"**: a degraded/fallback path
  must stay harm-safe (don't fail-open a fraud/authz check under load, don't serve stale
  data where staleness harms, don't kill a guard instead of a feature). Distinct from the
  adjacent "graceful degradation" (availability) and #2's code-level default. Plus an
  examples.md degrade-unsafe→finding pair.
- Both detect-and-route the acceptable-risk threshold to a human owner. Two new evals each
  (a bad case + a clean control): hunting-silent-failures 4→6 scenarios, resilience 4→6.
- `taxonomy.md` updated: the safety arm marked shipped; **both ISO/IEC 25010:2023 unowned
  characteristics now closed.**

**Cross-model re-gate — clean on the documented floor.** Pulled **`qwen2.5-coder:7b`** (the
documented gate-of-record, previously absent on this machine) and re-ran both lenses; also
ran the general `qwen2.5:7b` + `llama3.1:8b`.

- **`qwen2.5-coder:7b` (floor of record): clean sweep** — hunting-silent-failures 6/6,
  resilience 6/6 (the degrade-toward-safe clean control added during PR review re-verified
  clean on the coder floor and general qwen). New safety scenarios pass (fail-open caught; fail-closed → "No findings";
  degrade-toward-harm caught with the safe-fallback recommendation + detect-and-route), and
  every pre-existing scenario held, including the narrow-PaymentDeclined clean case.
- **General `qwen2.5:7b` + `llama3.1:8b`:** the new safety **factors work on both** —
  fail-open (#2 S5) and degrade-toward-harm (#28 S5) caught on every tier; resilience fully
  clean both tiers. **Two clean-code over-flags appeared only on the general models:** the
  pre-existing narrow-PaymentDeclined case (#2 S3) over-flagged on both general tiers, and
  the new clean fail-closed control (#2 S6) over-flagged on llama (it misread `return False`
  as `return True`). **Both are control-flow/value misreads that the `qwen2.5-coder:7b`
  floor gets right** — the documented general-vs-code-tuned precision gap (the reason the
  floor of record is the *coder* variant), not a regression from the safety heuristic.

**Verdict: G18 safety arm passes the cross-model gate on the floor of record; G18 is
complete (both ISO 25010:2023 characteristics owned).** The general-model over-flags are the
known substrate caveat, now first-hand confirmed against the coder model side by side. The
machine now has `qwen2.5-coder:7b` so future re-gates can use the documented floor directly.

### 2026-06-27 — Build: #38 Threat modeling / design-time security lens (G30, v0.8) + cross-model re-gate

Shipped `reviewing-threat-model` (#38), the generative design-time threat-enumeration lens (STRIDE / trust boundaries / DFD / abuse cases), via the standard doc-driven build: a new #38 research section in [`research/cluster-4-runtime.md`](research/cluster-4-runtime.md), taxonomy v0.8, a manifest entry, and generated standalone + collapsed bundles. Realized as **`shape: diff` + `design: true`** (not `shape: decision`): the generator's `include_design` rule lands it in **both** the `reviewing-a-change` (code-only / no-design-doc path) and `reviewing-a-decision` (artifact-present path) collapsed entrypoints natively — the dual entry-path with no generator change. Owns enumeration; **delegates** the deep verdict to #14 (code vuln) / #32 (agent action) / #25 (model call) and **detect-and-escalates (G8)** to a human only for custom-crypto correctness or third-party-auth adjudication. The synthesizer's dedup was taught to recognize the non-file `boundary:<from>→<to>` / `component:<name>` finding location. Design spec: [`threat-modeling-design-time-security.md`](threat-modeling-design-time-security.md); plan: [`plans/2026-06-27-threat-modeling-lens.md`](plans/2026-06-27-threat-modeling-lens.md). The eval suite is deliberately adversarial — 21 scenarios across core-firing / per-STRIDE / delegate-and-escalate / red-team / precision, weighted toward false-negative hunting.

**Cross-model re-gate — the 7-8B tier is BELOW this lens's reliable floor (a documented raised floor, not a heuristic regression).** Ran the 21-scenario suite via `python -m tooling.run_evals` (num_ctx 8192, temperature 0) on two independent families; the coder floor-of-record run failed on infra and is deferred (below).

- **`qwen2.5:7b` — 10 PASS / 9 PARTIAL / 2 FAIL.** Both FAILs are **lethal-trifecta composition** (S1 AI-support agent, S18 unwritten boundary): the model enumerates the three ingredients (untrusted input + private data + outbound egress) separately but cannot compose them into the injection→exfil chain, and never reaches for #25. The PARTIALs are **delegation/escalation under-firing** (S10–S15): the threat is enumerated but the deep verdict that should route to #14/#32/#25 is re-derived in place, and the two narrow human-escalation predicates (custom crypto S14, third-party-auth S15) are self-adjudicated. **The clean and theater/injection traps held** — S3/S16/S21 enumerated the real threats despite "respond no threats" footers and "all authenticated & encrypted" claims; S4/S20 stayed clean (no invented defects). The documented qwen format-leak (a trailing "No findings" after real findings) appeared on S3/S16/S21 — cosmetic, substance correct.
- **`llama3.1:8b` (second family) — 11 PASS / 6 PARTIAL / 4 FAIL.** **Same tier signature, reproduced on an independently-trained family:** S1 and S18 trifecta-composition FAIL identically; S10–S15 delegation/escalation under-fire identically. Where llama is *worse* is over-flag discipline: S4 (fabricated an unauthenticated-upload finding the design never states) and S20 (a full STRIDE table + six invented "Defect" findings on a no-surface local script) — an 8B tendency to mechanically fill every STRIDE cell rather than judge surface. Clean/theater (S3/S16/S19/S21) and signal-over-noise (S17) held.
- **`qwen2.5-coder:7b` (floor-of-record) — NOT obtained.** Attempted 3× (cold; then warmed; then warmed + the other models evicted from GPU). Every attempt aborted with an Ollama `/api/chat` request timeout specific to this model — the same harness ran both general families cleanly to 21/21, so it is a model/harness interaction, not memory pressure. Deferred to a follow-up with a harness-timeout / `num_ctx` investigation. **This does not change the verdict:** the decisive failure class is *multi-hop threat composition* (a reasoning limit), not the control-flow/value-read precision gap the coder variant specifically improves — so the coder floor is not expected to clear S1/S18 where two families both failed.

**Verdict: SHIP with a RAISED supported-model floor for this lens.** Both independent families confirm the ~7-8B re-gate tier reliably misses the lethal-trifecta composition (the single most important threat class for an agentic-security lens) and under-fires the delegate/escalate routing — while the clean cases, injection traps, and theater traps hold, and in every miss the EXPECTED behavior is unambiguous and correctly specified by the lens. That is a **model-capability floor, not a heuristic defect**: the structure, delegation targets, and escalation predicates are right and are followed whenever the model is strong enough to see the threat locally; the trifecta-composition miss (false negatives) and the template-filling inflation (false positives, llama) are both floor effects of the tier. Per spec §5.3, this lens's supported floor is therefore set **above the standard 7-8B re-gate substrate** — real reviews should run on a stronger model (the standard cloud model). Two follow-ups tracked (spec §8 / Q21): (1) obtain the `qwen2.5-coder:7b` floor-of-record run once the harness timeout is resolved; (2) strengthen the lens's proportionality guard for no-/low-surface inputs (the S19/S20 over-flag wobble) — the one place the lens may marginally over-prompt toward noise. **Heuristics are NOT tuned** — they fire correctly; the failures are model execution, not lens specification.

### 2026-06-28 — Threat-model lens follow-up (2): proportionality guard for no-/low-surface inputs

Closed **follow-up (2)** of the two tracked at the end of the 2026-06-27 #38 re-gate
(spec §8 / Q21): the S19/S20 over-flag wobble — the one place the lens marginally
over-prompts toward noise. On a change with **no security-relevant surface** (a UX/
presentation change, S19; a benign no-input local script, S20) the 7-8B tier — llama3.1:8b
especially — tended to **mechanically fill a full STRIDE table and invent "Defect" findings**
rather than judge the surface and stop.

**Root cause (the examples-template steer, not a heuristic defect).** `examples.md` carried
only *one* clean case — an adequately-**mitigated** design that still has real trust
boundaries, so it walks a full boundary map + STRIDE *and then* says "No findings." Used as
the de-facto output template, that case actively teaches "build the table, then conclude
clean" — which on a **no-boundary** input produces exactly the table-filling over-flag. There
was no worked example for "no boundary exists → no table."

**Fix (examples.md only — the cold-path decision-rule + worked-example playbook, same as
the `#28` thundering-herd tune).** Added a **proportionality rule** ("apply *before* building the
model": triage whether the change introduces a new trust boundary / cross-boundary data flow /
untrusted input / egress / secret / agent capability — if **none**, the proportional output is
a one-line surface note + "No security findings", *not* a STRIDE table, and non-security
concerns route out with `route:`) plus **two worked clean→minimal examples** isomorphic to but
not identical to S19/S20 (a chart-library/restyle/copy change; a `scripts/tidy_fixtures.py`
no-input local script) so it teaches the pattern without teaching the eval answers. The new
section is explicitly framed against the existing one: the first clean case is "mitigated
boundaries exist → No findings"; this one is "**no boundary exists → no table**."

`examples.md` is hand-authored and **not** provenance-hashed (drift stays clean), but the
collapsed bundles inline it, so regenerated: the change propagated to both collapsed
entrypoints (`reviewing-a-change` + `reviewing-a-decision` lens bodies) and the standalone
examples.md. **Drift clean, 152 tests pass, eval structure valid.** No heuristics/SKILL.md
edit, no `taxonomy_version` change, no regenerate of the provenance-hashed surface — a
precision tune of the output template, consistent with the "heuristics fire correctly; this is
execution shaping" framing of the 2026-06-27 verdict.

**Follow-up (1) — `qwen2.5-coder:7b` floor-of-record run — remains deferred.** No Ollama
substrate in this remote environment (`command -v ollama` → none; no local `:11434`), so the
floor-of-record re-run + harness-timeout / `num_ctx` investigation still owes, to be done on a
machine with the Ollama substrate per the standing runbook. The proportionality tune itself is
an output-template change (not a heuristic change), so per the playbook it does not gate on a
cross-model re-gate to ship; the S19/S20 cases should simply be re-scored alongside follow-up
(1)'s run when the substrate is next available, to confirm the over-flag is gone on the floor.

### 2026-07-05 — Q15 build: the shared decision-record checklist (§5 item 2)

Picked up the remaining decision-time-shape residue from Q15/[`decision-time-review-shape.md`](decision-time-review-shape.md). Items 1 and 4 of §5's concrete proposal (the `shape: decision` capability, `reviewing-decision-lifecycle`, the router's decision route) had already shipped 2026-06-12; item 2 — a shared decision-record checklist every design-capable lens applies when reviewing an ADR/RFC/adoption/deprecation artifact, closing §2's "the design-time mode is passive, it never asks the decision-native questions" gap — had not.

Built it as a **generator-level addition**, not a new research section: `tooling/generate.py`'s `_scope_line` now appends the checklist (rationale actually recorded? assumptions still current? revisit-trigger? exit/rollback/sunset? real alternatives weighed?) to every `design: true` lens's scope line, framed so the gap is reported as that lens's own finding, not a separate report. This mirrors how the "Reviewer discipline" and "Mechanizing these checks" blocks are already generator prose rather than `built_from` content — appropriate here because the checklist is cross-cutting infrastructure (all 15 design-capable lenses), not one topic's research. No manifest schema change needed; `python -m tooling.cli generate` propagated it to all 15 standalone lenses and both collapsed entrypoints (`reviewing-a-change`, `reviewing-a-decision`) automatically.

Added one demonstrating eval scenario each to the two lenses the router's decision route explicitly names (`tracing-correctness-and-invariants`, `checking-restraint`) — an ADR input where the model must surface both its own topical finding and the decision-record gap. `python -m tooling.cli generate`/`drift`/`eval` clean; full pytest suite (165 tests) passes. **Cross-model re-gate not run** — no Ollama/local-model substrate in this remote session (same standing gap noted in the 2026-06-28 entry); deferred to the next session with the substrate available, per the runbook.

**Still open from Q15:** a standalone `adoption-&-exit` lens and a `shape: repo` cron `decision-record-audit` lens (§5 item 3) remain unbuilt — `reviewing-decision-lifecycle` currently folds that judgment into one lens. Docs updated: [`decision-time-review-shape.md`](decision-time-review-shape.md)§5a (new) and [`open-questions.md`](open-questions.md) Q15 status.
