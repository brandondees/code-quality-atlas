---
name: reviewing-performance-and-efficiency
description: 'Reviews changes for performance and efficiency problems: N+1 queries,
  await-in-loop and chatty per-item I/O, accidental O(n²) on hot paths, recomputed
  expensive values, caches without invalidation, buffering whole payloads instead
  of streaming, allocation pressure, bundle/startup bloat, and per-request cloud cost.
  Demands a profile before accepting optimization claims. Use when reviewing queries
  in loops, hot paths, caching, large payloads, or anything justified by "performance."'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 15
    source: docs/research/cluster-4-runtime.md#15
    hash: 95468df6094ec91160285d106ef87d4c7f1de2709ea9f0befebe9aa676028351
---

# reviewing-performance-and-efficiency

## When to use

Reviews changes for performance and efficiency problems: N+1 queries, await-in-loop and chatty per-item I/O, accidental O(n²) on hot paths, recomputed expensive values, caches without invalidation, buffering whole payloads instead of streaming, allocation pressure, bundle/startup bloat, and per-request cloud cost. Demands a profile before accepting optimization claims. Use when reviewing queries in loops, hot paths, caching, large payloads, or anything justified by "performance."

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Is there a loop that issues a query/RPC/HTTP call per iteration? (N+1.) Push to a single batched/`IN`/join query or a bulk endpoint. Flag `await` inside `for` over independent items.
- What is the worst-case complexity on the hot path as input grows? Flag accidental O(n²) (nested loops over the same collection, `Array.includes` inside a loop → use a Set/Map), and unbounded growth.
- Is the same expensive value (DB read, computed result, parsed config, compiled regex) recomputed when it could be hoisted or memoized? Conversely, is anything memoized that's cheap and rarely reused (premature)?
- Caching correctness: is there a clear invalidation story (TTL, event-based, or write-through)? A cache without an invalidation answer is a future stale-data bug. Check key construction includes everything that affects the value (tenant, locale, version).
- I/O batching: are round-trips minimized (batch reads/writes, pipelining, HTTP keep-alive/connection pooling) rather than chatty per-item calls?
- Streaming vs buffering: for large payloads/files, is data streamed rather than fully loaded into memory? Flag "read entire file/response into a string then process."
- Allocation/GC pressure on hot paths: avoidable per-iteration allocations, boxing, large defensive copies, building huge intermediate collections? (Especially in tight loops and request handlers.)
- Lazy vs eager: is work deferred until needed (and *only* the needed work done), without re-triggering N+1 via lazy loading inside a loop?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
