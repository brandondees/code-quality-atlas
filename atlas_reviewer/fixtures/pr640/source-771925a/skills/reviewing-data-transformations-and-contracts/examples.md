# Examples — reviewing-data-transformations-and-contracts

Worked input→output pairs showing the output format: per-defect **findings** with a
concrete location, the mechanism (what silently goes wrong), and the evidence the
change should have carried. The data plane's defects are almost never loud — the
build stays green and the numbers just become wrong — so a finding here names the
*silence* as much as the code.

---

## Contents

- [Bad → a fan-out join inflating every aggregate downstream](#bad--a-fan-out-join-inflating-every-aggregate-downstream)
- [Bad → a consumer-breaking schema change with no gate](#bad--a-consumer-breaking-schema-change-with-no-gate)
- [Delegating → the half that belongs to another lens](#delegating--the-half-that-belongs-to-another-lens)
- [Bad → a timezone-naive type coercion](#bad--a-timezone-naive-type-coercion)
- [Clean → a refactor with data-diff evidence (the over-flagging guard)](#clean--a-refactor-with-data-diff-evidence-the-over-flagging-guard)
- [Clean → an additive, gated schema change (the proportionality guard)](#clean--an-additive-gated-schema-change-the-proportionality-guard)
- [Not applicable → no data-plane surface touched](#not-applicable--no-data-plane-surface-touched)

## Bad → a fan-out join inflating every aggregate downstream

**Input:**

> `models/marts/fct_customer_revenue.sql`
>
> ```sql
> select c.customer_id, c.region, sum(o.order_total) as lifetime_revenue, count(*) as order_count
> from {{ ref('dim_customers') }} c
> join {{ ref('fct_orders') }} o on o.customer_id = c.customer_id
> join {{ ref('fct_order_items') }} i on i.order_id = o.order_id
> group by 1, 2
> ```
>
> `schema.yml` adds a description and a `not_null` test on `customer_id`.

**Findings:**

- `models/marts/fct_customer_revenue.sql:4` — **fan-out join inflates both aggregates.**
  `fct_order_items` is one-to-many per order, so every order row is duplicated once per
  line item *before* the `group by`. `lifetime_revenue` and `order_count` are both
  overstated by a factor that varies per customer — a two-item order counts twice, a
  ten-item order ten times. Nothing fails: the model builds, the tests pass, and every
  dashboard reading this mart is quietly wrong. *(severity: Blocker.)*
- `models/marts/fct_customer_revenue.sql` — **the grain is claimed but not defended.**
  The `group by 1, 2` asserts one row per customer, but only `not_null` is tested. Add a
  `unique` test on `customer_id` (or `dbt_utils.unique_combination_of_columns` for a
  compound grain) so the next join that breaks the grain fails the build instead of
  shipping. *(severity: Major.)*
- `models/marts/fct_customer_revenue.sql:4` — **the join is unused.** No column from
  `fct_order_items` reaches the select list; it was added for an item count that isn't
  exposed. Drop it, or aggregate items to one row per order in a CTE first.
  *(severity: Major.)*

Evidence this change should have carried: a data-diff (`data-diff` / Recce) against
production showing the row and value delta. On a change to an aggregate, "the tests
pass" is not evidence — the tests do not assert the numbers.

---

## Bad → a consumer-breaking schema change with no gate

**Input:**

> `schemas/order_placed.avsc` drops `promo_code` (a required `string`) and changes
> `total_cents` from `long` to `double`. The producer is updated to match. "No other
> file in this repo reads the topic." The subject's registry compatibility is `NONE`.

**Findings:**

- `schemas/order_placed.avsc` — **both changes break *forward* compatibility, and a
  `BACKWARD`-only gate would wave them through.** Under Avro schema resolution, deleting
  `promo_code` and promoting `long` → `double` are both *backward*-compatible: a reader on
  the new schema handles old data fine (the removed field is ignored; `long` promotes to
  `double`). Neither is *forward*-compatible: a reader still on the old schema fails on the
  new data — `promo_code` is required there with no default, and `double` does not demote
  to `long`. On a rolling deploy old and new readers coexist, so every consumer not yet
  upgraded breaks on the first new message. `FULL`/`FULL_TRANSITIVE` is the mode that
  catches this; `BACKWARD` alone is not. *(severity: Blocker.)*
- `schemas/order_placed.avsc` — **compatibility `NONE` is the defect, not the mitigation.**
  The registry accepts anything on this subject, so the absence of a failure is the absence
  of a check. Set an enforced mode — `FULL_TRANSITIVE` for a contract with independently
  deployed readers — and run the compatibility check in CI on the PR. Absent that, either
  emit both fields through a deprecation window, or state the deploy ordering (consumers
  first) and the named consumer list that makes the break survivable. *(severity: Major.)*
- `services/checkout/publisher.py` — **`total_cents` moved to a float — schema-legal,
  semantically wrong.** The promotion passes Avro's type rules, which is exactly why the
  compatibility gate would not have caught it: a monetary field in a binary floating-point
  type accumulates representation error across every downstream sum regardless of what the
  registry says. Keep integer minor units; if fractional amounts are genuinely required,
  use a decimal type with a declared scale. *(severity: Major.)*

On the reasoning: **"nothing in this repo reads the topic" is not a consumer inventory.**
A grep finds only the consumers present in this source tree, and the consumers of an event
stream usually are not. Even in a monorepo where some of them are, the ones a grep cannot
reach are the ones that bite: BI tools, notebooks, scheduled extracts, and other teams'
services subscribe to the topic without appearing in any repo. The grep is evidence about
this repo, not about the consumer set. Removal needs a named consumer list, a version bump, and a deprecation window in
which both fields are emitted.

---

## Delegating → the half that belongs to another lens

**Input:**

> A migration sets `NOT NULL` on `orders.region` (400M rows), and
> `models/staging/stg_orders.sql` drops the `coalesce(region, 'unknown')` that was
> compensating for the nulls.

**Findings (this lens's half only):**

- `models/staging/stg_orders.sql` — **history changes meaning.** Rows previously bucketed
  as `'unknown'` will resolve differently once the `coalesce` is gone, so the published
  series has a discontinuity at the deploy boundary that nothing documents. Either backfill
  so history is consistent, or record the break where consumers of the `region` grouping
  will see it. *(severity: Major.)*
- `models/staging/stg_orders.sql` — **does anything depend on the literal bucket?**
  Downstream models, saved dashboards, and filters keyed on `'unknown'` will silently
  return empty. No test pins the value today. *(severity: Minor.)*

> **Delegated:** the `SET NOT NULL` takes a table-level lock on a 400M-row Postgres table,
> and the safe rewrite (`ADD CONSTRAINT … NOT VALID` → `VALIDATE CONSTRAINT` → set) is
> `reviewing-migration-and-data-safety`'s (#20) verdict. Named here, not re-derived — this
> lens does not own the operational DDL question.

The shape to copy: review your own half in full, name the neighbouring concern once with
enough detail for the owning lens to pick it up, and stop.

---

## Bad → a timezone-naive type coercion

**Input:**

> `models/marts/fct_shipments.sql`
>
> ```sql
> select shipment_id, warehouse_id,
>        cast(shipped_at as date) as shipped_date,   -- warehouse session tz is US/Pacific; source is UTC
>        cast(tracking_number as varchar) as tracking_number
> from {{ ref('stg_shipments') }}
> ```
>
> The warehouse session default timezone is `America/Los_Angeles`. No explicit
> timezone conversion is applied before the truncation.

**Findings:**

- `models/marts/fct_shipments.sql:3` — **timezone-naive truncation.**
  `cast(shipped_at as date)` truncates using the warehouse session's default
  timezone rather than an explicit one, so a shipment near midnight UTC can land
  on the wrong calendar date relative to any UTC-based reporting. The cast
  always succeeds — the discrepancy is silent. *(severity: Major.)*

Convert to an explicit, declared timezone before truncating rather than relying
on session default. This is a transformation-logic type-fidelity defect, not a
missing-test gap — no test would have caught it either, since the cast never
fails.

---

## Clean → a refactor with data-diff evidence (the over-flagging guard)

**Input:**

> `models/marts/fct_orders.sql` is reformatted — CTEs re-indented, alias `o` renamed to
> `orders`, trailing-comma style made consistent. Select list, joins, filters, and grouping
> are unchanged in meaning. Existing tests (`unique` + `not_null` on `order_id`,
> `accepted_values` on `status`, `relationships` to `dim_customers`) are untouched. The PR
> includes a data-diff run showing zero row and value differences against production.

**Output:**

> **No findings.** The transformation's semantics are unchanged, the grain is still pinned
> by the existing uniqueness test, and the data-diff is exactly the evidence this lens asks
> for on a model change.

No invented grain finding on an unchanged select list; no request for additional tests on a
model whose existing tests already cover its grain, its enum, and its referential integrity.
A rename inside a query is not a contract change — the *output* columns are what consumers
see, and those did not move.

---

## Clean → an additive, gated schema change (the proportionality guard)

**Proportionality rule (apply *before* writing anything):** this lens fires on the data
plane. If the change touches no SQL, no pipeline, no data test, and no schema another
reader consumes, the proportional output is one line saying so — not a speculative
contract finding to look useful.

**Input:**

> `schemas/order_placed.avsc` adds `{"name": "fulfillment_center", "type": ["null",
> "string"], "default": null}`. Subject compatibility is `FULL_TRANSITIVE`, CI runs the
> registry compatibility check on the PR, the schema version is bumped, and the PR lists the
> three consuming services and notes none need a change.

**Output:**

> **No findings.** A nullable field with a default is the canonical two-way-compatible
> addition, and it is gated by an enforced `FULL_TRANSITIVE` check rather than by assertion.
> Version bump, CI gate, and named consumers are precisely the evidence a contract change
> should carry.

No deprecation window is demanded for a purely additive optional field, and the
union-with-`null` type is the mechanism that makes the addition safe — not a smell.

---

## Not applicable → no data-plane surface touched

**Input:** a change to the marketing site's CSS (`site/styles/hero.css`) — a
button's color and padding. No SQL, pipeline, data test, ETL/ELT code, or
event/analytics schema is touched anywhere in the diff.

**Output:** Not applicable — this change touches no SQL, pipeline, data test, or
consumed schema, matching this lens's own explicit skip clause.

Say so with a line starting "Not applicable:", not "No findings" — the latter
implies the data-plane checks ran and found nothing, when there is no
data-plane surface here at all to check.
