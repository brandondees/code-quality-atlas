# Examples — reviewing-api-contract-safety

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code. The question for every
contract change: does an existing consumer, built against yesterday's contract,
still work today — and can a new consumer misuse what you just added?

## Bad → finding

**Input (diff to a public v1 endpoint):**

```diff
 GET /v1/orders/{id} response:
 {
-  "customer_id": 123,
-  "status": "shipped",            // "pending" | "shipped" | "delivered"
+  "customerId": 123,
+  "state": "SHIPPED",
   "total_cents": 4200
 }
```

**Expected finding:**

1. **Breaking rename, unversioned:** `customer_id` → `customerId` and `status` →
   `state` break every existing consumer of v1. Expand/contract instead: add the
   new fields alongside the old, deprecate with a window, remove in v2.
2. **Enum value format change** (`shipped` → `SHIPPED`) is equally breaking for
   consumers switching on the value — same treatment.

## Bad → finding

**Input (diff):**

```python
@app.post("/v1/transfers")                    # moves money
def create_transfer(req):
    t = Transfer.create(**req.json)           # network retry = duplicate transfer
    return t.row_dict()                       # includes internal_flags, shard_key

@app.get("/v1/transactions")
def list_transactions(req):
    return [t.row_dict() for t in Transaction.all()]   # unbounded
```

**Expected finding:**

1. **Unsafe operation without idempotency:** a retried POST creates a duplicate
   money transfer — require an `Idempotency-Key` (or accept a client token) and
   dedupe on it.
2. **Internal representation leaked:** `row_dict()` exposes `internal_flags` and
   `shard_key` — return an explicit response shape; internals can never be removed
   once consumers depend on them.
3. **Unbounded collection endpoint:** no pagination, no limit — define page/cursor
   parameters and a maximum page size before consumers bake in "returns everything".

## Good → no finding

**Input (diff to a public v1 endpoint):**

```diff
 GET /v1/orders/{id} response:
 {
   "customer_id": 123,
   "status": "shipped",
+  "tracking_url": "https://...",   // optional, may be null; documented; contract test updated
   "total_cents": 4200
 }
```

**Expected finding:** None — an additive optional field with the old shape intact is
the backward-compatible way to evolve a contract. Report "No findings". Do NOT flag
additive optional fields as breaking, and do NOT demand a version bump for a change
no existing consumer can observe failing.
