---
name: reviewing-api-contract-safety
description: 'Reviews public API and contract changes for safety: backward compatibility
  (versioned/deprecated if breaking), hard-to-misuse shapes, "when in doubt leave
  it out" on new surface, typed and stable error contracts, idempotency for unsafe
  operations, pagination and rate limits on collections, contract tests, and no internal-representation
  leakage. Use when reviewing REST/GraphQL/RPC endpoints, request or response shapes,
  SDK surface, webhooks, or any consumer-facing contract.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 13
    source: docs/research/cluster-3-structure.md#13
    hash: 0ef42009707c6564fea2b3fa46fbcc50b664c17d62e0978171efa782eef8d47e
---

# reviewing-api-contract-safety

## When to use

Reviews public API and contract changes for safety: backward compatibility (versioned/deprecated if breaking), hard-to-misuse shapes, "when in doubt leave it out" on new surface, typed and stable error contracts, idempotency for unsafe operations, pagination and rate limits on collections, contract tests, and no internal-representation leakage. Use when reviewing REST/GraphQL/RPC endpoints, request or response shapes, SDK surface, webhooks, or any consumer-facing contract.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Is the change to a public contract **backward-compatible**? If breaking, is it versioned and communicated (semver, deprecation window)?
- Is the API **easy to use, hard to misuse**? Required things required by the type; invalid combinations impossible; sensible defaults.
- **"When in doubt, leave it out":** any field/endpoint/param being added that isn't clearly needed? (You can add later; you can't remove.)
- **Consistent** with the rest of the surface (naming, pluralization, error shape, pagination, status codes, casing — cross #8)?
- Are **errors part of the contract** — typed, documented, stable codes — not ad-hoc strings?
- **Idempotency**: are unsafe operations idempotent or protected by idempotency keys (cross #3)?
- Pagination, rate limits, filtering defined for collection endpoints?
- Is there a **contract test** (Pact/schema) guarding the consumer-provider boundary?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
