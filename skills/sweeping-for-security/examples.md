# Examples — sweeping-for-security

A diff often contains several independent vulnerabilities. Check every untrusted
input against every sink it reaches and report each issue as its own numbered
finding — finding one does not end the sweep. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

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
