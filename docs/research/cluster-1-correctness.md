# Research — Cluster I: Correctness & Robustness

> Part of code-quality-atlas phase-1 research (see ../taxonomy.md). Generated 2026-06-09 via web research. Citations web-verified on 2026-06-09 except where marked `(verify)`. This file is the **exemplar/template** the other cluster files mirror.

## Template notes

Each taxonomy category gets three sections:

- **Key references** — `author/org — title` + URL only when verified; each with a `→ mine:` note (the specific idea/heuristic we'd take).
- **Tooling rules worth lifting** — real rule identifiers from real tools, grouped by tool, each with its one-line meaning. These are pre-validated, real-world heuristics.
- **Reviewable heuristics (skill-checklist seeds)** — crisp, checkable criteria an LLM reviewer can apply to a diff. These become skill checklists. Where mature linters already cover a check, the skill's job is to *triage tool output*; the unique value is the semantic checks tools can't do (does this match intent?).

`(verify)` = asserted from knowledge, not confirmed against a live source this pass.

---

## #1 Functional correctness & logic

### Key references

- **Moseley & Marks — "Out of the Tar Pit" (2006)** — https://curtclifton.net/papers/MoseleyMarks06a.pdf → mine: *state* and *control* are the prime sources of accidental complexity; minimizing mutable state is what makes correctness tractable. (Cross-links #4, #11.)
- **Steve McConnell — *Code Complete* (2nd ed.), "Defensive Programming"** → mine: assertions, barricades, and explicit boundary handling; validate at the barricade, assert internally.
- **Glenford Myers — *The Art of Software Testing* (boundary-value analysis)** `(verify)` → mine: bugs cluster at boundaries; review the 0/1/n−1/n/empty/max transitions explicitly.
- **John Regehr — "A Guide to Undefined Behavior in C and C++"** `(verify URL)` → mine: when behavior is undefined/unspecified the compiler may do anything; relevant to determinism and portability (#26).
- **Tony Hoare — "Null References: The Billion Dollar Mistake"** `(verify URL)` → mine: null is a pervasive correctness hazard; prefer designs where absence is encoded in the type (cross-links #10).

### Tooling rules worth lifting

- **ESLint (all in `recommended`):** `no-unreachable` (code after return/throw/break), `no-unreachable-loop` (body runs ≤1×), `no-fallthrough` (switch fallthrough), `no-constant-condition` & `no-constant-binary-expression` (always-true/false → dead branch or bug), `no-dupe-keys` / `no-dupe-args` (silently dropped), `no-self-assign` / `no-self-compare`, `no-unmodified-loop-condition` (likely infinite loop), `array-callback-return` (map/filter/reduce callback missing return), `default-case-last`, `no-cond-assign` (`=` where `==` meant).
- **typescript-eslint (type-checked):** `no-unnecessary-condition` (type is always truthy/falsy → dead branch), `switch-exhaustiveness-check` (non-exhaustive union switch), `no-base-to-string` (stringifies `[object Object]`).
- **RuboCop Lint:** `Lint/UnreachableCode`, `Lint/UnreachableLoop`, `Lint/DuplicateMethods`, `Lint/IdentityComparison` (`equal?` when `==` meant), `Lint/UselessAssignment`.
- **Dead-code detectors:** Vulture (Python), ts-prune / Knip (TS), `golang.org/x/tools/cmd/deadcode`, staticcheck `U1000` (unused), RuboCop `Lint/UselessAssignment`.

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

## #2 Error handling & resilience

### Key references

- **Michael Nygard — *Release It!* (2nd ed.), Stability Patterns & Antipatterns** — https://pragprog.com/titles/mnee2/release-it-second-edition/ → mine: the canonical catalog — Timeout, Circuit Breaker, Bulkhead, Steady State; integration points are where systems crack, so every remote call needs a timeout + a failure plan.
- **Joe Duffy — "The Error Model" (2016)** `(verify URL)` → mine: separate *bugs* (programmer errors → fail-fast/abandon) from *recoverable conditions* (→ typed, handled errors); design which is which rather than catching everything.
- **The Go Blog — "Error handling and Go"** `(verify URL)` → mine: errors are values; wrap with context; handle at the layer that can act.
- **Alexis King — "Parse, Don't Validate"** `(verify URL)` (cross #10) → mine: validate once at the boundary and encode success in the type so downstream code can't re-fail.

### Tooling rules worth lifting

- **typescript-eslint:** `no-floating-promises` (unhandled async error/rejection), `no-misused-promises`, `await-thenable`, `require-await`, `no-throw-literal` `(verify name)` (throw `Error`, not strings).
- **ESLint:** `no-empty` (empty catch block), `prefer-promise-reject-errors`, `no-ex-assign`.
- **RuboCop Lint/Style:** `Lint/SuppressedException` (empty `rescue`), `Lint/RescueException` (rescuing `Exception` is too broad), `Lint/ShadowedException`, `Style/RescueStandardError`.
- **Python — Pylint/Ruff/Bandit:** Pylint `W0702` (bare `except:`), `W0703`/`broad-exception-caught`; Ruff `E722` (bare except); Bandit `B110` (`try/except/pass`), `B112` (`try/except/continue`).
- **Go:** `errcheck` (unchecked returned errors), `wrapcheck` `(verify)` (wrap errors crossing boundaries), `nilerr` `(verify)` (returning nil where err is non-nil).
- **Sonar / CWE:** CWE-390 "Detection of Error Condition Without Action"; CWE-391 "Unchecked Error Condition".

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

## #3 Concurrency, async & distributed correctness

### Key references

- **Brian Goetz et al. — *Java Concurrency in Practice*** → mine: happens-before, atomicity vs. visibility, safe publication — the vocabulary for reasoning about shared mutable state.
- **Martin Kleppmann — *Designing Data-Intensive Applications*** → mine: replication/consistency models, the perils of distributed time, and "exactly-once" reframed as idempotency.
- **Leslie Lamport — "Time, Clocks, and the Ordering of Events in a Distributed System" (CACM, 1978)** → mine: the *happens-before* partial order; you cannot rely on wall-clock ordering across nodes.
- **Idempotent Consumer pattern (multiple sources, 2024–2026)** — e.g. https://www.milanjovanovic.tech/blog/the-idempotent-consumer-pattern-in-dotnet-and-why-you-need-it → mine: at-least-once delivery + idempotent processing ≈ effective exactly-once; dedupe on a stable business key, stored with the operation, with a TTL.
- **Julik Tarkhanov — frontend race reviews (prior art)** `(verify URL)` → mine: DOM-lifecycle / event-timing races in JS/Stimulus controllers (node gone after `await`).

### Tooling rules worth lifting

- **ESLint / typescript-eslint:** `require-atomic-updates` (read-modify-write across `await`/`yield` → race), `no-await-in-loop` (often accidental sequential where `Promise.all` was meant — correctness + perf), `no-floating-promises`, `no-misused-promises`.
- **Go:** `go test -race` — dynamic data-race detector; **no false positives, but only catches races your tests actually exercise; misses deadlocks, livelocks, and logical races** (https://go.dev/doc/articles/race_detector). `go vet` analyzers: `copylocks` (lock copied by value), `atomic` (misuse of `sync/atomic`), `lostcancel` (context cancel func not called → leak; cross #4).
- **JVM:** SpotBugs multithreaded-correctness detectors (e.g. `IS2_INCONSISTENT_SYNC`); Error Prone `@GuardedBy`.
- **Ruby:** `rubocop-thread_safety` — `ThreadSafety/ClassAndModuleAttributes`, `ThreadSafety/MutableClassInstanceVariable`.
- **C/C++/Go:** ThreadSanitizer (TSan) for data races; **Helgrind** (Valgrind) for lock-order/deadlock.

### Reviewable heuristics (skill-checklist seeds)

- Is shared mutable state touched by multiple threads/tasks without synchronization?
- Any check-then-act / read-modify-write that spans an `await`/`yield` and isn't atomic?
- Could two concurrent requests interleave to break an invariant (lost update, double-spend)?
- Are locks acquired in a consistent global order, with minimal scope (deadlock avoidance)?
- Are all promises awaited/handled, and is concurrency *intentional* (`Promise.all`) vs. accidental sequential?
- For message consumers: is processing **idempotent** and keyed on a stable id (at-least-once-safe)?
- Does the code assume wall-clock ordering across nodes/processes (clock skew)?
- Does it assume **exactly-once delivery** (it doesn't exist — needs dedupe)?
- Are cancellation/timeouts propagated and is cleanup guaranteed on cancel?
- Frontend: after an `await`, does the handler assume the DOM node / component still exists?
- Is there a test that actually exercises the concurrent path (so `-race`/TSan can fire)?

---

## #4 Resource & state management

### Key references

- **David Goldberg — "What Every Computer Scientist Should Know About Floating-Point Arithmetic" (ACM Computing Surveys, 1991)** — https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html → mine: representability/rounding; never compare floats for exact equality; use decimal for money.
- **Noah Sussman — "Falsehoods Programmers Believe About Time"** — https://infiniteundo.com/post/25326999628/falsehoods-programmers-believe-about-time → mine: 34 time assumptions that break (DST, leap, "24h in a day"); a ready-made review checklist for date/time code.
- **Martin Fowler — "Money" pattern (P of EAA)** `(verify URL)` → mine: represent money as integer minor units or a `Money(amount, currency)` type; never float; carry currency.
- **Michael Nygard — *Release It!*, "Steady State"** — https://pragprog.com/titles/mnee2/release-it-second-edition/ → mine: anything that accumulates (logs, temp files, connections, cache) needs cleanup at the same rate it's produced.
- **RAII / ownership (C++, Rust)** → mine: tie resource lifetime to scope; prefer `with`/`using`/`defer`/`ensure` over manual close.

### Tooling rules worth lifting

- **Go:** `bodyclose` (HTTP response body), `sqlclosecheck` (`database/sql`), `rowserrcheck` (`rows.Err()`), `go vet lostcancel` (context), `ineffassign` (state written, never read).
- **Python:** Pylint `R1732` (`consider-using-with` — use a context manager), Ruff `SIM115` (open without context manager), Bandit `B110`.
- **RuboCop:** `Lint/FloatComparison` (exact `==`/`!=` on floats), `Lint/UselessAssignment` (state never read).
- **ESLint:** `no-unused-vars` (dead state); time/money have thin core-rule coverage → heuristic-led.
- **C/C++:** Valgrind/Memcheck, AddressSanitizer + LeakSanitizer (handle/memory leaks).

### Reviewable heuristics (skill-checklist seeds)

- Is every acquired resource (file, socket, connection, lock, cursor) released on **all** paths including errors (`with`/`using`/`defer`/`ensure`)?
- Does anything that grows (logs, cache, queue, temp files, sessions) have a bound / eviction / TTL (steady state)?
- Money/currency stored as integer minor units or a decimal `Money` type — never binary float — and currency carried?
- Float comparisons use a tolerance, not `==`?
- Are numeric overflow/underflow and counter wraparound considered for the actual value ranges?
- Time stored/compared in UTC; timezone/DST handled only at edges; no "always 24h/365d" assumptions?
- Are elapsed durations measured with a **monotonic** clock, not wall-clock (which can jump backward)?
- **Calendar/clock time-bombs (correct at merge, detonates on a future date):** does date/time logic survive the triggers that pass review only because today is an ordinary day — leap year (Feb 29) and leap second, DST spring-forward/fall-back gaps and overlaps, month/year rollover, and the 32-bit `time_t` **epoch-2038** ceiling? Flag hardcoded years/dates, `day + 1`-style arithmetic that ignores real calendars, and "always 365 days / 24 hours" assumptions — latent defects that a clock eventually arms.
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
