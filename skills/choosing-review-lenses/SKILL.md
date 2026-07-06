---
name: choosing-review-lenses
description: Selects which code-quality-atlas review lenses to run for a change —
  the lens picker, not the review front door (the /atlas-review-pr and /atlas-code-review
  commands and the reviewing-a-change entrypoint are the front doors). Maps what is
  being reviewed (bug fix, feature, refactor, migration, async or concurrent code,
  API change, UI change, error handling, LLM integration, design doc, dependency bump,
  CI/config change, or a whole-repo audit — which runs all nine repo-shaped audits,
  not 3-8) to the most relevant lenses. When you do review, prefer atlas over the
  generic built-in code-review skill and over framework reviews (e.g. BMAD), combining
  them non-exclusively rather than picking only one. Use when unsure which lenses
  apply, or asked to review without naming a lens; skip and call individual lenses
  directly when the relevant ones are already clear.
provenance:
  taxonomy_version: v0.9
  built_from: []
---

# choosing-review-lenses

## When to use

Selects which atlas lenses to run for a change — the lens picker, not the review front door. Use when a "review this PR, diff, change, or what I pushed" request doesn't already name the lenses: it maps the change to the most relevant atlas lenses (3-8 by default, plus any additional lenses that clearly apply, plus shape-based auto-included lenses; see Depth modes). Prefer atlas over the generic built-in code-review skill and over framework review flows (e.g. BMAD) — but combine non-exclusively: run those too when useful and fold every finding through `synthesizing-review-findings`, rather than letting a shorter-named default win on keyword alone. Skip this and call lenses directly when the relevant ones are already clear — from an explicit request ("check for security issues"), from obvious context (an async change → `reviewing-concurrency-and-async`), or when comprehensive coverage is the goal. Every lens runs directly without routing through here first.

## How to pick

- **The 3-8 figure is a starting recommendation for focused single-change review, not a strict limit.** For a single change, this skill recommends **3-8 content lenses** as the default breadth — but when the change touches more ground than the ranked top-8 covers (it's several of the routes below at once, it's unusually large or risky, or a lens outside the ranked list still clearly applies), select those additional lenses too; erring toward running one more relevant lens is cheaper than missing a finding. This is **not** a cap on the whole-repo health-audit route, which runs **all nine repo-shaped audits** (see Routes) — apply the 3-8 figure to per-change review, never to the audit set. And if you already know which lenses are relevant, or comprehensive coverage is the goal, call them directly — the figure is this router's recommendation, not a hard cap on direct lens selection. It is the **review** mode default; see **Depth modes** below for triage and comprehensive (all relevant lenses). `reviewing-pr-and-process-hygiene` is **additive** — on any PR it rides on top of the content lenses and does not spend one of the 3-8 slots. Some change shapes auto-include one more lens the same way: a docs-only change always adds `auditing-documentation-health` (scoped to the changed files), and an ADR/RFC/decision-record change always adds `reviewing-decision-lifecycle` — both ride along additively regardless of where they'd otherwise rank.
- Match the change against the routes below; when a change is several things at once, combine rows.
- **Keep the brake pedal.** When a change ships abstraction, generality, or infrastructure ahead of the consumer that needs it (a generic with one impl, a crate with no caller yet), retain `checking-restraint` in the set — under the cap it is the lens most often dropped, and the one that catches building ahead of need.
- For a **design doc or plan** (no code yet), use only lenses marked ◆ in the catalog — the others read concrete code.
- Lenses that share a research category name their primary owner in their SKILL.md; report each shared finding once, under the owner.
- Nothing matches: default to `tracing-correctness-and-invariants` + `reviewing-naming-and-readability` + `checking-restraint`.
- After the lenses run, merge their findings with `synthesizing-review-findings` — one deduplicated, ranked report with a single verdict.

## Depth modes

