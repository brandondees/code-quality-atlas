# Examples — hunting-silent-failures

## Bad → finding

**Input (diff):**
```python
try:
    charge = payments.charge(order.total)
except Exception:
    pass
order.mark_paid()
```
**Expected finding:** Swallowed exception: the `except Exception: pass` hides charge
failures, and `order.mark_paid()` runs even when the charge failed. Fail loud — let
the error propagate, or handle the specific failure and do NOT mark the order paid.

## Bad → finding

**Input (diff):**
```js
const res = await fetch(url);   // no timeout, no error handling
return res.json();
```
**Expected finding:** No timeout and no failure handling on a remote call. Add an
AbortController timeout and handle non-OK responses / network errors with a defined
fallback; bare `await fetch` can hang indefinitely.

## Good → no finding

**Input (diff):**
```python
try:
    charge = payments.charge(order.total)
except PaymentDeclined as e:
    log.warning("charge declined", order_id=order.id, reason=e.code)
    return CheckoutResult.declined(e.code)   # specific, surfaced, no false "paid"
order.mark_paid()
```
**Expected finding:** None — narrow exception, surfaced with context, no silent
fallthrough. The early `return` is intentional and correct: a declined charge must
NOT fall through to `order.mark_paid()`. Do not suggest replacing it with `raise` or
removing it — that would break the declined-checkout path. **Catching one specific
exception (`PaymentDeclined`) and letting any other exception propagate is correct
fail-loud behavior** — do NOT flag it as "incomplete" and do NOT recommend broadening
the `except` to catch more types. Report "No findings."

## Good → no finding

**Input (diff):**
```python
resp = client.get(url, timeout=5)
resp.raise_for_status()
return resp.json()
```
**Expected finding:** None — the call has a timeout and `raise_for_status()` surfaces
non-2xx responses loudly. Report "No findings"; do not invent issues.
