# Examples — auditing-architecture-conformance

This skill is repo-shaped: its input is an import-graph / layering scan, not a
single diff. Report each distinct violation as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

**Decision rule (apply before flagging):** a conformance finding needs a stated
rule (documented layering, an import-linter/ArchUnit config, an ADR) that the scan
violates. High fan-in alone is not a violation — shared kernels and util layers
legitimately have many importers. If every declared rule passes, report exactly
"No findings: the codebase conforms to its declared architecture".

## Bad → finding

**Input (architecture scan; declared rule: ui → app → domain → infra, no upward or skip imports; no cycles):**
```text
violations:
  domain/pricing.py        imports  infra/stripe_client.py
  domain/orders.py         imports  ui/formatters.py
cycles:
  app/billing.py -> app/invoices.py -> app/billing.py
fan-in/fan-out:
  app/helpers.py   fan-in 74   fan-out 41
```
**Expected finding:**
1. **Layering violation (domain → infra):** `domain/pricing.py` imports the Stripe
   client directly — invert it: define a payment-gateway port in domain and
   implement it in infra (dependency inversion).
2. **Upward import (domain → ui):** `domain/orders.py` reaching into UI formatters
   couples the core to presentation — move the shared piece down or duplicate the
   trivial formatting.
3. **Dependency cycle:** `app/billing.py ↔ app/invoices.py` — break it by
   extracting the shared concept or inverting one edge.
4. **God module:** `app/helpers.py` with fan-in 74 AND fan-out 41 routes everything
   through itself — split by responsibility; also encode the layer rules as a
   fitness function (import-linter/ArchUnit) so violations fail CI instead of
   accumulating.

## Good → no finding

**Input (architecture scan; same declared rule):**
```text
violations: none
cycles: none
fan-in/fan-out (top): domain/models.py fan-in 38 fan-out 3
```
**Expected finding:** None — no rule violations, no cycles; `domain/models.py`'s
high fan-in with tiny fan-out is a healthy shared kernel, not a hub. Report
"No findings: the codebase conforms to its declared architecture". Do NOT flag
high fan-in alone as a problem, and do NOT invent architectural rules the project
never declared.
