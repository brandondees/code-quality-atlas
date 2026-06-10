# Tool rules to triage — auditing-architecture-conformance

## Contents
- From category #12

## From category #12

### Tooling rules worth lifting
- **dependency-cruiser, madge `--circular`** (JS/TS), **import-linter** layers/independence contracts (Python), **ArchUnit** (Java), **NetArchTest** (.NET), **pydeps**, **jdepend** — enforce layering, detect cycles, god modules, fan-in/out.
- **`@nx/enforce-module-boundaries`** (Nx) / Turborepo boundaries — monorepo module-boundary tags.
- **SonarQube** — cyclic-dependency / package-tangle measures.
