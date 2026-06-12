---
name: choosing-review-lenses
description: 'Picks which code-quality-atlas review lenses to run for a given change:
  maps what is being reviewed (bug fix, feature, refactor, migration, async or concurrent
  code, API change, UI change, error handling, LLM integration, design doc, dependency
  bump, CI/config change, or a whole-repo audit) to the 2-4 most relevant lenses.
  Use first when starting a code review or audit with the atlas suite, when unsure
  which review skills apply, or when asked to review something without a named lens.'
provenance:
  taxonomy_version: v0.3
  built_from: []
---

# choosing-review-lenses

## When to use

Picks which code-quality-atlas review lenses to run for a given change: maps what is being reviewed (bug fix, feature, refactor, migration, async or concurrent code, API change, UI change, error handling, LLM integration, design doc, dependency bump, CI/config change, or a whole-repo audit) to the 2-4 most relevant lenses. Use first when starting a code review or audit with the atlas suite, when unsure which review skills apply, or when asked to review something without a named lens.

## How to pick

- Run **2-4 content lenses** per change; more dilutes attention and duplicates findings. `reviewing-pr-and-process-hygiene` is **additive** — on any PR it rides on top of those lenses and does not spend one of the 2-4 slots.
- Match the change against the routes below; when a change is several things at once, combine rows but keep the cap.
- **Keep the brake pedal.** When a change ships abstraction, generality, or infrastructure ahead of the consumer that needs it (a generic with one impl, a crate with no caller yet), retain `checking-restraint` in the set — under the cap it is the lens most often dropped, and the one that catches building ahead of need.
- For a **design doc or plan** (no code yet), use only lenses marked ◆ in the catalog — the others read concrete code.
- Lenses that share a research category name their primary owner in their SKILL.md; report each shared finding once, under the owner.
- Nothing matches: default to `tracing-correctness-and-invariants` + `reviewing-naming-and-readability` + `checking-restraint`.
- After the lenses run, merge their findings with `synthesizing-review-findings` — one deduplicated, ranked report with a single verdict.

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
| UI / frontend change (components, templates, user-facing text) | `reviewing-accessibility-and-i18n`, `checking-idioms-and-consistency`, `reviewing-naming-and-readability` |
| Auth, user input, or anything handling untrusted data | `sweeping-for-security`, `hunting-silent-failures`, `tracing-correctness-and-invariants` |
| Performance-motivated change ("this makes it faster") | `reviewing-performance-and-efficiency`, `checking-restraint`, `tracing-correctness-and-invariants` |
| LLM / agent / model-API integration | `reviewing-llm-integration`, `sweeping-for-security`, `checking-restraint` |
| Logging, metrics, alerts, feature flags, deploy/rollback paths | `reviewing-observability-and-operability`, `sweeping-for-security` |
| Tests-only change | `reviewing-test-quality`, `checking-idioms-and-consistency` |
| Design doc / plan / RFC (no code yet) | `tracing-correctness-and-invariants`, `reviewing-concurrency-and-async`, `reviewing-migration-and-data-safety`, `reviewing-api-contract-safety` — pick by the design's domain, from design-capable (◆) lenses only |
| Dependency add or bump | `auditing-dependencies-and-supply-chain`, `checking-restraint` |
| CI / build / config change | `auditing-config-and-build-hygiene`, `sweeping-for-security` |
| Any pull request (the PR artifact itself, on top of content lenses) | `reviewing-pr-and-process-hygiene` |
| Whole-repo health audit (scheduled / cron) | `finding-maintainability-hotspots`, `auditing-architecture-conformance`, `auditing-dependencies-and-supply-chain`, `auditing-config-and-build-hygiene`, `auditing-documentation-health`, `auditing-compliance-and-provenance`, `auditing-enforcement-and-meta-artifacts` — the seven repo-shaped audits; run independently, not as one pass |
| Enforcement config — lint/type suppressions, alert rules or dashboards, or checked-in generated artifacts | `auditing-enforcement-and-meta-artifacts` — repo-shaped — scans suppression accretion and codegen/monitoring drift across the tree, not a single diff |
| A decision, not a diff — an ADR / RFC / design doc, a dependency or technology adoption, a build-vs-buy or vendor choice, or a deprecation / sunset plan | `reviewing-decision-lifecycle`, `checking-restraint`, `reviewing-api-contract-safety` — decision-shaped — reviews the choice and its record (rationale, assumptions, exit), not implementation code; pair with the design-capable (◆) lenses for the decision's domain |

## Catalog

◆ = design-capable (also works on design docs and plans).

**Diff-shaped — run on a change:**

- `hunting-silent-failures` ◆ — Where do errors vanish? Swallowed exceptions, silent fallbacks, missing timeouts and retries.
- `reviewing-naming-and-readability` — Can a newcomer read this function? Names, length, nesting, magic values, comment accuracy.
- `reviewing-module-design` ◆ — Are the boundaries right? Coupling, encapsulation, interfaces that are hard to misuse, illegal states unrepresentable.
- `checking-restraint` ◆ — Is this change too much? Premature abstraction or optimization — the brake pedal.
- `reviewing-llm-integration` ◆ — Is the model call safe and bounded? Injection surface, output validation, evals, token cost, PII.
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

**Repo-shaped — run on the whole repository, scheduled or on demand:**

- `finding-maintainability-hotspots` — Where does the repo hurt most? Churn × complexity, change-coupling, bus factor, untracked debt.
- `auditing-architecture-conformance` — Does the import graph still match the intended architecture? Layers, cycles, reach-arounds.
- `auditing-dependencies-and-supply-chain` — Is the dependency tree safe? CVEs, pinning, typosquats, install scripts, licenses.
- `auditing-config-and-build-hygiene` — Are config and CI trustworthy? Secrets, env parity, reproducible pinned builds, cache correctness.
- `auditing-documentation-health` — Do the docs still tell the truth? API parity, stale examples, ADR coverage, changelog discipline.
- `auditing-compliance-and-provenance` — Any licensing, PII, or provenance exposure? Detect and escalate to humans — never decide legal questions.
- `auditing-enforcement-and-meta-artifacts` — Is the enforcement apparatus healthy? Suppression hygiene & baseline trend, actionable alerts/monitoring-as-code, codegen-source drift gate.

**Decision-shaped — run on a decision or plan (ADR, RFC, adoption, deprecation, capacity/DR design), not a diff:**

- `reviewing-decision-lifecycle` — Is this decision sound and recorded? Adoption justification, lock-in/exit, ADR assumptions, revisit-triggers, planned retirement.
