# The Code Quality Map

**Status:** v0.8 (2026-06-27 — round-3 gap hunt, Wave C). Maximal scope.
**Shape:** 6 clusters → 37 categories → ~100 factors. Four **review shapes**: diff, repo/cron, **decision-time** ([`decision-time-review-shape.md`](decision-time-review-shape.md)), and **artifact** (D15 — designed; [`research/artifact-scoped-lenses.md`](research/artifact-scoped-lenses.md)).

Cross-links between factors are deliberate; quality dimensions genuinely overlap. Where a category is partly covered by existing prior art, see [`prior-art.md`](prior-art.md) for the mapping (kept out of this file so the map stays tool-agnostic).

> **v0.8 changes:** promoted **#38 Threat modeling / design-time security** (gap G30) — the generative, design-time threat-*enumeration* discipline (STRIDE / trust boundaries / attack trees / abuse cases) sibling to #14/#25/#32. **G1 boundary:** #38 owns enumeration and **delegates** the deep verdict to #14 (code vuln) / #32 (agent action) / #25 (model call), escalating to a human (G8) only for custom-crypto correctness or third-party-auth adjudication. Shape `diff`, design-capable (lands in both the change and decision collapsed entrypoints). Rationale: [`threat-modeling-design-time-security.md`](threat-modeling-design-time-security.md), [`map-gaps.md` G30](map-gaps.md#g30--threat-modeling-as-a-designdecision-time-security-discipline).
>
> **v0.7 changes:** promoted the **interoperability arm** of round-3 gap G18 — #37 Interoperability & external-standard conformance; the first of the two ISO/IEC 25010:2023 characteristics with no owner (**compatibility / interoperability**). Consolidates the scattered "does the code correctly speak an external standard" factor-notes (HTTP/OAuth/OIDC semantics, SemVer, RFC date/email/URI formats, Unicode normalization, cron dialects, OTel semconv, standard interchange formats) from #4/#8/#13/#26 into one owner. **G1 boundary:** #37 owns conformance to an *external/published* standard; the contract *we* author stays #13, internal time/encoding correctness stays #4, internal idiom stays #8, config validity stays #26. The **safety arm** of G18 (fail-toward-safe defaults, the new ISO 25010:2023 safety characteristic) **shipped 2026-06-24** as add-factors on #2 (code-level fail-toward-safe / fail-closed) and #28 (design-level degrade-toward-safe), each detect-and-escalating deep hazard analysis — completing G18 (both ISO/IEC 25010:2023 characteristics now owned). Rationale in [`research/taxonomy-gap-hunt-round-3.md`](research/taxonomy-gap-hunt-round-3.md) and [`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md).
>
> **v0.6 changes:** promoted the third round-3 (Wave C) new lens — #36 Ethical / responsible-design defects (non-ML) (gap G16); the diff-visible, code-level ethics class with no owner today — dark patterns, manipulative defaults, obstruction, and discriminatory business logic in plain conditionals. The **non-ML analog of #25's harmful-output** and a sibling of #14; strictly **detect-and-route** (consent-as-law → #27/legal, product trade-off → product, a11y mechanics → #23). Deep model-fairness auditing stays out of scope. Adds a `sweeping-for-security ↔ reviewing-ethical-design` tension (protective friction vs. obstruction). Rationale in [`research/taxonomy-gap-hunt-round-3.md`](research/taxonomy-gap-hunt-round-3.md) and [`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md).
>
> **v0.5 changes:** promoted the second round-3 (Wave C) new lens — #35 Agent-legibility (the codebase as a working environment for AI maintainers, gap G20); a Cluster II vantage rotation from "can a human understand it?" to "can an agent understand, navigate, and safely modify this within a context budget?" The **mirror image of #34** (quality of AI-authored code ↔ quality of code for AI readers); cross-links #5–#8/#21/#22/#24/#30. Natural shape `diff`; a whole-repo agent-navigability audit arm is a noted follow-up. Rationale in [`research/taxonomy-gap-hunt-round-3.md`](research/taxonomy-gap-hunt-round-3.md) and [`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md).
>
> **v0.4 changes:** promoted the first round-3 (Wave C) new lens — #34 AI-authored-code defects (the failure signature of machine-authored code, gap G14); attribution-agnostic, cross-refs #18/#1/#11/#14. Rationale in [`research/taxonomy-gap-hunt-round-3.md`](research/taxonomy-gap-hunt-round-3.md) and [`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md).
>
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

### 35. Agent-legibility — the codebase as an environment for AI maintainers  *(promoted v0.5)*

