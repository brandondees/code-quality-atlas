# Round-2 gap hunt — hunting *framing* gaps in the taxonomy

**Status:** in progress, opened 2026-06-12. Feeds a possible **taxonomy v0.3**.
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

*(To be filled by the round-2 research across axes A–E, each candidate scored against the rubric, then synthesized into a v0.2 → v0.3 disposition table mirroring `taxonomy.md`'s "Candidate additions — resolved".)*

### A — Meta-surfaces
_pending_

### B — Artifact types
_pending_

### C — Decision & lifecycle
_pending_

### D — Socio-technical
_pending_

### E — Operational & resilience
_pending_

## Disposition (v0.3 proposal)
_pending synthesis_
