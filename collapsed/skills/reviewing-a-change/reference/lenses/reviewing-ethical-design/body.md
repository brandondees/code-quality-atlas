# reviewing-ethical-design

Does this manipulate or disadvantage the user? Dark patterns, manipulative defaults, discriminatory conditionals — detect-and-route to product/legal.

## When to use

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Checklist

## From category #36

### Reviewable heuristics (skill-checklist seeds)

- **Dark pattern / deceptive flow (detect-and-route):** Does the change introduce a recognized dark pattern — **sneaking** (hidden costs, sneak-into-basket), **fabricated urgency/scarcity** (a countdown or "only 2 left" not backed by truth), **misdirection / confirmshaming**, **obstruction** (roach-motel cancel), **forced action**, or **nagging** (Mathur's 7 / the EDPB's 6 families)? Name the specific category and cite the code that implements it; route the keep-or-kill product judgment to `product` and any consent-law facet to #27 / `legal`. Surface with evidence — never decide the product trade-off here, never drop it either.
- **Manipulative defaults & asymmetric choices:** Are defaults set to benefit the business against the user's likely intent — **pre-checked** consent / marketing opt-in, opt-out materially harder than opt-in, "accept all" prominent while "reject" is buried or absent, negative-option / auto-renew with no clear disclosure? The default value and the *asymmetry of the choice* are the defect, visible right in the code that sets them.
- **Discriminatory business logic in plain conditionals:** Does a hardcoded threshold, branch, or rule disadvantage a protected or vulnerable group with **no model in sight** — pricing / eligibility / scoring keyed (directly, or by proxy: ZIP, surname, device, locale) on a protected attribute, or a cutoff with a foreseeable disparate effect? Flag the conditional with evidence; route the legal/fairness adjudication to #27 / `legal` and the policy call to `product` / `leadership`. (Deep dataset/metric fairness auditing is out of scope — no diff artifact.)
- **Honest state & truthful signals:** Do the user-facing claims the code emits match reality — a "secure" / "private" / "deleted" label for data that isn't, a **fabricated** progress bar / "N people are viewing this" / fake low-stock, or a synthetic error/system message engineered to drive a choice? A signal the code knows to be false is a defect regardless of product intent.
- **Consent & opt-out actually wired (not theater):** When the change gates behavior on consent, does *declining* actually stop the behavior rather than just hide a toggle, and is **withdrawal as easy as granting** (GDPR Art. 7(3))? Consent theater — a dialog whose "no" path still proceeds — is the defect; the consent-as-law verdict routes to #27.
- **Asymmetric friction (obstruction vs. protection):** Is the user-favorable path (cancel, unsubscribe, delete account, export data) made disproportionately harder than the business-favorable one (sign up, buy, opt in)? Distinguish **obstruction** (friction that serves the business against the user's clear intent) from **legitimate protective friction** (a confirmation on a destructive action, step-up auth, a cooling-off period) — route the protective-control side to #14 / `sweeping-for-security`; obstruction stays a finding here.
- **Coercion / pressure in control flow:** Does the flow block or repeatedly push toward the "preferred" choice — interstitials with no genuine dismiss, re-prompts after a clear "no," a continue button disabled until an upsell is taken, confirmshaming microcopy? Pressure engineered into ordinary control flow is reviewable code, not just visual design.
- **Vulnerable-user & high-stakes context:** For flows touching minors, health, finance, or addiction-adjacent mechanics (loot boxes, variable-reward infinite scroll, streak pressure), is there heightened care rather than the same growth-optimized defaults? Surface for `product` / `legal` with evidence; the bar is higher and the defaults that pass elsewhere may not pass here.
- **Accessibility-as-exclusion (xref #23):** Is an ethical harm delivered *through* an accessibility gap — the consent or cancel control operable only by sighted/mouse users, or contrast/affordance used to hide the user-favorable option while surfacing the business-favorable one? Route the a11y mechanics to #23; the deceptive intent is owned here.

---

## Examples

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

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
