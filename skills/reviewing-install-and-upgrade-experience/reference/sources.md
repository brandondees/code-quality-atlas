# References to mine — reviewing-install-and-upgrade-experience

## Contents

- From category #33

## From category #33

### Key references

- **Twelve-Factor App — III. Config / X. Dev-prod parity** — https://12factor.net/config
  → mine: config strictly separated from code and injected via the environment; minimize divergence between an adopter's environment and the developer's. A new *required*, environment-specific setting with no safe default is adoption friction, not a feature.
- **Semantic Versioning 2.0.0** — https://semver.org
  → mine: the machine-readable promise that lets a consumer — and Renovate/Dependabot, and an agent — tell a safe patch/minor from a breaking major. A consumer-facing break shipped under a non-major bump silently breaks every *automated* upgrade; SemVer correctness is what makes upgrades delegable.
- **Keep a Changelog** — https://keepachangelog.com
  → mine: newest-first, categorized (Added/Changed/Deprecated/Removed/Fixed/Security) changelog with an `Unreleased` section; the migration/"Upgrading" notes are what an adopter (or their agent) actually reads to move versions. A changelog entry is necessary but not sufficient — a *rename* needs an upgrade instruction, not just a line (cross #22).
- **Rich Hickey — "Spec-ulation" (2016)** `(verify)`
  → mine: "don't break, only accrete" — relax requirements / strengthen promises, never the reverse. Renaming or removing a consumer-facing name is a breaking change even when the code still runs. The discipline behind upgrades that don't require consumer rework.
- **Codemod & migration-tooling practice** — jscodeshift, OpenRewrite, Rector, Rust `cargo fix --edition`, Go `go fix` / API migration guides, the **Django deprecation policy + system checks**, React codemods `(verify)`
  → mine: ship the upgrade as *runnable tooling*, not just prose. An automated migration is what turns a version bump into a mechanical step a consumer or a code agent can run and verify, instead of a hand-translation of the diff.
- **RFC 8594 (Sunset) / RFC 8631 (deprecation links) + library deprecation warnings** — https://www.rfc-editor.org/rfc/rfc8594
  → mine: deprecation is a dated, signposted activity that names the replacement *at the point of use* (warning, header, `@deprecated`), giving consumers a migration window instead of a surprise removal discovered as a broken build (cross #29).
- **Developer-experience / "time to first success" writing (Stripe, Heroku, Twilio "time to hello world")** `(verify)`
  → mine: the highest-leverage adoption metric is steps-to-first-working-result; every required step before that is friction that loses adopters. The README quickstart that *actually runs* is the artifact to protect (cross #22 runnable example).
- **Configuration-as-schema / fail-fast validation (JSON Schema, pydantic-settings, envalid, viper, CUE)** `(verify)`
  → mine: validate config at startup against a declared schema and fail with a message that names the offending key *and the fix* — not a deep stack trace, and not a silent wrong default that surfaces three steps later (cross #26).
