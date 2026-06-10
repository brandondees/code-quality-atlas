# References to mine — hunting-silent-failures

## Contents
- From category #2
- From category #4

## From category #2

### Key references
- **Michael Nygard — *Release It!* (2nd ed.), Stability Patterns & Antipatterns** — https://pragprog.com/titles/mnee2/release-it-second-edition/ → mine: the canonical catalog — Timeout, Circuit Breaker, Bulkhead, Steady State; integration points are where systems crack, so every remote call needs a timeout + a failure plan.
- **Joe Duffy — "The Error Model" (2016)** `(verify URL)` → mine: separate *bugs* (programmer errors → fail-fast/abandon) from *recoverable conditions* (→ typed, handled errors); design which is which rather than catching everything.
- **The Go Blog — "Error handling and Go"** `(verify URL)` → mine: errors are values; wrap with context; handle at the layer that can act.
- **Alexis King — "Parse, Don't Validate"** `(verify URL)` (cross #10) → mine: validate once at the boundary and encode success in the type so downstream code can't re-fail.

## From category #4

### Key references
- **David Goldberg — "What Every Computer Scientist Should Know About Floating-Point Arithmetic" (ACM Computing Surveys, 1991)** — https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html → mine: representability/rounding; never compare floats for exact equality; use decimal for money.
- **Noah Sussman — "Falsehoods Programmers Believe About Time"** — https://infiniteundo.com/post/25326999628/falsehoods-programmers-believe-about-time → mine: 34 time assumptions that break (DST, leap, "24h in a day"); a ready-made review checklist for date/time code.
- **Martin Fowler — "Money" pattern (P of EAA)** `(verify URL)` → mine: represent money as integer minor units or a `Money(amount, currency)` type; never float; carry currency.
- **Michael Nygard — *Release It!*, "Steady State"** — https://pragprog.com/titles/mnee2/release-it-second-edition/ → mine: anything that accumulates (logs, temp files, connections, cache) needs cleanup at the same rate it's produced.
- **RAII / ownership (C++, Rust)** → mine: tie resource lifetime to scope; prefer `with`/`using`/`defer`/`ensure` over manual close.
