# Reviewable heuristics — tracing-correctness-and-invariants

## Contents

- From category #1
- From category #4

## From category #1

### Reviewable heuristics (skill-checklist seeds)

- Does every branch and early return preserve the function's stated invariant/postcondition?
- Are boundary values (0, 1, n−1, n, empty, max, negative) explicitly handled — and tested?
- Any off-by-one in ranges, slices, loop bounds, inclusive/exclusive ends?
- Is every externally-sourced value null/undefined-checked at the boundary, or typed non-null?
- Does every `switch`/`match` cover all cases or carry a safe, explicit default?
- Any always-true/false condition (dead branch) or unreachable code after a terminator?
- Right comparison operator everywhere (value vs identity; never exact-`==` on floats — see #4)?
- Is behavior deterministic — no reliance on map iteration order, unseeded randomness, or wall-clock (cross #3, #25)?
- For each loop: does it always make progress and terminate?
- Does the change keep the function total over its input type, or is partiality documented?
- Does the implementation actually match the spec/PR description's stated intent (the check no linter can do)?

---

## From category #4

### Reviewable heuristics (skill-checklist seeds)

- Is every acquired resource (file, socket, connection, lock, cursor) released on **all** paths including errors (`with`/`using`/`defer`/`ensure`)?
- Does anything that grows (logs, cache, queue, temp files, sessions) have a bound / eviction / TTL (steady state)?
- Money/currency stored as integer minor units or a decimal `Money` type — never binary float — and currency carried?
- Float comparisons use a tolerance, not `==`?
- Are numeric overflow/underflow and counter wraparound considered for the actual value ranges?
- Time stored/compared in UTC; timezone/DST handled only at edges; no "always 24h/365d" assumptions?
- Are elapsed durations measured with a **monotonic** clock, not wall-clock (which can jump backward)?
- Is mutable shared state minimized and is ownership (who may mutate) clear?
- Are caches invalidated correctly on the underlying change (cross #15)?
- Are connection pools bounded and reused, with no per-request unbounded resource creation?

---
