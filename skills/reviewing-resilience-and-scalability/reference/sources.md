# References to mine — reviewing-resilience-and-scalability

## Contents

- From category #28

## From category #28

### Key references

- **Michael Nygard, *Release It!* (2nd ed., 2018)** — the canonical stability-patterns catalog. Patterns: **Circuit Breaker**, **Bulkhead**, **Timeout**, **Steady State**, **Fail Fast**, **Back Pressure**, **Handshaking**, **Shed Load**. Antipatterns: **Integration Points** (every call out is a failure source), **Cascading Failures**, **Slow Responses**, **Unbounded Result Sets**.
  → mine: every synchronous call to another service needs a **timeout** and a defined behavior when it fails (circuit-breaker / fallback / fail-fast); a failure in one dependency must be **bulkheaded** so it can't exhaust the shared resource (threads, connections) and take down the whole system. An **unbounded result set or queue** is a latent OOM/overload — bound it.
- **Google SRE Book & SRE Workbook — "Addressing Cascading Failures", "Handling Overload", "Managing Critical State"** — https://sre.google/sre-book/addressing-cascading-failures/ .
  → mine: under overload, **shed load and degrade gracefully** (serve a cheaper/cached/partial response) rather than collapsing; retries need **budgets + jitter + exponential backoff** or they amplify an outage into a retry storm. A single-writer / global-lock / leader bottleneck caps throughput regardless of horizontal scale.
- **AWS Well-Architected Framework — Reliability Pillar** — https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/ . DR strategies on a cost/complexity ladder: **backup & restore → pilot light → warm standby → multi-site active/active**, each with an explicit **RTO** (how long to recover) and **RPO** (how much data loss is acceptable).
  → mine: a design that stores durable state must state its **RTO/RPO** and pick a DR strategy that meets them; "we take backups" is not recoverability until a **restore has actually been tested** — an untested backup is Schrödinger's backup.
- **"The Tail at Scale" (Dean & Barroso, CACM 2013)** — https://research.google/pubs/the-tail-at-scale/ .
  → mine: at scale, **tail latency** (p99/p999), not the mean, governs user experience and fan-out cost; a request that fans out to N backends is as slow as its slowest one. Bound per-call latency (timeouts, hedged requests) so one slow component doesn't define the whole response.
- **Principles of Chaos Engineering + Rosenthal & Jones, *Chaos Engineering* (O'Reilly)** — https://principlesofchaos.org/ .
  → mine: resilience is a *hypothesis* until tested — the strongest designs name how a failure mode would be exercised (game day / fault injection / DR drill), not just assert that failover "should" work.
- **Reactive Streams / backpressure** — https://www.reactive-streams.org/ ; Universal Scalability Law (Neil Gunther) for the contention + coherency ceilings on scaling.
  → mine: a fast producer feeding a slow consumer through an **unbounded buffer** trades a crash for a slower crash (memory) — apply **backpressure** (bounded queue + blocking/dropping/load-shedding policy). Shared mutable coordination (a global counter, a single sequence) is the coherency term that caps horizontal scaling.
- **Twelve-Factor App — Factor VI (processes are stateless)** — https://12factor.net/processes ; SaaS multi-tenancy "noisy neighbour".
  → mine: horizontally-scalable services keep **no in-process session/affinity state** (push it to a shared store); a new in-memory cache, sticky session, or local-disk write is a scaling and failover hazard. In multi-tenant systems, one tenant must not be able to exhaust a shared resource — **per-tenant quotas / fair scheduling / isolation**.
