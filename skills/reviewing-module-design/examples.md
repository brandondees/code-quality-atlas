# Examples — reviewing-module-design

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

## Bad → finding

**Input (diff):**
```python
class Order:
    def __init__(self):
        self.status = "draft"          # "draft" | "paid" | "shipped" | "cancelled"
        self.shipped_at = None         # set when shipped
        self.cancelled_reason = None   # set when cancelled
        self.tracking_number = ""      # "" until shipped
```
**Expected finding:**
1. **Illegal states are representable:** nothing stops `status == "cancelled"` with
   a `shipped_at`, or `status == "shipped"` with no tracking number. Model the
   lifecycle as a tagged union / state machine (e.g.
   `Shipped(shipped_at, tracking_number)` vs `Cancelled(reason)`) so each state
   carries exactly its own data.
2. **Stringly-typed status** invites typos — use an enum or the tagged union's tag.
3. **Sentinel values** (`""`, `None`) stand in for "absent" — use explicit optional
   types tied to the state that owns them.

## Bad → finding

**Input (diff):**
```js
function applyDiscount(customer) {
  const tier = customer.account.subscription.plan.tier;   // reach-through
  if (tier === "gold") {
    customer.cart.total = customer.cart.total * 0.9;      // mutates another object's data
  }
}
```
**Expected finding:**
1. **Law-of-Demeter violation:** the four-hop reach-through
   (`customer.account.subscription.plan.tier`) couples this function to the
   internal structure of three other objects — any reshuffle breaks it. Ask, don't
   take: `customer.discountTier()`.
2. **Feature Envy / broken encapsulation:** the function mutates `cart`'s data from
   outside — move the discount onto the cart (or have the customer apply it).

## Good → no finding

**Input (diff):**
```python
@dataclass(frozen=True)
class EmailAddress:
    value: str

    @classmethod
    def parse(cls, raw: str) -> "EmailAddress":
        if "@" not in raw:
            raise InvalidEmail(raw)
        return cls(raw.strip().lower())
```
**Expected finding:** None — untrusted input is parsed once into a precise immutable
type at the boundary (parse-don't-validate); downstream code can't hold an invalid
`EmailAddress`. Report "No findings". Do NOT flag the small surface as "needs more
methods," do NOT suggest an interface/abstract base for a single implementation, and
do NOT call a deliberately narrow value object "anemic."

## Good → no finding

**Input (diff):**
```ts
type PaymentState =
  | { kind: "pending" }
  | { kind: "settled"; settledAt: Date }
  | { kind: "failed"; reason: string };
```
**Expected finding:** None — a tagged union where each state carries exactly its own
data; illegal combinations are unrepresentable and `switch` over `kind` is
compiler-checked for exhaustiveness. Report "No findings"; do not invent issues.
