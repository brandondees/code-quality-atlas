# Examples — reviewing-observability-and-operability

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
