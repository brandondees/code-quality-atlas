---
name: reviewing-a-decision
description: Review a decision rather than code — an ADR, RFC, design doc, dependency
  or technology adoption, build-vs-buy or vendor choice, or a deprecation/sunset plan.
  Reviews the choice and its record (rationale, lock-in, exit, revisit trigger) with
  the decision lens plus the design-capable lenses for the decision's domain.
provenance:
  taxonomy_version: v0.14
  built_from: []
---

# reviewing-a-decision

## When to use

Review a decision rather than code — an ADR, RFC, design doc, dependency or technology adoption, build-vs-buy or vendor choice, or a deprecation/sunset plan. Reviews the choice and its record (rationale, lock-in, exit, revisit trigger) with the decision lens plus the design-capable lenses for the decision's domain.

## How this works

Rank the relevant lenses below by relevance to what is being reviewed, pick the breadth from the depth mode (default **review**), then for each selected lens **load its bundle** and apply it:

- Before the lenses judge anything, gather deterministic evidence with the procedure in `reference/tool-evidence.md` — run the linters, type checkers, and scanners this repo *already* configures, scoped to what's under review, and hand each lens its hits. Skip it when the repo configures none, or when running them would execute untrusted code; say so in the coverage line either way.
- Read `reference/lenses/<lens>/body.md` — the lens's checklist and examples. Open `reference/lenses/<lens>/tool-rules.md` or `sources.md` only if deeper tooling/provenance is called for.
- **A finding written in a lens's voice is valid only if that lens's `body.md` was actually read this round.** The one-line description in the Lenses list below exists to rank and select lenses, not to write findings in their style — it is specific enough on its own to produce a fluent, plausible-sounding finding for a lens whose bundle was never opened (issue #357). Selecting N lenses and loading only one, then backfilling the rest from their one-liners, reads identically to a review that ran every checklist. If a selected lens's `body.md` was not opened, it did not run: drop any finding attributed to it and say so in the coverage line instead.
- After the lenses run, merge their findings with the procedure in `reference/synthesis.md` — one deduplicated, ranked report with a single verdict.

## Depth modes

Routing first ranks **every** lens in scope by **relevance**, with no hard cap on the ranking itself — for a single change, scope is what the diff touches; for a whole-repo audit, scope is the repository. A depth mode then sets the **breadth** (how far down the ranked list to run, plus room for judgment calls above that floor) and the severity floor. Pick the mode from the request; default to **review**.

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
| Threat model / security-architecture review (a system or AI agent app, with or without a design doc) | `reviewing-threat-model`, `sweeping-for-security`, `reviewing-agentic-safety`, `reviewing-llm-integration` — enumeration-led — #38 builds the model and delegates the deep verdict to the topical security lenses |
| Design doc / plan / RFC (no code yet) | `tracing-correctness-and-invariants`, `reviewing-concurrency-and-async`, `reviewing-migration-and-data-safety`, `reviewing-api-contract-safety`, `reviewing-conceptual-integrity` — pick by the design's domain, from design-capable (◆) lenses — not "◆ lenses only": a decision-shaped design doc (an ADR, RFC, or deprecation plan) also pairs with reviewing-decision-lifecycle, which auto-includes via the decision route regardless of ranking even though it carries no ◆ itself (#383/#430) |
| A decision, not a diff — an ADR / RFC / design doc, a dependency or technology adoption, a build-vs-buy or vendor choice, or a deprecation / sunset plan | `reviewing-decision-lifecycle`, `checking-restraint`, `reviewing-api-contract-safety`, `reviewing-conceptual-integrity` — decision-shaped — reviews the choice and its record (rationale, assumptions, exit), not implementation code; pair with the design-capable (◆) lenses for the decision's domain. reviewing-decision-lifecycle auto-includes on this shape even if ranking would otherwise drop it |

## Lenses

◆ = design-capable.

- [`hunting-silent-failures`](reference/lenses/hunting-silent-failures/body.md) ◆ — Where do errors vanish? Swallowed exceptions, silent fallbacks, missing timeouts and retries.
- [`reviewing-module-design`](reference/lenses/reviewing-module-design/body.md) ◆ — Are the boundaries right? Coupling, encapsulation, interfaces that are hard to misuse, illegal states unrepresentable.
- [`checking-restraint`](reference/lenses/checking-restraint/body.md) ◆ — Is this change too much? Premature abstraction or optimization — the brake pedal.
- [`reviewing-llm-integration`](reference/lenses/reviewing-llm-integration/body.md) ◆ — Is the model call safe and bounded? Injection surface, output validation, evals, token cost, PII.
- [`reviewing-agentic-safety`](reference/lenses/reviewing-agentic-safety/body.md) ◆ — Is the agent's action surface safe? Tool least-privilege, approval gates & step budgets, untrusted tool metadata, sandboxed exec, egress control.
- [`reviewing-threat-model`](reference/lenses/reviewing-threat-model/body.md) ◆ — Enumerate what an adversary could do, boundary by boundary — STRIDE, trust boundaries, abuse cases — and whether each threat is mitigated.
- [`reviewing-usability-and-interaction`](reference/lenses/reviewing-usability-and-interaction/body.md) ◆ — Can a person use this? Undesigned loading/empty/error states, destructive actions with no way back, silent operations, errors that eat the form.
- [`reviewing-outcome-instrumentation`](reference/lenses/reviewing-outcome-instrumentation/body.md) ◆ — After this ships, how would anyone know it worked? Stated outcome, instrumentation in the same diff, a losing condition, experiment guardrails.
- [`reviewing-conceptual-integrity`](reference/lenses/reviewing-conceptual-integrity/body.md) ◆ — Does the product still say one thing? A second noun for an existing idea, a second path to the same job, a rule this change quietly breaks.
- [`sweeping-for-security`](reference/lenses/sweeping-for-security/body.md) ◆ — Can an attacker abuse this? Injection, authorization, secrets, crypto, untrusted data.
- [`reviewing-performance-and-efficiency`](reference/lenses/reviewing-performance-and-efficiency/body.md) ◆ — Will this be slow or expensive at scale? N+1, O(n²) hot paths, caching, payload buffering.
- [`reviewing-migration-and-data-safety`](reference/lenses/reviewing-migration-and-data-safety/body.md) ◆ — Can this migration lock tables or lose data? Expand/contract, backfills, reversibility.
- [`reviewing-data-transformations-and-contracts`](reference/lenses/reviewing-data-transformations-and-contracts/body.md) ◆ — Is the data plane correct and its contract safe? Grain and fan-out, SQL NULL traps, incremental idempotency, data tests, schema compatibility for consumers.
- [`tracing-correctness-and-invariants`](reference/lenses/tracing-correctness-and-invariants/body.md) ◆ — Does the code do what it claims? Invariants, boundaries, off-by-one, resource cleanup.
- [`reviewing-concurrency-and-async`](reference/lenses/reviewing-concurrency-and-async/body.md) ◆ — What breaks when two run at once? Races, lost updates, unawaited promises, idempotency.
- [`reviewing-api-contract-safety`](reference/lenses/reviewing-api-contract-safety/body.md) ◆ — Will this break a consumer? Compatibility, error contracts, idempotency, pagination.
- [`reviewing-observability-and-operability`](reference/lenses/reviewing-observability-and-operability/body.md) ◆ — Can you debug this in production at 3am? Logs, traces, health checks, kill switches, rollback.
- [`reviewing-decision-lifecycle`](reference/lenses/reviewing-decision-lifecycle/body.md) — Is this decision sound and recorded? Adoption justification, lock-in/exit, ADR assumptions, revisit-triggers, planned retirement.
- [`reviewing-resilience-and-scalability`](reference/lenses/reviewing-resilience-and-scalability/body.md) ◆ — Will it survive failure and scale? Unbounded queues, timeouts and blast radius, retries, statelessness, RTO/RPO — design-time, not #16's runtime.
- [`reviewing-install-and-upgrade-experience`](reference/lenses/reviewing-install-and-upgrade-experience/body.md) ◆ — Can a consumer install, configure, and upgrade this cleanly — even hand it to an agent? Setup friction, config UX, version-bump smoothness, migration path.

<!-- GENERATED by `python -m tooling.cli generate` — do not edit this file directly.
     Canonical sources: skills/manifest.yaml.
     Direct edits are overwritten on regeneration and fail the CI drift/regenerate gate. -->
