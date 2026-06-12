# Round-2 gap hunt — hunting *framing* gaps in the taxonomy

**Status:** synthesized 2026-06-12 → **adopted as taxonomy v0.3** (full draft, [D13](../open-questions.md)). Findings + disposition below; taxonomy updated, skill regeneration is the next (build) phase.
**Motivation:** [`map-gaps.md` G10](../map-gaps.md) — a taxonomy-vs-skills diff (the G9 method) finds *propagation* gaps (researched, didn't reach a check) but is **blind to framing gaps**: a missing category yields no thin heuristic to notice, just silence. Framing gaps are only found by re-asking, from first principles, *what kinds of reviewable surface exist* — and checking which the v0.2 map never carved a home for.

## The search heuristic (from G10)

The v0.2 map is strong on **artifacts → their properties → mistake-detection**. It is weak wherever a reviewable concern is:

- **Meta** — about the *apparatus around* the code (the gates, the tooling, the test/observability/review machinery) rather than the code itself; or
- **A decision and its lifecycle** — *choosing*, *adopting*, *revisiting*, *retiring* — rather than a static property to inspect; or
- **A non-code artifact type** the map mentions only glancingly (docs treated as freshness, not as designed information; binaries/generated output; data/assets).

Enforcement-apparatus + suppression-hygiene (G10) and dependency-*selection* (vs. #18's patching) were the seed examples. This pass tests how far the pattern goes.

## Evaluation rubric (every candidate must be scored, to avoid re-flagging covered facets)

For each candidate omission, the research must answer:

1. **Already covered?** Cite the v0.2 category/factor that arguably owns it, or state "absent." (Grep `taxonomy.md` + `docs/research/` before claiming absence — distinguish *absent* from *thin-but-present* (that is G9, not this).)
2. **Distinct review behavior?** Does it imply a question a reviewer asks that no existing lens asks? If it collapses into an existing lens's judgment, it is a *facet*, not a gap.
3. **Shape** — diff-reviewable / repo-or-cron-auditable / decision-record-shaped (some of these are reviewed at *decision* time, not diff time — a new shape the suite barely has).
4. **Prior art** — who already treats this as reviewable (frameworks, standards, linters, known checklists)? Web-verify; cite. Absence of prior art is itself signal (either genuinely novel, or not actually a quality concern).
5. **Disposition** — recommend one: **promote** to a category / **add factor** to an existing category / **fold** (it's a facet, no action) / **out-of-scope** (governance/legal/product, not code-review). Match the D5 discipline used for the v0.2 candidate additions.

## Candidate axes under research (5 parallel domains)

Organized so they are orthogonal to the original six clusters (which are altitude/topic-based, and so cannot surface these).

- **A — Meta-surfaces (the apparatus, not the code).** Enforcement & suppression hygiene (G10, confirmed); the test apparatus's own health (fixtures/factories-as-code, test orchestration, flaky-infra vs. flaky-test); observability-of-the-monitoring (alerts/dashboards/runbooks as reviewable artifacts); the build/codegen pipeline as a reviewable object; the review/quality tooling reviewing itself (the dogfood surface).
- **B — Under-covered artifact types.** Documentation as a *designed system* (information architecture, audience/diátaxis fit), not just #22 freshness; binary & generated artifacts (build output, vendored binaries, **model weights**, container images, lockfiles, generated code) — provenance, reproducibility, bloat, "is the generated output in sync with its source?"; data/fixtures/seed assets as artifacts; IaC / infra manifests (Terraform/k8s) as code under review; non-code **asset licensing** (fonts, images, datasets, model weights — distinct from #18/#27 dep licensing).
- **C — Decision & lifecycle (choose / adopt / revisit / retire).** Dependency *selection* & build-vs-buy & **exit/migration cost** (vs. #18's patch/CVE/pin); technology/framework selection & deprecation lifecycle; whether a recorded decision (ADR) *still holds* (#22 records the why; nothing reviews if it's stale); deletion / sunsetting / feature-retirement as a first-class activity (vs. #1's dead-code); revisit-triggers ("when should this decision be reopened?").
- **D — Socio-technical & responsible engineering.** Privacy-by-design / data-minimization as *design* (beyond #27 detection); ethics / fairness / responsible-AI beyond #25's security framing; contributor/maintainer DX as a system (beyond #21's onboarding-cost factor); content/i18n beyond UI strings; sustainability / green-software / carbon; cost / FinOps as a design concern (the #15 residual).
- **E — Operational & resilience design.** Capacity / scalability *design* (G9 found #12 lists but drops this — deepen); disaster recovery / backup-restore / business-continuity (only grazed in #20); data lifecycle / retention / archival / deletion (partly #27); failure-mode / chaos / resilience *as design* (beyond #2/#3 code-level error handling); rollout / progressive-delivery *strategy* (beyond #20 schema migration).

## Findings

Five parallel research passes (2026-06-12), each grepping `taxonomy.md` + `docs/research/*.md` to grade *absent* (framing gap) vs *thin-but-present* (G9 propagation), and web-verifying prior art. Condensed below; full per-axis reasoning in the session record.

### A — Meta-surfaces (the apparatus around the code)

| Candidate | Covered? | Shape | Prior art | Disposition |
|---|---|---|---|---|
| **A1 — In-code suppression rot** (`noqa`/`eslint-disable`/`type:ignore` accretion, baseline growth, no-rationale/no-expiry disables) | **Absent** (G10-confirmed) | diff + cron | ESLint bulk-suppressions/baseline, Ruff unused-`noqa`, Android lint baseline, Sonar suppression tracking | **promote / meta-category** — canonical framing gap, confirmed twice (also surfaced on axis D) |
| **A4 — Monitoring-config-as-artifact** (alert/dashboard/SLO files as reviewed objects: PromQL correctness, symptom-based alerting, runbook linkage, dashboard drift) | **Absent as review surface** (#16 *emits* SLIs from app code; `promtool` named as tool, never as behavior) | diff + cron | Grafana/Prometheus-as-code (Terraform), `promtool check rules`, SRE alert-tuning | **add-factor-#16** (or meta-category) |
| **A5 — Codegen ↔ source drift** (checked-in generated code stale vs its generator/spec) | **Absent** (#19 = build reproducibility; #18 = lockfiles) | diff (`go generate` + `git diff --exit-code`) | openapi-generator CI-verify, graphql-codegen check, OpenAPI drift detection | **add-factor-#19** *(= B4, merged)* |
| **A2 — Test-apparatus health** (fixtures/factories/builders-as-code: General Fixture, Mystery Guest, Generous Leftovers) | **Thin→absent** (#17 reviews tests-of-the-product, not the support code as its own surface) | diff + cron | Meszaros *xUnit Test Patterns* 18 smells, testsmells.org, xNose | **add-factor-#17** |
| A3 flaky-infra-vs-test + suite runtime/cost; A6 build-pipeline-as-object | thin-but-present | — | BuildPulse, Datadog Test Opt | **G9-class** (deepen, not new) |
| A7 the suite dogfooding itself | absent but project-specific | process | *(no prior art — it's a practice)* | **out-of-scope** |

### B — Under-covered artifact types

| Candidate | Covered? | Shape | Prior art | Disposition |
|---|---|---|---|---|
| **B1 — IaC / infra manifests as reviewed code** (Terraform/k8s/Helm/CFN: blast-radius, over-broad IAM, public exposure, state drift) | **Largely absent** (only a glancing cluster-4 note; #19 build, #26 config, #14 secrets — none owns infra correctness/drift) | diff + cron | Checkov, Trivy, OPA/Sentinel, TFLint | **promote-category** (strongest on B) |
| **B2 — Non-code asset licensing** (fonts, images, datasets, model weights — SPDX headers don't attach to blobs) | **Absent** (#27 is 100% software-dep/source-file licensing) | diff + cron | SIL OFL, Creative Commons, dataset licenses | **add-factor-#27** |
| **B3 — Model weights/checkpoints as artifacts** (model card, datasheet, training-data lineage, opaque-blob bloat) | **Absent** (#25 = integration code only) | diff + decision | Model Cards (Mitchell), Datasheets for Datasets (Gebru), HF card schema | **add-factor-#27** + xref #25 |
| B4 generated↔source sync | thin/partial | diff | Snyk out-of-sync, frozen-lockfile | **merged into A5** |
| B5 docs-as-designed-system (Diátaxis quadrant balance, audience fit) | **thin-but-present (G9)** — Diátaxis is researched but as *coverage*, not *design* | cron | Diátaxis, Good Docs Project, "Beyond Accuracy" | **add-factor-#22** (not promote) |
| B6 data/fixtures/golden files as artifacts (PII-in-fixtures, schema drift, provenance) | absent | diff + cron | datasheets-for-datasets, golden-file practice | **split-factor** — PII→#27, schema-drift→#20, golden→#17 *(overlaps A2)* |
| B7 container images (bloat/provenance/SLSA) | thin | diff + cron | SLSA, Trivy, distroless | **fold** #19+#18 |

### C — Decision & lifecycle (choose / adopt / revisit / retire)

The through-line: **every candidate is reviewed at *decision time* (ADR/RFC/adoption-PR), a shape the suite does not have.** Its closest analog, `reviewing-migration-and-data-safety`, reviews migration *mechanics*, never the *choice* to migrate.

| Candidate | Covered? | Shape | Prior art | Disposition |
|---|---|---|---|---|
| **C1/C2/C5 — Adoption & exit** (right dep/framework/platform to adopt? build-vs-buy? lock-in / exit cost?) | **Absent** (#18 = patch/CVE/pin/health of a dep you *already have*) | decision-time | build-vs-buy TCO, ThoughtWorks Tech Radar rings, one-way/two-way doors | **promote** (reviewable slice only; TCO/procurement → escalate, governance) |
| **C3/C4 — Does a recorded ADR still hold? + revisit-triggers** | **Absent** (#22 *records* the why; no lens *reopens* a decision) | cron + decision-time | Azure Well-Architected quarterly ADR-staleness scan; "revisit if write-vol > 10k/s" | **promote / add-factor-#22** — sharpest novelty |
| **C6 — Retire on a schedule** (deprecation header + sunset date + migration path as a planned activity) | **Absent** (#1 detects dead code post-hoc; #13 versioning) | decision-time + cron | RFC 8594 Sunset, 6–12mo windows, Keep-a-Changelog | **promote / add-factor-#13** |
| C7 migration/cutover *strategy* | thin-but-present | decision-time | expand/migrate/contract as strategy | **fold → axis E** |
| C8 suppression/decision expiry (`review_by:`) | absent | cron | (weak) | **owned by A1 / G10** |

**Net:** one promoted **"Decision lifecycle"** category spanning choose/adopt → revisit → retire, unified by the missing decision-time shape.

### D — Socio-technical & responsible engineering

Mostly a **boundary-drawing exercise** (restraint held): the responsible-engineering "gaps" are largely governance (out-of-scope), already double-booked, or already perf-shaped.

| Candidate | Covered? | Disposition |
|---|---|---|
| **D2 — Privacy/data-minimization as *design*** (does this flow *need* the field at all — one step before #27's PII detection) | thin-but-present | **add-factor-#27** (promote "minimized?" from note to check; Cavoukian #3) |
| **D5 — ML harmful-output eval coverage** | thin (#25 = security framing only) | **add-factor-#25**; deep fairness auditing **out-of-scope** (data-science governance) |
| D1 suppression rot | absent | **= A1** (confirms it from a 2nd angle) |
| D3 dark patterns / deceptive design | absent | **fold-#27** (consent-gating = legal facet, detect-and-escalate) *or* out-of-scope where pure product |
| D4 inclusive/non-exclusionary language | absent | **add-factor-#8/#23** — but linter-owned (woke/alex.js); thin LLM value |
| D6 sustainability/green; D7 FinOps/cost | green absent-as-category / FinOps thin | **fold-#15** — every actionable green smell is a perf/cost diff #15 already flags; carbon is a label, not a question. FinOps = known G9 residual |
| D8 contributor DevEx as a system; D10 a11y-as-law | DevEx absent / a11y covered | DevEx **out-of-scope** (org measurement, not diff-visible); a11y-law **no action** (#23 technical + #27 legal already) |

### E — Operational & resilience design

Design-time operability, **distinct from #16's *runtime* operability**. Resolves the known #12 (scalability) and #20 (backup-restore) dead-notes.

| Candidate | Covered? | Shape | Prior art | Disposition |
|---|---|---|---|---|
| **E3 — Resilience-as-design** (blast-radius, bulkheads, graceful degradation, dependency-failure plan) | **Partial** (#2/#3 = *code-level* timeouts/retries; #21 "blast radius" = change-ripple, not runtime cascade) | decision-time + diff | Chaos Engineering (minimize blast radius), Nygard *Release It!* bulkhead/steady-state, AWS WAF fault-isolation | **promote** (top novelty; escalation hand-off from #2/#3) |
| **E1 — DR / backup-restore / business-continuity** (RTO/RPO, *tested* restore — not just backups taken) | **Absent** (#20 grazes "backup/restore considerations" as a dead note) | decision-time + cron | AWS WAF REL13 recovery-objective ladder, Google SRE | **promote** |
| **E2 — Capacity / scalability design** (statelessness, horizontal scaling, single-writer bottleneck, backpressure on unbounded queues — absorbs E7 rate-limit/quota-as-system) | **#12 dropped-but-listed (G9)** — deserves real treatment | decision-time + diff | AWS WAF Reliability, SRE cascading-failures, Nygard backpressure | **promote** (resolves the #12 drop) |
| E4 data lifecycle / retention / archival / TTL **as design/growth** | partial (#27 = compliance framing only) | decision + cron | ILM, cloud storage lifecycle | **add-factor** (design/growth → op category; compliance stays #27) |
| E5 progressive-delivery *strategy* as a reviewed plan (cohorts, ramp %, guardrail metrics, auto-abort) | partial (#19 = tooling; #16 = kill-switch) | decision-time | Argo Rollouts/Flagger, Harness/Unleash | **add-factor-#19 + #24** (risk-signaling) |
| E6 multi-tenancy isolation & fairness (noisy-neighbor, per-tenant quota) | absent | decision + diff | AWS tiered throttling, noisy-neighbor literature | **promote-if-SaaS-in-scope, else add-factor** |
| E7 system-wide rate-limit/quota; E8 feature-flag *architecture* | E7 partial(#13) / E8 #12-dropped(G9) | — | token-bucket / progressive-delivery | E7 **fold→E2**; E8 **known G9** |

## Cross-axis synthesis — what round 2 actually found

Three structural findings, larger than any single category:

1. **A whole missing review *shape*: decision-time / decision-record review.** This is the biggest result. The suite has **diff-lenses** and **repo/cron-audits** — but no lens that reviews a *decision as it is made* (an ADR, RFC, adoption PR, rollout plan). It recurs everywhere: all of axis C (adopt/revisit/retire), most of axis E (DR/capacity/resilience/rollout are RFC-shaped), B3 (model adoption), D2 (privacy *by design*). Many of round 2's strongest gaps are invisible to a diff *and* to a repo scan because they live in the decision, not the artifact. The router already has a thin "design doc / RFC" route — this finding says that shape deserves a real lens family, not a routing footnote. **(Opens a candidate question — Q15 — on whether to build a decision-time lens family.)**

2. **The G10 meta-layer pattern generalizes.** "The apparatus wrapped around the code" is a recurring un-mapped surface: suppression hygiene (A1), monitoring config (A4), codegen output (A5), the test scaffolding (A2), IaC (B1). The artifact→property→mistake framing put *the code* on the map but not *the machinery around it*. This is one coherent omission with ~5 instances, not five unrelated gaps.

3. **A design-time operational cluster is missing (and restraint held on the rest).** Axis E cleanly separates **design-time operability** (will it scale / recover / degrade?) from #16's **runtime operability** (can I debug it at 3am?) — a real cluster-sized hole that also absorbs the two G9 #12 drops. Meanwhile axis D's discipline check **passed**: the socio-technical "gaps" mostly resolved to governance (out-of-scope) or already-covered, confirming the v0.2 maximal scope did not under-reach on the human axis. The real gaps are *structural* (shape, meta-layer, operational-design), not *ideological*.

## Disposition (v0.2 → v0.3 proposal)

Mirrors `taxonomy.md`'s "Candidate additions — resolved" discipline (D5). **Provisional** — for owner decision before any taxonomy edit. New numbers would append (as 25–27 did), not renumber.

### Promote — new categories (high-confidence, but a 3-category expansion; weigh against restraint)

| Proposed | Spans | Resolves | Confidence |
|---|---|---|---|
| **#28 Operational & resilience design** | E3 resilience-as-design, E1 DR/RTO-RPO, E2 capacity/scalability/backpressure, E4 data-growth, E6 multi-tenancy | the #12 scalability drop + the #20 backup-restore dead-note; distinct from #16 runtime | **High** — cohesive, strong prior art, clear boundary |
| **#29 Decision lifecycle** | C1/C2/C5 adopt-exit, C3/C4 ADR-still-valid + revisit-triggers, C6 retire-on-schedule | the missing decision-time shape (finding 1) | **Med-High** — strong, but scope to the reviewable slice; escalate TCO/procurement (G8-style) |
| **#30 Enforcement apparatus & meta-artifacts** | A1 suppression hygiene, A4 monitoring-config, A5 codegen-drift *(or distribute A4→#16, A5→#19 and keep #30 = suppression-only)* | the G10 framing gap (finding 2) | **High** on suppression hygiene; the *grouping* is the open call |
| **IaC as reviewed code (B1)** | infra correctness / blast-radius / drift | the infra-review hole | **High** as a need; **placement open** — own category, or under #28 |

### Add-factor — to existing categories (lower-risk, regenerable)

- **#27:** B2 asset licensing · B3 model-weight provenance/cards (xref #25) · D2 privacy-by-design/minimization · [D3 dark-patterns as detect-and-escalate]
- **#25:** D5 harmful-output eval coverage
- **#17:** A2 test-apparatus health (fixture smells) · B6 golden-file/fixture hygiene
- **#19:** A5/B4 codegen↔source drift · E5 rollout-plan-as-artifact (+ #24 risk-signaling)
- **#22:** B5 docs-as-designed-system (Diátaxis balance, audience fit)
- **#16:** A4 monitoring-config-as-artifact *(if not promoted into #30)*
- **#20 / #27:** B6 split (schema-drift / PII-in-fixtures) · E4 retention (compliance half stays #27)
- **#8/#23:** D4 inclusive-language (tool-orchestration; thin)

### Fold / no-action

B7 container images → #19/#18 · D6 sustainability → label on #15 · D7 FinOps → #15 (G9 residual) · D10 a11y-law → already #23/#27 · E7 rate-limit-as-system → #28 backpressure · C7 migration-strategy → #28.

### Out-of-scope (governance / not diff-visible — boundary held)

A7 suite-dogfooding (a practice) · D8 DevEx-as-a-system (org measurement) · deep model-fairness auditing (data-science governance) · build-vs-buy TCO & vendor selection (procurement — the non-reviewable slice of #29).

### Known G9 (propagation, route to the G9 fix — *not* new research)

#12 scalability (now folded into #28) · #12 feature-flag-architecture · #15 FinOps/cost · A3 flaky-infra-vs-test · A6 build-pipeline-as-object · B5 docs (partially).

### Cross-cutting, not a category

The **tool-mechanization nudge** (G10 item 1) — append an optional `mechanize-with:` line to each lens's finding contract from its existing `tool-rules.md`. A generator task, advisory, independent of all of the above.

---

**Recommendation.** The highest-confidence, highest-value moves are **#28 (operational & resilience design)** and the **G10 meta-cluster** (at minimum suppression hygiene + IaC), plus the low-risk **add-factors** (which regenerate from the manifest like the G9 fixes). **#29 (decision lifecycle)** is the most *intellectually* significant — it's a missing review *shape*, not just a topic — but also the one most entangled with governance, so it wants the tightest scope and possibly its own design pass (à la Q13). Net candidate expansion: **2–4 new categories + ~10 add-factors → a taxonomy v0.3**, gated on the owner's restraint call about how much to promote vs. fold.
