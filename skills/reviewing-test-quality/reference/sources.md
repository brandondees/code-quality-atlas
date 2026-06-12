# References to mine — reviewing-test-quality

## Contents
- From category #17

## From category #17

### Key references
- **Mike Cohn — *Succeeding with Agile* (the Test Pyramid)** → mine: more fast unit tests, fewer slow e2e; the cost/speed/stability gradient by test level.
- **Kent C. Dodds — "The Testing Trophy" (2018)**, building on **Guillermo Rauch — "Write tests. Not too many. Mostly integration."** → mine: integration tests give the best ROI — they test units collaborating without e2e fragility. The modern counter to a unit-heavy pyramid; use it to resist *both* over-mocked unit tests and over-heavy e2e.
- **Michael Feathers — *Working Effectively with Legacy Code*** → mine: "legacy code is code without tests"; seams, characterization tests, and **testability as a design property** (if it's hard to test, the design is the problem).
- **Claessen & Hughes — "QuickCheck: Lightweight Tools for Random Testing of Haskell Programs" (ICFP 2000)** → mine: **property-based testing** — assert invariants over generated inputs; the trio of *generators + properties + shrinking*. Ported as Hypothesis/fast-check/jqwik.
- **Mutation testing (PIT, Stryker, mutmut, cargo-mutants)** → mine: a **coverage-quality** signal — does the suite actually *catch injected bugs*? High line coverage + low mutation score = weak assertions. Cheapest and highest-signal on **pure, deterministic, fast-to-test** units (no I/O), where a run is minutes and surviving mutants are an exact list of unasserted behavior — there, prefer running the tool over only intuiting it.
- **"Test behavior, not implementation" (Dodds; Kent Beck)** → mine: tests coupled to internals break on refactor; assert observable behavior so tests survive refactoring (cross #21).
- **Martin Fowler — "Eradicating Non-Determinism in Tests"** `(verify URL)` → mine: flaky tests destroy trust; quarantine, then fix the root cause (time, order, concurrency, shared state).
