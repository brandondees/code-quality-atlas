# Reviewable heuristics — reviewing-test-quality

## Contents

- From category #17

## From category #17

### Reviewable heuristics (skill-checklist seeds)

- Do new/changed tests assert **observable behavior** (inputs→outputs, side effects), not internal calls/private state (refactor-resistant)?
- Is coverage **meaningful** on the new code — branches and edge cases, not just lines executed? Don't chase a % with assertion-free or **tautological** tests (asserting the mock, restating the framework, or a **Sensitive Equality** check on a whole serialized blob that breaks on unrelated change), and don't keep tests that pin no real requirement (Farley *necessary*).
- Bug fix → is there a **regression test** that fails before the fix and passes after?
- Are tests **isolated and deterministic** — no shared mutable state, order dependence, or real clock/network/unseeded random (flaky risk)?
- Is the test at the **right level** (pyramid/trophy) — logic in fast unit/integration, e2e reserved for critical journeys?
- **Over-mocking smell**: do mocks assert on implementation calls so a refactor breaks tests without behavior changing? Reach for the least-powerful **test double** — prefer a real collaborator, fake, or stub, and reserve a behavior-verifying mock for true outgoing commands (don't mock queries or value objects) (cross #11).
- Are **edge/boundary** cases covered (empty, null, max, error paths) — where the bugs live? Walk the **CORRECT** dimensions (Conformance, Ordering, Range, Reference, Existence, Cardinality, Time) to surface the missing edge (cross #1).
- Would the suite **catch a real bug**, not just execute lines? Apply mutation intuition — for a pure, deterministic, fast-to-test unit, prefer actually running a mutation tool (cheap, high-signal) over eyeballing it; otherwise high coverage masks weak assertions.
- Any disabled/focused/skipped tests (`.only`, `xit`, `@Disabled`) sneaking in?
- For nondeterministic/concurrent code, is the invariant property-tested and the concurrent path exercised (cross #3)?
- Is each test readable — clear arrange/act/assert, one behavior per test, name reads as a spec?
- Does each test have a **single reason to fail** — assertions that localize the cause when it breaks? Flag **Assertion Roulette** (a pile of asserts with no messages, so a failure doesn't say which expectation broke) and tests that bundle several unrelated behaviors (Beck *specific*; Farley *atomic*).
- Is the test **self-contained**, or a **Mystery Guest** — does it lean on a hidden external resource (file, DB, network) or a fixture defined far from the test, obscuring what's exercised and risking nondeterminism (cross isolation)?
- Is the test **DAMP** (readable at a glance) rather than over-DRY'd — does **Conditional Test Logic** (branches/loops in the test) or deep helper/fixture indirection hide what actually runs? In tests, readability beats deduplication (Beck *writable*).
- Beyond the happy path, does the suite use **inverse/round-trip** checks (encode→decode), a **cross-check** against an independent oracle, and **forced error conditions** (Right-BICEP) — not a single positive assertion?

---
