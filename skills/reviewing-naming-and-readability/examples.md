# Examples — reviewing-naming-and-readability

## Bad → finding

**Input (diff):**
```python
def process(data, flag):
    if data is not None:
        if flag == 3:
            tmp = []
            for d in data:
                if d.status == 2:
                    if d.amount > 10000:
                        tmp.append(d)
            return tmp
    return None
```
**Expected finding:** Placeholder names (`process`, `data`, `tmp`, `flag`, `d`) hide
intent — name the domain concept (e.g. `find_large_settled_orders`). Magic numbers
`3`, `2`, `10000` need named constants (`MODE_AUDIT`, `STATUS_SETTLED`,
`LARGE_ORDER_THRESHOLD_CENTS` — with units). Four levels of nesting: invert to guard
clauses (`if data is None: return ...`) so the happy path is un-indented.

## Bad → finding

**Input (diff):**
```js
// Retries the request 3 times before giving up.
async function fetchUserViaHttpGet(id) {
  const MAX_ATTEMPTS = 5;
  // const legacy = await oldFetchUser(id);
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) { /* ... */ }
}
```
**Expected finding:** The comment says "3 times" but the code allows 5 — a
contradicting comment is worse than none; fix one of them. Delete the commented-out
code (`oldFetchUser`) — version control is the archive. The name `fetchUserViaHttpGet`
encodes the mechanism; `fetchUser` survives a transport change. (This check applies
in every language: any name that bakes in the transport, library, or storage
mechanism — `saveViaJdbc`, `loadFromRedis` — should state intent instead, so always
scan function names for embedded mechanism, not just the obvious smells.)

## Good → no finding

**Input (diff):**
```python
MAX_LOGIN_ATTEMPTS = 5

def is_locked_out(account: Account) -> bool:
    if account.failed_logins < MAX_LOGIN_ATTEMPTS:
        return False
    return account.lock_expiry > clock.now()
```
**Expected finding:** None — intention-revealing names, a predicate boolean
(`is_locked_out`), the literal is a named constant, guard clause keeps nesting flat.
Report "No findings". Do NOT flag the short body as "needs comments" — clear code
needs no restating comment. Do NOT flag `0`/`1`-style obvious literals or demand
longer names for already-clear ones.

## Good → no finding

**Input (diff):**
```js
for (let i = 0; i < rows.length; i++) {
  total += rows[i].amountCents;
}
```
**Expected finding:** None — a one-letter index is fine for a three-line loop (name
length proportional to scope), and `amountCents` already carries its unit. Report
"No findings"; do not invent issues.
