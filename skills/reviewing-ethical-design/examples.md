# Examples — reviewing-ethical-design

Report each distinct issue as its own numbered finding, naming the specific pattern and citing the code. This lens **detects and routes** — surface every finding with evidence and route the *decision* (consent-as-law → #27 / legal, product trade-off → product, a11y mechanics → #23); never silently drop a finding because "that's product's call," and never adjudicate one that isn't engineering's. When the flow treats the user honestly, the entire response is exactly "No findings".

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
