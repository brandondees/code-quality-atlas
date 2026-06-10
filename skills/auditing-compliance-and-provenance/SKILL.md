---
name: auditing-compliance-and-provenance
description: 'Audits compliance, licensing, and provenance: dependency licenses compatible
  with the distribution model, copyleft contamination, missing SPDX headers and attribution,
  code of unclear provenance, PII data flows without minimization or retention limits,
  consent gating for telemetry, and SBOM currency. Detects and escalates to humans
  rather than deciding legal questions. A repo-wide / scheduled audit. Use when auditing
  licenses, PII handling, data retention, or provenance.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 27
    source: docs/research/cluster-6-evolution.md#27
    hash: 973cb4bcfda0d546fe1fa8a4cde13fda7368c1cd120d0581b2a02d5ace663cfc
---

# auditing-compliance-and-provenance

## When to use

Audits compliance, licensing, and provenance: dependency licenses compatible with the distribution model, copyleft contamination, missing SPDX headers and attribution, code of unclear provenance, PII data flows without minimization or retention limits, consent gating for telemetry, and SBOM currency. Detects and escalates to humans rather than deciding legal questions. A repo-wide / scheduled audit. Use when auditing licenses, PII handling, data retention, or provenance.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
