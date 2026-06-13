# Examples — reviewing-resilience-and-scalability

This lens reviews a change **or a design** for how it behaves under failure and
load. Report **each distinct weakness as its own numbered finding** — never fold
several into one line, and never stop at the first. When the change is sound —
bounded, timed-out, stateless where it must scale, with a tested recovery path —
the entire response is exactly "No findings".

**Decision rule (apply before flagging):** a resilience/scale finding needs a
concrete hazard the design will actually meet — an unbounded queue/buffer/result
set, a synchronous dependency call with no timeout or failure plan, a shared
resource whose exhaustion has no bulkhead, retries with no budget/backoff/jitter,
new in-process state that blocks horizontal scaling or surviving a restart, a
single-writer / global-lock throughput ceiling, durable state with no stated
RTO/RPO or an untested restore, or one tenant able to starve a shared resource.

**Match the check to the surface.** Recoverability (RTO/RPO, tested restore) and
HA apply **only** to changes that introduce or touch **durable state or a DR /
capacity design** — a datastore, a backup plan, a stateful service. A stateless
function, a bounded API call, or a pure transformation has **no recovery surface**:
do not demand RTO/RPO, replicas, or DR of it. Likewise do **not** demand circuit
breakers, multi-region, or HA for a system with no stated availability or scale
target — that is gold-plating (cross `checking-restraint`). If the change is
bounded, has timeouts and a failure plan where it calls out, and keeps no
scaling-blocking state, report exactly "No findings" — even though this lens
*could* ask RTO/RPO questions, they do not apply when nothing durable is at stake.

## Bad → finding (a code diff)

**Input (review this change):**

```python
def sync_partner_feed():
    rows = db.query("SELECT * FROM partners")          # all rows, no limit
    items = []
    for p in rows:
        resp = requests.get(p.feed_url)                # no timeout
        items.extend(resp.json())
    CACHE[:] = items                                    # module-level in-process cache
    return items
```

**Expected finding:**

1. **Unbounded result set:** `SELECT *` with no `LIMIT` loads the whole `partners`
   table into memory and accumulates every feed into `items` — memory grows with
   data and OOMs under growth. Page the query and bound/stream the accumulation.
2. **No timeout or failure plan on the dependency call:** `requests.get(p.feed_url)`
   has no timeout, so one slow partner blocks the worker indefinitely; one failing
   partner aborts the whole sync. Add a timeout, isolate per-partner failures
   (continue past one bad feed), and bound retries with backoff.
3. **In-process state blocks horizontal scaling:** the module-level `CACHE` makes
   the result instance-local — N workers see N different caches, and a restart
   loses it. Move shared state to a backing store (Redis/DB) if more than one
   instance must see it.

## Bad → finding (a design doc / RFC)

**Input (review this design):**

```text
RFC: "Orders service — single Postgres primary, no replica. A single `orders`
table with a global `next_order_no` counter incremented per insert. Nightly
pg_dump to S3. Target: 5k orders/sec at peak, 99.95% availability."
```

**Expected finding:**

1. **Single-writer bottleneck:** a global `next_order_no` counter serializes every
   insert through one row — it caps throughput regardless of scaling and will not
   reach 5k/sec. Use a sequence, UUID, or sharded ID generation.
2. **No HA for a 99.95% target:** a single primary with no replica cannot meet
   99.95% — any primary failure is full downtime. The availability target requires
   a replica + automated failover; state the RTO.
3. **Untested restore / RPO gap:** "nightly pg_dump" is a backup, not recoverability
   — up to 24h of data loss (RPO) and no evidence the restore has been exercised.
   State the RPO the business accepts, test the restore, and add PITR/WAL archiving
   if 24h is too much.

## Good → no finding

**Input (review this change):**

```python
async def fetch_quote(client, symbol):
    # bounded call: 2s timeout, breaker opens after repeated failures,
    # falls back to last cached quote; retries capped with jitter
    async with breaker:
        try:
            r = await client.get(f"/quote/{symbol}", timeout=2.0)
            return r.json()
        except (TimeoutError, UpstreamError):
            return cache.get(symbol)            # stale-but-serving fallback
```

**Expected finding:** None — the dependency call is bounded (timeout), the failure
path is defined (circuit breaker + cached fallback / graceful degradation), and it
holds no instance-local state that blocks scaling. Report exactly "No findings".
This is **stateless** code with no datastore or DR design, so RTO/RPO,
recoverability, and HA simply do not apply — do not raise them here, and do not
demand multi-region or extra redundancy absent a stated requirement.
