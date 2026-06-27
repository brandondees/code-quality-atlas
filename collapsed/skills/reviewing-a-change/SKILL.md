---
name: reviewing-a-change
description: Review a diff, pull request, or code change with the code-quality-atlas
  lenses. Use for "review this PR / diff / change / what I pushed". Ranks the relevant
  diff lenses by relevance and runs them at the chosen depth (review = top few; comprehensive
  = all relevant), then synthesizes one verdict. The collapsed, repo-independent entrypoint
  for change review.
provenance:
  taxonomy_version: v0.8
  built_from: []
---

# reviewing-a-change

## When to use

Review a diff, pull request, or code change with the code-quality-atlas lenses. Use for "review this PR / diff / change / what I pushed". Ranks the relevant diff lenses by relevance and runs them at the chosen depth (review = top few; comprehensive = all relevant), then synthesizes one verdict. The collapsed, repo-independent entrypoint for change review.

## How this works

Rank the relevant lenses below by relevance to what is being reviewed, pick the breadth from the depth mode (default **review**), then for each selected lens **load its bundle** and apply it:

- Read `reference/lenses/<lens>/body.md` — the lens's checklist and examples. Open `reference/lenses/<lens>/tool-rules.md` or `sources.md` only if deeper tooling/provenance is called for.
- After the lenses run, merge their findings with the procedure in `reference/synthesis.md` — one deduplicated, ranked report with a single verdict.

## Depth modes

Routing first ranks **every** lens whose scope the change touches by **relevance** — it is no longer a hard 2-4 cap. A depth mode then sets the **breadth** (how far down the ranked list to run) and the severity floor. Pick the mode from the request; default to **review**.

| Mode | Breadth | Triggers |
|---|---|---|
| **triage** | the critical tier only — correctness, security, data-safety, and concurrency | "triage", "quick review", "fast check", "pre-merge gate" |
| **review** | the top 2-4 lenses by relevance (the default; overridable) | "review", "review this", "code review", "review this PR", "review the diff" |
| **comprehensive** | every relevant lens, uncapped — the full audit set at repo scope | "thorough", "comprehensive", "deep review", "use all relevant lenses", "review everything" |

