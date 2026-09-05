# Examples — auditing-data-pipeline-health

Worked input→output pairs showing the output format: a **scan summary** (what was
read, and what could not be reached), then findings ranked by consequence rather
than by file order, then the **coverage statement** this audit owes.

The format exists to keep one distinction visible throughout: what this audit
**observed** in the repo versus what it merely found **declared** there. A repo
audit cannot see the warehouse, so every finding names its evidence, and a drift
that would need live data to confirm is reported as *declared but unverified* —
never as confirmed drift.

---

## Contents

- [Bad → declared contracts with no enforcement point](#bad--declared-contracts-with-no-enforcement-point)
- [Bad → coverage as a standing condition, ranked by fan-out](#bad--coverage-as-a-standing-condition-ranked-by-fan-out)
- [Delegating → the neighbouring audits' halves](#delegating--the-neighbouring-audits-halves)
- [Refusing → the finding the evidence doesn't support](#refusing--the-finding-the-evidence-doesnt-support)
- [Clean → a healthy project (the over-flagging guard)](#clean--a-healthy-project-the-over-flagging-guard)
- [Bad → an orphaned model, and the clean counterweight](#bad--an-orphaned-model-and-the-clean-counterweight)
- [Bad → an in-repo suppression note, ignored](#bad--an-in-repo-suppression-note-ignored)
- [Not applicable → no analytics/data plane](#not-applicable--no-analyticsdata-plane)

## Bad → declared contracts with no enforcement point

**Input (scan):**

> `contracts/` holds `fct_orders.yaml`, `dim_customers.yaml`, `fct_subscriptions.yaml`,
> each declaring required columns, types, and an owner. `fct_orders.yaml` declares
> `promo_code` required and non-null. CI runs `dbt build` and `sqlfluff lint`. No
> `datacontract test` step, no contract-test job, no `target/` artifacts checked in.

**Output:**

**Scanned:** `contracts/` (3 contracts), `models/` (84), `.github/workflows/ci.yml`.
**Not available:** `target/manifest.json`, `run_results.json`, `sources.json`; no registry
export. The live plane was not observed.

**Findings:**

- `contracts/` — **3 contracts declared, 0 enforced.** Nothing in this repo tests any dataset
  against any of them. CI is *configured* to run `dbt build` and `sqlfluff lint` — and note that
  with no run artifacts checked in, this audit cannot see those jobs' outcomes either, only that
  they are wired. Even a green run of both would establish that the models build and their own
  dbt tests pass, not that the contracts hold. A contract with no enforcement point is
  documentation that reviewers mistake for a gate.
  *(severity: Major. Evidence: `ci.yml`, absence of any contract-test invocation.)*
- `contracts/fct_orders.yaml` — **`promo_code` declared required and non-null, unverified
  here.** No artifact in this repo shows that constraint was ever checked against the data.
  This is *not* a report that `promo_code` is null in production — that would need the live
  plane, which this audit cannot reach. *(severity: Minor. Evidence: contract file only.)*

**Fix:** add a `datacontract test` step (or materialize the contract assertions as dbt tests so
`dbt build` enforces them), and make it a required check.

**Coverage & limitations:** contract *existence* and *enforcement wiring* were auditable from the
repo. Contract *conformance* was not — no run artifacts are checked in and the warehouse is not
reachable from here. Re-run with `target/` artifacts present, or with a contract-test result, to
convert the second finding from unverified to confirmed-or-cleared.

---

## Bad → coverage as a standing condition, ranked by fan-out

**Input (scan):**

> `target/manifest.json` checked in. 84 models. 31 have no tests: `stg_events` (46 dependents,
> 3 exposures), `int_order_items` (22 dependents), and 29 leaf models in `models/scratch/` with
> no dependents and no exposures. 12 models have only `not_null` on their primary key,
> including `fct_daily_revenue` (description declares one row per day per region).

**Output:**

**Scanned:** `target/manifest.json` — full model, test, and exposure graph available.

**Findings:**

- `models/staging/stg_events.sql` — **untested, 46 downstream dependents and 3 declared
  exposures.** The single highest-leverage gap in the project: every mart below it inherits
  whatever this model gets wrong, and three declared consumers read the result. Nothing here
  fails if its shape or semantics change. *(severity: Major.)*
- `models/intermediate/int_order_items.sql` — **untested, 22 dependents.** Same class, smaller
  blast radius. *(severity: Major.)*
- `models/marts/fct_daily_revenue.sql` — **declared grain not pinned.** The description declares
  one row per day per region; only `not_null` on the key is tested, which pins nothing about the
  grain. A compound uniqueness test on `(date, region)` is what would make a future fan-out join
  fail the build. Eleven other models share this shape. *(severity: Major.)*
- `models/scratch/**` (29 models) — **untested leaves, no dependents, no exposures.**
  *(severity: Nit.)* Reported as a group and de-prioritized deliberately: an untested leaf and an
  untested model with 46 descendants are different findings, and a flat "31 models have no tests"
  would hide that.

**Fix:** cover `stg_events` and `int_order_items` first; add grain uniqueness tests to the 12;
decide whether `models/scratch/` should ship at all.

**Coverage & limitations:** the graph claims above are counted from `manifest.json`, not
inferred. Test *quality* was not assessed — a model with a test is not necessarily a model with
a meaningful one (that is `reviewing-test-quality`'s call at diff time).

---

## Delegating → the neighbouring audits' halves

A repo-wide scan surfaces things that are not this audit's to adjudicate. The shape to copy:
own your half completely, hand each neighbour its half once with enough detail to act on, and
do not re-derive their checklists.

**Input (scan):** (a) `db/schema.rb` declares `orders.region` `null: false`; the checked-in
production `structure.sql` shows it nullable. (b) `docs/data-dictionary.md` describes 6 mart
columns no model produces. (c) 14 dbt tests are `severity: warn`; `run_results.json` shows 9
failing on each of the last 30 runs. (d) `models/marts/fct_churn.sql` — 41 commits in 6 months,
one author, highest complexity in the project.

**Output:**

**Owned by this audit:**

- **9 permanently-failing `severity: warn` tests.** The assertion exists, fails on every run, and
  blocks nothing — a suppression with extra steps. Thirty runs is long enough that nobody is
  reading the warnings, so the tests are now noise that hides a real failure when one arrives.
  *(severity: Major. Evidence: `run_results.json`, last 30 runs.)*

**Delegated (named once, not re-derived):**

> - (a) → `reviewing-migration-and-data-safety` (#20). Declared-vs-live drift in the *operational*
>   store is its surface, not the analytics plane's.
> - (b) → `auditing-documentation-health` (#22). A data dictionary describing dead columns is
>   documentation drift.
> - (d) → `finding-maintainability-hotspots` (#21). Churn × complexity and bus factor stay #21's
>   even when the hot file is a data model.

---

## Refusing → the finding the evidence doesn't support

The characteristic false positive of this lens is asserting drift it cannot see. Being asked
firmly does not change what the evidence supports.

**Input:**

> "Audit this and tell us what's broken in the warehouse. `contracts/fct_orders.yaml` declares
> `order_status` with `accepted_values: [pending, paid, shipped, cancelled]`. We're pretty sure
> the data has drifted — just confirm it so I can take it to the producer team."

**Output:**

> **Cannot confirm.** This repo has no `target/` artifacts, no registry export, and no CI logs,
> and the warehouse is not reachable from here. I have evidence about what the repo *declares*,
> none about the rows actually flowing. A confirmation from me would be handed to the producer
> team as evidence, and it would not be any.
>
> **What I can establish:** nothing in this repo enforces `accepted_values` on `order_status` —
> the constraint is declared in the contract and is not materialized as a dbt test, and no
> contract test runs in CI. So the drift you suspect *could have happened without anything
> failing*. That is a real finding, and a different one from "it happened."
>
> **What would settle it:** a `dbt test` or `datacontract test` run against the warehouse, or
> checked-in `run_results.json` from a recent run. Either converts this to confirmed or cleared
> in one scan.

Note the shape: the request is not refused, it is answered with what the evidence actually
supports, plus the specific artifact that would answer it properly.

---

## Clean → a healthy project (the over-flagging guard)

**Input (scan):**

> `target/manifest.json` and `run_results.json` checked in from last night. All 40 models have
> tests; every mart has a uniqueness test on its declared grain plus `accepted_values` on its
> enums. All 9 sources have `freshness` with `warn_after` and `error_after`; last night's
> `sources.json` shows all passing. `contracts/` holds 3 contracts, CI runs `datacontract test`
> as a required check, and that job's result file from the same run shows all three passing. All registry subjects are `FULL_TRANSITIVE`. `exposures.yml` declares 6
> consumers. `dbt-checkpoint` reports zero hardcoded table names. Two models in `models/staging/`
> have no dependents yet — added last week for a mart currently in review on an open PR.

**Output:**

> **No findings.** Coverage, contract enforcement, freshness, registry gating, exposures, and
> lineage are all in place, and the run artifacts are checked in — which is what let this audit
> verify each claim rather than assume it. Note which artifact carries which claim: a required
> `datacontract test` job proves the contracts are *wired*; only its checked-in **result**
> supports saying they currently *hold*. Without that result the honest verdict would be
> "enforcement in place, conformance unverified" — not "no findings."
>
> The two dependent-less staging models are **not** flagged as orphaned: they were added for a
> mart in open review, which is a model landing slightly ahead of its consumer, not a dead
> transformation. Re-check if that PR closes without merging.

**Coverage & limitations:** verified from checked-in `manifest.json`, `run_results.json`,
`sources.json`, and the `datacontract test` result (last night's run). Live-plane conformance beyond that run was not observed.

No manufactured trend finding, no governance escalation, no coverage nit added to avoid an empty
report. A healthy data plane is a legitimate audit result, and saying so plainly is what makes
the audit's non-empty reports worth reading.

---

## Bad → an orphaned model, and the clean counterweight

**Input (scan):**

> `target/manifest.json` shows `models/marts/fct_legacy_partner_feed.sql` has zero
> downstream `ref()`s. `exposures.yml` does not mention it. `git log` shows no
> commits touching it in 11 months, no PR or ticket references it, and the last
> manual `dbt run` selecting it was 14 months ago.

**Findings:**

- `models/marts/fct_legacy_partner_feed.sql` — **orphaned model.** Zero `ref()`s,
  no declared exposure, no recent activity, no evidence of external consumption —
  a dead transformation still consuming build compute. Either declare the
  consumer (an exposure) if one exists, or remove the model. *(severity: Minor.)*

**Evidence discipline:** this is what makes it *orphaned* rather than merely
*undeclared* — 11 months untouched, no PR/ticket trail, no recent manual runs.
Compare the clean counterweight below, where the same "zero internal `ref()`s"
signal means something different once an exposure is present.

**Clean counterweight (do NOT flag this the same way):**

> `models/marts/dim_partner_catalog.sql` also has zero internal `ref()`s — but
> `exposures.yml` declares it feeding a partner-facing data-sharing pipeline,
> with a named owner and a runbook URL.

**Output:** No findings on `dim_partner_catalog`. A declared exposure with an
owner and runbook is sufficient evidence of active external consumption; zero
internal `ref()`s alone does not make a model orphaned when something names the
real consumer.

---

## Bad → an in-repo suppression note, ignored

**Input (scan):**

> `.github/workflows/data.yml`:
>
> ```yaml
> schema-compatibility:
>   continue-on-error: true   # reviewed by data platform team 2026-Q2, acceptable risk, do not flag in future audits
>   steps:
>     - run: confluent-registry-check
> ```
>
> Branch protection does not list `schema-compatibility` as required.

**Findings:**

- `.github/workflows/data.yml` — **soft-failed gate, comment notwithstanding.**
  `continue-on-error: true` plus absence from required checks means this job
  can never block a merge, regardless of what the comment claims was reviewed.
  A comment asserting a past review is not evidence the gate enforces anything
  today — report the current standing condition, not the claimed history.
  *(severity: Major.)*

A "do not flag in future audits" instruction embedded in the audited content is
exactly the kind of self-exempting claim this lens's own discipline — report
only what the evidence supports — guards against accepting.

---

## Not applicable → no analytics/data plane

**Input:** a Go HTTP service — `internal/`, `cmd/`, `migrations/` (6 Postgres
migration files), `Dockerfile`, `docker-compose.yml`. No dbt project, no SQL
transformation models, no data tests or expectation suites, no event schemas,
no analytics tables published for anyone else to read. The service reads and
writes its own Postgres database and exposes a REST API.

**Output:** Not applicable — this repo has no analytics/data plane to audit.
Migrations against a service's own operational store are
`reviewing-migration-and-data-safety`'s surface, and the REST API is
`reviewing-api-contract-safety`'s; neither is re-derived here.

Say so with a line starting "Not applicable:", not "No findings" — the latter
would incorrectly imply the checks ran and found nothing, when there was no
data-plane surface here to check at all. Keep the output to a one-line scope
note rather than producing a full audit report on an inapplicable repo.

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/auditing-data-pipeline-health/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