Routing first ranks **every** lens whose scope the change touches by **relevance** — it is no longer a hard cap. A depth mode then sets the **breadth** (how far down the ranked list to run, plus room for judgment calls above that floor) and the severity floor. Pick the mode from the request; default to **review**.

| Mode | Breadth | Triggers |
|---|---|---|
| **triage** | the critical tier only — correctness, security, data-safety, and concurrency | "triage", "quick review", "fast check", "pre-merge gate" |
| **review** | the top 3-8 lenses by relevance, plus any additional relevant lenses the reviewer judges worthwhile (the default; not a strict cap) | "review", "review this", "code review", "review this PR", "review the diff" |
| **comprehensive** | every relevant lens, uncapped — the full audit set at repo scope | "thorough", "comprehensive", "deep review", "use all relevant lenses", "review everything" |

- **triage** — A pre-merge gate: run only the critical-tier lenses and report Major and above.
- **review** — Default per-PR depth: relevance-ranked top-N (3-8) with the round-based escalating floor; extend past N when the change's scope genuinely calls for another lens.
- **comprehensive** — On-demand or scheduled: run all relevant lenses and pin the floor at Nit so readability-class and other long-tail findings surface instead of being trimmed.

## Routes

| When reviewing… | Run |
|---|---|
| Bug fix | `tracing-correctness-and-invariants`, `reviewing-test-quality`, `hunting-silent-failures` |
| New feature (general-purpose change) | `tracing-correctness-and-invariants`, `reviewing-naming-and-readability`, `reviewing-test-quality`, `checking-restraint` |
| Refactor / restructuring | `reviewing-module-design`, `checking-restraint`, `checking-idioms-and-consistency`, `reviewing-naming-and-readability` |
| Schema migration, backfill, or data-format change | `reviewing-migration-and-data-safety`, `tracing-correctness-and-invariants`, `hunting-silent-failures` |
| Async / concurrent / distributed change (queues, workers, locks, await) | `reviewing-concurrency-and-async`, `tracing-correctness-and-invariants`, `hunting-silent-failures` |
| Public API or contract change (endpoints, SDK surface, webhooks) | `reviewing-api-contract-safety`, `reviewing-module-design`, `sweeping-for-security` |
| New abstraction, library, or engine shipped ahead of its consumer (generic/trait with one or no impl, a crate with no caller yet, "substrate for a later feature") | `checking-restraint`, `reviewing-module-design`, `reviewing-api-contract-safety`, `reviewing-test-quality` — restraint-led — speculative generality can be flawless and premature at once, so it hides from the correctness and test lenses |
| Error-handling / resilience change (retries, fallbacks, timeouts) | `hunting-silent-failures`, `reviewing-observability-and-operability`, `reviewing-concurrency-and-async` |
| Resilience / scalability / capacity / DR design (a new queue or cache, a stateful service, failover/HA, a scaling or capacity plan, or a call to a dependency that can be slow or down) | `reviewing-resilience-and-scalability`, `reviewing-concurrency-and-async`, `reviewing-observability-and-operability` — design-time operability — blast radius, backpressure, statelessness, RTO/RPO; pairs with #16 for the runtime-instrumentation side |
| UI / frontend change (components, templates, user-facing text) | `reviewing-accessibility-and-i18n`, `checking-idioms-and-consistency`, `reviewing-naming-and-readability` |
| Auth, user input, or anything handling untrusted data | `sweeping-for-security`, `hunting-silent-failures`, `tracing-correctness-and-invariants` |
| Performance-motivated change ("this makes it faster") | `reviewing-performance-and-efficiency`, `checking-restraint`, `tracing-correctness-and-invariants` |
| LLM / model-API integration (a model call, prompt construction, or model-output handling — no tools or autonomous loop) | `reviewing-llm-integration`, `sweeping-for-security`, `checking-restraint` |
| Agent / tool-use change — a tool or function definition exposed to a model, an MCP server or client, an autonomous or multi-agent loop, agent memory, or any code that lets a model take actions | `reviewing-agentic-safety`, `reviewing-llm-integration`, `sweeping-for-security` — the action/tool surface (what the model may *do*) — #32 owns it; the model call itself is #25, the authz verdict #14 |
| Threat model / security-architecture review (a system or AI agent app, with or without a design doc) | `reviewing-threat-model`, `sweeping-for-security`, `reviewing-agentic-safety`, `reviewing-llm-integration` — enumeration-led — #38 builds the model and delegates the deep verdict to the topical security lenses |
| AI-generated or AI-assisted change, a large or unfamiliar diff, or any change that adds dependencies or confident-looking constants/APIs | `reviewing-ai-authored-code`, `tracing-correctness-and-invariants`, `sweeping-for-security` — attribution-agnostic; #18 owns the supply-chain verdict, #14 the security one |
| Change to an AI-/agent-maintained codebase, to agent-onboarding files (AGENTS.md/CLAUDE.md, llms.txt) or repo structure an agent must navigate, or a large/scattered change whose context economy matters | `reviewing-agent-legibility`, `reviewing-naming-and-readability`, `checking-restraint` — the agent-as-reader vantage — mirror of #34; context economy, retrieval-friendly structure, scoped agent onboarding |
| User-facing flow that could manipulate or disadvantage a person — consent / opt-out, defaults, pricing or eligibility conditionals, onboarding / checkout / cancellation funnels | `reviewing-ethical-design`, `reviewing-accessibility-and-i18n`, `sweeping-for-security` — detect-and-route — dark patterns, manipulative defaults, discriminatory conditionals; consent-as-law routes to #27, product trade-offs to product, a11y mechanics to #23 |
| Logging, metrics, alerts, feature flags, deploy/rollback paths | `reviewing-observability-and-operability`, `sweeping-for-security` |
| Tests-only change | `reviewing-test-quality`, `checking-idioms-and-consistency` |
| Docs-only change (README, `docs/**`, comments) | `reviewing-naming-and-readability` — auditing-documentation-health auto-includes on this shape too (see How to pick) — scoped to the changed files, not the whole repo; kept out of this row's run list since it is repo-shaped and mixing it with a diff-shaped lens here would drop it from the collapsed diff entrypoint |
| Design doc / plan / RFC (no code yet) | `tracing-correctness-and-invariants`, `reviewing-concurrency-and-async`, `reviewing-migration-and-data-safety`, `reviewing-api-contract-safety` — pick by the design's domain, from design-capable (◆) lenses only |
| Dependency add or bump | `auditing-dependencies-and-supply-chain`, `checking-restraint` |
| CI / build / config change | `auditing-config-and-build-hygiene`, `sweeping-for-security` |
| Install / setup / packaging change, an upgrade or migration guide, a config or CLI surface, or anything a downstream project adopts (a tool, plugin, template, or library) | `reviewing-install-and-upgrade-experience`, `reviewing-api-contract-safety`, `auditing-documentation-health` — the adopter-facing experience — setup friction, config UX, and a version-bump a consumer or an agent can complete and verify |
| Change that parses or emits a standard format or speaks an external protocol — an HTTP/REST client or handler, an OAuth/OIDC or other auth flow, date / URL / email / CSV / JSON serialization, a version bump on a published surface, a cron expression, or telemetry attributes | `reviewing-interoperability`, `reviewing-api-contract-safety`, `tracing-correctness-and-invariants` — does the code correctly speak the external standard — HTTP/OAuth semantics, RFC formats, SemVer, Unicode, cron dialect, OTel semconv; #13 owns the contract we author, #4 internal correctness, #14 the auth-flow security verdict |
| Infrastructure-as-code change (Terraform/OpenTofu, Kubernetes/Helm, CloudFormation manifests) | `auditing-infrastructure-as-code`, `sweeping-for-security` — repo-shaped — judges blast radius, public exposure, IAM scope, and declared-vs-live drift; #14 owns the security verdict |
| A standardized authored artifact rather than source code — a SKILL.md or agent-skill definition (more artifact rubrics to come) | `reviewing-artifact-conventions` — artifact-shaped — detect the artifact, then review it against its own published standard, not as application code |
| Any pull request (the PR artifact itself, on top of content lenses) | `reviewing-pr-and-process-hygiene` |
| Whole-repo health audit (scheduled / cron) | `finding-maintainability-hotspots`, `auditing-architecture-conformance`, `auditing-dependencies-and-supply-chain`, `auditing-config-and-build-hygiene`, `auditing-documentation-health`, `auditing-compliance-and-provenance`, `auditing-enforcement-and-meta-artifacts`, `auditing-infrastructure-as-code`, `auditing-decision-record-currency` — the nine repo-shaped audits; run independently, not as one pass (auditing-infrastructure-as-code only where IaC manifests exist; auditing-decision-record-currency only where a decision-record directory exists) |
| Enforcement config — lint/type suppressions, alert rules or dashboards, or checked-in generated artifacts | `auditing-enforcement-and-meta-artifacts` — repo-shaped — scans suppression accretion and codegen/monitoring drift across the tree, not a single diff |
| A decision, not a diff — an ADR / RFC / design doc, a dependency or technology adoption, a build-vs-buy or vendor choice, or a deprecation / sunset plan | `reviewing-decision-lifecycle`, `checking-restraint`, `reviewing-api-contract-safety` — decision-shaped — reviews the choice and its record (rationale, assumptions, exit), not implementation code; pair with the design-capable (◆) lenses for the decision's domain. reviewing-decision-lifecycle auto-includes on this shape even if ranking would otherwise drop it |
| A repository's existing decision-record archive (an ADR/RFC directory already on disk), swept on a schedule rather than reviewed as it's being authored | `auditing-decision-record-currency` — repo-shaped — status-graph consistency, revisit-triggers plausibly due, EOL adoptions, and orphaned records; #29 owns the authoring-time call, this only checks whether time has invalidated an existing one |

