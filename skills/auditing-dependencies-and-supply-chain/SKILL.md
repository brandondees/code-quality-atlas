---
name: auditing-dependencies-and-supply-chain
description: 'Audits dependencies and the supply chain: known CVEs in direct and transitive
  deps, unpinned or floating versions, lockfile integrity, abandoned or low-reputation
  packages, typosquats, install scripts, license compatibility of the dependency tree,
  and SBOM currency. A repo-wide / scheduled audit. Use when auditing package.json,
  lockfiles, requirements, vendored code, or supply-chain risk.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 18
    source: docs/research/cluster-5-verification.md#18
    hash: 4fe1f2e6410b4843fc0beaf6ab2c81e62f237d854fe1ba878dced8ae6bad501c
  - category: 27
    source: docs/research/cluster-6-evolution.md#27
    hash: 973cb4bcfda0d546fe1fa8a4cde13fda7368c1cd120d0581b2a02d5ace663cfc
---

# auditing-dependencies-and-supply-chain

## When to use

Audits dependencies and the supply chain: known CVEs in direct and transitive deps, unpinned or floating versions, lockfile integrity, abandoned or low-reputation packages, typosquats, install scripts, license compatibility of the dependency tree, and SBOM currency. A repo-wide / scheduled audit. Use when auditing package.json, lockfiles, requirements, vendored code, or supply-chain risk.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
