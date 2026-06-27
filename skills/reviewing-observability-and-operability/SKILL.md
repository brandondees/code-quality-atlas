---
name: reviewing-observability-and-operability
description: 'Reviews changes for production operability: structured logs with consistent
  fields and correlation/trace IDs, right log levels with no PII, context-rich errors
  that wrap rather than swallow, golden-signal instrumentation and propagated trace
  context, liveness/readiness checks, kill switches for risky changes, graceful shutdown,
  and metric cardinality discipline. Use when reviewing logging, metrics, tracing,
  alerts, health checks, feature flags, or deploy/rollback paths.'
provenance:
  taxonomy_version: v0.8
  built_from:
  - category: 16
    source: docs/research/cluster-4-runtime.md#16
    hash: a1b7c3b359329ad08a45a9425bc6d5e84aa0260976e7209d3fe96c94e8cb8397
---

# reviewing-observability-and-operability

*Can you debug this in production at 3am? Logs, traces, health checks, kill switches, rollback.*

## When to use

Reviews changes for production operability: structured logs with consistent fields and correlation/trace IDs, right log levels with no PII, context-rich errors that wrap rather than swallow, golden-signal instrumentation and propagated trace context, liveness/readiness checks, kill switches for risky changes, graceful shutdown, and metric cardinality discipline. Use when reviewing logging, metrics, tracing, alerts, health checks, feature flags, or deploy/rollback paths.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Are logs structured (key-value/JSON) with consistent fields (timestamp, level, service, request/trace ID) rather than interpolated prose? Can you grep/query by field in production?
- Is the log *level* appropriate (no INFO spam in hot loops; real failures at ERROR; nothing security/PII-sensitive logged at any level)? Is there a correlation/trace ID threaded through so one request's logs are linkable?
- Do new failure paths emit a context-rich error (what operation, which inputs/IDs — non-sensitive, the wrapped cause) rather than a bare `error`/stack with no story? Errors should wrap, not swallow, and not be both logged *and* rethrown (double-logging).
- For any new meaningful operation: is it instrumented with at least one of the four golden signals (latency histogram, error counter, throughput)? Are spans created and trace context propagated across service/async boundaries?
- Does a new service/endpoint expose liveness and readiness checks, and do readiness checks actually reflect dependency health (DB/cache reachable) without being so strict they flap?
- Risky/irreversible behavior change: is it behind a feature flag or kill switch so it can be disabled in prod without a redeploy? Is there a documented rollback?
- Startup/shutdown: does the service start only after dependencies are ready, and on shutdown drain in-flight work, stop accepting new requests, flush logs/metrics, and close connections (handle SIGTERM)? (Graceful shutdown.)
- Is there an SLI/SLO implied by this change, and is the data to measure it being emitted (good-event and total-event counts)? Don't alert on causes you can fix later; alert on user-facing symptoms.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
