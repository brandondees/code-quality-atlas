---
name: auditing-compliance-and-provenance
description: 'Audits compliance, licensing, and provenance: dependency licenses compatible
  with the distribution model, copyleft contamination, missing SPDX headers and attribution,
  code of unclear provenance, PII data flows without minimization or retention limits,
  consent gating for telemetry, and SBOM currency. Detects and escalates to humans
  rather than deciding legal questions. A repo-wide / scheduled audit. Use when auditing
  licenses, PII handling, data retention, or provenance.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 27
    source: docs/research/cluster-6-evolution.md#27
    hash: ba00467edc777fed0fce3439c40c1d7cede1c341eafc278465121b57c67c3ccc
---

# auditing-compliance-and-provenance

*Any licensing, PII, or provenance exposure? Detect and escalate to humans — never decide legal questions.*

## When to use

Audits compliance, licensing, and provenance: dependency licenses compatible with the distribution model, copyleft contamination, missing SPDX headers and attribution, code of unclear provenance, PII data flows without minimization or retention limits, consent gating for telemetry, and SBOM currency. Detects and escalates to humans rather than deciding legal questions. A repo-wide / scheduled audit. Use when auditing licenses, PII handling, data retention, or provenance.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **New dependency license check:** does an added dependency (and its transitive tree) carry a license compatible with the project's distribution model? Block/strongly-flag GPL/AGPL pulled into a permissive or proprietary product.
- **Copyleft contamination / linkage:** does the change *link* or *combine* with copyleft code in a way that triggers obligations (esp. AGPL over a network service)? Static vs. dynamic linking and "mere aggregation" matter — flag for legal if unsure.
- **License/attribution preservation:** are upstream license texts, copyright notices, and NOTICE files retained when vendoring/copying code? Removed attribution = violation.
- **Provenance of copied code:** does this diff include code pasted from Stack Overflow, a blog, another repo, or AI generation without attribution/license clarity? Treat as untrusted: verify license, run secret/IP scan, label it.
- **Per-file license header:** do new source files have an `SPDX-License-Identifier` + copyright (REUSE)? Missing header = provenance gap.
- **PII data-flow:** does new code collect, store, log, or transmit personal data? If so — lawful basis/consent present, **minimized** to what's needed, not logged in plaintext, and not sent to a third party/region without basis (cross-links #14, #16, #25).
- **Retention & deletion:** is there a retention limit and an erasure path for new personal data (right-to-be-forgotten), or does it accumulate indefinitely?
- **Data residency / cross-border:** does the change move PII to a new region, vendor, or third-party model (incl. LLM APIs) — is that transfer permitted and documented? (cross-links #25 PII-to-model.)

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
