# Tool rules to triage — reviewing-module-design

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents

- From category #9
- From category #10

## From category #9

### Tooling rules worth lifting

- **dependency-cruiser** (JS/TS) — `no-circular`, `no-orphans`, custom `forbidden` rules for cross-module reach-ins. (https://github.com/sverweij/dependency-cruiser)
- **madge** (JS/TS) — `--circular` flags dependency cycles; graphs fan-in/out.
- **eslint-plugin-import `import/no-cycle`**, **eslint-plugin-boundaries** — module-boundary enforcement in lint.
- **import-linter** (Python) — contract types `forbidden`, `independence`, `layers` enforce module boundaries. (https://import-linter.readthedocs.io/)
- **ArchUnit** (Java) / **NetArchTest** (.NET) — assert "no cycles", "X may not depend on Y" as unit tests. (https://www.archunit.org/)
- **Reek** (Ruby) — `FeatureEnvy` (method uses another object more than `self` → move it), `DataClump` (same param group recurs → extract a type), `UtilityFunction` (no `self` refs → misplaced), `TooManyInstanceVariables`. (https://github.com/troessner/reek)
- **PMD** (Java) — `CouplingBetweenObjects`, `ExcessiveImports`, `LawOfDemeter`.

## From category #10

### Tooling rules worth lifting

- **TypeScript** `strict` (`strictNullChecks`, `noImplicitAny`); **typescript-eslint** `strict-boolean-expressions`, `no-unnecessary-condition`, `switch-exhaustiveness-check` (compiler-checked exhaustive unions), `no-non-null-assertion` (no `!` papering over null).
- **Python** — `mypy --strict` / **pyright** strict; **Pydantic** (runtime parse-into-type at boundaries); `typing.NewType`, `Literal`, `Enum`, frozen dataclasses for value objects.
- **Rust** — newtype pattern, `#[non_exhaustive]`, exhaustive `match`, clippy.
- *Note:* "primitive obsession" itself is weakly tooled → largely a judgment heuristic (map-gaps G5).
