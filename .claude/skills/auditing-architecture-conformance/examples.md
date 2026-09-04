# Examples — auditing-architecture-conformance

This skill is repo-shaped: its input is an import-graph / layering scan, not a
single diff. Report each distinct violation as its own numbered finding. When the scan is healthy, the entire response is exactly this skill's no-finding sentence given in the decision rule below — never a numbered list of findings for a healthy scan.

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

## Good → no finding (correct dependency inversion)

**Input (declared rule: domain owns its own ports; infra implements them):**

```python
# domain/ports.py
class PaymentGateway(Protocol):
    def charge(self, amount: int) -> None: ...

# domain/orders.py
from domain.ports import PaymentGateway

class OrderService:
    def __init__(self, gateway: PaymentGateway):
        self.gateway = gateway

# infra/stripe_gateway.py
from domain.ports import PaymentGateway

class StripeGateway(PaymentGateway):
    def charge(self, amount: int) -> None: ...

# app/composition_root.py
order_service = OrderService(StripeGateway())
```

**Expected finding:** None — domain defines the `PaymentGateway` port,
`infra/stripe_gateway.py` implements it, and only the composition root wires
the concrete class into `OrderService`. `infra` importing `domain.ports` is
the port flowing in the intended direction, not a violation; `domain` never
imports or instantiates the concrete `StripeGateway`.

## Not applicable

**Input:**

```text
Q3 Product Newsletter

We shipped three new customer-facing features this quarter and grew active
users by 12%. Thanks to everyone on the team for a great quarter!
```

**Expected finding:** "Not applicable: no import graph, layering, or
module-boundary information is present to audit." Do NOT report "No
findings" here — that sentence means a check ran and found nothing, not that
nothing in this input was checkable.

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/auditing-architecture-conformance/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
