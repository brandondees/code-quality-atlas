---
name: reviewing-concurrency-and-async
description: 'Reviews concurrent and async code for races and ordering bugs: shared
  mutable state without synchronization, check-then-act spanning an await, lost updates
  from interleaved requests, lock ordering, unawaited promises, accidental sequential
  awaits, non-idempotent message consumers, exactly-once assumptions, and missing
  cancellation/timeout propagation. Use when reviewing threads, async/await, promises,
  locks, queues, message handlers, or anything two callers can run at once. Skip when
  the code is single-threaded and synchronous with no shared mutable state, async/await,
  or message handling — nothing two callers race on.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 3
    source: docs/research/cluster-1-correctness.md#3
    hash: c9755d9b409479e2fac960b39449dc1eaaf0f98e8bbe01fd2758ad97a6bd7ba5
---

# reviewing-concurrency-and-async

*What breaks when two run at once? Races, lost updates, unawaited promises, idempotency.*

## When to use

Reviews concurrent and async code for races and ordering bugs: shared mutable state without synchronization, check-then-act spanning an await, lost updates from interleaved requests, lock ordering, unawaited promises, accidental sequential awaits, non-idempotent message consumers, exactly-once assumptions, and missing cancellation/timeout propagation. Use when reviewing threads, async/await, promises, locks, queues, message handlers, or anything two callers can run at once. Skip when the code is single-threaded and synchronous with no shared mutable state, async/await, or message handling — nothing two callers race on.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Is shared mutable state touched by multiple threads/tasks without synchronization?
- Any check-then-act / read-modify-write that spans an `await`/`yield` and isn't atomic?
- Could two concurrent requests interleave to break an invariant (lost update, double-spend)?
- Are locks acquired in a consistent global order, with minimal scope (deadlock avoidance)?
- Are all promises awaited/handled, and is concurrency *intentional* (`Promise.all`) vs. accidental sequential?
- For message consumers: is processing **idempotent** and keyed on a stable id (at-least-once-safe)?
- Does the code assume wall-clock ordering across nodes/processes (clock skew)?
- Does it assume **exactly-once delivery** (it doesn't exist — needs dedupe)?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
