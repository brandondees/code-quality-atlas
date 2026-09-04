# Examples — reviewing-migration-and-data-safety

This skill is low-freedom: findings should quote the exact safe recipe, not general
advice. The running app and the migration deploy at different moments — every
change must be compatible with both the old and new code being live. Report each
distinct unsafe operation as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

**Decision rules (apply before flagging):**

- **Any one-step rename or type-change of a live column/table is breaking** during
  a rolling deploy — old code references the old name while both versions run.
  Always demand the expand/contract recipe, never an in-place rename.
- **`ADD COLUMN ... DEFAULT <constant>` is fast and safe on Postgres 11+** (no table
  rewrite) — do not flag the default itself; flag only what is actually unsafe in
  the change (plain `CREATE INDEX`, giant `UPDATE`, …).
- **If the migration already uses the safe variant** (nullable add,
  `CREATE INDEX CONCURRENTLY`, `NOT VALID` constraint, batched backfill), do NOT
  flag the deferred later steps as missing — deferring them IS the pattern. Report
  exactly "No findings".
- **This lens's scope is data-safety, not just DDL syntax.** A diff with zero
  migration statements is still in scope when application code assumes a data
  guarantee the database doesn't actually enforce — a uniqueness check-then-act
  with no `UNIQUE` constraint, an ordering or cardinality assumption nothing in
  the schema backs. Do not answer "Not applicable" for app-level code just
  because there's no `ALTER`/`CREATE`/migration file in front of you; ask
  whether the code's correctness depends on the database catching something it
  isn't set up to catch.
- **`ADD COLUMN col type NOT NULL DEFAULT <constant>` is one safe pattern, not
  two conflicting signals.** Read past `NOT NULL` to check for `DEFAULT
  <constant>` on the same line before flagging — `NOT NULL` alone (no default)
  fails/locks on existing rows, but paired with a constant default it is the
  fast, safe, no-rewrite form the decision rule above already covers. Flagging
  it as if the default weren't there is a fabricated finding on a line whose
  actual keywords already show it's safe.

## Bad → finding

**Input (diff):**

```sql
ALTER TABLE events ADD COLUMN tenant_id bigint NOT NULL;
CREATE INDEX idx_events_tenant ON events (tenant_id);
UPDATE events SET tenant_id = (SELECT tenant_id FROM users WHERE users.id = events.user_id);
```

**Expected finding:**

1. **`ADD COLUMN ... NOT NULL` with no default** fails/locks on existing rows — add
   it **nullable**, backfill, then add the constraint (`NOT VALID` then
   `VALIDATE CONSTRAINT`).
2. **Plain `CREATE INDEX`** takes a write-blocking lock — use
   `CREATE INDEX CONCURRENTLY` (outside a transaction).
3. **Single giant `UPDATE`** rewrites every row in one transaction (lock + WAL
   blowup) — backfill in batches (1k–10k rows) with sleeps, idempotent and
   resumable, as a separate step from the DDL.

## Bad → finding

**Input (diff):**

```python
class Migration(migrations.Migration):
    operations = [
        migrations.RenameField("invoice", "amount", "amount_cents"),
        migrations.RemoveField("invoice", "legacy_total"),
    ]
```

**Expected finding:**

1. **In-place rename breaks the running app:** old code still reading/writing
   `amount` errors the moment this applies (rolling deploy = both versions live).
   Use the expand/contract rename recipe: add `amount_cents` → deploy code writing
   both → backfill → move reads → stop writing old → drop `amount` last.
2. **Destructive DDL in the same change:** `RemoveField` drops a column now — gate
   the drop until the new path is verified live and old code is drained, and
   confirm the migration is reversible (or the irreversibility is deliberate and
   documented).

## Bad → finding (in-place type change — same breakage as a rename)

**Input (diff, Postgres, `orders.customer_id` currently `int`, customer volume
has outgrown int range):**

```sql
ALTER TABLE orders ALTER COLUMN customer_id TYPE bigint;
```

**Expected finding:**

1. **In-place type change breaks the running app:** during a rolling deploy, old
   app-code instances still marshal `customer_id` as a 32-bit int while the new
   type is live underneath them — the same backward-compatibility break as an
   in-place rename, not merely a locking/performance concern. Use the
   expand/contract recipe: add a new `bigint` column, dual-write both, backfill,
   cut reads over to the new column, then drop the old one.

