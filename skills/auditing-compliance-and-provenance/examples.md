# Examples — auditing-compliance-and-provenance

This skill is repo-shaped: its input is a license / PII / provenance scan. Its job
is to **detect and escalate, not decide** — legal questions (copyleft linkage,
lawful basis, export control) go to humans with the evidence attached. Report each
distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

**Decision rule (apply before flagging):** a compliance finding needs concrete
evidence — an incompatible license in the tree, missing attribution/SPDX, code of
unknown origin, a PII flow without minimization/retention, ungated telemetry.
Don't speculate beyond the scan; escalate ambiguity rather than ruling on it. If
licenses are compatible and attributed, provenance is clean, and PII flows are
minimized with retention paths, report exactly
"No findings: compliance and provenance are clean".

## Bad → finding

**Input (compliance scan; product: proprietary SaaS, EU customers):**
```text
licenses:    vendored/chart-lib/ (copied from GitHub, LICENSE file deleted, author header stripped)
             dep `pdf-magic` AGPL-3.0 — imported by the web rendering service
spdx:        41/180 source files missing SPDX-License-Identifier headers
pii:         new analytics.py sends user_id, email, full search history to thirdparty.example
             retention: no TTL; deletion: no erasure path implemented
telemetry:   enabled by default, no consent gate, EU traffic included
```
**Expected finding:**
1. **Stripped attribution on vendored code:** the deleted LICENSE and author
   headers in `vendored/chart-lib/` violate the upstream license regardless of
   which permissive license it was — restore the license text and attribution.
2. **AGPL in a proprietary network service:** `pdf-magic` (AGPL-3.0) imported by
   the web service plausibly triggers network-copyleft obligations — escalate to
   legal with the import graph; do not ship until resolved.
3. **PII over-collection to a third party:** email + full search history exceed
   what analytics needs (minimization), with no retention TTL and no erasure path
   (right-to-be-forgotten) — minimize fields, add TTL and deletion.
4. **Consent gap:** default-on telemetry for EU users with no consent gate —
   escalate; gate collection on consent.
5. **SPDX coverage gap:** 41 files missing license headers — add them (REUSE) so
   provenance stays machine-checkable.

## Good → no finding

**Input (compliance scan; product: MIT-licensed library):**
```text
licenses:   all deps MIT/BSD/Apache-2.0; tree scan clean; NOTICE retained for the
            one Apache dep
spdx:       180/180 files carry SPDX headers (REUSE check green)
pii:        none collected (library code; no telemetry)
provenance: no vendored code; SBOM regenerated on release
```
**Expected finding:** None — compatible licenses with attribution retained, full
SPDX coverage, no PII surface, current SBOM. Report
"No findings: compliance and provenance are clean". Do NOT speculate about legal
risk the scan shows no evidence for, and do NOT rule on genuinely legal questions —
escalating those is correct, deciding them is not.