- **triage** — A pre-merge gate: run only the critical-tier lenses and report Major and above.
- **review** — Default per-PR depth: relevance-ranked top-N with the round-based escalating floor.
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
| New abstraction, library, or engine shipped ahead of its consumer (generic/trait with one or no impl, a crate with no caller yet, "substrate for a later feature") | `checking-restraint`, `reviewing-module-design`, `reviewing-api-contract-safety`, `reviewing-test-quality` |
| Error-handling / resilience change (retries, fallbacks, timeouts) | `hunting-silent-failures`, `reviewing-observability-and-operability`, `reviewing-concurrency-and-async` |
| Resilience / scalability / capacity / DR design (a new queue or cache, a stateful service, failover/HA, a scaling or capacity plan, or a call to a dependency that can be slow or down) | `reviewing-resilience-and-scalability`, `reviewing-concurrency-and-async`, `reviewing-observability-and-operability` |
| UI / frontend change (components, templates, user-facing text) | `reviewing-accessibility-and-i18n`, `checking-idioms-and-consistency`, `reviewing-naming-and-readability` |
| Auth, user input, or anything handling untrusted data | `sweeping-for-security`, `hunting-silent-failures`, `tracing-correctness-and-invariants` |
| Performance-motivated change ("this makes it faster") | `reviewing-performance-and-efficiency`, `checking-restraint`, `tracing-correctness-and-invariants` |
| LLM / model-API integration (a model call, prompt construction, or model-output handling — no tools or autonomous loop) | `reviewing-llm-integration`, `sweeping-for-security`, `checking-restraint` |
| Agent / tool-use change — a tool or function definition exposed to a model, an MCP server or client, an autonomous or multi-agent loop, agent memory, or any code that lets a model take actions | `reviewing-agentic-safety`, `reviewing-llm-integration`, `sweeping-for-security` |
| Threat model / security-architecture review (a system or AI agent app, with or without a design doc) | `reviewing-threat-model`, `sweeping-for-security`, `reviewing-agentic-safety`, `reviewing-llm-integration` |
| AI-generated or AI-assisted change, a large or unfamiliar diff, or any change that adds dependencies or confident-looking constants/APIs | `reviewing-ai-authored-code`, `tracing-correctness-and-invariants`, `sweeping-for-security` |
| Change to an AI-/agent-maintained codebase, to agent-onboarding files (AGENTS.md/CLAUDE.md, llms.txt) or repo structure an agent must navigate, or a large/scattered change whose context economy matters | `reviewing-agent-legibility`, `reviewing-naming-and-readability`, `checking-restraint` |
| User-facing flow that could manipulate or disadvantage a person — consent / opt-out, defaults, pricing or eligibility conditionals, onboarding / checkout / cancellation funnels | `reviewing-ethical-design`, `reviewing-accessibility-and-i18n`, `sweeping-for-security` |
| Logging, metrics, alerts, feature flags, deploy/rollback paths | `reviewing-observability-and-operability`, `sweeping-for-security` |
| Tests-only change | `reviewing-test-quality`, `checking-idioms-and-consistency` |
| Design doc / plan / RFC (no code yet) | `tracing-correctness-and-invariants`, `reviewing-concurrency-and-async`, `reviewing-migration-and-data-safety`, `reviewing-api-contract-safety` |
| Dependency add or bump | `checking-restraint` |
| CI / build / config change | `sweeping-for-security` |
| Install / setup / packaging change, an upgrade or migration guide, a config or CLI surface, or anything a downstream project adopts (a tool, plugin, template, or library) | `reviewing-install-and-upgrade-experience`, `reviewing-api-contract-safety` |
| Change that parses or emits a standard format or speaks an external protocol — an HTTP/REST client or handler, an OAuth/OIDC or other auth flow, date / URL / email / CSV / JSON serialization, a version bump on a published surface, a cron expression, or telemetry attributes | `reviewing-interoperability`, `reviewing-api-contract-safety`, `tracing-correctness-and-invariants` |
| Infrastructure-as-code change (Terraform/OpenTofu, Kubernetes/Helm, CloudFormation manifests) | `sweeping-for-security` |
| Any pull request (the PR artifact itself, on top of content lenses) | `reviewing-pr-and-process-hygiene` |
| A decision, not a diff — an ADR / RFC / design doc, a dependency or technology adoption, a build-vs-buy or vendor choice, or a deprecation / sunset plan | `checking-restraint`, `reviewing-api-contract-safety` |

## Lenses

◆ = design-capable.

