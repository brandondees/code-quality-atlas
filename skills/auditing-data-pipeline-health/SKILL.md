---
name: auditing-data-pipeline-health
description: 'Audits the analytics/data plane''s standing condition on a schedule
  rather than reviewing a change: declared contracts and published schemas that nothing
  tests the dataset against, repo-vs-registry divergence, test and expectation coverage
  across the model graph ranked by downstream fan-out, freshness expectations that
  are absent, lapsed, or too wide to fire, permanently-warning data tests, expired
  deprecation windows with live readers, orphaned models with no declared consumer,
  ungated registry subjects, soft-failed contract checks, and hardcoded table names
  that hide lineage. Reads the repo, not the warehouse — reports drift it cannot observe
  as declared-but-unverified and names the plane it could not reach. A repo-wide /
  scheduled audit; the scheduled companion to reviewing-data-transformations-and-contracts.
  Use when auditing data contracts, dbt/SQLMesh project health, data-test coverage,
  or pipeline drift. Skip when the repo has no SQL models, pipelines, data tests,
  or published data schemas.'
provenance:
  taxonomy_version: v0.13
  built_from:
  - category: 41
    source: docs/research/cluster-5-verification.md#41
    hash: 23a9cea6acfd120b6583824481aace23ec055f2a9a8264150929e7a9ead20771
---

# auditing-data-pipeline-health

*Has the data plane drifted since anyone looked? Contract currency, test coverage by fan-out, lapsed freshness, expired deprecations, hidden lineage.*

## When to use

Audits the analytics/data plane's standing condition on a schedule rather than reviewing a change: declared contracts and published schemas that nothing tests the dataset against, repo-vs-registry divergence, test and expectation coverage across the model graph ranked by downstream fan-out, freshness expectations that are absent, lapsed, or too wide to fire, permanently-warning data tests, expired deprecation windows with live readers, orphaned models with no declared consumer, ungated registry subjects, soft-failed contract checks, and hardcoded table names that hide lineage. Reads the repo, not the warehouse — reports drift it cannot observe as declared-but-unverified and names the plane it could not reach. A repo-wide / scheduled audit; the scheduled companion to reviewing-data-transformations-and-contracts. Use when auditing data contracts, dbt/SQLMesh project health, data-test coverage, or pipeline drift. Skip when the repo has no SQL models, pipelines, data tests, or published data schemas.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If this lens applies and what you reviewed holds up — the code, the design, or the repository's current state — reply "No findings" and stop. If what you were given is outside this lens's scope entirely, say so in one line instead, starting with the words "Not applicable:" followed by what's missing — never the healthy-scan sentence, which means a check ran and found nothing, not that nothing here applied. Either way, do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Declared contract vs. the plane it describes.** For each declared contract, published schema, or `accepted_values`/type declaration, is anything actually testing the dataset against it — and does the most recent available evidence (test results, contract-test run, registry state) show it still holding? Report a violation only from evidence you can point at; where the repo declares a constraint but holds no artifact showing it was ever checked, the finding is **"declared but unverified — no enforcement point in this repo,"** which is a real defect and a different one from "the data has drifted." Never assert observed drift you cannot observe.
- **Test and expectation coverage across the model graph, ranked by fan-out.** Walk the graph rather than the file list: which models have no tests at all, no uniqueness test pinning their declared grain, or only `not_null` on a key? Rank by **downstream dependents plus declared exposures** — an untested model with thirty descendants is a systemic risk; an untested leaf is a nit. Report the ranked head and the trend, not every row.
- **Freshness and volume expectations: absent, lapsed, or decorative.** Which sources carry no `freshness` block at all; which thresholds are so wide they could not fire before a human noticed anyway; which have been in `warn` continuously long enough that nobody reads them. A monitor that cannot fail is not coverage (cross #2 for the fail-loud verdict, #30 for the general alert-fatigue pattern).
- **Expired deprecation windows with live readers.** A model or schema version marked deprecated, superseded, or past its `deprecation_date` that still has `ref()`s, registered subscribers, or exposures pointing at it. The window closed and nobody drained it — the removal is now permanently blocked or silently about to break someone.
- **Ungated subjects and soft-failed contract checks.** Registry subjects on `NONE` (or on a default nobody chose), compatibility checks present in CI but `continue-on-error` or not required, `datacontract test` wired but never run. The general pattern is #30's; the data-plane instance is this lens's, and it is the standing condition that lets every future breaking change through.
- **Repo-vs-registry divergence.** A `.avsc`/`.proto`/contract file in the repo with no corresponding registered version, or a registered version with no counterpart in the repo. Either way the source of truth is ambiguous, and reviewers have been reviewing the wrong artifact.
- **Orphaned and dead models.** Models nothing `ref()`s, with no exposure and no external consumer declared — dead transformations still consuming compute and misleading readers. Distinguish genuinely dead from **consumed-but-undeclared**: a model a BI tool reads without an exposure looks identical from inside the repo, so the finding is "no declared consumer" and the fix may be an exposure, not a deletion.
- **Lineage the graph cannot see.** Hardcoded table names instead of `ref()`/`source()`, cross-project references outside the graph, and models built by scripts outside the framework. Count and locate them, and state the consequence plainly: every blast-radius and impact answer this repo can give is under-reported by exactly these edges.
- **Permanently-failing or permanently-warning data tests.** A `severity: warn` test that has failed continuously is a suppression with extra steps; a test disabled "temporarily" with no dated reason is the data plane's `# noqa`. Report the accumulation and its trend (cross #30).
- **Unowned contracts and stale ownership.** A published dataset or contract with no named owner, or one naming a team, rota, or CODEOWNERS entry that no longer resolves. This is the escalation trigger, not a verdict: **detect and escalate to a data owner (G8)** — who should own it, and whether a drifted contract gets re-negotiated or the producer corrected, are not this lens's calls.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI catches it automatically from then on. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
