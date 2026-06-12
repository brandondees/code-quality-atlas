# Tool rules to triage — reviewing-test-quality

## Contents
- From category #17

## From category #17

### Tooling rules worth lifting
- **Coverage:** coverage.py (Python), Istanbul/nyc & V8 (JS), JaCoCo (Java), SimpleCov (Ruby), `go test -cover`. Lift: track **branch** coverage and the coverage **delta on the diff**, not a global %.
- **Mutation:** PIT/pitest (Java), **Stryker** (JS/TS, C#, Scala — https://stryker-mutator.io/), mutmut & cosmic-ray (Python), Mutant (Ruby), **cargo-mutants** (Rust — https://mutants.rs/), gremlins (Go). For a pure crate/module with fast deterministic tests, a mutation run is cheap, and the surviving-mutant list makes a good CI gate.
- **Property-based:** Hypothesis (Python), fast-check (JS/TS), jqwik (Java), PropEr/QuickCheck.
- **Flaky control:** `pytest-randomly` (random order), `pytest-rerunfailures`, Jest `--detectOpenHandles`, Gradle/Maven retry, flaky trackers (BuildPulse, Datadog Test Optimization).
- **Test linters:** `eslint-plugin-jest` (`no-disabled-tests`, `no-focused-tests`, `expect-expect`, `no-conditional-expect`), `rubocop-rspec`, `flake8-pytest-style`.
