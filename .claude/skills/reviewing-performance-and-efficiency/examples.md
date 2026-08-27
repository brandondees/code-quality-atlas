# Examples — reviewing-performance-and-efficiency

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

**Decision rule (apply before flagging):** a performance finding needs a path that
is plausibly hot — a request handler, a loop over unbounded data, a render path.
Code on a cold path (cron jobs, admin tools, startup, once-a-day batch) with small
bounded inputs is fine as plain readable code: report "No findings" and do NOT
suggest batching, caching, or parallelism there. Conversely, an *optimization*
without a profile is a finding the other way (premature optimization).

## Bad → finding

**Input (diff):**

```python
def order_summaries(user):
    summaries = []
    for order_id in db.query("SELECT id FROM orders WHERE user_id = %s", [user.id]):
        order = db.query("SELECT * FROM orders WHERE id = %s", [order_id])   # per-row query
        items = db.query("SELECT * FROM items WHERE order_id = %s", [order_id])
        summaries.append(render(order, items))
    return summaries
```

**Expected finding:**

1. **N+1 queries:** one query per order (×2) inside the loop — a user with 500
   orders issues 1001 round-trips. Fetch all orders in one query and all items
   with a single `WHERE order_id IN (...)` (or a join), then group in memory.

## Bad → finding

**Input (diff):**

```js
async function tagActiveUsers(users, activeIds) {
  for (const u of users) {
    if (activeIds.includes(u.id)) {            // O(n²): includes() scans per user
      u.active = true;
      await api.patch(`/users/${u.id}`, { active: true });   // await per item
    }
  }
}
```

**Expected finding:**

1. **Accidental O(n²):** `Array.includes` inside the loop scans `activeIds` per
   user — build a `Set` once and use `set.has(u.id)`.
2. **Serialized I/O:** `await` per item turns independent requests into sequential
   round-trips — batch via a bulk endpoint, or bound the concurrency
   (`Promise.all` over chunks).
3. **Repeated work that belongs outside the loop** (the Set construction) — hoist
   per-iteration recomputation of anything loop-invariant.

## Good → no finding

**Input (diff):**

```python
def nightly_export():
    # runs once per night from the scheduler
    rows = [serialize(r) for r in load_completed_jobs()]
    write_csv("/exports/jobs.csv", rows)
```

**Expected finding:** None — a once-a-night batch on bounded data is a cold path;
the simple loop is appropriate. Report "No findings". Do NOT recommend streaming,
caching, parallelism, or batching that no profile has justified — an unforced
"make it faster" suggestion is itself a finding-quality failure (premature
optimization).
