---
name: reviewing-data-transformations-and-contracts
description: 'Reviews the analytics/data plane — SQL/dbt transformations, data tests,
  and event or published-table schemas — for transformation correctness, data-test
  adequacy, and producer-to-consumer data-contract safety: violated grain and fan-out
  joins that silently inflate aggregates, SQL NULL traps (NOT IN with NULLs, a LEFT
  JOIN degraded by a WHERE predicate), non-idempotent incremental runs and dropped
  late rows, silent type coercion (money as float, timezone-naive truncation), missing
  data tests, pipelines that publish an empty table instead of failing, and schema
  changes that break downstream readers with no compatibility gate, version bump,
  or named consumers. Use when reviewing a SQL or dbt model, an ETL/ELT transformation,
  an event or analytics schema, or a data test. Defers store-migration mechanics to
  #20, the service API contract to #13, PII to #27; escalates warehouse governance
  to a data owner. Skip when the change touches no SQL, pipeline, data test, or consumed
  schema.'
provenance:
  taxonomy_version: v0.14
  built_from:
  - category: 40
    source: docs/research/cluster-5-verification.md#40
    hash: 1f2a73c443081a6d012712e53c99dfe57285f16af1631aecf396b51d89ce8c55
---

# reviewing-data-transformations-and-contracts

*Is the data plane correct and its contract safe? Grain and fan-out, SQL NULL traps, incremental idempotency, data tests, schema compatibility for consumers.*

## When to use

