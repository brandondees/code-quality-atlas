---
name: reviewing-migration-and-data-safety
description: 'Reviews schema migrations and data changes for safety: backward compatibility
  with the running app (expand/migrate/contract), table locks from NOT NULL/index/FK
  on large tables, unbatched backfills, missing dual-write during transitions, irreversible
  or destructive DDL, and integrity constraints left to app code. Use when reviewing
  migrations, ALTER TABLE, backfills, schema or data-format changes, or anything touching
  persistence.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 20
    source: docs/research/cluster-5-verification.md#20
    hash: ca756d5c5da010385d8f372ef96f75141cd2af0836bbb0da480d40f432e56cef
---

# reviewing-migration-and-data-safety

## When to use

Reviews schema migrations and data changes for safety: backward compatibility with the running app (expand/migrate/contract), table locks from NOT NULL/index/FK on large tables, unbatched backfills, missing dual-write during transitions, irreversible or destructive DDL, and integrity constraints left to app code. Use when reviewing migrations, ALTER TABLE, backfills, schema or data-format changes, or anything touching persistence.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Is the schema change **backward-compatible** with the currently-running app version (rolling deploy)? If breaking, is it split expand→migrate→contract?
- Does adding a NOT NULL column / index / FK **lock the table** (esp. large tables)? Use safe variants (`CREATE INDEX CONCURRENTLY`; add nullable then backfill; `NOT VALID` then validate).
- Is a data **backfill batched, throttled, idempotent, and resumable** — not one giant `UPDATE`?
- During the transition, does the app **dual-write/dual-read** so neither old nor new code breaks?
- Are migrations **reversible** — or is the irreversibility deliberate and documented?
- Are **integrity constraints** (FK, UNIQUE, CHECK, NOT NULL) used so the DB enforces invariants, not just app code (cross #10)?
- Are **transaction boundaries** correct — multi-step writes atomic, no partial commit on failure (cross #2)?
- Is **destructive DDL** (DROP column/table) gated until the new path is verified live and old code drained?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
