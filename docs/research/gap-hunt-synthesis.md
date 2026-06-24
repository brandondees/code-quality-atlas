# Gap-hunt synthesis — what to promote first (G12–G32)

**Status:** synthesis, 2026-06-14. **Decision-support, not decisions** — every item stays owner-gated; this only ranks and sequences the pile so the separate decision pass is tractable. Sources: [`map-gaps.md`](../map-gaps.md) G12–G32, [`open-questions.md`](../open-questions.md) (Q3/Q4/Q8/Q13/Q14/Q15/Q17/Q19) and the three round-3 research docs.
**How to read it:** each item is typed (**mechanism** / **new-lens** / **add-factor** / **tooling** / **enabling-build** / **fold**), scored value × cost × confidence, deduped against overlaps, and placed in a dependency-ordered wave. The headline is the **sequence**, not the scores.

## The pile at a glance (21 gaps + Q19)

| ID | One-line | Type | Lean | Value | Cost | Conf |
|---|---|---|---|---|---|---|
| **G23** | Detect-and-route (surfacing ≠ deciding) | mechanism | adopt | High | Low | High |
| **G26** | `valence: defect\|improvement` axis + anti-churn floor | mechanism | adopt | High | Low-Med | High |
| **G19** | Review-coverage transparency (a synthesizer "limitations" block) | mechanism | fold into D12 | Med | Low | High |
| **G31** | Enrich the restraint-centric tensions table (cross-quality pairs) | mechanism | enrich manifest | Med | Low | High |
| **Q19** | Ship the `mechanize-with:` nudge + coverage/perf/complexity presence | tooling | build | Med | Low | High |
| **G27** | Segregation of duties / maker-checker in authz | add-factor #14 | promote | High | Low | High |
| **G21** | Operational time-bombs (cert/credential expiry & rotation, calendar, exhaustion) | add-factor #4/#14/#26/#28 | promote | High | Low | High |
| **G25** | Upgrade green + FinOps to routed #15 factors | add-factor #15 | promote | Med | Low | High |
| **G28** | Claims-vs-evidence verification (generalized) | add-factor / principle | promote | Med-High | Low-Med | Med-High |
| **G29** | Root-cause vs symptom (band-aid detection) | add-factor #1/silent-failures | promote | Med | Low | Med |
| **G13** | *Tidy First?* economics + tidying *suggestions* (via G26) | add-factor #21/#24 | promote | Med | Low | Med |
| **G32** | Pre-existing/adjacent defects (Boy-Scout, attribution axis) | add-factor (opt-in) | promote | Med | Low | Med-High |
| **G18** | Interoperability (consolidate) + Safety (add-factor + escalate) | add-factor / new-lens | interop **✅ shipped** (v0.7, #37); safety pending | Med-High | Med | Med-High |
| **G12** | Acceptance-criteria / requirements traceability | new-lens / add-factor | promote | High | Med | Med |
| **G14** | Characteristic defects of AI-authored code | new-lens | **✅ shipped** (v0.4, #34) | High | Med | High |
| **G27→** | *(SoD listed above)* | | | | | |
| **G16** | Ethical / responsible-design (non-ML) | new-lens | **✅ shipped** (v0.6, #36) | High | Med | Med-High |
| **G20** | Codebase as a working environment for AI maintainers | new-lens | **✅ shipped** (v0.5, #35) | Med-High | Med | Med-High |
| **G30** | Threat modeling (STRIDE) as a design-time discipline | new-lens (decision-shape) | promote | High | Med-High | Med-High |
| **G24** | Cluster VII — Product, Experience & Value (10 lenses) | new-cluster | promote (incremental) | High | High | Med-High |
| **G17** | Data-engineering & data-contract quality | new-lens (paired) | promote | High | High | Med-High |
| **G22** | Diff-isolation blindness (interaction/composition) | new-lens (scoped) | promote (scoped) | Med-High | High | Med |
| **G15** | Production-evidence / runtime-informed review | new-shape | promote | High | Very High | Med |

Enabling builds already in the backlog that several of the above depend on: **Q13** team-preferences overlay (designed, deferred), **Q14** review-depth modes (open), **Q15** decision shape (resolved, lenses pending), plus **#32** agentic-safety and the `shape: artifact` lens (D14/D15, pending).

## Dependency graph (what unlocks what)

- **G23 (route axis)** is a prerequisite for everything that surfaces a non-engineer-owned finding: **G16, G24, G32**, and the product/UX routing generally.
- **G26 (valence axis + anti-churn)** unlocks **G13's suggestion half** and **G32**, and largely **resolves Q3**; its *verbosity policy* lives in **Q13**.
- **Q13 (overlay)** gates the noise controls for **G24 / G26 / G32** (default-quiet, team-tunable).
- **Q15 (decision shape)** gates **G30** (and benefits G12 and the design-time facets of G24).
- **Q14 (depth modes)** gates *how much* of the enlarged suite runs per change — the materiality control that keeps a bigger map affordable.
- **G19 + G31** are independent, cheap synthesizer upgrades with no prerequisites.

The practical consequence: **the two primitives (G23, G26) and the overlay (Q13) are upstream of most of the high-value lenses.** Build them first or the lenses have nowhere to put routed/improvement-valence findings.

## The sequence (four waves)

### Wave A — foundations: the primitives + near-free synthesizer wins

Low cost, high leverage, all manifest/synthesizer/contract edits that regenerate cleanly (no per-lens hand-editing, no drift). **Do these first; they unblock the rest.**

- **G23** route axis on the finding contract + synthesizer. **✅ Shipped 2026-06-15** — `route:` axis + detect-and-route principle + a Routed report section; generator prose, regenerates cleanly.
- **G26** `valence` axis + the built-in anti-churn/convergence floor (defaults strict). **✅ Shipped 2026-06-15** — `valence:` axis, refined per-lens guard (defect-only default, improvements opt-in), non-configurable anti-churn floor, Improvements report section; the team verbosity dial still waits on Q13.
- **G19** synthesizer "coverage & limitations" block. **✅ Shipped 2026-06-15** — required block naming lenses run/skipped + what's unverifiable from the diff; always present.
- **G31** enrich the tensions table with cross-quality pairs. **✅ Shipped 2026-06-15** — added the 3 pairs whose lenses exist (observability↔privacy, performance↔accessibility, consistency↔evolvability); the 2 G24-dependent pairs wait on Cluster VII.
- **Q19** the `mechanize-with:` generator pass + coverage/perf/complexity presence checks in `auditing-config-and-build-hygiene`. **✅ Shipped 2026-06-15** — mechanize-with nudge in every lens (advisory, `route: implementer`); coverage/perf/complexity presence as a preference-tunable advisory. Cross-model re-gate passed (2026-06-15, qwen2.5:7b + llama3.2:3b — no over-flagging on a healthy repo).

### Wave B — high-value add-factors (regenerate from the manifest; low risk)

Pure heuristic additions to existing lenses — the cheapest way to bank real coverage, and the model the G9 fixes already use.

- **G27** SoD/maker-checker → #14 *(highest value-per-cost in the whole pile)*. **✅ Shipped 2026-06-15** — add-factor on `sweeping-for-security`; cross-model re-gate passed on the 7–8B floor (5/5) after a "role-gate ≠ dual-control" tuning pass; 3B below the precision floor (expected).
- **G21** operational time-bombs → #4/#14/#26/#28 (assign each factor a single owner). **✅ Shipped 2026-06-15** — expiry/rotation → #14, calendar/clock → #4, thundering-herd + exhaustion → #28; each with an eval. **Cross-model re-gate 2026-06-24** (qwen2.5:7b + llama3.1:8b): expiry/rotation (#14) and calendar/clock (#4) **pass both tiers**; thundering-herd / cache-stampede (#28) is **below the 7-8B floor** — both tiers misdiagnose the coordinated-TTL stampede (documented data-flow-reasoning ceiling), detection-at-deployment-tier-only, with an `examples.md` decision-rule tuning candidate noted in the session-log.
- **G28** claims-vs-evidence → generalize across lenses (+ synthesizer). **✅ Shipped 2026-06-15** — factor on #24 `reviewing-pr-and-process-hygiene`; kept as a per-lens factor (not a synthesizer check); eval added. **Cross-model re-gate passed 2026-06-24** (qwen2.5:7b + llama3.1:8b; each tier catches the core claim-vs-evidence legs, union covers all — see session-log).
- **G29** root-cause-vs-symptom → tracing-correctness / hunting-silent-failures + bug-fix route. **✅ Shipped 2026-06-15** — band-aid factor on `hunting-silent-failures` (#2), marked priority; eval added.
- **G25** green + FinOps → routed #15 factors. **✅ Shipped 2026-06-15** — unified into one routed cost+carbon factor on `reviewing-performance-and-efficiency` (#15), marked priority; eval added.
- **G13** tidying *suggestions* (now that G26 exists) + the now/after/never economics → #21/#24. **✅ Economics + sequencing shipped 2026-06-15** — now/after/never → #21, structural-vs-behavioral split → #24; auto-apply remains Q8.
- **G32** pre-existing/adjacent defects → an opt-in, route-tagged factor (needs G23 + G26). **✅ Shipped 2026-06-16** (Wave B close-out) — shipped as the **attribution axis** (cross-cutting generator prose, the fourth conflation-pattern primitive after G23/G26), not a single-lens factor: a per-lens *Reviewer discipline* clause + an `attribution: introduced | pre-existing` field, *Boy-Scout (scoped)* principle, verdict rule, and a dedicated opt-in *Pre-existing* report section on the synthesizer. Drift clean; tests + eval added. **Closes Wave B.**
- **G12** acceptance-criteria traceability — *start* as a factor on the bug-fix/feature routes; promote to a lens (Wave C) if it earns it. **✅ Shipped 2026-06-15 as a factor** on `reviewing-pr-and-process-hygiene` (#24); eval added.

### Wave C — high-value new lenses (each gets the full research + ≥3-eval pass, D6/D8)

- **G14** AI-authored-code defects — *highest-priority new lens*: high base rate, strong prior art, reflexively important (the suite is AI-built). Cross-refs #18/#1/restraint. **✅ Shipped 2026-06-17 (v0.4)** as `reviewing-ai-authored-code` — new category #34, primary-owns #34 + cross-refs #18, attribution-agnostic, dedicated router route, 4 evals. **Wave C opened.** **Cross-model re-gate passed 2026-06-24** (qwen2.5:7b floor + llama3.1:8b cross-confirm; no over-flagging — see session-log).
- **G27** *(if treated as a dedicated check rather than a #14 factor)*.
- **G16** ethical / responsible-design (non-ML) — needs G23; detect-and-route. **✅ Shipped 2026-06-17 (v0.6)** as `reviewing-ethical-design` — new Cluster IV category #36, the non-ML analog of #25 / sibling of #14; dark patterns, manipulative defaults, discriminatory conditionals, consent theater. Strictly detect-and-route on the shipped G23 axis (consent→#27/legal, product→product, a11y→#23); 2 ★ top-checks, dedicated router route, a security↔ethical-design tension, 4 evals. Design-time arm noted as a follow-up. **Cross-model re-gate passed 2026-06-24** (qwen2.5:7b floor + llama3.1:8b cross-confirm; no over-flagging — see session-log).
- **G20** agent-legibility (cluster-II rotation) — diff arm + repo arm. **✅ Shipped 2026-06-17 (v0.5)** as `reviewing-agent-legibility` — new Cluster II category #35, the mirror of #34; ships the **diff arm** (context economy / 40%-rule, retrieval-friendly + AST-navigable structure, scoped AGENTS.md/CLAUDE.md onboarding, `llms.txt`), 2 ★ top-checks, dedicated router route, 4 evals. The repo arm (agent-navigability audit) is a noted follow-up; the operator role stays #24/#32/#30. **Cross-model re-gate passed 2026-06-24** (qwen2.5:7b floor + llama3.1:8b cross-confirm; no over-flagging — see session-log).
- **G30** threat modeling — needs Q15 (decision shape); the security analog of #28.
- **G18-interoperability** as a consolidated lens (or a factor sweep across #4/#8/#13/#26). **✅ Shipped 2026-06-24 (v0.7)** as `reviewing-interoperability` — new Cluster IV category #37, the first of the two unowned ISO/IEC 25010:2023 characteristics. Consolidated (a single-category lens, not a factor sweep): HTTP/OAuth/OIDC semantics, SemVer, RFC date/URI/email/JSON/CSV formats, Unicode normalization, cron dialects, OTel semconv, co-existence; 2 ★ top-checks, dedicated router route, 4 evals. Owns external-standard conformance, defers internal correctness (#4) / idiom (#8) / the contract we author (#13) / config (#26), routes the auth-flow security verdict to #14. **The safety arm stays open** (add-factor #2/#28 + detect-and-escalate). **Cross-model re-gate passed 2026-06-24** (qwen2.5:7b floor + llama3.1:8b cross-confirm; no over-flagging — see session-log).

### Wave D — bigger bets: new shapes, clusters, substrates

Higher cost, longer horizon, often gated on an enabling build.

- **G24 Cluster VII** — *incremental*: ship **VII-A (usability/Nielsen) + VII-F (value/outcome instrumentation)** first; needs G23 + G26 + Q13; **VII-H (conceptual integrity)** is the cluster's own counterweight and should land early.
- **G17** data-engineering & data-contracts — new substrate; diff lens + repo/cron arm.
- **G22** diff-isolation — *scoped* LLM ripple-trace only (escalate the heavy semantic-conflict detection to tools).
- **G15** production-evidence — a 5th shape; **longest horizon** (needs a telemetry-access substrate); log and revisit.
- Enabling builds to schedule alongside: **Q13** overlay, **Q14** depth modes, **Q15** decision-native lenses.

## Dedup / single-owner boundaries to settle in the decision pass (G1 discipline)

- **Ethics/transparency triad:** G16 (non-ML ethical defects, *detection*) ↔ G24 VII-G (user-facing transparency *UX*) ↔ #27 (legal/privacy *adjudication*). Three distinct owners; draw the lines explicitly.
- **"Matches what's claimed/required" family:** G28 (claims-vs-evidence) ↔ G12 (acceptance-criteria) ↔ #1 (matches stated intent). Candidate to unify as one lens family rather than three factors.
- **Contracts:** G17 (data/event contracts) ↔ #13 (service API contracts) ↔ #20 (persistence). Boundary needed.
- **Safety vs reliability:** G18-safety (fail-toward-safe / harm) ↔ #2 (fail-loud) ↔ #28 (degradation). *(Still owed: the interoperability arm shipped as #37 v0.7; the safety add-factor pass against #2/#28 is the remaining half of G18.)*
- **Security design vs detection:** G30 (threat enumeration, design-time) ↔ #14 (vuln detection, diff-time) ↔ #32 (agentic).
- **Time-bombs:** G21's factors span #4/#14/#26/#28 — assign each to one owner.
- **Agent surfaces:** G20-operator ↔ #24/#32/#30 (already mapped).

## If you only do five things

1. **G23 + G26** — the two primitives. They unlock the most downstream value and G26 largely resolves Q3.
2. **G27** — segregation of duties. The best value-per-cost in the pile; an SOX-grade control the suite simply lacks.
3. **G14** — the AI-authored-code lens. Highest base rate of any new lens, and the suite should hold its own output to it.
4. **G19 + G31** — the two near-free synthesizer upgrades (honest coverage statements; complete tension reconciliation).
5. **G24, started small** — VII-A (usability) + VII-F (value instrumentation) + VII-H (conceptual integrity). The biggest strategic expansion, de-risked by going incremental.

## Process caveats (so the synthesis doesn't become a checklist to blindly execute)

- **Restraint is a feature.** Not everything here should ship; the suite's value includes *not* nagging. Wave D especially should be paced against real demand (Q14 materiality), and the conflation-audit closure says the framing seam is mined — further *finding* has diminishing returns.
- **Every promotion runs the compounding loop** (D6/D8): research section → manifest entry → generate → ≥3 evals + cross-model gate → re-gate. The add-factors (Wave B) are cheap because they regenerate; the new lenses (C/D) each carry that full cost.
- **The standing methods are themselves a deliverable.** This hunt produced three reusable gap-finding methods — external-completeness sweep, the conflation audit, the cross-discipline practice sweep — plus two new primitives (detect-and-route, valence). Those compound beyond this pile.
