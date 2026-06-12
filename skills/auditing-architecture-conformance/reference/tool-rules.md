# Tool rules to triage — auditing-architecture-conformance

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents
- From category #12

## From category #12

### Tooling rules worth lifting
- **dependency-cruiser, madge `--circular`** (JS/TS), **import-linter** layers/independence contracts (Python), **ArchUnit** (Java), **NetArchTest** (.NET), **pydeps**, **jdepend** — enforce layering, detect cycles, god modules, fan-in/out.
- **`@nx/enforce-module-boundaries`** (Nx) / Turborepo boundaries — monorepo module-boundary tags.
- **SonarQube** — cyclic-dependency / package-tangle measures.
