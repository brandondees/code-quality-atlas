# auditing-dependencies-and-supply-chain

Is the dependency tree safe? CVEs, pinning, typosquats, install scripts, licenses.

## When to use

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Checklist

The full review checklist, grouped by the research category each check draws from:

## From category #18

### Reviewable heuristics (skill-checklist seeds)

- Is the new dependency **necessary**, or could stdlib/a few lines do it (avoid trivial deps and transitive bloat)?
- Is it **healthy**: recently maintained, broadly used, reasonable Scorecard, not single-maintainer abandonware?
- Any **known CVEs** in it or its transitive tree (run the scanner)? Is the version **pinned via lockfile** and honored in CI (`npm ci`)?
- Does it pull in a large transitive subtree or **duplicate** an existing dependency's capability?
- License **compatible** with the project (cross #27)?
- Does the install run scripts or request network/filesystem access it shouldn't (malicious-package surface)?
- Are updates **automated** (Dependabot/Renovate) with the lockfile committed and enforced?
- Version bump → are breaking changes reviewed (changelog), especially across a major version?
- **Vendor lock-in**: does this couple us to a proprietary API where a standard/portable option exists?

---

## From category #27

### Reviewable heuristics (skill-checklist seeds)

- **New dependency license check:** does an added dependency (and its transitive tree) carry a license compatible with the project's distribution model? Block/strongly-flag GPL/AGPL pulled into a permissive or proprietary product.
- **Copyleft contamination / linkage:** does the change *link* or *combine* with copyleft code in a way that triggers obligations (esp. AGPL over a network service)? Static vs. dynamic linking and "mere aggregation" matter — flag for legal if unsure.
- **License/attribution preservation:** are upstream license texts, copyright notices, and NOTICE files retained when vendoring/copying code? Removed attribution = violation.
- **Provenance of copied code:** does this diff include code pasted from Stack Overflow, a blog, another repo, or AI generation without attribution/license clarity? Treat as untrusted: verify license, run secret/IP scan, label it.
- **Per-file license header:** do new source files have an `SPDX-License-Identifier` + copyright (REUSE)? Missing header = provenance gap.
- **PII data-flow:** does new code collect, store, log, or transmit personal data? If so — lawful basis/consent present, **minimized** to what's needed, not logged in plaintext, and not sent to a third party/region without basis (cross-links #14, #16, #25).
- **Retention & deletion:** is there a retention limit and an erasure path for new personal data (right-to-be-forgotten), or does it accumulate indefinitely?
- **Data residency / cross-border:** does the change move PII to a new region, vendor, or third-party model (incl. LLM APIs) — is that transfer permitted and documented? (cross-links #25 PII-to-model.)
- **Consent & purpose:** for new tracking/telemetry/analytics, is consent gating in place and is use limited to the stated purpose? No silent expansion of data use.
- **Accessibility-as-legal:** for regulated/consumer surfaces, does the change keep WCAG 2.x AA conformance (cross-links #23) given its legal weight?
- **Export / sanctions / crypto constraints:** does new cryptography, or distribution to restricted regions, hit export-control or compliance obligations? Flag for review (don't assume).
- **SBOM currency:** if dependencies changed, is the SBOM / license inventory regenerated so provenance stays accurate?

---

## Examples

This skill is repo-shaped: its input is a dependency / supply-chain scan. Report
each distinct risk as its own numbered finding. When the scan is healthy, the entire response is exactly this skill's no-finding sentence given in the decision rule below — never a numbered list of findings for a healthy scan.

**Decision rule (apply before flagging):** flag a dependency only for a concrete
risk signal — a known CVE, no pin/lockfile drift, abandonment (years without
maintenance + single maintainer), an incompatible license, install scripts, or a
typosquat-adjacent name. Age alone, popularity alone, or "I would have chosen a
different library" are not findings. Cite only risk signals the scan actually
shows: an empty `cves` column means there is NO CVE finding — never invent a
vulnerability, a version number, or a license problem the scan does not contain. If every dependency is pinned, scanned clean,
licensed compatibly, and maintained, report exactly
"No findings: dependencies and supply chain are healthy".

## Bad → finding

**Input (dependency scan; project license: MIT, distributed commercially):**

```text
package         version   pinned?  cves          last release  maintainers  license  notes
left-pad-x      ^1.0      no       -             6 years ago   1            MIT      name 1 char off popular pkg
yaml-parse      4.1.2     lock     CVE-2025-881  2 months ago  4            MIT      fix in 4.1.3
report-gen      2.0.0     lock     -             1 month ago   3            AGPL-3.0 postinstall script downloads binary
```

**Expected finding:**

1. **Known CVE with a fix available:** `yaml-parse` 4.1.2 carries CVE-2025-881,
   fixed in 4.1.3 — bump it now.
2. **Typosquat-shaped, abandoned, unpinned:** `left-pad-x` is one character off a
   popular package, single-maintainer, 6 years stale, and floating on `^` with no
   lock entry — verify it's the intended package, pin it, or replace with stdlib.
3. **License incompatibility:** `report-gen` is AGPL-3.0 inside an MIT-licensed
   commercially distributed product — network copyleft obligations likely apply;
   escalate to legal or replace.
4. **Install-script risk:** `report-gen`'s postinstall downloads a binary — an
   unauditable supply-chain surface; vendor a checksummed artifact or build from
   source.

## Good → no finding

**Input (dependency scan; project license: MIT):**

```text
package    version  pinned?  cves  last release  maintainers  license       notes
fastify    5.2.1    lock     -     3 weeks ago   12           MIT           -
pino       9.4.0    lock     -     2 months ago  6            MIT           -
zod        3.24.0   lock     -     1 month ago   8            MIT           renovate enabled
```

**Expected finding:** None — pinned via lockfile, scanned clean, actively
maintained, compatible licenses, automated updates. Report
"No findings: dependencies and supply chain are healthy". Do NOT flag a dependency
merely for being popular, small, or not the auditor's personal preference.

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
