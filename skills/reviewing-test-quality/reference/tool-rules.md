# Tool rules to triage — reviewing-test-quality

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents
- From category #17

## From category #17

### Tooling rules worth lifting
- **Coverage:** coverage.py (Python), Istanbul/nyc & V8 (JS), JaCoCo (Java), SimpleCov (Ruby), `go test -cover`. Lift: track **branch** coverage and the coverage **delta on the diff**, not a global %.
- **Mutation:** PIT/pitest (Java), **Stryker** (JS/TS, C#, Scala — https://stryker-mutator.io/), mutmut & cosmic-ray (Python), Mutant (Ruby), **cargo-mutants** (Rust — https://mutants.rs/), gremlins (Go — https://gremlins.dev/). For a pure crate/module with fast deterministic tests, a mutation run is cheap, and the surviving-mutant list makes a good CI gate.
- **Property-based:** Hypothesis (Python), fast-check (JS/TS), jqwik (Java), PropEr/QuickCheck.
- **Flaky control:** `pytest-randomly` (random order), `pytest-rerunfailures`, Jest `--detectOpenHandles`, Gradle/Maven retry, flaky trackers (BuildPulse, Datadog Test Optimization).
- **Test linters:** `eslint-plugin-jest` (`no-disabled-tests`, `no-focused-tests`, `expect-expect`, `no-conditional-expect`), `rubocop-rspec`, `flake8-pytest-style`.