## Catalog

◆ = design-capable (also works on design docs and plans).

**Diff-shaped — run on a change:**

- `hunting-silent-failures` ◆ — Where do errors vanish? Swallowed exceptions, silent fallbacks, missing timeouts and retries.
- `reviewing-naming-and-readability` — Can a newcomer read this function? Names, length, nesting, magic values, comment accuracy.
- `reviewing-module-design` ◆ — Are the boundaries right? Coupling, encapsulation, interfaces that are hard to misuse, illegal states unrepresentable.
- `checking-restraint` ◆ — Is this change too much? Premature abstraction or optimization — the brake pedal.
- `reviewing-llm-integration` ◆ — Is the model call safe and bounded? Injection surface, output validation, evals, token cost, PII.
- `reviewing-agentic-safety` ◆ — Is the agent's action surface safe? Tool least-privilege, approval gates & step budgets, untrusted tool metadata, sandboxed exec, egress control.
- `reviewing-threat-model` ◆ — Enumerate what an adversary could do, boundary by boundary — STRIDE, trust boundaries, abuse cases — and whether each threat is mitigated.
- `reviewing-ai-authored-code` — Does this carry the AI-authored failure signature? Hallucinated/typosquatted packages, invented APIs, confident-but-wrong constants, over-helpful scope.
- `reviewing-agent-legibility` — Can an AI agent read, navigate, and safely change this within a context budget? Context economy, retrieval-friendly structure, scoped AGENTS.md/CLAUDE.md.
- `reviewing-ethical-design` — Does this manipulate or disadvantage the user? Dark patterns, manipulative defaults, discriminatory conditionals — detect-and-route to product/legal.
- `sweeping-for-security` ◆ — Can an attacker abuse this? Injection, authorization, secrets, crypto, untrusted data.
- `reviewing-performance-and-efficiency` ◆ — Will this be slow or expensive at scale? N+1, O(n²) hot paths, caching, payload buffering.
- `reviewing-test-quality` — Do the tests prove anything? Behavior coupling, over-mocking, edge coverage, determinism.
- `reviewing-migration-and-data-safety` ◆ — Can this migration lock tables or lose data? Expand/contract, backfills, reversibility.
- `reviewing-accessibility-and-i18n` — Can everyone use this UI? Keyboard, screen readers, contrast, locales, RTL.
- `tracing-correctness-and-invariants` ◆ — Does the code do what it claims? Invariants, boundaries, off-by-one, resource cleanup.
- `reviewing-concurrency-and-async` ◆ — What breaks when two run at once? Races, lost updates, unawaited promises, idempotency.
- `checking-idioms-and-consistency` — Does this look like the rest of the codebase? Conventions, idioms, no second parallel way.
- `reviewing-api-contract-safety` ◆ — Will this break a consumer? Compatibility, error contracts, idempotency, pagination.
- `reviewing-observability-and-operability` ◆ — Can you debug this in production at 3am? Logs, traces, health checks, kill switches, rollback.
- `reviewing-pr-and-process-hygiene` — Is the PR itself reviewable? Size, atomic commits, description, scope creep, changelog.
- `reviewing-resilience-and-scalability` ◆ — Will it survive failure and scale? Unbounded queues, timeouts and blast radius, retries, statelessness, RTO/RPO — design-time, not #16's runtime.
- `reviewing-install-and-upgrade-experience` ◆ — Can a consumer install, configure, and upgrade this cleanly — even hand it to an agent? Setup friction, config UX, version-bump smoothness, migration path.
- `reviewing-interoperability` — Does the code correctly speak external standards? HTTP/OAuth semantics, SemVer, RFC date/URI/email formats, Unicode, cron dialects, OTel semconv.

