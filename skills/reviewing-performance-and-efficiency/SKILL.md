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
    hash: 0a3ca5033ee175b2933254b92caa1e23b8536ab91cc08680d1fa63143183c7c9
---

# reviewing-performance-and-efficiency

## When to use

Reviews changes for performance and efficiency problems: N+1 queries, await-in-loop and chatty per-item I/O, accidental O(n²) on hot paths, recomputed expensive values, caches without invalidation, buffering whole payloads instead of streaming, allocation pressure, bundle/startup bloat, and per-request cloud cost. Demands a profile before accepting optimization claims. Use when reviewing queries in loops, hot paths, caching, large payloads, or anything justified by "performance."

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
