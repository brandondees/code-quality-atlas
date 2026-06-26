# reviewing-interoperability

Does the code correctly speak external standards? HTTP/OAuth semantics, SemVer, RFC date/URI/email formats, Unicode, cron dialects, OTel semconv.

## When to use

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Checklist

## From category #37

### Reviewable heuristics (skill-checklist seeds)

- **Standard protocol semantics (HTTP / OAuth / OIDC):** Does the code obey the **protocol it speaks**, not just a happy-path mock? For HTTP: are methods **safe/idempotent as the spec requires** (a retried `POST` not double-charging; `PUT`/`DELETE` idempotent), are status codes used per their meaning (201/204/409/422, not 200-for-everything), and are conditional requests / caching (`ETag`, `If-None-Match`, `Cache-Control`, `Vary`) correct? For OAuth/OIDC: is `redirect_uri` **exact-matched**, is **`state`** validated (CSRF), is **`nonce`** checked (replay), is **PKCE** present on public clients, and are tokens kept out of the front channel? A flow that authenticates in the demo but skips `state` is interoperable-looking and unsafe.
- **RFC / format conformance at the boundary (dates, URIs, email, Unicode, JSON/CSV):** Does every value crossing an external boundary **parse and emit per its spec** — dates as **RFC 3339** (offset/`Z`, not a locale string), URIs per **RFC 3986** (proper percent-encoding, no naive string-concat), email per RFC 5321/5322 (and IDN/punycode where relevant), JSON per RFC 8259 (no duplicate keys, number-precision aware), CSV per RFC 4180 (quoting/embedded-newline)? Is text **Unicode-normalized (NFC) before compare/store/index**, UTF-8 validated, and the **YAML "Norway"/sexagesimal** class quoted? A value that *looks* right but a strict third-party parser rejects is the core interoperability defect.
- **Versioning & wire/format back-compat (semver discipline):** Is a **breaking** change to a published API, event schema, serialized format, or CLI surface reflected in the version (a major bump per **SemVer 2.0.0**), and does the change preserve compatibility for existing consumers (additive/optional fields, tolerant readers, no field-meaning reuse)? A breaking change shipped under a patch bump is a compatibility defect even when the code is correct in isolation.
- **Encoding, charset & content negotiation:** Are `Content-Type` / `charset`, `Accept` negotiation, and MIME types correct and consistent with what the body actually is — no `application/json` over a text blob, no charset assumed rather than declared, BOM and surrogate-pair edges handled? Mismatched declared-vs-actual encoding breaks the consumer, not the producer's tests.
- **Time, calendar & locale tags on the wire:** Are timestamps serialized with an explicit offset/zone (**RFC 3339**), zone identifiers from the **IANA tz database** (not fixed offsets that break across DST), and locale/language tags **BCP 47**-valid? (Internal clock/timezone correctness stays #4; this check is about the *format crossing the boundary* a third party must read.)
- **Schedule-expression & cron dialect:** Does a cron / schedule expression match the **dialect of the engine that runs it** — 5-field POSIX vs. Quartz's 6/7-field (seconds + year), differing day-of-week indexing and `?`/`L`/`#` extensions, and the runner's timezone assumption? A valid-looking expression in the wrong dialect silently misfires.
- **Convention conformance for observability & interchange (OTel semconv, well-known files):** Where the change emits telemetry or standard artifacts, does it follow the **OpenTelemetry semantic conventions** (stable attribute names, not bespoke keys), standard MIME types, and well-known formats/locations (`robots.txt`, `.well-known/`, sitemap, `llms.txt`) so external tooling consumes them? Off-convention names are technically valid and practically un-interoperable.
- **Co-existence (share the environment without detriment):** Does the change assume a resource it does not own — a **hardcoded port**, a global singleton or shared mutable file/lock path, an env-var name likely to collide, a fixed temp path — that breaks when co-located with another instance or service? The ISO co-existence facet: correct alone, broken sharing a host.

---

## Examples

Report each distinct issue as its own numbered finding, naming the **specific standard** the code fails (the RFC / spec / protocol) and citing the code at the boundary. This lens owns conformance to an *external* standard; it **defers** the contract we author to #13, internal time/encoding correctness to #4, idiom to #8, and config validity to #26 — and routes the security verdict on an auth-flow defect to #14. When the code already speaks the standard correctly, the entire response is exactly "No findings".

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

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
