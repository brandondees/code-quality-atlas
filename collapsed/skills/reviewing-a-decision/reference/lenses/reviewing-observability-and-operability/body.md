# reviewing-observability-and-operability

Can you debug this in production at 3am? Logs, traces, health checks, kill switches, rollback.

## When to use

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Checklist

The full review checklist, grouped by the research category each check draws from:

## From category #16

### Reviewable heuristics (skill-checklist seeds)

- Are logs structured (key-value/JSON) with consistent fields (timestamp, level, service, request/trace ID) rather than interpolated prose? Can you grep/query by field in production?
- Is the log *level* appropriate (no INFO spam in hot loops; real failures at ERROR; nothing security/PII-sensitive logged at any level)? Is there a correlation/trace ID threaded through so one request's logs are linkable?
- Do new failure paths emit a context-rich error (what operation, which inputs/IDs — non-sensitive, the wrapped cause) rather than a bare `error`/stack with no story? Errors should wrap, not swallow, and not be both logged *and* rethrown (double-logging).
- For any new meaningful operation: is it instrumented with at least one of the four golden signals (latency histogram, error counter, throughput)? Are spans created and trace context propagated across service/async boundaries?
- Does a new service/endpoint expose liveness and readiness checks, and do readiness checks actually reflect dependency health (DB/cache reachable) without being so strict they flap?
- Risky/irreversible behavior change: is it behind a feature flag or kill switch so it can be disabled in prod without a redeploy? Is there a documented rollback?
- Startup/shutdown: does the service start only after dependencies are ready, and on shutdown drain in-flight work, stop accepting new requests, flush logs/metrics, and close connections (handle SIGTERM)? (Graceful shutdown.)
- Is there an SLI/SLO implied by this change, and is the data to measure it being emitted (good-event and total-event counts)? Don't alert on causes you can fix later; alert on user-facing symptoms.
- Cardinality discipline: are high-cardinality values (user IDs, raw URLs, emails) used as *event attributes*, not as Prometheus metric *labels* (which explode series count and cost)?
- Are timeouts, retries, and deadlines observable (logged/metered with reason) so on-call can see *why* something is slow or failing, not just that it is?

---

## Examples

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code. The test for every change:
at 3am, can on-call see what this code is doing, why it failed, and turn it off
without a redeploy?

## Bad → finding

**Input (diff):**

```python
def checkout(request, user):
    try:
        charge(user, request.total)
    except ChargeError as e:
        log.error("Charge failed for " + user.email + ": " + str(e))
        raise
```

**Expected finding:**

1. **Unstructured, ungreppable log:** interpolated prose instead of structured
   fields — use key-value logging (`log.error("charge_failed", user_id=..., ...)`)
   so production queries can filter by field.
2. **PII in logs:** the user's email is logged — log the user id, never the email.
3. **Log-and-rethrow double-logging:** the exception is logged here AND will be
   logged again wherever it's finally handled — either handle it or enrich and
   re-raise (`raise ChargeFailed(order_id=...) from e`), not both.
4. **No correlation id:** nothing links this log line to the request's other lines —
   thread a request/trace id through.

## Bad → finding

**Input (diff):**

```python
@app.get("/health")          # wired as the readiness probe
def health():
    return "ok"

def settle_batch():          # NEW: retries failed settlements up to 10x nightly
    for s in failed_settlements():
        retry_settlement(s)
```

**Expected finding:**

1. **Readiness probe that checks nothing:** it returns "ok" even when the DB/cache
   are down, so traffic routes to a dead instance — readiness must reflect
   dependency health (without being so strict it flaps).
2. **Risky new behavior with no kill switch:** a nightly 10x retry storm over
   settlements can't be disabled without a redeploy — put it behind a feature
   flag/kill switch and document the rollback.
3. **No instrumentation on a meaningful operation:** no counter/latency/error
   metric for the retries — on-call can't see whether it's running, failing, or
   storming.

## Good → no finding

**Input (diff):**

```python
def checkout(request, user):
    try:
        charge(user, request.total)
    except ChargeError as e:
        raise CheckoutFailed(order_id=request.order_id, cause=e)  # enriched, single-logged at the boundary

log = structlog.get_logger()
log.info("checkout_complete", order_id=order.id, request_id=ctx.request_id,
         amount_cents=order.total_cents)
```

**Expected finding:** None — structured fields, correlation id, no PII, the error is
wrapped with context and logged once at the boundary. Report "No findings". Do NOT
demand metrics, tracing, or feature flags for every trivial internal helper — the
golden-signal bar applies to meaningful operations, and a reversible copy change
needs no kill switch.

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
