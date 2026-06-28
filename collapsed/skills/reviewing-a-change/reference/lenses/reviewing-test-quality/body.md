# reviewing-test-quality

Do the tests prove anything? Behavior coupling, over-mocking, edge coverage, determinism.

## When to use

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Checklist

The full review checklist, grouped by the research category each check draws from:

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
- Is the test **readable and descriptive** rather than over-DRY'd — does **Conditional Test Logic** (branches/loops in the test) or deep helper/fixture indirection hide what actually runs? In tests, readability beats deduplication (Beck *writable*).
- Beyond the happy path, does the suite use **inverse/round-trip** checks (encode→decode), a **cross-check** against an independent oracle, and **forced error conditions** (Right-BICEP) — not a single positive assertion?

---

## Examples

A test diff often contains several independent problems. Check every line against
the checklist and report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

## Bad → finding

**Input (diff):**

```js
test("processOrder", () => {
  const validator = { check: jest.fn().mockReturnValue(true) };
  const repo = { save: jest.fn() };
  const mailer = { send: jest.fn() };
  processOrder(order, validator, repo, mailer);
  expect(validator.check).toHaveBeenCalledTimes(1);
  expect(repo.save).toHaveBeenCalledBefore(mailer.send);
});
```

**Expected finding:**

1. **Over-mocked, implementation-coupled test:** every collaborator is a mock and
   the assertions only verify which internals were called and in what order — any
   refactor breaks it while a real bug (wrong total, wrong recipient) passes.
   Assert observable behavior instead: the saved order's state and the email's
   recipient/content, using real or fake collaborators.
2. **No behavior assertion at all:** nothing checks an output or side effect a
   user/caller could observe.

## Bad → finding

**Input (diff):**

```python
processed = []

@pytest.mark.skip(reason="flaky")
def test_expiry():
    assert is_expired(make_token(ttl=1), now=datetime.now())

def test_batch():
    processed.append(process(next_item()))     # appends to module-level list
    assert len(processed) == 1                 # passes only if run first
```

**Expected finding:**

1. **Shared mutable state:** `test_batch` appends to a module-level list, so it
   passes only when run first/alone (order dependence) — isolate with a fixture.
2. **Real clock:** `test_expiry` uses `datetime.now()` — inject/freeze time.
3. **Skipped-as-flaky:** a skipped flaky test is an untested code path; fix the
   nondeterminism (the clock) that made it flaky instead of parking it.

## Good → no finding

**Input (diff):**

```python
def test_refund_rejected_after_30_days():
    # regression test for #842
    order = make_order(paid_at=fixed_now - timedelta(days=31))
    result = request_refund(order, now=fixed_now)
    assert result.rejected
    assert result.reason == RefundReason.WINDOW_EXPIRED

def test_refund_allowed_on_day_30():
    order = make_order(paid_at=fixed_now - timedelta(days=30))
    assert request_refund(order, now=fixed_now).approved
```

**Expected finding:** None — behavior-level assertions, injected clock
(deterministic), both sides of the boundary covered, regression test linked to its
bug. Report "No findings". Do NOT demand mocks for collaborators that are already
fast and deterministic, and do NOT ask for more tests when the changed behavior's
branches and boundary are covered — coverage padding is not a finding.

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