- [`hunting-silent-failures`](reference/lenses/hunting-silent-failures/body.md) ◆ — Where do errors vanish? Swallowed exceptions, silent fallbacks, missing timeouts and retries.
- [`reviewing-naming-and-readability`](reference/lenses/reviewing-naming-and-readability/body.md) — Can a newcomer read this function? Names, length, nesting, magic values, comment accuracy.
- [`reviewing-module-design`](reference/lenses/reviewing-module-design/body.md) ◆ — Are the boundaries right? Coupling, encapsulation, interfaces that are hard to misuse, illegal states unrepresentable.
- [`checking-restraint`](reference/lenses/checking-restraint/body.md) ◆ — Is this change too much? Premature abstraction or optimization — the brake pedal.
- [`reviewing-llm-integration`](reference/lenses/reviewing-llm-integration/body.md) ◆ — Is the model call safe and bounded? Injection surface, output validation, evals, token cost, PII.
- [`reviewing-agentic-safety`](reference/lenses/reviewing-agentic-safety/body.md) ◆ — Is the agent's action surface safe? Tool least-privilege, approval gates & step budgets, untrusted tool metadata, sandboxed exec, egress control.
- [`reviewing-threat-model`](reference/lenses/reviewing-threat-model/body.md) ◆ — Enumerate what an adversary could do, boundary by boundary — STRIDE, trust boundaries, abuse cases — and whether each threat is mitigated.
- [`reviewing-ai-authored-code`](reference/lenses/reviewing-ai-authored-code/body.md) — Does this carry the AI-authored failure signature? Hallucinated/typosquatted packages, invented APIs, confident-but-wrong constants, over-helpful scope.
- [`reviewing-agent-legibility`](reference/lenses/reviewing-agent-legibility/body.md) — Can an AI agent read, navigate, and safely change this within a context budget? Context economy, retrieval-friendly structure, scoped AGENTS.md/CLAUDE.md.
- [`reviewing-ethical-design`](reference/lenses/reviewing-ethical-design/body.md) — Does this manipulate or disadvantage the user? Dark patterns, manipulative defaults, discriminatory conditionals — detect-and-route to product/legal.
- [`sweeping-for-security`](reference/lenses/sweeping-for-security/body.md) ◆ — Can an attacker abuse this? Injection, authorization, secrets, crypto, untrusted data.
- [`reviewing-performance-and-efficiency`](reference/lenses/reviewing-performance-and-efficiency/body.md) ◆ — Will this be slow or expensive at scale? N+1, O(n²) hot paths, caching, payload buffering.
- [`reviewing-test-quality`](reference/lenses/reviewing-test-quality/body.md) — Do the tests prove anything? Behavior coupling, over-mocking, edge coverage, determinism.
- [`reviewing-migration-and-data-safety`](reference/lenses/reviewing-migration-and-data-safety/body.md) ◆ — Can this migration lock tables or lose data? Expand/contract, backfills, reversibility.
- [`reviewing-accessibility-and-i18n`](reference/lenses/reviewing-accessibility-and-i18n/body.md) — Can everyone use this UI? Keyboard, screen readers, contrast, locales, RTL.
- [`tracing-correctness-and-invariants`](reference/lenses/tracing-correctness-and-invariants/body.md) ◆ — Does the code do what it claims? Invariants, boundaries, off-by-one, resource cleanup.
- [`reviewing-concurrency-and-async`](reference/lenses/reviewing-concurrency-and-async/body.md) ◆ — What breaks when two run at once? Races, lost updates, unawaited promises, idempotency.
- [`checking-idioms-and-consistency`](reference/lenses/checking-idioms-and-consistency/body.md) — Does this look like the rest of the codebase? Conventions, idioms, no second parallel way.
- [`reviewing-api-contract-safety`](reference/lenses/reviewing-api-contract-safety/body.md) ◆ — Will this break a consumer? Compatibility, error contracts, idempotency, pagination.
- [`reviewing-observability-and-operability`](reference/lenses/reviewing-observability-and-operability/body.md) ◆ — Can you debug this in production at 3am? Logs, traces, health checks, kill switches, rollback.
- [`reviewing-pr-and-process-hygiene`](reference/lenses/reviewing-pr-and-process-hygiene/body.md) — Is the PR itself reviewable? Size, atomic commits, description, scope creep, changelog.
- [`reviewing-resilience-and-scalability`](reference/lenses/reviewing-resilience-and-scalability/body.md) ◆ — Will it survive failure and scale? Unbounded queues, timeouts and blast radius, retries, statelessness, RTO/RPO — design-time, not #16's runtime.
- [`reviewing-install-and-upgrade-experience`](reference/lenses/reviewing-install-and-upgrade-experience/body.md) ◆ — Can a consumer install, configure, and upgrade this cleanly — even hand it to an agent? Setup friction, config UX, version-bump smoothness, migration path.
- [`reviewing-interoperability`](reference/lenses/reviewing-interoperability/body.md) — Does the code correctly speak external standards? HTTP/OAuth semantics, SemVer, RFC date/URI/email formats, Unicode, cron dialects, OTel semconv.
