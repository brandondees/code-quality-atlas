# Examples — reviewing-concurrency-and-async

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code. Ask of every line: what
happens if two callers run this at once, and what may have changed across each
`await`?

**Decision rule — run this trace explicitly before answering "No findings":**
for *every* function in the diff, list each piece of state it reads or writes
(a row, a dict entry, a counter, a lock, a cache key) and each `await`/yield
point. Then, for each pair of operations on the *same* piece of state, ask:
"if a second caller entered this function right now — at any point between
any two of these operations — would the result be wrong?" This includes
sequences that don't look concurrency-flavored at first glance: a plain
`if condition: do_thing()` where `condition` was computed by an earlier
`await` is a check-then-act pair, a module-level dict or counter touched by a
handler is shared state, and two locks taken in sequence are a lock-ordering
question. Do this trace for every candidate before concluding there's nothing
to flag — "no findings" is a conclusion the trace must reach, not a default
for code that doesn't obviously mention threads, locks, or races.

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

## Bad → finding

**Input (diff):**

```python
async def transfer(from_acct, to_acct, amount):
    async with lock_for(from_acct):
        async with lock_for(to_acct):
            await debit(from_acct, amount)
            await credit(to_acct, amount)
```

**Expected finding:**

1. **Inconsistent lock ordering (deadlock risk):** `transfer(A, B)` locks A then
   B; a concurrent `transfer(B, A)` locks B then A. If both run at once, each
   can hold one lock while waiting for the other — deadlock. Acquire locks in a
   consistent global order regardless of call direction (e.g. sort the two
   account ids first, always lock the lower id first).

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

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/reviewing-concurrency-and-async/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
