# checking-restraint

Is this change too much? Premature abstraction or optimization — the brake pedal.

## When to use

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Checklist

## From category #11

### Reviewable heuristics (skill-checklist seeds)

- Is this abstraction introduced on **real, repeated need** (rule of three), or speculatively for one/two uses (YAGNI)?
- Does it have a single, nameable responsibility — or is it a grab-bag taking flags/conditionals to fit multiple callers (the **wrong-abstraction** smell)?
- Is there an **existing** abstraction this duplicates/competes with (reuse/extend it, don't fork — cross #8)?
- Would **inlining** make the code clearer? If the abstraction fights its callers, recommend re-inlining.
- Is the indirection earning its keep, or a **shallow wrapper** that just adds a layer to read through (Ousterhout)?
- Any **speculative generality**: config options, plugin hooks, "just in case" parameters with a single caller? Remove.
- Is the duplication here actually **coincidental** (looks the same, will evolve differently)? If so, leave it duplicated.
- **Counterweight discipline:** am I recommending an abstraction the evidence doesn't yet justify? Default to "duplicate once more, then extract."

---

## From category #15

### Reviewable heuristics (skill-checklist seeds)

- Is there a loop that issues a query/RPC/HTTP call per iteration? (N+1.) Push to a single batched/`IN`/join query or a bulk endpoint. Flag `await` inside `for` over independent items.
- What is the worst-case complexity on the hot path as input grows? Flag accidental O(n²) (nested loops over the same collection, `Array.includes` inside a loop → use a Set/Map), and unbounded growth.
- Is the same expensive value (DB read, computed result, parsed config, compiled regex) recomputed when it could be hoisted or memoized? Conversely, is anything memoized that's cheap and rarely reused (premature)?
- Caching correctness: is there a clear invalidation story (TTL, event-based, or write-through)? A cache without an invalidation answer is a future stale-data bug. Check key construction includes everything that affects the value (tenant, locale, version).
- I/O batching: are round-trips minimized (batch reads/writes, pipelining, HTTP keep-alive/connection pooling) rather than chatty per-item calls?
- Streaming vs buffering: for large payloads/files, is data streamed rather than fully loaded into memory? Flag "read entire file/response into a string then process."
- Allocation/GC pressure on hot paths: avoidable per-iteration allocations, boxing, large defensive copies, building huge intermediate collections? (Especially in tight loops and request handlers.)
- Lazy vs eager: is work deferred until needed (and *only* the needed work done), without re-triggering N+1 via lazy loading inside a loop?
- Frontend: does this change grow the bundle or block startup (new heavy dep, non-code-split route, render-blocking resource, large synchronous work on the main thread hurting INP)? Is the dep tree-shakeable and the import scoped?
- **Cost & carbon efficiency (FinOps + green) — `route: eng/leadership`:** does the change add per-request **cost *and* energy/carbon** that scale badly — chatty cross-AZ/egress traffic, unbounded fan-out, over-provisioned or always-on instances, polling instead of events, queries that scan far more than they return? These are one diff signal (wasted work per request) with two weights; surface the waste and **route** the spend/footprint trade-off to eng/leadership rather than adjudicating it here. Diff-visible inefficiency is in scope; an org-level carbon/cost *target* is not.
- **Premature-optimization smell test (counterweight):** Is this off a measured hot path, justified by no profile/benchmark, and does it trade real readability/correctness risk for unmeasured gains (hand-rolled cache, micro-bit-twiddling, denormalization, custom data structure)? If yes, push back and ask for a profile or a benchmark. "Make it correct and clear first; optimize the measured 3%."
- Did a perf claim (either "this is slow" or "this is faster") come with a number — benchmark, profile, or Big-O argument — rather than intuition?

---

## Examples

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

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

**Expected finding:**

1. **Speculative generality:** a factory + plugin registry + config overrides for a
   single implementation with one caller (YAGNI / rule of three). Inline it to
   `send_email(...)` and extract an abstraction only when a real second channel
   arrives — the right interface is unknowable from one example, and a wrong
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

**Expected finding:**

1. **Premature optimization:** a hand-rolled, unbounded cache with no invalidation
   story, on a path measured in calls per day, justified by no profile. Remove the
   cache; if this path ever shows up in a profile, add caching with an explicit
   invalidation/TTL plan then.
2. **Concrete risks the optimization smuggles in:** a stale-user bug (no
   invalidation) and a memory leak (unbounded growth) — when flagging a premature
   optimization, always name the module-level/shared mutable state, staleness, or
   leak it introduces, not just the readability cost.

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

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
