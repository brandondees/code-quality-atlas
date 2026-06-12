# The Code Quality Map

**Status:** v0.2 (2026-06-08 — pressure-tested). Maximal scope.
**Shape:** 6 clusters → 27 categories → ~80 factors.

Cross-links between factors are deliberate; quality dimensions genuinely overlap. Where a category is partly covered by existing prior art, see [`prior-art.md`](prior-art.md) for the mapping (kept out of this file so the map stays tool-agnostic).

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
Structured logging (levels, no PII); metrics, tracing, instrumentation; health/readiness checks; feature flags & kill switches; debuggability (context-rich errors); graceful startup/shutdown; SLO/error-budget instrumentation.

### 25. AI/LLM-integration quality  *(promoted v0.2)*
Prompt-injection & untrusted-input surface; structured-output validation & schema enforcement; eval/test coverage for nondeterministic behavior; model & prompt versioning/pinning; token & cost efficiency; timeouts / retries / fallbacks for model calls; PII sent to third-party models; response caching; guardrails & refusal handling; reproducibility & temperature discipline; graceful degradation when the model is wrong.

---

## Cluster V — The system around the code (Verification & Supply)

### 17. Test quality & coverage
*Meaningful* coverage (not vanity %); isolation, determinism, speed; edge-case coverage; test-pyramid balance (unit/integration/e2e); flakiness; testing behavior not implementation; mocking discipline vs. over-mocking; testability/seams; regression tests for fixed bugs; property-based/fuzz where valuable.

### 18. Dependencies & supply chain
Necessity (avoid trivial deps); CVE status; version staleness; transitive bloat; lockfile/pinning & reproducible builds; vendor lock-in risk. *(License compatibility moved to #27.)*

### 19. Build, CI/CD & tooling
Build reproducibility/hermeticity; CI reliability (not flaky, fast); lint/format/static-analysis gates; type-checking in CI; pre-commit hooks; deploy safety (rollbacks, canaries); pipeline-as-code quality; secrets in CI.

### 20. Data & persistence safety
Migration safety (reversible, zero-downtime, backfills); transaction boundaries; integrity constraints; idempotent migrations; schema-drift detection; backup/restore considerations.

### 26. Configuration & environment  *(promoted v0.2)*
Config validation & safe defaults; secret/config separation; environment parity (dev/staging/prod); feature-flag *lifecycle* & stale-flag cleanup; twelve-factor adherence; portability & environment assumptions (OS/arch/runtime-version, hardcoded paths, locale/encoding/timezone assumptions).

---

## Cluster VI — Evolution & humans (Maintainability & Process)

### 21. Maintainability & evolvability
Change amplification (one change → many edits); blast radius / ripple effects; refactorability (safe to change); tech-debt visibility & accounting; onboarding cost; bus factor / knowledge concentration.

### 22. Documentation & knowledge
API docs & docstrings; README / onboarding docs; architecture decision records (the *why*); runbooks & operational docs; changelogs; usage examples & diagrams.

### 23. Accessibility & i18n
WCAG conformance; semantic markup & ARIA; keyboard nav & focus management; localization (no hardcoded strings, RTL, number/date/**currency & unit** formatting — correctness facet cross-links #4); responsive/edge layouts; design fidelity vs. spec.

### 24. Process & collaboration
PR size & reviewability; commit atomicity & message hygiene; risk signaling in commits/PRs; ownership (CODEOWNERS); definition of done; agent-native parity (any action a user can take, an agent can too).

### 27. Compliance, licensing & provenance  *(promoted v0.2)*
Dependency license compatibility & copyleft contamination (moved/extended from #18); code provenance & attribution (incl. AI-generated code); regulatory & data-privacy obligations (GDPR/CCPA-style data handling, residency, retention, consent); accessibility-as-legal-requirement; export/compliance constraints.

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
- **Agentic / tool-use safety** *(2026-06-12)* — no longer "low priority": OWASP shipped a dedicated agentic Top 10 (ASI01–ASI10). Research filed under #25; **promotion decision tracked as Q14** (map-gaps G2).
- **IaC / workflow review depth** *(2026-06-12)* — Terraform/K8s/Dockerfile/CI-workflow review currently factor-notes in #19 ("pipeline-as-code") and #26 (portability); tooling + heuristics now filed in cluster-5 research (#19). Promote only if IaC-heavy repos prove to need a dedicated lens.

---

## Notes on structure

- **Two counterweights** are embedded deliberately: premature abstraction (#11) and premature optimization (#15). The suite must value restraint, not only addition. (See open question Q5 on enforcing this structurally.)
- **Overlaps are intentional.** Concurrency (#3) is a facet of correctness; security (#14) overlaps dependencies (#18) and compliance (#27); data safety (#20) overlaps migrations and architecture; AI/LLM (#25) overlaps security, testing, and performance. The map is a graph, not a strict tree.
- **Numbering note:** v0.2 additions kept the stable 1–24 numbers and appended 25–27 within their clusters (rather than renumber and churn cross-references). Order within a cluster is by topic, not number.
- **Granularity remains the central phase-2 question:** 27 categories will *not* become 27 skills. Expect collapse into coarser, composable skills. See [`open-questions.md`](open-questions.md) Q1.
