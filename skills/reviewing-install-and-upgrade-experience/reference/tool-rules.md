# Tool rules to triage — reviewing-install-and-upgrade-experience

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents

- From category #33

## From category #33

### Tooling rules worth lifting

- **Fresh-install / quickstart CI job** — a job that starts from a clean checkout or an empty environment and runs *only* the documented install + quickstart steps (`npx`, `pipx run`, `docker run`, a scratch container), so an undocumented prerequisite or a rotted quickstart fails CI rather than the adopter. `(verify)`
- **Config-schema validators** — `ajv` / JSON Schema, **pydantic-settings** / **envalid** / **viper** + struct validation, **confuse** (Python), **`cue vet`** — declare and validate config, surfacing unknown or missing keys with actionable messages at startup. `(verify)`
- **API/surface break detectors** — **`cargo-semver-checks`** (Rust), **`@microsoft/api-extractor`** + **`@arethetypeswrong/cli`** (TS), **`griffe check`** (Python), **`gorelease`** (Go), **`japicmp`/`revapi`** (Java) — catch a consumer-facing break and assert the SemVer bump matches it. `(verify)`
- **Migration / codemod runners** — **jscodeshift**, **OpenRewrite**, **Rector** (PHP), **`cargo fix --edition`**, **`go fix`**, **`pyupgrade`/`ruff --fix`** — distribute the upgrade as a command the consumer (or an agent) runs, not a prose diff to re-apply by hand. `(verify)`
- **Release + upgrade-notes automation** — **release-please** / **changesets** / **git-cliff** with a `BREAKING`/`Migration` section keyed off Conventional Commits, so the changelog and upgrade notes can't lag the release. `(verify)` (cross #22, #24)
- **Deprecation surfacing** — runtime deprecation warnings (`util.deprecate`, Python `DeprecationWarning`, `@deprecated`), `Deprecation`/`Sunset` HTTP headers, OpenAPI `deprecated: true` — make the deprecation visible at the point of use with the replacement named. `(verify)` (cross #29)
- **Reproducible install** — lockfiles (`package-lock.json`, `poetry.lock`, `Cargo.lock`, `uv.lock`) + pinned base images / toolchains, so two adopters and CI install the same bytes. `(verify)` (cross #18, #19)
- **Consumer-side upgrade automation** — Renovate / Dependabot with automerge of clean (passing, non-major) upgrades — the workflow a well-versioned, well-tested project *enables* for its own consumers; review whether this change keeps the project friendly to it. `(verify)`
