---
name: reviewing-concurrency-and-async
description: 'Reviews concurrent and async code for races and ordering bugs: shared
  mutable state without synchronization, check-then-act spanning an await, lost updates
  from interleaved requests, lock ordering, unawaited promises, accidental sequential
  awaits, non-idempotent message consumers, exactly-once assumptions, and missing
  cancellation/timeout propagation. Use when reviewing threads, async/await, promises,
  locks, queues, message handlers, or anything two callers can run at once.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 3
    source: docs/research/cluster-1-correctness.md#3
    hash: 73a657fe1397e6e9260927b0922fd03bc9a6e3cdab1fa1d002dc32a4b2e3c10a
---

# reviewing-concurrency-and-async

## When to use

Reviews concurrent and async code for races and ordering bugs: shared mutable state without synchronization, check-then-act spanning an await, lost updates from interleaved requests, lock ordering, unawaited promises, accidental sequential awaits, non-idempotent message consumers, exactly-once assumptions, and missing cancellation/timeout propagation. Use when reviewing threads, async/await, promises, locks, queues, message handlers, or anything two callers can run at once.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
