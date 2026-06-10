---
name: reviewing-test-quality
description: 'Reviews tests for quality: behavior vs implementation coupling, over-mocking,
  meaningful branch/edge coverage on the diff, regression tests for bug fixes, isolation
  and determinism (no shared state, real clocks, or unseeded randomness), right level
  per the pyramid/trophy, and disabled/focused tests sneaking in. Use when reviewing
  test files, test coverage, mocks, fixtures, flaky tests, or a bug fix''s tests.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 17
    source: docs/research/cluster-5-verification.md#17
    hash: 52dd483c959a98d8c492566859693f11a6d3a025898824612d13d723d3f4d1c0
---

# reviewing-test-quality

## When to use

Reviews tests for quality: behavior vs implementation coupling, over-mocking, meaningful branch/edge coverage on the diff, regression tests for bug fixes, isolation and determinism (no shared state, real clocks, or unseeded randomness), right level per the pyramid/trophy, and disabled/focused tests sneaking in. Use when reviewing test files, test coverage, mocks, fixtures, flaky tests, or a bug fix's tests.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
