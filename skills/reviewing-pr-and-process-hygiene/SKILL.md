---
name: reviewing-pr-and-process-hygiene
description: 'Reviews the PR itself rather than just the code: size and single purpose
  (~<=400 net LOC), atomic commits with imperative why-bearing messages, correct conventional
  type and breaking-change signaling, risk and rollback notes, docs/changelog updated
  with the API surface, no drive-by scope creep, no committed secrets or debug leftovers.
  Use when reviewing a pull request''s structure, commits, description, changelog,
  or readiness to merge.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 24
    source: docs/research/cluster-6-evolution.md#24
    hash: 7c8122197c0e3193fe0661f0a70e35a54345d07beabe6395e85d263b3be0d73d
  - category: 22
    source: docs/research/cluster-6-evolution.md#22
    hash: c2b968248bfa961bf8a9ca267334e64935892ae4074bd2a1cf1028044482c669
---

# reviewing-pr-and-process-hygiene

## When to use

Reviews the PR itself rather than just the code: size and single purpose (~<=400 net LOC), atomic commits with imperative why-bearing messages, correct conventional type and breaking-change signaling, risk and rollback notes, docs/changelog updated with the API surface, no drive-by scope creep, no committed secrets or debug leftovers. Use when reviewing a pull request's structure, commits, description, changelog, or readiness to merge.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
