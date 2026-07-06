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
  taxonomy_version: v0.9
  built_from:
  - category: 28
    source: docs/research/cluster-4-runtime.md#28
    hash: 9e77d41919d9e676eecee65967c10df9a8fa11a1debf386050f9b56fdfd6a2c1
---

# reviewing-resilience-and-scalability

*Will it survive failure and scale? Unbounded queues, timeouts and blast radius, retries, statelessness, RTO/RPO — design-time, not #16's runtime.*

## When to use

Reviews a change or design for operational resilience and scale: unbounded queues/buffers/result sets, missing timeouts and failure plans on calls to other services, blast radius and bulkheading, retry budgets and idempotency, in-process state that blocks horizontal scaling, single-writer bottlenecks, recoverability (RTO/RPO and tested restore), graceful degradation under overload, and multi-tenant isolation. Design-time operability — distinct from #16's runtime observability. Use when reviewing a new queue, cache, stateful service, failover/HA/DR design, capacity or scaling plan, or a call to a dependency that could be slow or down. Skip when the change is a small, stateless local edit with no new dependency call, queue, shared state, or scaling/recovery surface.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Unbounded growth:** does the change introduce a queue, buffer, list, cache, or result set with **no size bound or backpressure**? Unbounded accumulation is a latent OOM / overload under load — bound it and define the drop/block/shed policy when full.
- **Dependency failure plan:** does every synchronous call to another service / DB / third-party API have a **timeout** and a defined behavior when it is slow or down (circuit-breaker, fallback, fail-fast)? A bare call with no timeout blocks a thread indefinitely and cascades (Integration Points → Cascading Failure).
- **Blast radius & bulkheading:** if this component fails or slows, what else goes with it? Is the failure **isolated** (separate pool/bulkhead/process), or does it share a resource (thread pool, connection pool, event loop) whose exhaustion takes down unrelated work?
- **Retry safety:** do retries have a **budget, backoff, and jitter**, and is the retried operation **idempotent** (cross #3)? Naive immediate retries amplify a partial outage into a retry storm.
- **Coordinated-client failure modes (thundering herd / cache stampede):** even with per-client backoff, can clients **synchronize** into a herd — aligned retry timers, a cache key that expires for everyone at once, a cron/restart that fires every instance together, or all reconnecting the moment a dependency recovers? Want jittered/staggered timing and **request coalescing / single-flight** on the recompute so one miss doesn't become N concurrent recomputes.
- **Resource-exhaustion classes (correct at merge, detonates as usage accumulates):** does the change risk hitting a **hard, finite ceiling** that creeps up under real load rather than failing immediately — disk/inode space (logs, temp files, spool), **file descriptors / sockets**, ephemeral ports, connection-pool slots, thread/worker counts, or memory? Name the bounded resource and the back-pressure or quota that keeps it from filling silently (cross #4 leaks, #26 limits).
- **Statelessness / horizontal scale:** does the change add **in-process state** (a local cache, session affinity, an in-memory counter, local-disk write) that prevents running N identical instances or surviving an instance restart? Push durable/shared state to a backing store.
- **Single-writer bottleneck:** is there a global lock, a leader-only path, a single sequence/counter, or a hot row that **caps throughput** no matter how many instances run? Name it as the scaling ceiling.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
