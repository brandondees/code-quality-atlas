# References to mine — reviewing-migration-and-data-safety

## Contents

- From category #20

## From category #20

### Key references

- **Martin Fowler — "Parallel Change" (expand/contract)** → mine: never do a breaking schema change in one step — **expand** (add new alongside old) → **migrate** (dual-write + batched backfill) → **contract** (drop old once drained). Each phase independently deployable and reversible.
- **Online schema-change tools — gh-ost (GitHub, binlog-based, *triggerless*), pt-online-schema-change (Percona, trigger + shadow table), pgroll (Postgres)** → mine: large-table `ALTER`s take blocking metadata locks; these copy rows in batches and keep the copy in sync for near-zero downtime.
- **ankane/strong_migrations** — https://github.com/ankane/strong_migrations → mine: the best single **catalog of unsafe migration operations and their safe rewrites** (the rename-column 6-step: add column → write both → backfill → move reads → stop writing old → drop). Lift these directly as checklist items.
- **Martin Kleppmann — *Designing Data-Intensive Applications*** → mine: ACID, isolation levels, and constraints as the last line of defense for integrity.
- **Batched-backfill discipline** → mine: backfill in small batches (1k–10k rows) with a sleep to avoid lock/IO saturation; make it **idempotent and resumable**.
