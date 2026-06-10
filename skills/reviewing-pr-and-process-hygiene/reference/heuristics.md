# Reviewable heuristics — reviewing-pr-and-process-hygiene

## Contents
- From category #24
- From category #22

## From category #24

### Reviewable heuristics (skill-checklist seeds)
- **PR size & focus:** is the PR small and single-purpose (roughly ≤~400 net LOC, one concern)? If it mixes refactor + feature + format churn, suggest splitting — mixed diffs hide bugs.
- **Atomic commits:** does each commit represent one logical change that builds and (ideally) passes tests on its own, enabling clean `revert`/`bisect`? No "fix typo"/"wip"/"address review" noise left in final history.
- **Commit message hygiene:** imperative-mood subject within length limit; body explains *why* and trade-offs, not a restatement of the diff; links the issue/ticket.
- **Conventional type & scope:** is the commit/PR typed correctly (`fix` vs `feat` vs `refactor`) — because it drives versioning and changelog?
- **Breaking-change signaling:** if the change alters a public API/contract/schema/config, is it marked breaking (`!` / `BREAKING CHANGE:`) and is the migration noted? Silent breaking changes are a top review failure.
- **Risk signaling:** does the PR description state blast radius, rollback plan, feature-flag status, and what was/wasn't tested? Risky areas (auth, money, migrations, concurrency) called out for closer review.
- **Ownership routing:** do touched paths have CODEOWNERS, and are the right owners requested? Unowned critical paths flagged.
- **Definition of done:** tests added/updated, docs/changelog updated, lint/type/CI green, no debug/console/commented-out code, no TODOs without tracked issues — all present before merge.
- **Reviewability aids:** PR description, screenshots/recordings for UI, and a self-review pass; large mechanical changes separated from logic changes so reviewers can focus.
- **No drive-by scope creep:** unrelated reformatting/renames bundled into a feature PR — flag to separate so the diff stays reviewable.
- **Agent-native parity:** does a new user-facing action also have a programmatic path (API/CLI/tool), and is it documented for automation — not UI-only?
- **Secrets / artifacts in commits:** no credentials, `.env`, large binaries, or generated files committed (links #14/#19).

---

## From category #22

### Reviewable heuristics (skill-checklist seeds)
- **API surface ↔ docs parity:** does every new/changed public function, endpoint, CLI flag, or config key have a docstring/doc updated in the same diff? Stale signature-vs-doc = drift.
- **Docstring accuracy:** do param names, types, return, and `raises`/`throws` in the docstring match the actual signature *after* this change? (params renamed but docstring not — flag.)
- **Diátaxis coverage:** for a new feature, is there at least the right *mode* of doc — a how-to for a task, reference for an API? Don't accept a tutorial as a substitute for reference.
- **README front-door:** does the README still answer what/why/install/minimal-example/next-steps after this change? New setup step but no README update = onboarding regression.
- **Runnable example:** does the example actually run against the new code (compiles, imports resolve, no removed API)? Prefer doctests/CI-checked snippets.
- **ADR for non-obvious decisions:** does an architecturally significant or surprising choice (new dependency, pattern, boundary, trade-off) have an ADR capturing context/decision/consequences? Code comments are not a substitute for the *why*.
- **Changelog discipline:** does a user-facing change add a CHANGELOG entry in the right category, and is the SemVer impact (patch/minor/major, esp. breaking) correct?
- **Runbook for operability:** for a new operational surface (job, queue, feature flag, alert), is there a runbook saying how to detect, diagnose, and remediate / roll back?
- **Diagrams as code & current:** are diagrams diffable text (Mermaid/PlantUML), and do they still reflect the components after this change, or are they now stale?
- **No orphaned/contradictory docs:** does this change delete or supersede docs it invalidates (removed endpoint still documented; deprecated path still in tutorial)?
- **Comment rot:** are nearby comments/docstrings that the change falsifies updated or removed (not left lying)?
- **Discoverability:** is the new doc linked from an index/nav/README, not just dropped in a folder?

---
