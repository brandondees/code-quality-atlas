# References to mine — tracing-correctness-and-invariants

## Contents

- From category #1
- From category #4

## From category #1

### Key references

- **Moseley & Marks — "Out of the Tar Pit" (2006)** — https://curtclifton.net/papers/MoseleyMarks06a.pdf → mine: *state* and *control* are the prime sources of accidental complexity; minimizing mutable state is what makes correctness tractable. (Cross-links #4, #11.)
- **Steve McConnell — *Code Complete* (2nd ed.), "Defensive Programming"** → mine: assertions, barricades, and explicit boundary handling; validate at the barricade, assert internally.
- **Glenford Myers — *The Art of Software Testing* (boundary-value analysis)** `(verify)` → mine: bugs cluster at boundaries; review the 0/1/n−1/n/empty/max transitions explicitly.
- **John Regehr — "A Guide to Undefined Behavior in C and C++"** `(verify URL)` → mine: when behavior is undefined/unspecified the compiler may do anything; relevant to determinism and portability (#26).
- **Tony Hoare — "Null References: The Billion Dollar Mistake"** `(verify URL)` → mine: null is a pervasive correctness hazard; prefer designs where absence is encoded in the type (cross-links #10).

## From category #4

### Key references

- **David Goldberg — "What Every Computer Scientist Should Know About Floating-Point Arithmetic" (ACM Computing Surveys, 1991)** — https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html → mine: representability/rounding; never compare floats for exact equality; use decimal for money.
- **Noah Sussman — "Falsehoods Programmers Believe About Time"** — https://infiniteundo.com/post/25326999628/falsehoods-programmers-believe-about-time → mine: 34 time assumptions that break (DST, leap, "24h in a day"); a ready-made review checklist for date/time code.
- **Martin Fowler — "Money" pattern (P of EAA)** `(verify URL)` → mine: represent money as integer minor units or a `Money(amount, currency)` type; never float; carry currency.
- **Michael Nygard — *Release It!*, "Steady State"** — https://pragprog.com/titles/mnee2/release-it-second-edition/ → mine: anything that accumulates (logs, temp files, connections, cache) needs cleanup at the same rate it's produced.
- **RAII / ownership (C++, Rust)** → mine: tie resource lifetime to scope; prefer `with`/`using`/`defer`/`ensure` over manual close.
