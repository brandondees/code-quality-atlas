---
name: reviewing-api-contract-safety
description: 'Reviews public API and contract changes for safety: backward compatibility
  (versioned/deprecated if breaking), hard-to-misuse shapes, "when in doubt leave
  it out" on new surface, typed and stable error contracts, idempotency for unsafe
  operations, pagination and rate limits on collections, contract tests, and no internal-representation
  leakage. Use when reviewing REST/GraphQL/RPC endpoints, request or response shapes,
  SDK surface, webhooks, or any consumer-facing contract.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 13
    source: docs/research/cluster-3-structure.md#13
    hash: 0ef42009707c6564fea2b3fa46fbcc50b664c17d62e0978171efa782eef8d47e
---

# reviewing-api-contract-safety

## When to use

Reviews public API and contract changes for safety: backward compatibility (versioned/deprecated if breaking), hard-to-misuse shapes, "when in doubt leave it out" on new surface, typed and stable error contracts, idempotency for unsafe operations, pagination and rate limits on collections, contract tests, and no internal-representation leakage. Use when reviewing REST/GraphQL/RPC endpoints, request or response shapes, SDK surface, webhooks, or any consumer-facing contract.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