A type change is covered by the same "any one-step rename or type-change of a
live column is breaking" decision rule as a rename — do not report only the
table-rewrite/locking cost (real, but secondary) while missing the
backward-compatibility break that the decision rule already calls out by name.

## Bad → finding (missing dual-write during a column cutover)

**Input (diff and the app change deployed in the same release):**

```sql
ALTER TABLE users ADD COLUMN display_name text;
```

```python
# app code, deployed in the same release as the migration
def get_name(user):
    return user.display_name  # old `full_name` column is no longer read anywhere
```

**Expected finding:**

1. **Missing dual-write during the cutover:** the schema change itself is
   safe — a nullable add locks nothing and breaks nothing. The unsafe part is
   the app code: during a rolling deploy, instances still running the *old*
   version never write `display_name`, so a request served by a *new*-version
   instance reads null/empty for any row the old code touched in between.
   Recommend a transition phase where the app writes both columns (or the
   column is backfilled first) before cutting reads over exclusively to the
   new one.

The defect here is entirely in the app-side read/write sequencing, not the
migration's SQL — do not clear this as safe just because the DDL by itself is
the nullable-add pattern this lens already treats as sound. A safe schema
change and an unsafe deployment sequence are two different questions; check
both.

## Bad → finding (no migration statement at all — the guarantee the app assumes doesn't exist in the schema)

**Input (diff — no `UNIQUE` constraint exists on `users.email` in the schema):**

```python
class SignupForm:
    def save(self):
        if User.objects.filter(email=self.email).exists():
            raise ValidationError("Email already registered")
        return User.objects.create(email=self.email, ...)
```

**Expected finding:**

1. **App-level uniqueness check with no database-level enforcement:** two
   concurrent signup requests can both pass the `.exists()` check before either
   commits, creating duplicate accounts with the same email — the check and the
   create are not atomic, and nothing at the database layer would reject the
   race even if the app-level check is perfectly written. Add a database-level
   `UNIQUE` constraint on `users.email` so the database itself rejects the
   duplicate, rather than relying solely on an app-level pre-check.

This diff contains no `ALTER`/`CREATE`/migration file — do not report "Not
applicable" on that basis. The question this lens asks is whether a data
guarantee the code depends on is actually backed by the schema; here it
isn't, and that gap is squarely this lens's own finding regardless of what
shape the diff arrives in.

## Good → no finding

**Input (diff):**

```sql
-- expand step 1 of 3 (contract tracked in #514)
ALTER TABLE events ADD COLUMN tenant_id bigint;            -- nullable
CREATE INDEX CONCURRENTLY idx_events_tenant ON events (tenant_id);
```

```python
# separate backfill task: batches of 5000, sleeps, restarts from last id
def backfill_tenant_ids(start_after=0): ...
```

**Expected finding:** None — nullable expand, concurrent index, batched/resumable
backfill as a separate step, contract phase tracked. Report "No findings". Do NOT
demand the NOT NULL constraint, constraint validation, or the old-column drop
happen now — deferring them IS the safe pattern, not an omission. A correct expand
step is complete in itself.

**Before flagging any `ALTER TABLE ... ADD`, read its keywords literally:**
`ADD COLUMN x type;` with no `NOT NULL` is the SAFE nullable add — never flag it as
"NOT NULL with no default". Flag an add-column only when the words `NOT NULL`
actually appear without a safe backfill plan. Likewise `CONCURRENTLY` present =
safe index; `NOT VALID` present = safe constraint. Quote the offending keyword in
any finding; if you cannot quote it from the diff, the finding is invented.

**"Destructive DDL" means an actual `DROP`/`TRUNCATE` of a table, column, or
constraint — nothing else.** Before citing the destructive-DDL/gating checklist
item, check the statement's actual keyword. A `DELETE` (even a bulk one) is a data
operation, not schema DDL — its risk is batching/backup, not "gate until old code
is drained." A `CREATE TABLE ... AS SELECT` or a plain `INSERT` creates or copies
data — it destroys nothing. Reusing the destructive-DDL finding text for a
statement that isn't actually a `DROP`/`TRUNCATE` is a fabricated finding, not a
cautious one — trace what the statement literally does before reaching for that
checklist item, the same discipline as the `NOT NULL` rule above. And when a
destructive `DROP` *does* appear, check whether the diff or its context already
supplies concrete drain evidence — production-usage data confirming the old path
has actually stopped being read/written (not merely a ticket link or a stated
retirement date on their own, which document intent but not proof) — if it does,
that satisfies the gating requirement; do not re-demand it.

