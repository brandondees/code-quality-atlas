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
    hash: a23983c37d2f69b081917fea51fe2aaa23f416b5590fb72c24da04289cc62733
---

# reviewing-test-quality

## When to use

Reviews tests for quality: behavior vs implementation coupling, over-mocking, meaningful branch/edge coverage on the diff, regression tests for bug fixes, isolation and determinism (no shared state, real clocks, or unseeded randomness), right level per the pyramid/trophy, and disabled/focused tests sneaking in. Use when reviewing test files, test coverage, mocks, fixtures, flaky tests, or a bug fix's tests.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Do new/changed tests assert **observable behavior** (inputs→outputs, side effects), not internal calls/private state (refactor-resistant)?
- Is coverage **meaningful** on the new code — branches and edge cases, not just lines executed? Don't chase a % with assertion-free tests.
- Bug fix → is there a **regression test** that fails before the fix and passes after?
- Are tests **isolated and deterministic** — no shared mutable state, order dependence, or real clock/network/unseeded random (flaky risk)?
- Is the test at the **right level** (pyramid/trophy) — logic in fast unit/integration, e2e reserved for critical journeys?
- **Over-mocking smell**: do mocks assert on implementation calls so a refactor breaks tests without behavior changing? Prefer real collaborators / fakes (cross #11).
- Are **edge/boundary** cases covered (empty, null, max, error paths) — where the bugs live (cross #1)?
- Would the suite **catch a real bug**, not just execute lines? Apply mutation intuition — for a pure, deterministic, fast-to-test unit, prefer actually running a mutation tool (cheap, high-signal) over eyeballing it; otherwise high coverage masks weak assertions.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
