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
text carrying its own license terms. License decision (user): **dual MIT (code)
+ CC BY 4.0 (content)** — see D11. Added LICENSE / LICENSE-MIT /
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
only `acknowledge`d with a rationale that still surfaces). **Bootstrap = template
+ inference, but inference is proposal-only** — the inference skill emits a
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
#26 portability, #16 SLO, #6 symmetry/altitude, #21 change-amplification, #24
agent-native parity, #9 caller ergonomics, #4 numeric overflow. Noted the irony:
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
  + eval). So "re-enable / provision the missing scanner" was a false alarm.
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
#28 operational & resilience design, #30 enforcement apparatus & meta-artifacts,
#31 infrastructure-as-code (each: research section + skill + evals), and the ~10
add-factor regenerations (#16/#17/#19/#20/#22/#25/#27). Optional polish: a
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
