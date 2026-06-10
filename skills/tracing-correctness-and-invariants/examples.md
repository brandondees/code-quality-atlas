# Examples — tracing-correctness-and-invariants

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code. Trace the code against
what it *claims* to do (name, docstring, PR description) — the spec-vs-implementation
check is the one no linter can do.

## Bad → finding

**Input (diff):**
```js
// Buckets events by month index (0..monthCount-1).
function monthlyBuckets(events, monthCount) {
  const buckets = [];
  for (let m = 0; m <= monthCount; m++) buckets.push([]);
  for (const e of events) buckets[e.month].push(e);
  return buckets;
}
```
**Expected finding:**
1. **Off-by-one:** `m <= monthCount` creates `monthCount + 1` buckets — the comment
   promises indices `0..monthCount-1`; use `m < monthCount`.
2. **Unvalidated boundary:** `e.month` outside `0..monthCount-1` either lands in the
   phantom extra bucket or throws on `undefined.push` — validate or clamp at the
   boundary, and handle the empty-`events` and `monthCount = 0` cases explicitly.

## Bad → finding

**Input (diff):**
```python
def export_and_time(path, rows):
    start = time.time()
    f = open(path, "w")
    for r in rows:
        f.write(f"{r.id},{r.price * 1.07}\n")
    f.close()
    return time.time() - start
```
**Expected finding:**
1. **Resource leak on the error path:** if a write raises, `f.close()` never runs —
   use `with open(path, "w") as f:` so cleanup happens on all paths.
2. **Float arithmetic on money:** `r.price * 1.07` in binary float accumulates
   rounding error — use integer minor units or `Decimal`, and carry the currency.
3. **Wall clock for a duration:** `time.time()` can jump (NTP); measure elapsed time
   with the monotonic clock (`time.monotonic()`).

## Good → no finding

**Input (diff):**
```python
def clamp_percent(value: int) -> int:
    """Clamp to 0..100 inclusive."""
    return max(0, min(value, 100))
```
**Expected finding:** None — total over its input type, boundaries inclusive as
documented, no hidden partiality. Report "No findings". Do NOT invent boundary
issues the code already handles, and do NOT demand defensive checks for conditions
the type system or the function's contract already excludes.

## Good → no finding

**Input (diff):**
```python
with db.connection() as conn:
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        if poll(conn):
            return True
    return False
```
**Expected finding:** None — connection released on all paths, monotonic clock for
the deadline, loop provably terminates. Report "No findings"; do not invent issues.
