# Examples — reviewing-test-quality

A test diff often contains several independent problems. Check every line against
the checklist and report each distinct issue as its own numbered finding.

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
