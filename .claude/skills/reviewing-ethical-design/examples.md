# Examples — reviewing-ethical-design

Report each distinct issue as its own numbered finding, naming the specific pattern and citing the code. This lens **detects and routes** — surface every finding with evidence and route the *decision* (consent-as-law → #27 / legal, product trade-off → product, a11y mechanics → #23); never silently drop a finding because "that's product's call," and never adjudicate one that isn't engineering's. When the flow treats the user honestly, the entire response is exactly "No findings".

## Contents

- [Bad → finding (manipulative default + consent symmetry)](#bad--finding-manipulative-default--consent-symmetry)
- [Bad → finding (discriminatory business logic)](#bad--finding-discriminatory-business-logic)
- [Bad → finding (fabricated urgency + obstruction)](#bad--finding-fabricated-urgency--obstruction)
- [Good → no finding](#good--no-finding)
- [Bad → finding (dishonest state signal)](#bad--finding-dishonest-state-signal)
- [Good → no finding (consent actually wired)](#good--no-finding-consent-actually-wired)
- [Not applicable → no user-facing behavior](#not-applicable--no-user-facing-behavior)

## Bad → finding (manipulative default + consent symmetry)

**Input (diff):**

```python
@app.post("/signup")
def signup(form):
    user = User(email=form.email)
    user.marketing_opt_in = True   # defaulted on; the form shows no way to decline
    user.save()
```

**Expected finding:**

1. **Manipulative default (pre-checked consent):** `marketing_opt_in` is defaulted
   to `True` with no symmetric, equally-easy way to decline — a recognized
   deceptive-design pattern set in the code that writes the default. Default it to
   `False` with a symmetric opt-in. **Route:** the consent-as-law facet (opt-in must
   be freely given — GDPR Art. 7) to `auditing-compliance-and-provenance` (#27) /
   `legal`; the product call to `product`. Surfaced with evidence, not decided here.

## Bad → finding (discriminatory business logic)

**Input (diff):**

```python
# pricing.py
def quote(applicant):
    base = 100
    if applicant.zip_code in HIGH_RISK_ZIPS:   # neighborhood proxy
        base *= 1.5
    if applicant.surname in FOREIGN_SOUNDING:   # explicit proxy
        base *= 1.2
    return base
```

**Expected finding:**

1. **Discriminatory logic in plain conditionals:** surcharges keyed on ZIP and on
   surname are proxies for protected attributes (race / national origin) with a
   foreseeable disparate effect — no model in sight, a code-level defect. **Route:**
   the legal/fairness adjudication to #27 / `legal`, the pricing-policy call to
   `product` / `leadership`. Cite the conditionals as evidence; do not adjudicate
   fairness here, and do not claim a statistic the diff can't support (a dataset
   audit is out of scope).

## Bad → finding (fabricated urgency + obstruction)

**Input (diff):** a checkout shows a countdown re-seeded on every load and a
hardcoded "Only 2 left!", and subscription cancellation redirects to a phone line
while sign-up is one click.

**Expected finding:**

1. **Fabricated urgency / scarcity (sneaking):** the countdown is re-seeded each
   page load (fake deadline) and `stock_label` is a constant, not real inventory.
2. **Obstruction (roach motel):** cancel is phone-only while sign-up is one click —
   asymmetric friction serving the business against the user's clear intent,
   distinct from legitimate protective friction. **Route:** keep-or-kill to
   `product`; any auto-renew/consent-law facet to #27 / `legal`.

## Good → no finding

**Input (diff):**

```python
@app.post("/account/delete")
def delete_account(user, confirmation):
    if confirmation != "DELETE":          # confirm a destructive, irreversible action
        return error("Type DELETE to confirm")
    purge(user)

# settings form: marketing_opt_in defaults to False; toggling it off stops sends immediately
```

**Expected finding:** No findings

Note: the confirmation guards a destructive, irreversible action (legitimate
protective friction, not obstruction), consent defaults to off, and declining
actually stops the behavior. Do NOT flag the destructive-action confirmation as a
dark pattern, and do NOT invent ethical findings on a flow that treats the user
honestly.

## Bad → finding (dishonest state signal)

**Input (diff):**

```python
@app.post("/account/delete")
def delete_account(user):
    user.is_deleted = True
    user.save()
    return {"message": "Your account and all data have been permanently deleted."}
    # user record and all associated data remain in the database, fully queryable
```

**Expected finding:**

1. **Dishonest state signal:** the response claims data is "permanently deleted,"
   but the code only sets a soft-delete flag — the record and all associated data
   remain fully queryable in the database. A signal the code knows to be false is
   a defect regardless of product intent. Either implement actual deletion (or a
   stated, accurately disclosed retention/anonymization policy) or correct the
   message to match what the code does. **Route:** any data-retention/compliance
   policy question to `auditing-compliance-and-provenance` (#27) / `legal`.

## Good → no finding (consent actually wired)

**Input (diff):**

```python
@app.post("/settings/marketing-consent")
def update_consent(user, consented: bool):
    user.marketing_consent = consented
    user.save()

def send_marketing_email(user):
    if not user.marketing_consent:
        return
    email_service.send(user.email, MARKETING_TEMPLATE)
```

**Expected finding:** No findings

Note: `send_marketing_email` actually checks `user.marketing_consent` before
sending — declining genuinely stops the behavior rather than just recording a
preference nobody reads (consent theater). Do NOT demand additional ceremony on
a toggle that is already correctly wired.

## Not applicable → no user-facing behavior

**Input (diff):**

```python
def reconcile_nightly_inventory_snapshot(warehouse_id):
    snapshot = fetch_warehouse_counts(warehouse_id)
    write_to_reporting_table(snapshot)
```

An internal batch job with no user-facing behavior, no consent flow, no pricing
logic, and no UI.

**Expected finding:** Not applicable — this is internal batch/reporting code
with no user-facing behavior, matching this lens's own explicit skip clause. Say
so with a line starting "Not applicable:". Do NOT report "No findings" (which
implies the checks ran and found nothing) and do NOT invent an ethical-design
concern in internal-only code.

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/reviewing-ethical-design/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
