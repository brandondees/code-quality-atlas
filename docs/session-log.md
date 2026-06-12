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
   #25. G2 updated; **promotion decision opened as Q14** (user call, D5-style).
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
