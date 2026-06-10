# Reviewable heuristics — reviewing-migration-and-data-safety

## Contents
- From category #20

## From category #20

### Reviewable heuristics (skill-checklist seeds)
- Is the schema change **backward-compatible** with the currently-running app version (rolling deploy)? If breaking, is it split expand→migrate→contract?
- Does adding a NOT NULL column / index / FK **lock the table** (esp. large tables)? Use safe variants (`CREATE INDEX CONCURRENTLY`; add nullable then backfill; `NOT VALID` then validate).
- Is a data **backfill batched, throttled, idempotent, and resumable** — not one giant `UPDATE`?
- During the transition, does the app **dual-write/dual-read** so neither old nor new code breaks?
- Are migrations **reversible** — or is the irreversibility deliberate and documented?
- Are **integrity constraints** (FK, UNIQUE, CHECK, NOT NULL) used so the DB enforces invariants, not just app code (cross #10)?
- Are **transaction boundaries** correct — multi-step writes atomic, no partial commit on failure (cross #2)?
- Is **destructive DDL** (DROP column/table) gated until the new path is verified live and old code drained?
- Is there a **tested backup/restore** path before a risky data change?

---
