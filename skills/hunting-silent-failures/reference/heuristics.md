# Reviewable heuristics — hunting-silent-failures

## Contents
- From category #2
- From category #4

## From category #2

### Reviewable heuristics (skill-checklist seeds)
- Is any error swallowed — empty catch/`rescue`, `except: pass`, ignored Go `err`, discarded Result?
- Does each handler narrow to the *expected* exception type, not a blanket catch-all?
- On failure does it **fail loud** (surface + log with context) or **degrade intentionally** — never silently?
- Do error messages carry actionable context (what failed, key inputs, remediation) without leaking secrets/PII (cross #14/#16)?
- Does every remote/IO call have a timeout? Retries with capped backoff + jitter, not unbounded?
- Is there a fallback / circuit breaker for a dependency that fails repeatedly?
- On partial failure, is state left consistent / rolled back (transaction boundaries — cross #20)?
- Is the error handled at the layer that can actually do something, vs. caught-and-rethrown noise?
- Is input validated once at the trust boundary (parse-don't-validate)?
- Are all async rejections handled (no floating promises)?
- Are *bugs* (assertion-worthy) treated differently from *recoverable errors*?

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

## Open threads

- **Leak ↔ error-handling intertwine:** resource leaks (#4) overwhelmingly occur on error paths (#2). A combined "fail-and-clean-up" review behavior may be worth more than two separate ones — note for phase-2 granularity.
- **Distributed correctness spans clusters:** #3's distributed facet overlaps #20 (transactions/data safety) and #16 (timeouts, failure observability). Single-owner question (see map-gaps G1).
- **Tool-covered vs. judgment-only:** #1 logic and #2/#4 leak checks are heavily covered by the *recommended* linter sets — here the skill should **triage tool output**, not re-implement it. The unique LLM value in this cluster is *intent-matching* (#1) and the semantic "is this the right failure behavior?" (#2) that no linter judges (map-gaps G5).
- **Money/units double-booked** with #23 (already cross-linked): value-correctness lives here (#4), formatting lives in #23.
- **Determinism** (#1) cross-links #25 (LLM nondeterminism) and #17 (flaky tests) — a shared "is this reproducible?" heuristic could serve all three.
- **Thin tooling for time/float/money semantics** beyond `Lint/FloatComparison` and the falsehoods checklist → this sub-area is heuristic-led, a good early skill target.
