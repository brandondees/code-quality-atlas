---
name: auditing-config-and-build-hygiene
description: 'Audits configuration and build/CI health: config schema-validated at
  startup and fail-fast, secrets out of config files, parity across environments,
  reproducible and hermetic builds, pinned toolchains and CI actions, cache correctness,
  flaky or slow pipelines, and unused or drifting config keys. A repo-wide / scheduled
  audit. Use when auditing CI pipelines, Dockerfiles, build scripts, env vars, or
  config files.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 19
    source: docs/research/cluster-5-verification.md#19
    hash: 10e8a2c0840226222cb146a50f937358eb30bedab3c75a57a0f87a63754a9914
  - category: 26
    source: docs/research/cluster-5-verification.md#26
    hash: 332a4105b73167f5473ffd530cded8ae14cab373ebaa46588b191bc68a47d980
---

# auditing-config-and-build-hygiene

*Are config and CI trustworthy? Secrets, env parity, reproducible pinned builds, cache correctness.*

## When to use

Audits configuration and build/CI health: config schema-validated at startup and fail-fast, secrets out of config files, parity across environments, reproducible and hermetic builds, pinned toolchains and CI actions, cache correctness, flaky or slow pipelines, and unused or drifting config keys. A repo-wide / scheduled audit. Use when auditing CI pipelines, Dockerfiles, build scripts, env vars, or config files.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Does CI run the full gate on the diff — lint, format-check, type-check, tests, dep/security scan — and is passing **required** to merge?
- Is the build **reproducible/hermetic** enough to not depend on machine-local state (pinned toolchain, lockfiles, no network in build)?
- Is CI **fast and reliable**? A new slow/flaky job is a defect — parallelized, cached, deterministic?
- Is any **quality gate disabled or soft-failed** (`continue-on-error`, `|| true`, `allow_failure`, a skipped/excluded check) — a deliberate, tracked decision or silent debt? A gate that's off because its tool broke on the current toolchain (language/runtime version, build) is a **gap to close**: fix it or swap in a maintained equivalent — often a younger, less well-known one — not a permanent `continue-on-error` (cross #21).
- Is config **separated from code** and injected via env — no secrets or env-specific values hardcoded/committed?
- Is config **validated at startup** (fail fast, clear message), not lazily at first use?
- Are **safe, secure defaults** used (deny-by-default, TLS on, debug off in prod — cross #14)?
- **Dev/prod parity**: does the change keep environments close (same backing services, same config shape), avoiding env-specific code branches?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
