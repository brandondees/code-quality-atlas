# The Code Quality Map

**Status:** v0.3 (2026-06-12 — round-2 gap hunt). Maximal scope.
**Shape:** 6 clusters → 31 categories → ~95 factors. Three **review shapes**: diff, repo/cron, and (new in v0.3) **decision-time** ([`decision-time-review-shape.md`](decision-time-review-shape.md)).

Cross-links between factors are deliberate; quality dimensions genuinely overlap. Where a category is partly covered by existing prior art, see [`prior-art.md`](prior-art.md) for the mapping (kept out of this file so the map stays tool-agnostic).

> **v0.3 changes:** promoted four categories from the round-2 gap hunt — #28 Operational & resilience design, #29 Decision lifecycle, #30 Enforcement apparatus & meta-artifacts, #31 Infrastructure-as-code; added factors to #16/#17/#19/#20/#22/#25/#27; named **decision-time** as a third review shape. Resolves the G9 #12 drops (folded into #28) and the G10 framing gap (#30). Rationale in [`open-questions.md`](open-questions.md) (D13) and [`research/taxonomy-gap-hunt-round-2.md`](research/taxonomy-gap-hunt-round-2.md).
>
> **v0.2 changes:** promoted three categories (#25 AI/LLM-integration, #26 Configuration & environment, #27 Compliance/licensing/provenance); broadened #3 (distributed correctness) and #9 (caller ergonomics / internal-API DX); cross-linked money/units between #4 and #23; kept logging folded in #16. Rationale in [`open-questions.md`](open-questions.md) (D5).

---

## Cluster I — Does it work? (Correctness & Robustness)

### 1. Functional correctness & logic
Matches intent/spec; edge cases & boundary conditions; off-by-one; null/undefined handling; invariant preservation; dead/unreachable code; determinism & reproducibility.

### 2. Error handling & resilience
No silent failures / swallowed exceptions; fail-loud vs. graceful degradation; actionable error messages; input validation at boundaries; retry/backoff/circuit-breaker correctness; timeout handling; partial-failure & rollback.

### 3. Concurrency, async & distributed correctness
Data races; deadlocks & lock ordering; atomicity & visibility; async/await & unhandled rejections; thread-safety of shared state; frontend DOM/timing/lifecycle races. **Distributed facet:** message ordering; idempotent consumers; "exactly-once" myths; eventual consistency; clock skew; saga / distributed-transaction integrity.

### 4. Resource & state management
Leaks (memory, file handles, sockets, connections); lifecycle & cleanup; idempotency where required; numerical precision/overflow; time/timezone/clock correctness; money/units/measurement correctness *(cross-links #23)*.

---

## Cluster II — Can humans understand it? (Readability & Clarity)

### 5. Naming
Intention-revealing; consistent; domain language; progressive refinement of vague/placeholder names.

### 6. Local readability
Function/method length & single responsibility; cyclomatic/cognitive complexity; nesting depth & control-flow clarity (early returns); magic numbers/strings → named constants; "altitude" mixing (high + low level in one function); symmetry of expression.

### 7. Comments & inline docs
Why-not-what; docstring completeness & accuracy; comment rot / staleness; commented-out code.

### 8. Consistency & idiom
Adherence to project conventions/style guide; idiomatic language/framework use; pattern consistency across the codebase.

---

## Cluster III — Is it well-designed? (Structure & Architecture)

### 9. Module / unit design
Cohesion (SRP); coupling (loose, explicit interfaces); encapsulation & information hiding; interface design (minimal, hard-to-misuse); **caller ergonomics / internal-API DX** — the next engineer should fall into the pit of success; composition vs. inheritance.

### 10. Type & data modeling
Make illegal states unrepresentable; invariants encoded in types; parse-don't-validate boundaries; schema/constraint design.

### 11. Abstraction & simplicity
YAGNI / no speculative generality; DRY vs. *premature* abstraction (the wrong-abstraction trap); over-engineering / accidental complexity; removing rather than adding (dependency elimination). **(Counterweight category.)**

### 12. System architecture
Layering & boundary enforcement; dependency-graph health (cycles, god modules, fan-in/out); architectural pattern compliance; scalability of the design; backward/forward compatibility strategy; feature-flag architecture.

### 13. API & contract design
Versioning; backward/forward compatibility; consistent conventions (REST/GraphQL/RPC); error-response contracts; pagination & rate limiting; idempotency keys; contract tests. *(External contracts; for the internal-caller side see #9.)*

---

## Cluster IV — Cross-cutting runtime qualities

### 14. Security
Injection (SQL/command/XSS/path traversal); authn/authz gaps & IDOR; hardcoded secrets; sensitive-data/PII handling & logging; crypto correctness (no homegrown crypto); dependency/supply-chain CVEs; least privilege; safe defaults; CSRF/SSRF/deserialization.

### 15. Performance & efficiency
Algorithmic complexity & hot paths; N+1 queries & DB access patterns; redundant work; allocations/GC pressure; caching correctness & invalidation; I/O batching & network round-trips; lazy vs. eager / streaming vs. buffering; bundle size & startup (frontend); cloud-resource cost efficiency (FinOps facet). **Counterweight:** premature optimization.

### 16. Observability & operability
Structured logging (levels, no PII); metrics, tracing, instrumentation; health/readiness checks; feature flags & kill switches; debuggability (context-rich errors); graceful startup/shutdown; SLO/error-budget instrumentation. *(Instrumentation emitted from app code; the monitoring **config** as a reviewed artifact — alert rules, dashboards, SLO definitions — is #30.)*

### 25. AI/LLM-integration quality  *(promoted v0.2)*
Prompt-injection & untrusted-input surface; structured-output validation & schema enforcement; eval/test coverage for nondeterministic behavior; model & prompt versioning/pinning; token & cost efficiency; timeouts / retries / fallbacks for model calls; PII sent to third-party models; response caching; guardrails & refusal handling; reproducibility & temperature discipline; graceful degradation when the model is wrong; **harmful-output eval coverage** (bias/toxicity/safety, detect-and-escalate — deep fairness auditing stays governance, out of scope). *(Model weights as an artifact — model card, datasheet, training-data provenance — are #27.)*

### 28. Operational & resilience design  *(promoted v0.3)*
Design-time operability, distinct from #16's *runtime* operability. **Resilience as design:** failure-mode / blast-radius analysis, bulkheads, graceful degradation, dependency-failure plans (beyond #2/#3 code-level handling). **Recoverability:** RTO/RPO, *tested* restore — not just backups taken (absorbs #20's backup-note). **Scalability as design:** statelessness, horizontal-scaling readiness, single-writer bottlenecks, backpressure on unbounded queues (resolves the dropped #12 factor; absorbs system-wide rate-limit/quota). **Multi-tenancy isolation** (noisy-neighbour, per-tenant quotas). Reviewed at *decision time* (RFC/design doc) and on a diff (a new stateful singleton or unbounded queue). Cross-links #12, #16, #2/#3.

---

## Cluster V — The system around the code (Verification & Supply)

### 17. Test quality & coverage
*Meaningful* coverage (not vanity %); isolation, determinism, speed; edge-case coverage; test-pyramid balance (unit/integration/e2e); flakiness; testing behavior not implementation; mocking discipline vs. over-mocking; testability/seams; regression tests for fixed bugs; property-based/fuzz where valuable; **test-apparatus health** — fixtures/factories/builders as first-class code (General Fixture, Mystery Guest, Generous-Leftovers smells), test-data & golden-file hygiene (provenance, schema-drift, no real PII).

### 18. Dependencies & supply chain
Necessity (avoid trivial deps); CVE status; version staleness; transitive bloat; lockfile/pinning & reproducible builds; vendor lock-in risk. *(License compatibility moved to #27.)*

### 19. Build, CI/CD & tooling
Build reproducibility/hermeticity; CI reliability (not flaky, fast); lint/format/static-analysis gates; type-checking in CI; pre-commit hooks; deploy safety (rollbacks, canaries); pipeline-as-code quality; secrets in CI; **progressive-delivery strategy** as a reviewed plan (cohorts, ramp %, guardrail metrics, auto-abort — cross #24, #28). *(Suppression hygiene and codegen↔source drift are #30; IaC manifests are #31.)*

### 20. Data & persistence safety
Migration safety (reversible, zero-downtime, backfills); transaction boundaries; integrity constraints; idempotent migrations; schema-drift detection; backup/restore considerations; **data lifecycle as design** — retention/TTL/archival/growth bounds *(the compliance facet of retention is #27; the recoverability facet — RTO/RPO, tested restore — is #28)*.

### 26. Configuration & environment  *(promoted v0.2)*
Config validation & safe defaults; secret/config separation; environment parity (dev/staging/prod); feature-flag *lifecycle* & stale-flag cleanup; twelve-factor adherence; portability & environment assumptions (OS/arch/runtime-version, hardcoded paths, locale/encoding/timezone assumptions).

### 30. Enforcement apparatus & meta-artifacts  *(promoted v0.3)*
The machinery wrapped around the code, reviewed as its own surface (the G10 framing gap — a *silent* hole no taxonomy-vs-skills diff could find). **Suppression hygiene:** `# noqa` / `eslint-disable` / `# type: ignore` accretion, blanket-disabled rules, lint-baseline growth, suppressions with no rationale or expiry — the act of *opting out of enforcement* (cross #8, #19, #21). **Monitoring-config as artifact:** alert-rule / dashboard / SLO-definition correctness, symptom-based alerting, runbook linkage, dashboard drift — the config, not the instrumentation (#16). **Codegen ↔ source drift:** checked-in generated/compiled output stale vs. its generator/spec.

### 31. Infrastructure-as-code  *(promoted v0.3)*
IaC manifests (Terraform / k8s / Helm / CloudFormation) as reviewed code: change blast-radius, over-broad IAM / public exposure (cross #14 least-privilege), drift between declared and live infra, module/provider hygiene. Distinct from #19 (the build/CI pipeline) and #26 (app config keys). Mature scanners exist (Checkov, Trivy, OPA/Sentinel) → the lens orchestrates + judges blast-radius, it doesn't re-implement them.

---

## Cluster VI — Evolution & humans (Maintainability & Process)

### 21. Maintainability & evolvability
Change amplification (one change → many edits); blast radius / ripple effects; refactorability (safe to change); tech-debt visibility & accounting; onboarding cost; bus factor / knowledge concentration.

### 22. Documentation & knowledge
API docs & docstrings; README / onboarding docs; architecture decision records (the *why*); runbooks & operational docs; changelogs; usage examples & diagrams; **documentation as a designed system** — information architecture & audience fit (Diátaxis quadrant balance, mode-mixing), not just freshness/accuracy.

### 23. Accessibility & i18n
WCAG conformance; semantic markup & ARIA; keyboard nav & focus management; localization (no hardcoded strings, RTL, number/date/**currency & unit** formatting — correctness facet cross-links #4); responsive/edge layouts; design fidelity vs. spec.

### 24. Process & collaboration
PR size & reviewability; commit atomicity & message hygiene; risk signaling in commits/PRs; ownership (CODEOWNERS); definition of done; agent-native parity (any action a user can take, an agent can too).

### 27. Compliance, licensing & provenance  *(promoted v0.2)*
Dependency license compatibility & copyleft contamination (moved/extended from #18); code provenance & attribution (incl. AI-generated code); regulatory & data-privacy obligations (GDPR/CCPA-style data handling, residency, retention, consent); accessibility-as-legal-requirement; export/compliance constraints; **non-code asset licensing** (fonts, images, datasets, model weights — SPDX headers don't attach to blobs); **model/dataset provenance** (model cards, datasheets, training-data lineage — cross #25); **privacy-by-design / data-minimization** as a design-time check (does the flow *need* the field at all — one step before PII detection).

### 29. Decision lifecycle  *(promoted v0.3)*
Decisions reviewed *as they are made*, not the code that implements them — the **decision-time shape** ([`decision-time-review-shape.md`](decision-time-review-shape.md)). **Choose / adopt:** is this the right dependency / framework / platform to adopt vs. a smaller option or building it; lock-in & **exit cost** (build-vs-buy *TCO / procurement* escalates to humans, G8-style). **Revisit:** does an accepted ADR still hold — are its assumptions current, are revisit-triggers recorded (a `shape: repo` cron over decision records). **Retire:** deprecation header + sunset date + migration path as a *planned* activity (cross #1 dead-code, #13 versioning). The topic whose natural shape is `decision`.

---

## Candidate additions — resolved (v0.2)

| Candidate | Disposition |
|---|---|
| Configuration management | **Promoted** → #26 (merged with portability/environment). |
| Logging as first-class | **Kept folded** in #16 — not larger than observability. |
| i18n money / units / measurement | **Kept, cross-linked** #4 ↔ #23 — correctness facet + formatting facet, not its own category. |
| Licensing / compliance / provenance | **Promoted** → #27. |
| AI/LLM-specific code quality | **Promoted** → #25. |
| Internal-API DX / ergonomics | **Folded** into #9 (broadened wording). |
| Portability & environment assumptions | **Promoted** (merged into #26). |

### Residual minor candidates (still open, low priority)
- **Cloud cost / FinOps efficiency** — currently a factor-note in #15. Promote only if it proves to need its own review behavior. *(2026-06-12: standards now exist — FOCUS billing-data spec, SCI/ISO 21031 carbon rate — filed in cluster-4 research; still factor-level.)*
- **SLO / error-budget framing** — factor-note in #16; partly a process concern (#24).
- **Telemetry / analytics privacy** — sits across #16 and #27.
- **Agentic / tool-use safety** *(2026-06-12)* — no longer "low priority": OWASP shipped a dedicated agentic Top 10 (ASI01–ASI10). Research filed under #25; **promotion decision tracked as Q16** (map-gaps G2).
- **IaC / workflow review depth** *(2026-06-12)* — Terraform/K8s/Dockerfile/CI-workflow review currently factor-notes in #19 ("pipeline-as-code") and #26 (portability); tooling + heuristics now filed in cluster-5 research (#19). Promote only if IaC-heavy repos prove to need a dedicated lens.

## Candidate additions — resolved (v0.3)

From the round-2 gap hunt ([`research/taxonomy-gap-hunt-round-2.md`](research/taxonomy-gap-hunt-round-2.md)). Disposition discipline per D5.

| Candidate | Disposition |
|---|---|
| Operational & resilience design (DR/RTO-RPO, capacity, resilience-as-design, multi-tenancy) | **Promoted** → #28 (resolves the G9 #12 scalability drop). |
| Decision lifecycle (adopt/exit, ADR-still-valid, retire-on-schedule) | **Promoted** → #29; introduces the **decision-time** shape. |
| Enforcement apparatus (suppression hygiene, monitoring-config, codegen-drift) | **Promoted** → #30 (the G10 framing gap). |
| Infrastructure-as-code | **Promoted** → #31. |
| Non-code asset & model/dataset licensing/provenance | **Folded** → #27 (factors). |
| Privacy-by-design / data-minimization | **Folded** → #27 (design-time factor). |
| ML harmful-output eval coverage | **Folded** → #25; deep fairness auditing **out-of-scope** (governance). |
| Test-apparatus health; docs-as-designed-system; data-lifecycle-as-design; rollout-plan | **Folded** → #17 / #22 / #20 / #19 (factors). |
| Feature-flag *architecture* (#12) | **G9 propagation** — route to the skill-coverage fix, not a new category. |
| Sustainability / green-software | **Folded** → #15 (a carbon *label* on existing perf/cost findings, not a behavior). |
| Contributor DevEx as a system; build-vs-buy TCO & vendor selection; deep model-fairness; suite self-dogfooding | **Out-of-scope** — org-measurement / procurement / governance / a practice, not diff-reviewable. |
| Inclusive / non-exclusionary language | **Folded** → #8/#23 (tool-orchestration; linter-owned, thin LLM value). |
| Container images; system-wide rate-limit/quota | **Folded** → #19+#18 / #28 (covered as facets). |

---

## Notes on structure

- **Two counterweights** are embedded deliberately: premature abstraction (#11) and premature optimization (#15). The suite must value restraint, not only addition. (See open question Q5 on enforcing this structurally.)
- **Overlaps are intentional.** Concurrency (#3) is a facet of correctness; security (#14) overlaps dependencies (#18) and compliance (#27); data safety (#20) overlaps migrations and architecture; AI/LLM (#25) overlaps security, testing, and performance. The map is a graph, not a strict tree.
- **Numbering note:** v0.2 appended 25–27 and v0.3 appended 28–31 within their clusters (rather than renumber and churn cross-references). Order within a cluster is by topic, not number.
- **Topic vs. shape are different axes.** A category is a *topic*; how it's reviewed is a *shape* (diff / repo-cron / decision-time). Most categories are diff-shaped; #21/#30/#31 and the repo audits are repo-shaped; #29 — and the decision-time facets of #27/#28/#25 — are **decision-shaped** ([`decision-time-review-shape.md`](decision-time-review-shape.md)). The shape cuts across the topic-clusters, like diff-vs-repo already does.
- **Granularity remains the central phase-2 question:** the categories will *not* map 1:1 to skills. Expect collapse into coarser, composable skills. See [`open-questions.md`](open-questions.md) Q1.
