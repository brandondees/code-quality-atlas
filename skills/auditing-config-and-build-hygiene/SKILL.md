---
name: auditing-config-and-build-hygiene
description: 'Audits configuration and build/CI health: config schema-validated at
  startup and fail-fast, secrets out of config files, parity across environments,
  reproducible and hermetic builds, pinned toolchains and CI actions, cache correctness,
  flaky or slow pipelines, and unused or drifting config keys. A repo-wide / scheduled
  audit. Use when auditing CI pipelines, Dockerfiles, build scripts, env vars, or
  config files.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 19
    source: docs/research/cluster-5-verification.md#19
    hash: 6beb4e0197f9d737af372f8b572900ed9c6ca3fdb9a5534d77704009afd0bed5
  - category: 26
    source: docs/research/cluster-5-verification.md#26
    hash: 42e2be56b6d2859933b1a540245ad825af444334b08d1524956437dd6afc3f4a
---

# auditing-config-and-build-hygiene

*Are config and CI trustworthy? Secrets, env parity, reproducible pinned builds, cache correctness.*

## When to use

Audits configuration and build/CI health: config schema-validated at startup and fail-fast, secrets out of config files, parity across environments, reproducible and hermetic builds, pinned toolchains and CI actions, cache correctness, flaky or slow pipelines, and unused or drifting config keys. A repo-wide / scheduled audit. Use when auditing CI pipelines, Dockerfiles, build scripts, env vars, or config files.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Portability**: any hardcoded paths, OS/arch assumptions, locale/encoding/timezone assumptions, or non-portable shell?
- Does CI run the full gate on the diff — lint, format-check, type-check, tests, dep/security scan — and is passing **required** to merge?
- Beyond that required floor, are the **deterministic quality signals** this stack benefits from actually present — **coverage reporting** (with a branch/diff threshold, not a vanity global %), a **performance benchmark** on the hot paths, and **complexity/maintainability scoring**? Their absence is a **preference-tunable advisory** (`route: implementer`), not a floor-tier block: surface "no coverage gate / no perf benchmark / no complexity budget" as a gap worth wiring up, and let a repo that deliberately skips it suppress the note (cross #17, #21).
- Is the build **reproducible/hermetic** enough to not depend on machine-local state (pinned toolchain, lockfiles, no network in build)?
- Is CI **fast and reliable**? A new slow/flaky job is a defect — parallelized, cached, deterministic?
- Is config **separated from code** and injected via env — no secrets or env-specific values hardcoded/committed?
- Is config **validated at startup** (fail fast, clear message), not lazily at first use?
- Are **safe, secure defaults** used (deny-by-default, TLS on, debug off in prod — cross #14)?
- **Dev/prod parity**: does the change keep environments close (same backing services, same config shape), avoiding env-specific code branches?

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