## Good → no finding (`NOT NULL` *with* a constant default is the safe form, not the unsafe one)

**Input (diff, Postgres 11+):**

```sql
ALTER TABLE payments ADD COLUMN retry_count int NOT NULL DEFAULT 0;
```

**Expected finding:** None — `NOT NULL` is present, but so is `DEFAULT 0`, and
the decision rule above is explicit that `ADD COLUMN ... DEFAULT <constant>` is
fast and safe (no table rewrite, no per-row backfill) regardless of table size.
Report "No findings". Do NOT flag this as "`NOT NULL` with no backfill logic
will fail on existing rows" — that failure mode is real only for `NOT NULL`
*without* a default; this line has one. The same discipline as the nullable-add
keyword rule above: read every keyword on the line — `NOT NULL` and `DEFAULT`
both — before deciding which pattern is in front of you, not just the first
keyword that looks alarming.

## Bad → finding (a bulk `DELETE` is a data operation, not "destructive DDL")

**Input (diff):**

```sql
DELETE FROM sessions WHERE created_at < now() - interval '1 year';
```

(`sessions` has ~50M rows; no other context given.)

**Expected finding:**

1. **Unbatched bulk delete:** a single `DELETE` over ~50M rows takes a long lock
   and a large transaction/WAL — batch it (e.g. `DELETE ... WHERE id IN (SELECT id
   ... LIMIT 5000)` in a loop) rather than one giant statement.
2. **No backup/snapshot before an irreversible bulk deletion:** once this commits
   there is no rollback path — take a backup or snapshot first. A dry-run count is
   a reasonable *additional* sanity check on scope, but it is not a substitute:
   it tells you how many rows will be deleted, not how to get them back.

Do NOT label this "destructive DDL" or demand the drop-column gating recipe — a
`DELETE` doesn't drop a table or column, so that checklist item doesn't apply
here. Its risk is batching and backup, the same as any other large data mutation.

## Good → no finding (evidenced contract-phase drop)

**Input (diff):**

```sql
-- contract phase; expand shipped 3 weeks ago per #452, and #452 confirms
-- legacy_status has had zero reads/writes in production since
ALTER TABLE orders DROP COLUMN legacy_status;
```

**Expected finding:** None — this *is* an actual `DROP`, but the diff already
supplies concrete drain evidence: not just a ticket link and a date, but a
confirmed **production-usage fact** — zero reads/writes since the expand phase
shipped. Report "No findings". Do NOT re-demand proof that was already given,
and do NOT treat every `DROP` as needing more evidence than this. (A ticket
link and a stated date *alone*, with no usage confirmation, would NOT be enough
— see the decision rule above.)

## Bad → finding

**Input (diff):**

```python
def up(db):
    db.execute("INSERT INTO ledger_entries (account_id, amount) VALUES (%s, %s)", (acct, amt))
    recompute_and_write_balance(db, acct)  # separate statement/commit, not in the same transaction
```

**Expected finding:**

1. **No transaction boundary across a multi-step write:** the ledger insert and
   the balance recompute are two separate statements/commits, not wrapped in one
   transaction — a crash or error between them leaves the ledger and the cached
   balance inconsistent. Wrap both writes in a single transaction (or make the
   balance update part of the same atomic unit of work) so a failure leaves either
   both applied or neither.

## Bad → finding

**Input (diff):**

```sql
-- amount_cents is validated by the Money value object at the app layer,
-- so no DB-level CHECK constraint is needed here.
ALTER TABLE payments ADD COLUMN amount_cents bigint;
```

**Expected finding:**

1. **DB-level constraint skipped in favor of an app-layer claim:** relying solely
   on application validation means any direct DB write, migration, or future code
   path that bypasses the app-layer type can insert an invalid value with nothing
   at the database level to stop it. A comment asserting the app layer already
   handles it is not itself a database constraint — add a DB-level `CHECK`
   constraint (e.g. `amount_cents >= 0`) as defense-in-depth regardless of what
   validates it upstream.

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/reviewing-migration-and-data-safety/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
