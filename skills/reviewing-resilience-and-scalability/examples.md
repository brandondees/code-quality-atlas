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

**Coordinated-client failure (read this before diagnosing a shared cache).** When a
**single shared cache key** has **one TTL** and an **expensive recompute on miss**,
the hazard is a **cache stampede / thundering herd**, *not* "isolation" or
"bulkheading" or a "single-writer bottleneck": the key expires for every caller at
the same instant, so on each expiry **all N callers run the expensive recompute
concurrently**. It looks fine under light load and detonates under concurrency. The
fix is **single-flight / request coalescing** (one caller recomputes, the rest wait
or serve stale) **plus jittered / staggered TTLs** so one miss does not fan out into
N recomputes. Do not misread it as a per-tenant isolation problem or a write
serialization problem — name the stampede.

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

## Contents

- [Bad → finding (a code diff)](#bad--finding-a-code-diff)
- [Bad → finding (a design doc / RFC)](#bad--finding-a-design-doc--rfc)
- [Bad → finding (a cache stampede / coordinated-client failure)](#bad--finding-a-cache-stampede--coordinated-client-failure)
- [Bad → finding (degrade toward safe, not just toward available)](#bad--finding-degrade-toward-safe-not-just-toward-available)
- [Good → no finding (degradation stays safe)](#good--no-finding-degradation-stays-safe)
- [Good → no finding (bounded, with a defined failure path)](#good--no-finding-bounded-with-a-defined-failure-path)

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

## Bad → finding (a cache stampede / coordinated-client failure)

**Input (review this change):**

```python
# every web node serves the dashboard from one shared cache key, same TTL
DASH_TTL = 600
def get_dashboard():
    v = cache.get("dashboard")          # one key, shared by all nodes
    if v is None:
        v = db.expensive_rollup()       # ~3s
        cache.set("dashboard", v, DASH_TTL)
    return v
```

**Expected finding:**

1. **Cache stampede / thundering herd:** one shared key (`"dashboard"`) with a single
   TTL expires for every node at the same instant, so on each expiry **all** nodes run
   the ~3s `expensive_rollup()` concurrently — a coordinated recompute that looks fine
   under light load and detonates under concurrency (the DB takes N simultaneous
   expensive queries, latency spikes, the miss storm can cascade). Add **single-flight
   / request coalescing** (one caller recomputes, the rest wait or serve stale) plus
   **jittered / staggered TTLs** so a single expiry does not fan out into N recomputes.
   This is a coordinated-client failure mode, not a per-tenant isolation or
   write-serialization problem.

## Bad → finding (degrade toward safe, not just toward available)

**Input (review this change):**

```python
# Keep checkout fast when we're busy.
def checkout(order):
    if load_high():
        return approve(order)            # skip fraud scoring under load
    if fraud_score(order) > THRESHOLD:
        return decline(order)
    return approve(order)
```

**Expected finding:**

1. **Degrade-toward-harm (drops a safety check under load):** the high-load path
   **bypasses fraud scoring** to stay fast, so the system fails **open** under exactly
   the conditions an attacker would create load to trigger. Graceful degradation
   optimizes *availability*, but the degraded path must stay **harm-safe** — degrade to
   a safe fallback (queue / hold the order for async review, or apply a stricter default
   decision) rather than removing the guard. This is the ISO/IEC 25010:2023 *safety*
   direction (distinct from #14 attacker-facing security, and from #2's code-level
   fail-closed default). Surface it and route the acceptable-risk threshold to a human
   owner; do not decide it here.

## Good → no finding (degradation stays safe)

**Input (review this change):**

```python
# Keep checkout responsive under load — defer, don't bypass.
def checkout(order):
    if load_high():
        return hold_for_async_review(order)   # queue for the SAME fraud check, run async
    if fraud_score(order) > THRESHOLD:
        return decline(order)
    return approve(order)
```

**Expected finding:** None — the degraded path stays **harm-safe**: under load it
**holds** the order for asynchronous review rather than approving it, so the fraud
check is **deferred, not dropped** (it fails toward safe, not open). Do not flag a safe
degradation (queue / hold / stricter default) as a violation, and do not demand the
full check run synchronously under load when a safe deferral is in place. Report "No
findings".

## Good → no finding (bounded, with a defined failure path)

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
