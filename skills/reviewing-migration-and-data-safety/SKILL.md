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

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
