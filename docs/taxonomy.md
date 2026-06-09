# The Code Quality Map

**Status:** v0.1 (first pass, 2026-06-08). Maximal scope.
**Shape:** 6 clusters → 24 categories → factors.

Cross-links between factors are deliberate; quality dimensions genuinely overlap. Where a category is partly covered by existing prior art, see [`prior-art.md`](prior-art.md) for the mapping (kept out of this file so the map stays tool-agnostic).

---

## Cluster I — Does it work? (Correctness & Robustness)

### 1. Functional correctness & logic
Matches intent/spec; edge cases & boundary conditions; off-by-one; null/undefined handling; invariant preservation; dead/unreachable code; determinism & reproducibility.

### 2. Error handling & resilience
No silent failures / swallowed exceptions; fail-loud vs. graceful degradation; actionable error messages; input validation at boundaries; retry/backoff/circuit-breaker correctness; timeout handling; partial-failure & rollback.

### 3. Concurrency & async correctness
Data races; deadlocks & lock ordering; atomicity & visibility; async/await & unhandled rejections; thread-safety of shared state; frontend DOM/timing/lifecycle races.

### 4. Resource & state management
Leaks (memory, file handles, sockets, connections); lifecycle & cleanup; idempotency where required; numerical precision/overflow; time/timezone/clock correctness.

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
Cohesion (SRP); coupling (loose, explicit interfaces); encapsulation & information hiding; interface design (minimal, hard-to-misuse); composition vs. inheritance.

### 10. Type & data modeling
Make illegal states unrepresentable; invariants encoded in types; parse-don't-validate boundaries; schema/constraint design.

### 11. Abstraction & simplicity
YAGNI / no speculative generality; DRY vs. *premature* abstraction (the wrong-abstraction trap); over-engineering / accidental complexity; removing rather than adding (dependency elimination). **(Counterweight category.)**

### 12. System architecture
Layering & boundary enforcement; dependency-graph health (cycles, god modules, fan-in/out); architectural pattern compliance; scalability of the design; backward/forward compatibility strategy; config & feature-flag architecture.

### 13. API & contract design
Versioning; backward/forward compatibility; consistent conventions (REST/GraphQL/RPC); error-response contracts; pagination & rate limiting; idempotency keys; contract tests.

---

## Cluster IV — Cross-cutting runtime qualities

### 14. Security
Injection (SQL/command/XSS/path traversal); authn/authz gaps & IDOR; hardcoded secrets; sensitive-data/PII handling & logging; crypto correctness (no homegrown crypto); dependency/supply-chain CVEs; least privilege; safe defaults; CSRF/SSRF/deserialization.

### 15. Performance & efficiency
Algorithmic complexity & hot paths; N+1 queries & DB access patterns; redundant work; allocations/GC pressure; caching correctness & invalidation; I/O batching & network round-trips; lazy vs. eager / streaming vs. buffering; bundle size & startup (frontend). **Counterweight:** premature optimization.

### 16. Observability & operability
Structured logging (levels, no PII); metrics, tracing, instrumentation; health/readiness checks; feature flags & kill switches; debuggability (context-rich errors); graceful startup/shutdown.

---

## Cluster V — The system around the code (Verification & Supply)

### 17. Test quality & coverage
*Meaningful* coverage (not vanity %); isolation, determinism, speed; edge-case coverage; test-pyramid balance (unit/integration/e2e); flakiness; testing behavior not implementation; mocking discipline vs. over-mocking; testability/seams; regression tests for fixed bugs; property-based/fuzz where valuable.

### 18. Dependencies & supply chain
Necessity (avoid trivial deps); CVE status; license compliance; version staleness; transitive bloat; lockfile/pinning & reproducible builds; vendor lock-in risk.

### 19. Build, CI/CD & tooling
Build reproducibility/hermeticity; CI reliability (not flaky, fast); lint/format/static-analysis gates; type-checking in CI; pre-commit hooks; deploy safety (rollbacks, canaries); pipeline-as-code quality; secrets in CI.

### 20. Data & persistence safety
Migration safety (reversible, zero-downtime, backfills); transaction boundaries; integrity constraints; idempotent migrations; schema-drift detection; backup/restore considerations.

---

## Cluster VI — Evolution & humans (Maintainability & Process)

### 21. Maintainability & evolvability
Change amplification (one change → many edits); blast radius / ripple effects; refactorability (safe to change); tech-debt visibility & accounting; onboarding cost; bus factor / knowledge concentration.

### 22. Documentation & knowledge
API docs & docstrings; README / onboarding docs; architecture decision records (the *why*); runbooks & operational docs; changelogs; usage examples & diagrams.

### 23. Accessibility & i18n
WCAG conformance; semantic markup & ARIA; keyboard nav & focus management; localization (no hardcoded strings, RTL, number/date/currency formatting); responsive/edge layouts; design fidelity vs. spec.

### 24. Process & collaboration
PR size & reviewability; commit atomicity & message hygiene; risk signaling in commits/PRs; ownership (CODEOWNERS); definition of done; agent-native parity (any action a user can take, an agent can too).

---

## Candidate additions (under consideration)

Raised but not yet promoted to their own category. Tracked here so they aren't lost; decision pending in [`open-questions.md`](open-questions.md).

- **Configuration management** — currently a factor inside #12 / #16. Promote?
- **Logging as a first-class concern** — currently inside #16. Some argue it deserves standalone treatment.
- **Internationalized money / units / measurement** — currently inside #23. Correctness-critical; could pair with #4.
- **Licensing & compliance beyond dependencies** — e.g., code provenance, copyleft contamination, attribution.
- **AI/LLM-specific code quality** — prompt injection surface, eval coverage, nondeterminism handling, token/cost efficiency, model-version pinning. A genuinely new axis as more codebases embed LLM calls.
- **Developer experience / ergonomics of *internal* APIs** — distinct from #13 (external contracts): how pleasant/safe the code is for the next engineer to *call*, not just to read.
- **Portability & environment assumptions** — OS/arch/runtime-version assumptions, hardcoded paths, locale/encoding assumptions.

---

## Notes on structure

- **Two counterweights** are embedded deliberately: premature abstraction (#11) and premature optimization (#15). The suite must value restraint, not only addition.
- **Overlaps are intentional.** Concurrency (#3) is a facet of correctness; security (#14) overlaps dependencies (#18); data safety (#20) overlaps migrations and architecture. The map is a graph, not a strict tree.
- **Granularity is the central open question** for phase 2: 24 skills would be too many and several would be thin. Expect categories to collapse into coarser, composable skills. See [`open-questions.md`](open-questions.md).
