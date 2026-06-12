# Examples — synthesizing-review-findings

**Input:** Three lenses ran on a PR that adds a Redis cache in front of a pricing
query and rewrites the payment retry logic.

- `reviewing-performance-and-efficiency`: "cache has no invalidation on price
  update (orders/pricing.py:42)"; "the cache is added without a profile."
- `checking-restraint`: "no profile justifies the cache (orders/pricing.py:42)";
  "retry count is now configurable for a single caller — speculative."
- `hunting-silent-failures`: "the retry loop swallows the provider error after
  the last attempt (orders/payment.py:88)."

**Good synthesis:**

```
Verdict: approve with changes — one swallowed error must be fixed; the cache needs a profile or invalidation.

Major
- orders/payment.py:88 — final retry swallows the provider error; failures look like successes (hunting-silent-failures). Re-raise or return a typed error after the last attempt.

Minor
- orders/pricing.py:42 — cache has no invalidation on price update; stale prices possible (reviewing-performance-and-efficiency). Add invalidation, or drop the cache until a profile shows it's needed.

Tensions
- checking-restraint ↔ reviewing-performance-and-efficiency: no profile justifies the cache → restraint wins; ship without it unless a profile shows the pricing query is the bottleneck.

Nit
- orders/payment.py — retry count made configurable for one caller (checking-restraint). Inline the constant until a second caller needs it.
```

Note the dedupe: "no profile justifies the cache" was raised by *both* performance
and restraint at the same location — it appears **once**, folded into the cache
finding and the tension, not twice.

**Bad synthesis:** listing all five raw findings ungrouped, reporting the
"no profile" point twice (once per lens), and stamping "block" when nothing is a
Blocker — inflation the *Reviewer discipline* section forbids.

---

**Input:** Two lenses ran on a small refactor that extracts a `PricingStrategy`
interface with one implementation.

- `reviewing-module-design`: "extracting the interface clarifies the seam
  (pricing/strategy.py)."
- `checking-restraint`: "one implementation, no second consumer — premature
  abstraction (pricing/strategy.py)."

**Good synthesis:** these conflict, so reconcile rather than pick silently:

```
Verdict: approve with changes — collapse the premature interface.

Minor
- pricing/strategy.py — interface has a single implementation and no second consumer; premature abstraction (checking-restraint). Inline it; reintroduce the seam when a second strategy actually appears.

Tensions
- checking-restraint ↔ reviewing-module-design: one consumer today → restraint wins; the boundary is justified only once a second concrete strategy exists.
```

**Bad synthesis:** reporting module-design's "clarifies the seam" as a positive
finding *and* restraint's "premature" as a negative one, leaving the author with
two contradictory verdicts and no resolution.

---

**Input:** All four selected lenses returned "No findings" on a one-line typo fix.

**Good synthesis:**

```
Verdict: approve — No findings. All lenses clear.
```

**Bad synthesis:** inventing a "consider adding a test" Nit so the report doesn't
look empty. No lens raised it; synthesis adds nothing.