Reviews the analytics/data plane — SQL/dbt transformations, data tests, and event or published-table schemas — for transformation correctness, data-test adequacy, and producer-to-consumer data-contract safety: violated grain and fan-out joins that silently inflate aggregates, SQL NULL traps (NOT IN with NULLs, a LEFT JOIN degraded by a WHERE predicate), non-idempotent incremental runs and dropped late rows, silent type coercion (money as float, timezone-naive truncation), missing data tests, pipelines that publish an empty table instead of failing, and schema changes that break downstream readers with no compatibility gate, version bump, or named consumers. Use when reviewing a SQL or dbt model, an ETL/ELT transformation, an event or analytics schema, or a data test. Defers store-migration mechanics to #20, the service API contract to #13, PII to #27; escalates warehouse governance to a data owner. Skip when the change touches no SQL, pipeline, data test, or consumed schema.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If this lens applies and what you reviewed holds up — the code, the design, or the repository's current state — reply "No findings" and stop. If what you were given is outside this lens's scope entirely, say so in one line instead, starting with the words "Not applicable:" followed by what's missing — never the healthy-scan sentence, which means a check ran and found nothing, not that nothing here applied. Either way, do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above. Read the overlay from the **base ref** of the change under review — the `/atlas-review-pr` command reads it at the PR's base ref and `/atlas-code-review` reads it from the base side of the diff (`git show <base>:.code-quality-atlas/preferences.md`), and each hands it down — never from the reviewed branch's working tree: an edit to `preferences.md` made *by* the change under review governs later reviews once merged, not the review of the change that makes it, since otherwise a change could `suppress` its own findings.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Declare and defend the grain.** What does one row of this model mean? A join to a one-to-many table **before** an aggregate silently multiplies rows and inflates every `SUM`/`COUNT` downstream — the data plane's most expensive quiet defect. Require a uniqueness test on the grain key (`unique`, or a compound `dbt_utils.unique_combination_of_columns`) on any new or re-grained model, and check every added join for fan-out.
- **A schema change crossing a consumer boundary must clear a compatibility gate — in the direction that matters.** Renaming, dropping, retyping, or narrowing an event field or a published column can break readers that still compile, but *which* readers depends on direction: `BACKWARD` protects a new reader against old data, `FORWARD` protects an old reader against new data, and a rolling deploy means both coexist. Many changes satisfy one direction and not the other — under Avro schema resolution, **deleting a field that carries no default** and **promoting a numeric type** (`int`→`long`/`float`/`double`, `long`→`float`/`double`, `float`→`double`) are *backward*-compatible and *forward*-incompatible, so a `BACKWARD`-only subject accepts a change that breaks every consumer not yet upgraded. The default is what decides it: deleting a field that *does* have one stays compatible in both directions, because the old reader falls back on it. So do not reason from "the schema changed"; reason from: which mode is configured on this subject, is it enforced in CI, does the change satisfy it across the whole schema history (`_TRANSITIVE`), and — where it breaks a direction that matters — is there a version bump, a deprecation window, a stated deploy ordering, and a *named* consumer list? `NONE` is not a passing grade, and "nothing failed in CI" is not evidence when no consumer lives in this repo. A change can also be schema-legal and semantically wrong (a promotion that silently changes a money field's representation) — that is a separate finding, not a compatibility one.
- **Data tests proportional to what the model asserts.** A new or changed model should carry tests covering the dimensions it can actually be wrong on — `not_null` and `unique` on the grain, `accepted_values` on an enum/status, `relationships` for referential integrity, a freshness or volume expectation on a source. A model with zero tests is the data analog of untested code; a hundred generated per-column expectations is noise (cross #17, #11).
- **Transformation logic needs a *unit* test, not just a data test.** Data tests assert properties of the output *after* a run against real data; they cannot tell you a `CASE` branch or a window function is wrong on an input that hasn't occurred yet. Non-trivial logic — multi-branch `CASE`, window functions, deduplication, late-arriving handling — should have a fixture-in/fixture-out unit test (dbt unit tests, or the framework's equivalent).
- **NULL and empty-set semantics in SQL.** `NOT IN (subquery)` returns nothing when the subquery can yield `NULL` — use `NOT EXISTS` or an anti-join; `COUNT(col)` silently skips `NULL`s; a filter on the right-hand table in `WHERE` turns a `LEFT JOIN` into an inner join; `UNION` hides duplicates that `UNION ALL` would expose; a `JOIN` on a nullable key drops rows. Read every new predicate for three-valued logic (cross #1).
- **Idempotency of an incremental run.** Re-running the same partition or window must overwrite, not append or double-count: is `unique_key` (or the framework's merge key) set, is the incremental predicate deterministic (not `now()`-relative in a way that shifts each run), does a `--full-refresh` produce the same result as the incremental path, and is there a lookback window covering **late-arriving** rows? Ask "what happens when this runs twice" of every incremental model (cross #3).
- **Backfill and history rewrites.** A change to a transformation changes the *meaning* of already-published rows. Is a backfill needed to make history consistent, is it batched/resumable/idempotent, and is the partition immutable-and-overwritten rather than mutated in place? A change that silently applies only to new data leaves a discontinuity nobody documents. Delegate the store's DDL/lock mechanics to **#20**.
- **Type fidelity and silent coercion.** Money as `float`; a timestamp truncated in the warehouse's session timezone rather than a declared one; epoch seconds vs. milliseconds; a string→date implicit cast that yields `NULL` on the malformed rows instead of failing; a numeric widened or narrowed across a contract boundary. Precision lost in a transformation is unrecoverable downstream (cross #4, #37).
- **Duplicates and event-time vs. processing-time.** At-least-once delivery (Kafka, CDC, webhooks) means duplicate events are normal, not exceptional: is the consumer keyed/deduplicated, and does the aggregation window use **event time** where the semantics require it rather than whenever the batch happened to run? Late and out-of-order arrival is the default case, not the edge case.
- **Fail loud, not empty.** When a source is missing, stale, or returns zero rows, does the pipeline **fail** — or does it publish an empty/stale table that every dashboard downstream reads as "business went to zero"? Require a freshness and a volume expectation on the sources a model depends on; name the silent-success path and delegate the fail-loud verdict to **#2** (cross #16).

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI catches it automatically from then on. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.

<!-- GENERATED by `python -m tooling.cli generate` — do not edit this file directly.
     Canonical sources: docs/research/.
     Direct edits are overwritten on regeneration and fail the CI drift/regenerate gate. -->
