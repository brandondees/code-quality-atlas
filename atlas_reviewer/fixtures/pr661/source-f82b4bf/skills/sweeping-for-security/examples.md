# Examples — sweeping-for-security

A diff often contains several independent vulnerabilities. Check every untrusted
input against every sink it reaches and report each issue as its own numbered
finding — finding one does not end the sweep. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

## Contents

- [Bad → finding](#bad--finding)
- [Bad → finding](#bad--finding-1)
- [Bad → finding](#bad--finding-2)
- [Good → no finding](#good--no-finding)
- [Good → no finding](#good--no-finding-1)

## Bad → finding

**Input (diff):**

```python
API_KEY = "prod-payments-secret-EXAMPLE-NOT-REAL"   # hardcoded production credential

def get_invoice(request):
    inv_id = request.GET["id"]
    rows = db.execute(f"SELECT * FROM invoices WHERE id = {inv_id}")
    return JsonResponse(rows[0])
```

**Expected finding:**

1. **SQL injection:** `inv_id` comes from the request and is interpolated into the
   query — use a parameterized query
   (`db.execute("SELECT * FROM invoices WHERE id = %s", [inv_id])`).
2. **Missing authorization (IDOR):** any authenticated user can fetch any invoice
   by id; scope the lookup to the resource owner.
3. **Hardcoded production secret** `API_KEY` in source — move to a secrets
   manager / runtime env and rotate the exposed key.

## Bad → finding

**Input (diff):**

```python
def render_user_template(request):
    name = request.GET["template"]
    body = open(f"/srv/templates/{name}").read()        # user-controlled path
    html = os.popen(f"render-md {name}").read()          # user input in a shell
    if hashlib.md5(request.GET["sig"].encode()).hexdigest() == body[:32]:
        return HttpResponse(html)
```

**Expected finding:**

1. **Path traversal:** the user-supplied `name` reaches a filesystem path —
   `../../etc/passwd` escapes `/srv/templates`. Resolve the path and confine it to
   the directory, or allow-list known template names.
2. **Command injection:** the same untrusted value is interpolated into a shell
   command via `os.popen` — use `subprocess.run([...])` with an argument list and
   no shell.
3. **Weak hash for an integrity check:** MD5 is broken for security purposes — use
   an HMAC with a server-side key.

## Bad → finding

**Input (diff):**

```python
@require_role("refund_approver")              # caller is authorized to approve any refund
@router.post("/refunds/{refund_id}/approve")
def approve_refund(refund_id, request):
    refund = Refund.objects.get(id=refund_id)
    refund.status = "approved"
    refund.approved_by = request.user.id      # but nothing checks they aren't the requester
    refund.save()
    process_payout(refund)                     # money leaves immediately
    return {"ok": True}
```

**Expected finding:**

1. **Missing segregation of duties (maker-checker):** the approver role gates *who*
   may approve, but nothing stops the same actor who requested the refund from
   approving their own — one principal completes a high-consequence payout alone.
   Require the approver to be a distinct actor from the requester (reject when
   `refund.requested_by == request.user.id`). This is a workflow-authorization
   control, distinct from least-privilege and IDOR — the role-gated lookup itself is
   appropriate for an approver acting on others' refunds, so don't flag it as IDOR;
   *which* operations need dual-control is a business-policy call, so surface it to
   security/compliance rather than deciding the threshold here.

**Decision rule:** a role or permission check (`@require_role`, an `is_admin` gate,
a scope) authorizes *who* may act — it is **not** segregation of duties. When a
high-consequence action records an initiator (`requested_by`, `created_by`) and an
approver but never compares their identities, the maker-checker control is missing
and you must report it, *even though* an authorization gate is present. "Auth is
handled" is not evidence of dual-control.

## Good → no finding

**Input (diff):**

```python
def get_invoice(request):
    invoice = Invoice.objects.get(
        id=request.GET["id"], owner=request.user)   # ownership enforced, ORM-parameterized
    return JsonResponse(invoice.as_dict())
```

**Expected finding:** None — the ORM parameterizes the lookup and the query is
scoped to the resource owner, so there is no injection and no IDOR. Report
"No findings". Do NOT demand extra defenses that add nothing here (the id needs no
manual sanitizing once parameterized; authentication is the framework's job), and
do NOT flag reading a request parameter as inherently unsafe — what matters is how
it reaches the sink.

## Good → no finding

**Input (diff):**

```python
@require_role("refund_approver")
@router.post("/refunds/{refund_id}/approve")
def approve_refund(refund_id, request):
    refund = Refund.objects.get(id=refund_id)
    if refund.requested_by == request.user.id:        # maker-checker enforced
        raise PermissionDenied("approver must differ from requester")
    refund.status = "approved"
    refund.approved_by = request.user.id
    refund.save()
    process_payout(refund)
    return {"ok": True}
```

**Expected finding:** None — segregation of duties is enforced: an approver-role
gate plus an explicit check that the approver is not the requester, so no single
actor completes the payout alone. Report "No findings". Do NOT invent further
dual-control requirements, and do NOT flag the role-gated `get(id=...)` as an IDOR
— an approver is meant to act on others' refunds.
