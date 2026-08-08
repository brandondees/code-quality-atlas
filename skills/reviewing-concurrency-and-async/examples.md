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

**Second step — before reporting a traced interleaving, look for the guard.**
The trace above finds *candidate* races; it is not a verdict. An interleaving
is a finding only if nothing in the code already prevents it, so check for
these three guards before writing it up:

- **The store makes it atomic.** A conditional `UPDATE ... WHERE <precondition>`
  whose affected-row count is checked, an `INSERT ... ON CONFLICT`, a
  compare-and-swap on a version column, or an atomic operator like Redis
  `INCR` — the check and the act are a single statement, so the window you
  traced does not exist. This is the pattern this lens *recommends* as the fix;
  flagging it as the bug teaches the reader away from the correct answer.
- **A lock or transaction spans the whole check-and-act.** If the read, the
  decision, and the write all sit inside one `async with lock_for(key)` (or one
  transaction over the same key), a second caller cannot interleave between
  them. Trace where the guard *opens and closes*, not merely whether the words
  appear.
- **The code states a tolerance.** A comment declaring a value approximate or
  best-effort, and naming what it is not used for, is a specification rather
  than an excuse. An imprecision inside a stated tolerance is not a defect —
  demanding a lock there is a finding against a requirement that does not exist.

If a guard covers the interleaving you traced, that interleaving is not a
finding. Say so and move on; do not report it hedged ("could theoretically
race"). Both halves are load-bearing: skip the trace and real races go
unreported, skip the guard check and correct code gets convicted — and a
reviewer that convicts correct code costs more trust than one that misses a
bug, because every later finding it makes now has to be re-checked by hand.

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

## Good → no finding

**Input (diff):**

```python
async def apply_discount(cart_id, pct):
    while True:
        row = await db.fetchrow(
            "SELECT total, version FROM carts WHERE id=$1", cart_id)
        new_total = row["total"] * (1 - pct)
        updated = await db.execute(
            "UPDATE carts SET total=$1, version=version+1 "
            "WHERE id=$2 AND version=$3",
            new_total, cart_id, row["version"])
        if updated.rowcount == 1:
            return new_total
        # lost the race — another writer bumped the version; re-read and retry
```

**Expected finding:** None — the trace finds a real candidate interleaving (two
callers both read `version = 7` and both compute a total), and the **guard**
resolves it: the `WHERE version=$3` makes the write conditional on nothing
having changed since the read, `rowcount` tells the loser it lost, and the retry
re-reads fresh state. Report "No findings". Do NOT flag the read-then-write
pair here — compare-and-swap *is* the fix for it, and a bare `SELECT` followed
by an `UPDATE` is only a defect when the `UPDATE` cannot tell that the world
moved. Do NOT demand a lock on top of it, and do NOT call the retry loop
unbounded — it terminates as soon as one writer wins.
