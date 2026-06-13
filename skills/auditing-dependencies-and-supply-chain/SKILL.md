---
name: auditing-dependencies-and-supply-chain
description: 'Audits dependencies and the supply chain: known CVEs in direct and transitive
  deps, unpinned or floating versions, lockfile integrity, abandoned or low-reputation
  packages, typosquats, install scripts, license compatibility of the dependency tree,
  and SBOM currency. A repo-wide / scheduled audit. Use when auditing package.json,
  lockfiles, requirements, vendored code, or supply-chain risk.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 18
    source: docs/research/cluster-5-verification.md#18
    hash: f876d3646ec45597347f3dd84153ef0d860abaf9eb3211d7d97cb8aca56cc9da
  - category: 27
    source: docs/research/cluster-6-evolution.md#27
    hash: ba00467edc777fed0fce3439c40c1d7cede1c341eafc278465121b57c67c3ccc
---

# auditing-dependencies-and-supply-chain

*Is the dependency tree safe? CVEs, pinning, typosquats, install scripts, licenses.*

## When to use

Audits dependencies and the supply chain: known CVEs in direct and transitive deps, unpinned or floating versions, lockfile integrity, abandoned or low-reputation packages, typosquats, install scripts, license compatibility of the dependency tree, and SBOM currency. A repo-wide / scheduled audit. Use when auditing package.json, lockfiles, requirements, vendored code, or supply-chain risk.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Is the new dependency **necessary**, or could stdlib/a few lines do it (avoid trivial deps and transitive bloat)?
- Is it **healthy**: recently maintained, broadly used, reasonable Scorecard, not single-maintainer abandonware?
- Any **known CVEs** in it or its transitive tree (run the scanner)? Is the version **pinned via lockfile** and honored in CI (`npm ci`)?
- Does it pull in a large transitive subtree or **duplicate** an existing dependency's capability?
- License **compatible** with the project (cross #27)?
- Does the install run scripts or request network/filesystem access it shouldn't (malicious-package surface)?
- **New dependency license check:** does an added dependency (and its transitive tree) carry a license compatible with the project's distribution model? Block/strongly-flag GPL/AGPL pulled into a permissive or proprietary product.
- **Copyleft contamination / linkage:** does the change *link* or *combine* with copyleft code in a way that triggers obligations (esp. AGPL over a network service)? Static vs. dynamic linking and "mere aggregation" matter — flag for legal if unsure.

**Shared categories:** category #27 checks are shared with **auditing-compliance-and-provenance** (their primary owner). When both lenses run on the same change, report each shared finding once, under the primary owner.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
