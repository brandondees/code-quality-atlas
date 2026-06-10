---
name: reviewing-observability-and-operability
description: 'Reviews changes for production operability: structured logs with consistent
  fields and correlation/trace IDs, right log levels with no PII, context-rich errors
  that wrap rather than swallow, golden-signal instrumentation and propagated trace
  context, liveness/readiness checks, kill switches for risky changes, graceful shutdown,
  and metric cardinality discipline. Use when reviewing logging, metrics, tracing,
  alerts, health checks, feature flags, or deploy/rollback paths.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 16
    source: docs/research/cluster-4-runtime.md#16
    hash: 4b280c5dde5faf35119ff2dfaed34505d683cb292b998047a9343594c14ad854
---

# reviewing-observability-and-operability

## When to use

Reviews changes for production operability: structured logs with consistent fields and correlation/trace IDs, right log levels with no PII, context-rich errors that wrap rather than swallow, golden-signal instrumentation and propagated trace context, liveness/readiness checks, kill switches for risky changes, graceful shutdown, and metric cardinality discipline. Use when reviewing logging, metrics, tracing, alerts, health checks, feature flags, or deploy/rollback paths.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