Cluster II's readability axis (#5–#8) **rotated to the agent reader**: *can an AI agent understand, navigate, and safely modify this within a context budget?* — distinct from #5–#8 (human-framed, same axis) and from #24's agent *operator* parity. **Context economy / self-containment:** the change is a depth-first slice understandable without loading the whole repo (the "40% context rule"; grounded in *lost-in-the-middle* retrieval limits). **Retrieval-friendly, AST-navigable structure:** names/paths/boundaries an agent reaches by search, behavior exposed through structurally-addressable surfaces rather than stringly-typed indirection. **Local self-explanation:** the *why* an agent needs sits at the edit site, not in distant files (cross-links #7). **Agent onboarding:** `AGENTS.md` / `CLAUDE.md` present, accurate, and *scoped* (the agent analog of #22's README front-door — drift is #22/#24, artifact-conformance is #30, but *good scoped onboarding content* is here), with do-not-touch guardrails so autonomous edits fail safe; an `llms.txt`-style index for agent-consumed repos. The **mirror image of #34** (quality *of* AI-authored code ↔ quality of code *for* AI readers — neither subsumes the other), and the **G11 pattern again** (the suite optimizes its own artifacts for agent-legibility via D7 but never reviewed for it). **G1 single-owner:** #35 owns the attribution-agnostic agent-as-reader signature and names the overlap, deferring the deep verdict to the owning lens. Natural shape `diff`; a whole-repo agent-navigability audit arm is a noted follow-up. *(Resolves map-gaps G20 — code-owner role; the operator role stays a G9-deepen of #24 + #32/#30.)*

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

Prompt-injection & untrusted-input surface; structured-output validation & schema enforcement; eval/test coverage for nondeterministic behavior; model & prompt versioning/pinning; token & cost efficiency; timeouts / retries / fallbacks for model calls; PII sent to third-party models; response caching; guardrails & refusal handling; reproducibility & temperature discipline; graceful degradation when the model is wrong; **harmful-output eval coverage** (bias/toxicity/safety, detect-and-escalate — deep fairness auditing stays governance, out of scope). *(Model weights as an artifact — model card, datasheet, training-data provenance — are #27.)* **#25 owns the *model call*; the *action/tool* surface is #32 (D14).**

### 32. Agentic & tool-use safety  *(promoted v0.3, D14)*

The **action/tool surface** of agent systems — what the model is permitted to *do*, distinct from #25's *model call*. Tool least-privilege & explicit allow-lists; approval gates & step/iteration budgets on autonomous loops; **tool metadata as untrusted input** (poisoned tool descriptions); confused-deputy & token-audience discipline; inter-agent authentication; sandboxed code execution; agent-memory hygiene; action audit trails; **excessive agency** (OWASP LLM06 / ASI-class). Grounded in OWASP's **Top 10 for Agentic Applications** (ASI01–ASI10) + Threats-and-Mitigations companion and the MCP security-best-practices page. Cross-cuts #13 (tool contracts), #14 (authz), #24 (agent process), #25 (model call). **G1 single-owner:** #32 owns agentic action-safety; the **lethal-trifecta *framing*** stays in #25, but the mitigations that gate its exfil/action leg are #32 (#25 references #32, no double-report). Natural shape `diff`; a repo-shaped whole-agent-system audit arm is a noted follow-up. *(Resolves map-gaps G2; closes Q16.)*

### 28. Operational & resilience design  *(promoted v0.3)*

Design-time operability, distinct from #16's *runtime* operability. **Resilience as design:** failure-mode / blast-radius analysis, bulkheads, graceful degradation, dependency-failure plans (beyond #2/#3 code-level handling). **Recoverability:** RTO/RPO, *tested* restore — not just backups taken (absorbs #20's backup-note). **Scalability as design:** statelessness, horizontal-scaling readiness, single-writer bottlenecks, backpressure on unbounded queues (resolves the dropped #12 factor; absorbs system-wide rate-limit/quota). **Multi-tenancy isolation** (noisy-neighbour, per-tenant quotas). Reviewed at *decision time* (RFC/design doc) and on a diff (a new stateful singleton or unbounded queue). Cross-links #12, #16, #2/#3.

### 34. AI-authored-code defects  *(promoted v0.4)*

The **failure signature of machine-authored code itself**, independent of who or what wrote it — distinct from #25 (code that *calls* a model) and #27 (a provenance *marker*). Now that AI-assisted code is the median diff, these recur and are diff-reviewable: **package hallucination → slopsquatting** (~20% of LLM-recommended packages don't exist, ~43% recur — a registration target); **plausible-but-wrong** constants/APIs and logic that reads fluently; **invented/misused APIs** and **hallucinated internal references** (a symbol used but never defined here); **over-helpful, unrequested additions** (scope creep as a generation artifact); the **weak-default security signature** (~45% of LLM code carries a flaw); **tests that assert the implementation** rather than the spec; fabricated comments/citations; and **duplication instead of reuse**. Does *not* require knowing the author was a model — the signature is attribution-agnostic — but the base rate is highest on generated diffs. **G1 single-owner:** #34 owns the attribution-agnostic AI-defect *signature* and names the overlap, deferring the deep verdict to the owning lens — the *package-existence/slopsquat* leg cross-refs **#18** supply-chain, *plausible-wrong logic* is adjacent to **#1**, *over-helpful additions* to **#11** restraint, the *security* leg to **#14**. Natural shape `diff`. *(Resolves map-gaps G14.)*

### 36. Ethical / responsible-design defects (non-ML)  *(promoted v0.6)*

The **diff-visible, code-level** ethics class — reviewed today only where it is *legal* (#27) or *ML-output* (#25 harmful-output); the **non-ML analog of #25** and a sibling of #14 (harm to the *user/subject* vs. via an *attacker*). **Dark patterns / deceptive flows:** sneaking, fabricated urgency/scarcity, misdirection/confirmshaming, obstruction, forced action, nagging (Mathur's 7 categories; the EDPB's 6 families / 16 subcategories). **Manipulative defaults & asymmetric choices:** pre-checked consent, opt-out harder than opt-in, buried "reject," negative-option/auto-renew. **Discriminatory business logic in plain conditionals:** a hardcoded threshold/branch (direct or by proxy — ZIP, surname, device, locale) that disadvantages a protected or vulnerable group, no model in sight. **Honest state, wired consent (withdrawal as easy as granting — GDPR Art. 7(3)), and coercion-free control flow.** Grounded in live regulation (GDPR Art. 7, DSA Art. 25, FTC Act §5); automated detection caps below ~50%, so it is a **judgment lens**. **G1 single-owner:** #36 owns the attribution-agnostic diff-visible ethical-defect signature and is strictly **detect-and-route (G8/G23)** — names the pattern with evidence, then routes the *decision*: consent-as-law → **#27** / `legal`, product/UX trade-off → `product` / `leadership`, a11y mechanics → **#23**; it never adjudicates a non-engineering call nor silently drops one. Discriminatory logic and consent-theater are typically genuine `defect`s; most dark-pattern verdicts are `route: product`. Natural shape `diff`; a design-time arm is a noted follow-up. **Out of scope:** deep model-fairness / dataset auditing (no diff artifact — governance); user-facing *transparency UX* is the unbuilt G24 VII-G. *(Resolves map-gaps G16.)*

### 37. Interoperability & external-standard conformance  *(promoted v0.7)*

The first of the two ISO/IEC 25010:2023 characteristics with no owner — **compatibility / interoperability**: *does the code correctly speak the external standards and protocols it claims to?* #13 owns the contract **we** design and publish; #8 owns **internal** idiom; #4 owns **internal** time/encoding/number correctness — none asks whether a value crossing the boundary conforms to the **external** spec a third party parses. Consolidates the scattered factor-notes: **HTTP semantics** (safe/idempotent methods, status codes, conditional requests & caching — RFC 9110/9111; idempotency keys); **OAuth 2.0 / OIDC** flow correctness (exact `redirect_uri`, `state`/`nonce`, PKCE — RFC 9700, OIDC Core); **SemVer** discipline and wire/format back-compat; **RFC-defined formats** (date RFC 3339, URI RFC 3986, email RFC 5321/5322, JSON RFC 8259, CSV RFC 4180); **Unicode** normalization & encoding edges (UAX #15, UTS #39/#46, UTF-8, the YAML "Norway" class); **cron/schedule dialects** (POSIX vs. Quartz); **OTel semantic conventions** and well-known files; and the ISO **co-existence** facet (sharing ports/global state/filesystem without detriment). **G1 single-owner:** #37 owns conformance to an *external/published* standard and cross-links #4/#8/#13/#26, deferring the internal-correctness or contract-authoring verdict to them. Natural shape `diff`; deep standards-**certification** machinery escalates (G8). *(Resolves the interoperability arm of map-gaps G18; the safety arm shipped 2026-06-24 as add-factors on #2/#28 — both ISO/IEC 25010:2023 unowned characteristics now closed.)*

### 38. Threat modeling / design-time security  *(promoted v0.8, G30)*

The **generative** design-time security discipline: enumerate what an adversary could do, boundary by boundary, before the code is trusted — **STRIDE** per component, **data-flow + trust-boundary** analysis, **attack trees**, **abuse/misuse cases**, Shostack's four questions. Distinct from #14 (diff-time vuln *detection*), #32 (agentic action surface), and #25 (the model call). **G1 single-owner:** #38 owns the enumeration and **delegates** the deep verdict — a concrete vuln → #14, an agent action/tool threat → #32, an LLM prompt-injection/output threat → #25 — and **detect-and-escalates (G8)** to human security review only for custom-crypto correctness or third-party-auth adjudication. Works on a design doc/RFC when present and **reconstructs** the implied design from code/config when absent (bounded to architecture level). Natural shape `diff`, design-capable. *(Resolves map-gaps G30.)*

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

The machinery wrapped around the code, reviewed as its own surface (the G10 framing gap — a *silent* hole no taxonomy-vs-skills diff could find). **Suppression hygiene:** `# noqa` / `eslint-disable` / `# type: ignore` accretion, blanket-disabled rules, lint-baseline growth, suppressions with no rationale or expiry — the act of *opting out of enforcement* (cross #8, #19, #21). **Monitoring-config as artifact:** alert-rule / dashboard / SLO-definition correctness, symptom-based alerting, runbook linkage, dashboard drift — the config, not the instrumentation (#16). **Codegen ↔ source drift:** checked-in generated/compiled output stale vs. its generator/spec. **Artifact-authoring quality** *(G11, D15)*: is a non-source artifact that carries its own published "well-formed X" standard actually well-formed per that standard — `SKILL.md` / agent skills (Anthropic authoring best-practices), `AGENTS.md`, MCP tool surfaces, model cards, datasheets — *the authoring quality, distinct from #22 doc-drift and #32 runtime agent-safety.* Reviewed via the **`shape: artifact`** mechanism (D15, **shipped 2026-06-24**): the lens `reviewing-artifact-conventions` presence-detects an artifact and loads its bundled rubric (rubric content in [`research/artifact-rubrics.md`](research/artifact-rubrics.md)); first artifact is `SKILL.md` authoring.

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

### 33. Install, upgrade & configuration experience  *(promoted v0.3)*

The experience of a downstream **consumer** adopting, configuring, and upgrading this software — the adopter-facing counterpart to #29's "should *we* adopt this dependency" call, and distinct from end-user product UX. **Install / setup:** first-run friction, undocumented prerequisites, idempotent & reproducible installers, time-to-first-success. **Config UX:** safe defaults and a zero-config common case, startup schema validation with fail-fast actionable errors, backward-compatible keys (#26 is the *internal* config-hygiene view; this is the *adopter*-facing one). **Upgrade / migration:** SemVer-correct breaking-change signaling, codemods / migration commands and upgrade notes that let a consumer *or a code agent* complete and verify a version bump from the docs alone, deprecation windows over silent removals, and a downgrade / rollback path. Pulls together the adopter-facing slices of #22 (docs), #13 (contract), #26 (config), and #29 (deprecation) as one reviewable experience. Natural shape `diff`, design-capable; a whole-repo "is this pleasant to adopt" audit arm is a noted follow-up. Grounded in the scope-boundary reframe ([`research/product-experience-value-cluster.md`](research/product-experience-value-cluster.md), G23 detect-and-route): adopter experience is reviewable at review time even when some calls route to maintainers/product.

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
- **Agentic / tool-use safety** *(2026-06-12)* — **PROMOTED → #32 (D14, closes Q16 / map-gaps G2).** OWASP shipped a dedicated agentic Top 10 (ASI01–ASI10); the trigger gap (agent-heavy repos that don't read as "LLM integration") + G1 cross-cutting ownership cleared the bar. Research moves from #25 to a new #32 section in the build phase.
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
- **Numbering note:** v0.2 appended 25–27, v0.3 appended 28–33, v0.4 appended #34, v0.5 appended #35, and v0.6 appended #36 within their clusters (rather than renumber and churn cross-references). Order within a cluster is by topic, not number. (#32 sits with #25 in the AI/LLM cluster; #33 sits with #21/#22/#29 in Cluster VI; #34 and #36 sit with the runtime cluster IV; #35 sits with #5–#8 in Cluster II.) v0.8 appended #38 in cluster IV (with #14/#25/#32 in the runtime cluster).
- **Topic vs. shape are different axes.** A category is a *topic*; how it's reviewed is a *shape* (diff / repo-cron / decision-time / **artifact**). Most categories are diff-shaped; #21/#30/#31 and the repo audits are repo-shaped; #29 — and the decision-time facets of #27/#28/#25 — are **decision-shaped** ([`decision-time-review-shape.md`](decision-time-review-shape.md)); the #30 artifact-authoring factor is **artifact-shaped** — a fourth shape (D15) where a presence-detected artifact gates an on-demand, artifact-specific rubric ([`research/artifact-scoped-lenses.md`](research/artifact-scoped-lenses.md)). The shape cuts across the topic-clusters, like diff-vs-repo already does.
- **Granularity remains the central phase-2 question:** the categories will *not* map 1:1 to skills. Expect collapse into coarser, composable skills. See [`open-questions.md`](open-questions.md) Q1.
