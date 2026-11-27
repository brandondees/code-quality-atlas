# Examples — hunting-silent-failures

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

## Contents

- [Bad → finding](#bad--finding)
- [Bad → finding](#bad--finding-1)
- [Bad → finding (fail-open: fails toward harm, not toward safe)](#bad--finding-fail-open-fails-toward-harm-not-toward-safe)
- [Good → no finding (fail-closed on auth check)](#good--no-finding-fail-closed-on-auth-check)
- [Good → no finding (narrow exception, no false success)](#good--no-finding-narrow-exception-no-false-success)
- [Good → no finding (timeout + raise_for_status)](#good--no-finding-timeout--raise_for_status)

## Bad → finding

**Input (diff):**

```python
try:
    charge = payments.charge(order.total)
except Exception:
    pass
order.mark_paid()
```

**Expected finding:**

1. **Swallowed exception:** the `except Exception: pass` hides charge failures —
   fail loud (let the error propagate) or handle the specific failure.
2. **False success state:** `order.mark_paid()` runs even when the charge failed —
   the failure path must NOT fall through to marking the order paid.

## Bad → finding

**Input (diff):**

```js
const res = await fetch(url);   // no timeout, no error handling
return res.json();
```

**Expected finding:**

1. **No timeout on a remote call:** bare `await fetch` can hang indefinitely — add
   an AbortController timeout.
2. **No failure handling:** non-OK responses and network errors are unhandled —
   handle them with a defined fallback.

## Bad → finding (fail-open: fails toward harm, not toward safe)

**Input (diff):**

```python
def can_access(user, doc):
    try:
        return authz.check(user, doc)        # True/False
    except AuthzServiceError:
        return True   # authz down — let them through so the page still works
```

**Expected finding:**

1. **Fail-open on an authorization check (fails toward harm):** when `authz.check`
   cannot be evaluated the code defaults to **allow**, so an authz outage silently
   grants access. A permission / auth / quota / limit check must **fail closed** —
   `return False` on error (and surface the error) — not default-allow. This is the
   *direction* the failure resolves (ISO/IEC 25010:2023 *safety* / harm-prevention),
   distinct from attacker-facing #14 security. The acceptable-risk call is a
   detect-and-route to a human owner, not a verdict to settle here.

## Good → no finding (fail-closed on auth check)

**Input (diff):**

```python
def can_access(user, doc):
    try:
        return authz.check(user, doc)
    except AuthzServiceError as e:
        log.error("authz unavailable", user=user.id, doc=doc.id, err=str(e))
        return False   # deny on failure — fail closed
```

**Expected finding:** None — the check **fails closed** (denies when it cannot be
evaluated) and surfaces the error with context: the safe, fail-loud direction. Do not
invent a fail-open or swallowed-error issue, and do not suggest defaulting to allow
"for availability." Report "No findings".

## Good → no finding (narrow exception, no false success)

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
the `except` to catch more types. Report "No findings".

## Good → no finding (timeout + raise_for_status)

**Input (diff):**

```python
resp = client.get(url, timeout=5)
resp.raise_for_status()
return resp.json()
```

**Expected finding:** None — the call has a timeout and `raise_for_status()` surfaces
non-2xx responses loudly. Report "No findings"; do not invent issues.
