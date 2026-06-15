---
name: reviewing-resilience-and-scalability
description: 'Reviews a change or design for operational resilience and scale: unbounded
  queues/buffers/result sets, missing timeouts and failure plans on calls to other
  services, blast radius and bulkheading, retry budgets and idempotency, in-process
  state that blocks horizontal scaling, single-writer bottlenecks, recoverability
  (RTO/RPO and tested restore), graceful degradation under overload, and multi-tenant
  isolation. Design-time operability — distinct from #16''s runtime observability.
  Use when reviewing a new queue, cache, stateful service, failover/HA/DR design,
  capacity or scaling plan, or a call to a dependency that could be slow or down.
  Skip when the change is a small, stateless local edit with no new dependency call,
  queue, shared state, or scaling/recovery surface.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 28
    source: docs/research/cluster-4-runtime.md#28
    hash: 91b12107f4499137fe81ce85cf1be3a0ebbb75d73a22c4312f5e882c156dc9fa
---

# reviewing-resilience-and-scalability

*Will it survive failure and scale? Unbounded queues, timeouts and blast radius, retries, statelessness, RTO/RPO — design-time, not #16's runtime.*

## When to use

Reviews a change or design for operational resilience and scale: unbounded queues/buffers/result sets, missing timeouts and failure plans on calls to other services, blast radius and bulkheading, retry budgets and idempotency, in-process state that blocks horizontal scaling, single-writer bottlenecks, recoverability (RTO/RPO and tested restore), graceful degradation under overload, and multi-tenant isolation. Design-time operability — distinct from #16's runtime observability. Use when reviewing a new queue, cache, stateful service, failover/HA/DR design, capacity or scaling plan, or a call to a dependency that could be slow or down. Skip when the change is a small, stateless local edit with no new dependency call, queue, shared state, or scaling/recovery surface.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Unbounded growth:** does the change introduce a queue, buffer, list, cache, or result set with **no size bound or backpressure**? Unbounded accumulation is a latent OOM / overload under load — bound it and define the drop/block/shed policy when full.
- **Dependency failure plan:** does every synchronous call to another service / DB / third-party API have a **timeout** and a defined behavior when it is slow or down (circuit-breaker, fallback, fail-fast)? A bare call with no timeout blocks a thread indefinitely and cascades (Integration Points → Cascading Failure).
- **Blast radius & bulkheading:** if this component fails or slows, what else goes with it? Is the failure **isolated** (separate pool/bulkhead/process), or does it share a resource (thread pool, connection pool, event loop) whose exhaustion takes down unrelated work?
- **Retry safety:** do retries have a **budget, backoff, and jitter**, and is the retried operation **idempotent** (cross #3)? Naive immediate retries amplify a partial outage into a retry storm.
- **Statelessness / horizontal scale:** does the change add **in-process state** (a local cache, session affinity, an in-memory counter, local-disk write) that prevents running N identical instances or surviving an instance restart? Push durable/shared state to a backing store.
- **Single-writer bottleneck:** is there a global lock, a leader-only path, a single sequence/counter, or a hot row that **caps throughput** no matter how many instances run? Name it as the scaling ceiling.
- **Recoverability (RTO/RPO):** for a change touching durable state, are the **RTO and RPO** stated and met by the chosen backup/DR strategy, and has the **restore actually been tested**? "Backups are taken" without a tested restore is not recoverability.
- **Graceful degradation under overload:** when a dependency is down or load spikes, does the system **shed load / degrade to a cached-or-partial response**, or does it collapse? Is there a kill switch / feature flag to shed a non-critical path (cross #16)?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
