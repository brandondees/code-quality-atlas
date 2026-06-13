# Examples — reviewing-concurrency-and-async

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code. Ask of every line: what
happens if two callers run this at once, and what may have changed across each
`await`?

## Bad → finding

**Input (diff):**

```js
async function redeemCoupon(userId, couponId) {
  const used = await db.couponUsed(userId, couponId);
  if (!used) {
    await wallet.credit(userId, 10_00);
    await db.markUsed(userId, couponId);
  }
}
```

**Expected finding:**

1. **Check-then-act across an await (TOCTOU race):** two concurrent requests both
   read `used == false` and both credit — a double-spend. Make the check-and-mark
   atomic: a unique constraint on `(user_id, coupon_id)` with insert-first, or a
   conditional update, and credit only when the insert wins.
2. **Crash window:** crediting before marking used means a crash between the two
   awaits credits without recording — order the durable write first or wrap in a
   transaction / idempotency key.

## Bad → finding

**Input (diff):**

```python
request_count = 0

def handle(request):            # served by a thread pool
    global request_count
    request_count += 1
    asyncio.create_task(push_metrics())   # fire-and-forget, no reference kept
```

**Expected finding:**

1. **Unsynchronized read-modify-write:** `request_count += 1` from multiple threads
   loses updates — use a lock, an atomic counter, or your metrics library's counter.
2. **Dropped task:** the `create_task` result is discarded — its exceptions vanish
   silently and the task can be garbage-collected mid-flight; keep a reference and
   handle failures (done-callback), or await it.

## Good → no finding

**Input (diff):**

```python
async def on_payment_event(msg):
    # at-least-once delivery: idempotent upsert keyed on the event id
    await db.execute(
        "INSERT INTO payments (event_id, amount) VALUES ($1, $2) "
        "ON CONFLICT (event_id) DO NOTHING",
        msg.event_id, msg.amount,
    )
```

**Expected finding:** None — the consumer is idempotent, keyed on a stable id, and
the database enforces the atomicity (no app-level check-then-act). Report
"No findings". Do NOT demand a lock where a database constraint already provides
the atomicity, and do NOT flag at-least-once redelivery as a bug when the handler
is idempotent — that is the correct design for it.
