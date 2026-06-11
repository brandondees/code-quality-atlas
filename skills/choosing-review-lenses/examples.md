# Examples — choosing-review-lenses

**Input:** "Review this PR: adds a worker that consumes payment events from a queue and writes results to the orders table."

**Good selection:**
1. `reviewing-concurrency-and-async` — queue consumer: idempotency, redelivery, interleaving.
2. `tracing-correctness-and-invariants` — the write logic and its edge cases.
3. `hunting-silent-failures` — what happens when the provider call or the write fails.

Money is involved, so `sweeping-for-security` is a defensible fourth; stop there.

**Bad selection:** listing eight lenses "to be thorough." Attention dilutes, and the
shared categories (e.g. resource cleanup in both correctness and silent-failures)
get reported twice.

---

**Input:** "Can you review our design doc for the new export pipeline? No code yet."

**Good selection:** only ◆ design-capable lenses, picked by the design's domain —
e.g. `reviewing-api-contract-safety` for the export format contract,
`reviewing-performance-and-efficiency` for the full-table read it proposes,
`checking-restraint` for the plugin system it sketches for one consumer.

**Bad selection:** `reviewing-naming-and-readability` or
`checking-idioms-and-consistency` — there is no code for them to read; they are
not design-capable.