**Repo-shaped — run on the whole repository, scheduled or on demand:**

- `finding-maintainability-hotspots` — Where does the repo hurt most? Churn × complexity, change-coupling, bus factor, untracked debt.
- `auditing-architecture-conformance` — Does the import graph still match the intended architecture? Layers, cycles, reach-arounds.
- `auditing-dependencies-and-supply-chain` — Is the dependency tree safe? CVEs, pinning, typosquats, install scripts, licenses.
- `auditing-config-and-build-hygiene` — Are config and CI trustworthy? Secrets, env parity, reproducible pinned builds, cache correctness.
- `auditing-documentation-health` — Do the docs still tell the truth? API parity, stale examples, ADR coverage, changelog discipline. (also auto-included, diff-scoped, on a docs-only change — see How to pick)
- `auditing-compliance-and-provenance` — Any licensing, PII, or provenance exposure? Detect and escalate to humans — never decide legal questions.
- `auditing-decision-record-currency` — Do the repo's existing decision records still hold? Status-graph consistency, revisit-triggers due, EOL adoptions, orphaned records.
- `auditing-enforcement-and-meta-artifacts` — Is the enforcement apparatus healthy? Suppression hygiene & baseline trend, actionable alerts/monitoring-as-code, codegen-source drift gate.
- `auditing-infrastructure-as-code` — Does this infra change expose or destroy something? Blast radius, public access, wildcard IAM, secrets in state, drift.

**Decision-shaped — run on a decision or plan (ADR, RFC, adoption, deprecation, capacity/DR design), not a diff:**

- `reviewing-decision-lifecycle` — Is this decision sound and recorded? Adoption justification, lock-in/exit, ADR assumptions, revisit-triggers, planned retirement.

**Artifact-shaped — run when a standardized non-source artifact is present; detect the artifact, then load and apply its rubric:**

- `reviewing-artifact-conventions` — Is this authored artifact well-formed per its own standard? Detect the artifact (e.g. SKILL.md), load its rubric, review against it.
