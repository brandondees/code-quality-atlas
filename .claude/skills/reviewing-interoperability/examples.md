# Examples — reviewing-interoperability

Report each distinct issue as its own numbered finding, naming the **specific standard** the code fails (the RFC / spec / protocol) and citing the code at the boundary. This lens owns conformance to an *external* standard; it **defers** the contract we author to #13, internal time/encoding correctness to #4, idiom to #8, and config validity to #26 — and routes the security verdict on an auth-flow defect to #14. When the code already speaks the standard correctly, the entire response is exactly "No findings".

## Contents

- [Bad → finding (non-RFC-3339 date on the wire)](#bad--finding-non-rfc-3339-date-on-the-wire)
- [Bad → finding (OAuth `state` not validated — detect-and-route)](#bad--finding-oauth-state-not-validated--detect-and-route)
- [Bad → finding (cron-dialect mismatch)](#bad--finding-cron-dialect-mismatch)
- [Good → no finding](#good--no-finding)
- [Bad → finding (breaking change, unreflected version)](#bad--finding-breaking-change-unreflected-version)
- [Bad → finding (co-existence: hardcoded shared resource)](#bad--finding-co-existence-hardcoded-shared-resource)
- [Good → no finding (breaking change, correctly versioned)](#good--no-finding-breaking-change-correctly-versioned)
- [Not applicable → no boundary-crossing surface](#not-applicable--no-boundary-crossing-surface)

## Bad → finding (non-RFC-3339 date on the wire)

**Input (diff):**

```python
# api.py — payload sent to a partner webhook
def serialize(event):
    return {"id": event.id, "ts": str(event.created_at)}   # -> "2026-06-24 12:00:00.123456"
```

**Expected finding:**

1. **RFC 3339 violation at the boundary:** `str(datetime)` emits a space separator
   and no timezone offset, which a strict RFC 3339 parser (the partner's) rejects or
   misreads. The value may be correct internally (#4's concern); it is
   *un-interoperable* on the wire. Emit `created_at.astimezone(timezone.utc).isoformat()`
   (e.g. `2026-06-24T12:00:00.123456+00:00`) or an explicit `T`…`Z` form.

## Bad → finding (OAuth `state` not validated — detect-and-route)

**Input (diff):**

```python
@app.get("/oauth/callback")
def callback(code, state):
    token = exchange_code(code)          # no check that `state` matches the value we issued
    session["user"] = userinfo(token)
    return redirect("/")
```

**Expected finding:**

1. **OAuth/OIDC flow non-conformance (missing `state` check):** the callback exchanges
   the code without comparing `state` to the per-session value issued at authorization
   start — a CSRF / login-forgery hole the protocol (RFC 9700 / OIDC Core) requires
   closing. Generate, store, and constant-time-compare `state`; validate `nonce` and
   use PKCE on public clients. **Route:** the security verdict to `sweeping-for-security`
   (#14); the protocol-conformance defect is owned here.

## Bad → finding (cron-dialect mismatch)

**Input (diff):** a job scheduled on 5-field POSIX/Vixie cron is given the expression
`"0 0 12 * * ?"` (copied from a Quartz example).

**Expected finding:**

1. **Cron-dialect mismatch:** `"0 0 12 * * ?"` is a 6-field Quartz expression (leading
   seconds, `?` day-of-week) but the runner is 5-field POSIX cron — it cannot parse it
   (or misreads the fields), so the job silently never fires or fires at the wrong
   time. A valid-looking expression in the wrong dialect. Use `"0 12 * * *"` for
   noon-daily on POSIX, or switch to a Quartz-compatible runner if seconds/year are
   actually needed.

## Good → no finding

**Input (diff):**

```python
@app.post("/charge")
def charge(req):
    key = req.headers["Idempotency-Key"]      # retries dedupe on this key
    if seen(key):
        return stored_response(key)
    resp = do_charge(req)
    return remember(key, resp)

def serialize(event):
    return {"ts": event.created_at.astimezone(timezone.utc).isoformat()}   # 2026-06-24T12:00:00+00:00
```

**Expected finding:** No findings

Note: the `POST` is made retry-safe via an `Idempotency-Key` (correct HTTP semantics)
and the timestamp is emitted in RFC 3339 with an explicit offset. Do NOT invent a
conformance defect on code that already speaks the external standards correctly.

## Bad → finding (breaking change, unreflected version)

**Input (diff; public API response model, consumed by external partners; CHANGELOG shows the package version bumped 2.4.1 -> 2.4.2):**

```python
# schema.py
class OrderResponse(BaseModel):
    id: str
    order_status: str   # renamed from `status`; the `status` field is removed entirely
```

**Expected finding:**

1. **SemVer violation (breaking change under a patch bump):** removing `status` in
   favor of `order_status` breaks existing consumers reading the old field, but the
   version only moved 2.4.1 → 2.4.2. SemVer 2.0.0 requires a major bump for breaking
   changes. Bump to 3.0.0, or keep `status` alongside `order_status` for a back-compat
   transition. Does not assess whether the rename itself was good API design — only
   the versioning mismatch.

## Bad → finding (co-existence: hardcoded shared resource)

**Input (diff):**

```python
LOCK_FILE = "/tmp/myapp.lock"   # hardcoded, shared across all instances

def acquire():
    open(LOCK_FILE, "x").close()
```

**Expected finding:**

1. **Co-existence defect (hardcoded shared path):** a second instance of this service
   on the same host collides on the same fixed lock path. Derive the path from a
   per-instance identifier or a properly namespaced temp directory. The ISO
   co-existence facet: correct alone, broken sharing a host.

## Good → no finding (breaking change, correctly versioned)

**Input (diff; CHANGELOG: 2.9.0 -> 3.0.0 -- breaking: `status` field removed, replaced by `order_status`):**

```python
class OrderResponse(BaseModel):
    id: str
    order_status: str
```

**Expected finding:** No findings

Note: the breaking field rename is correctly reflected in a major version bump. Do
NOT flag a breaking change merely for being breaking — only one shipped under a
version bump that doesn't reflect it.

## Not applicable → no boundary-crossing surface

**Input (diff):** a pure internal refactor that renames a local variable and extracts
a private helper function, touching no external protocol, wire format, versioned
surface, or shared resource.

**Expected finding:** Not applicable — this change crosses no boundary this lens
reviews (no protocol, wire format, versioned surface, or shared resource), matching
this lens's own explicit skip clause. Say so with a line starting "Not applicable:".
Do NOT report "No findings" (which implies the checks ran and found nothing) and do
NOT invent an interoperability angle on a purely internal refactor.

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/reviewing-interoperability/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
