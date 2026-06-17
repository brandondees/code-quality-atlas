---
name: reviewing-api-contract-safety
description: 'Reviews public API and contract changes for safety: backward compatibility
  (versioned/deprecated if breaking), hard-to-misuse shapes, "when in doubt leave
  it out" on new surface, typed and stable error contracts, idempotency for unsafe
  operations, pagination and rate limits on collections, contract tests, and no internal-representation
  leakage. Use when reviewing REST/GraphQL/RPC endpoints, request or response shapes,
  SDK surface, webhooks, or any consumer-facing contract. Skip when the change is
  internal-only with no consumer-facing surface — private helpers or implementation
  details no external caller depends on.'
provenance:
  taxonomy_version: v0.6
  built_from:
  - category: 13
    source: docs/research/cluster-3-structure.md#13
    hash: 7f725163d5f31734656d5099caa13bf51bc3ab1c71fb65f48ee6e1d0c6543d5a
---

# reviewing-api-contract-safety

*Will this break a consumer? Compatibility, error contracts, idempotency, pagination.*

## When to use

Reviews public API and contract changes for safety: backward compatibility (versioned/deprecated if breaking), hard-to-misuse shapes, "when in doubt leave it out" on new surface, typed and stable error contracts, idempotency for unsafe operations, pagination and rate limits on collections, contract tests, and no internal-representation leakage. Use when reviewing REST/GraphQL/RPC endpoints, request or response shapes, SDK surface, webhooks, or any consumer-facing contract. Skip when the change is internal-only with no consumer-facing surface — private helpers or implementation details no external caller depends on.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

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

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
