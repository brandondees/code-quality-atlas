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

- **G23 detect-and-route.** Added a `route:` axis (`eng | implementer | product | design | legal | leadership`) to the synthesizer finding contract, generalizing the G8 detect-and-escalate pattern into a map-wide principle: a holistic review *surfaces* every reviewable finding with evidence and *routes the decision* to its owner — never silently dropping a non-engineering call, never self-adjudicating one. New **Routed — decide outside engineering** report section; routed-outside-eng findings are escalated but do not set the engineering verdict.
- **G26 valence axis.** Added `valence: defect | improvement` to the contract. Refined the per-lens *Reviewer discipline* guard (in `generate.py`, so it regenerates across all ~26 lenses) from an absolute "do not suggest changes to correct code" into "**defect-only by default; improvements opt-in**." Improvements are admissible only as `nit`-severity, `route: implementer`, and must clear a **non-configurable anti-churn floor** (genuine-improvement bar + convergence/no-oscillation). New **Improvements — opt-in, optional** report section. Default behavior unchanged (strict); the team verbosity dial still depends on the Q13 overlay (designed, unbuilt).

**Verification:** `pytest tests/` 88 pass (added guard + contract assertions); `cli drift` clean (regenerated in sync); `cli eval` OK (2 new synthesizer scenarios — a product/design routed case, an improvement-valence + anti-churn case — for 6 total); markdownlint 0 errors. Cross-model eval re-gate pending (lighter than a new lens — mechanism/prose, not new judgment).

**Resolves:** G23, G26 dispositions → shipped; **Q3 largely resolved** (review/maintenance is a valence toggle, not a separate mode). Remaining Wave A: G19 (synthesizer coverage/limitations block), G31 (tensions enrichment), Q19 (mechanize-with nudge).
