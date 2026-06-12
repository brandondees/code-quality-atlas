# Reviewable heuristics — reviewing-resilience-and-scalability

## Contents
- From category #28

## From category #28

### Reviewable heuristics (skill-checklist seeds)
- **Unbounded growth:** does the change introduce a queue, buffer, list, cache, or result set with **no size bound or backpressure**? Unbounded accumulation is a latent OOM / overload under load — bound it and define the drop/block/shed policy when full.
- **Dependency failure plan:** does every synchronous call to another service / DB / third-party API have a **timeout** and a defined behavior when it is slow or down (circuit-breaker, fallback, fail-fast)? A bare call with no timeout blocks a thread indefinitely and cascades (Integration Points → Cascading Failure).
- **Blast radius & bulkheading:** if this component fails or slows, what else goes with it? Is the failure **isolated** (separate pool/bulkhead/process), or does it share a resource (thread pool, connection pool, event loop) whose exhaustion takes down unrelated work?
- **Retry safety:** do retries have a **budget, backoff, and jitter**, and is the retried operation **idempotent** (cross #3)? Naive immediate retries amplify a partial outage into a retry storm.
- **Statelessness / horizontal scale:** does the change add **in-process state** (a local cache, session affinity, an in-memory counter, local-disk write) that prevents running N identical instances or surviving an instance restart? Push durable/shared state to a backing store.
- **Single-writer bottleneck:** is there a global lock, a leader-only path, a single sequence/counter, or a hot row that **caps throughput** no matter how many instances run? Name it as the scaling ceiling.
- **Recoverability (RTO/RPO):** for a change touching durable state, are the **RTO and RPO** stated and met by the chosen backup/DR strategy, and has the **restore actually been tested**? "Backups are taken" without a tested restore is not recoverability.
- **Graceful degradation under overload:** when a dependency is down or load spikes, does the system **shed load / degrade to a cached-or-partial response**, or does it collapse? Is there a kill switch / feature flag to shed a non-critical path (cross #16)?
- **Multi-tenancy isolation:** can one tenant (or one abusive caller) exhaust a shared resource and starve the rest? Are there **per-tenant quotas / rate limits / fair scheduling**?
- **Resilience as a tested hypothesis:** for a design that claims failover/HA/DR, is there a stated way it has been (or will be) **exercised** — a game day, fault-injection test, or DR drill — rather than an untested "it should fail over" assertion?

---
