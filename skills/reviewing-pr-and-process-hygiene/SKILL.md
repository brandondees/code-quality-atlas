---
name: reviewing-pr-and-process-hygiene
description: 'Reviews the PR itself rather than just the code: size and single purpose
  (~<=400 net LOC), atomic commits with imperative why-bearing messages, correct conventional
  type and breaking-change signaling, risk and rollback notes, docs/changelog updated
  with the API surface, no drive-by scope creep, no committed secrets or debug leftovers.
  Use when reviewing a pull request''s structure, commits, description, changelog,
  or readiness to merge.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 24
    source: docs/research/cluster-6-evolution.md#24
    hash: ada06f4719199568f3ff41c1080b068a218dfcfc3b7604d8b7bc589f3c4fb09f
  - category: 22
    source: docs/research/cluster-6-evolution.md#22
    hash: 688743a28f3d05b13c5aa6762e6941820eb10a8825850180eaf8c3277139142d
---

# reviewing-pr-and-process-hygiene

*Is the PR itself reviewable? Size, atomic commits, description, scope creep, changelog.*

## When to use

Reviews the PR itself rather than just the code: size and single purpose (~<=400 net LOC), atomic commits with imperative why-bearing messages, correct conventional type and breaking-change signaling, risk and rollback notes, docs/changelog updated with the API surface, no drive-by scope creep, no committed secrets or debug leftovers. Use when reviewing a pull request's structure, commits, description, changelog, or readiness to merge.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **PR size & focus:** is the PR small and single-purpose (roughly ≤~400 net LOC, one concern)? If it mixes refactor + feature + format churn, suggest splitting — mixed diffs hide bugs.
- **Atomic commits:** does each commit represent one logical change that builds and (ideally) passes tests on its own, enabling clean `revert`/`bisect`? No "fix typo"/"wip"/"address review" noise left in final history.
- **Commit message hygiene:** imperative-mood subject within length limit; body explains *why* and trade-offs, not a restatement of the diff; links the issue/ticket.
- **Conventional type & scope:** is the commit/PR typed correctly (`fix` vs `feat` vs `refactor`) — because it drives versioning and changelog?
- **Breaking-change signaling:** if the change alters a public API/contract/schema/config, is it marked breaking (`!` / `BREAKING CHANGE:`) and is the migration noted? Silent breaking changes are a top review failure.
- **Risk signaling:** does the PR description state blast radius, rollback plan, feature-flag status, and what was/wasn't tested? Risky areas (auth, money, migrations, concurrency) called out for closer review.
- **API surface ↔ docs parity:** does every new/changed public function, endpoint, CLI flag, or config key have a docstring/doc updated in the same diff? Stale signature-vs-doc = drift.
- **Docstring accuracy:** do param names, types, return, and `raises`/`throws` in the docstring match the actual signature *after* this change? (params renamed but docstring not — flag.)

**Shared categories:** category #22 checks are shared with **auditing-documentation-health** (their primary owner). When both lenses run on the same change, report each shared finding once, under the primary owner.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
