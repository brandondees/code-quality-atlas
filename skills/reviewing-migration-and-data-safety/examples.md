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
