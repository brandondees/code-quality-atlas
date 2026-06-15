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
- **Claims vs. evidence:** is every claim the PR makes checkable against evidence *in the diff*? "Fixes X" / "closes #N" wants a regression test that fails without the change; "faster" / "optimizes" wants a benchmark or profile, not an assertion; "no behavior change" / "pure refactor" wants the diff to be genuinely behavior-preserving (no logic quietly changed alongside the move). An unsupported claim is itself a finding — flag it and name the missing evidence rather than taking the description's word (generalizes the perf lens's profile-demand; cross #1 stated-intent, #15 perf, #17 tests).
- **Ownership routing:** do touched paths have CODEOWNERS, and are the right owners requested? Unowned critical paths flagged.
- **Definition of done:** tests added/updated, docs/changelog updated, lint/type/CI green, no debug/console/commented-out code, no TODOs without tracked issues — all present before merge.
- **Reviewability aids:** PR description, screenshots/recordings for UI, and a self-review pass; large mechanical changes separated from logic changes so reviewers can focus.
- **No drive-by scope creep:** unrelated reformatting/renames bundled into a feature PR — flag to separate so the diff stays reviewable.
- **Structural vs. behavioral separation:** beyond "one purpose," are structure-only changes (renames, moves, extractions, formatting) kept in a *separate* commit/PR from behavior changes — even when both serve one feature — so each is independently reviewable and revertible? (Beck's tidy-first sequencing; the *economics* of when to tidy is #21.)
- **Acceptance-criteria traceability:** if a linked issue/ticket exists, does the PR deliver exactly what it asked — *no less* (every acceptance criterion met) and *no more* (no unrequested scope riding along)? An unlinked PR is a finding only when its scope and purpose aren't self-evident from the description — a self-describing change (typo fix, docs-only, tooling PR) needs no ticket; flag by *intent*, not mere absence of a link, so the signal stays on genuine under/over-delivery. This is **validation** (did we build the right thing), distinct from #1's "code matches the stated intent" and #29's decision soundness; the "no more" half cross-links checking-restraint.
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
- **Agent-instructions drift:** if the repo carries an agent-instructions file (AGENTS.md / CLAUDE.md / equivalent), does this change keep it true — build/test/lint commands still correct, conventions and layout still accurate, subproject files updated where nearest-file-wins applies? Same drift class as README rot, but higher blast radius: agents follow stale instructions literally (cross #24 agent-native parity).

---
