# Reviewable heuristics — reviewing-test-quality

## Contents
- From category #17

## From category #17

### Reviewable heuristics (skill-checklist seeds)
- Do new/changed tests assert **observable behavior** (inputs→outputs, side effects), not internal calls/private state (refactor-resistant)?
- Is coverage **meaningful** on the new code — branches and edge cases, not just lines executed? Don't chase a % with assertion-free tests.
- Bug fix → is there a **regression test** that fails before the fix and passes after?
- Are tests **isolated and deterministic** — no shared mutable state, order dependence, or real clock/network/unseeded random (flaky risk)?
- Is the test at the **right level** (pyramid/trophy) — logic in fast unit/integration, e2e reserved for critical journeys?
- **Over-mocking smell**: do mocks assert on implementation calls so a refactor breaks tests without behavior changing? Prefer real collaborators / fakes (cross #11).
- Are **edge/boundary** cases covered (empty, null, max, error paths) — where the bugs live (cross #1)?
- Would the suite **catch a real bug**, not just execute lines? Apply mutation intuition — for a pure, deterministic, fast-to-test unit, prefer actually running a mutation tool (cheap, high-signal) over eyeballing it; otherwise high coverage masks weak assertions.
- Any disabled/focused/skipped tests (`.only`, `xit`, `@Disabled`) sneaking in?
- For nondeterministic/concurrent code, is the invariant property-tested and the concurrent path exercised (cross #3)?
- Is each test readable — clear arrange/act/assert, one behavior per test, name reads as a spec?

---
