# Examples — checking-restraint

## Bad → finding

**Input (diff):**
```python
class NotificationChannelFactory:
    """Pluggable notification backends (currently only email is implemented)."""
    def __init__(self, config: dict):
        self.config = config
        self.plugins = {}

    def register(self, name, channel_cls):
        self.plugins[name] = channel_cls

    def create(self, name="email", **overrides):
        return self.plugins[name](self.config, **overrides)
```
**Expected finding:** Speculative generality: a factory + plugin registry + config
overrides for a single implementation with one caller (YAGNI / rule of three).
Inline it to `send_email(...)` and extract an abstraction only when a real second
channel arrives — the right interface is unknowable from one example, and a wrong
abstraction is costlier than duplication.

## Bad → finding

**Input (diff):**
```js
// Cache user lookups for speed. (Invalidation TODO.)
const userCache = new Map();
function getUser(id) {
  const key = `u:${id}`;
  if (userCache.has(key)) return userCache.get(key);
  const u = db.users.findById(id);   // admin page, ~20 lookups/day
  userCache.set(key, u);
  return u;
}
```
**Expected finding:** Premature optimization: a hand-rolled, unbounded cache with no
invalidation story, on a path measured in calls per day, justified by no profile.
It buys nothing measurable and adds a stale-user bug and a memory leak. Remove the
cache; if this path ever shows up in a profile, add caching with an explicit
invalidation/TTL plan then. (When flagging a premature optimization, always name the
concrete risk it smuggles in — stale data, a memory leak, module-level/shared mutable
state that leaks across users or requests — not just the readability cost.)

## Good → no finding

**Input (diff):**
```python
def format_receipt(order):
    lines = [f"{li.name}: {cents_to_display(li.price_cents)}" for li in order.items]
    lines.append(f"Total: {cents_to_display(order.total_cents)}")
    return "\n".join(lines)
```
**Expected finding:** None — a direct, concrete implementation with no speculative
layers. Report "No findings". Do NOT recommend introducing an abstraction, interface,
formatter class, or template engine "for flexibility" — recommending un-needed
abstraction is exactly the failure mode this skill guards against. (When reporting
no findings, say "No findings" plainly; don't borrow a justification from another
case — only cite the rule of three when the repeated call sites are actually named.)

## Good → no finding

**Input (diff):**
```python
# Third call site needing this exact rounding rule (also in billing.py, refunds.py).
def round_to_cents(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
```
**Expected finding:** None — this extraction is justified by real, repeated need
(rule of three: third occurrence, sites named). Report "No findings"; the rule-of-three
counterweight cuts both ways — do not call a well-evidenced extraction premature.
