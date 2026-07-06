# References to mine — auditing-decision-record-currency

## Contents

- From category #39

## From category #39

### Key references

- **Michael Nygard — "Documenting Architecture Decisions" (2011)** (see #29) — the `status` field (proposed/**accepted**/**superseded**/deprecated) is the machine-checkable hook a sweep needs: an ADR still marked `accepted` while a later, contradicting ADR exists with no `Supersedes`/`Superseded-by` link is a currency defect, not just a documentation nicety.
  → mine: a sweep's first, cheapest check is internal consistency of the status field graph across all records, before any judgment about real-world drift.
- **Azure Well-Architected Framework — architecture decision records & maintenance** *(already cited under #29; verified 2026-07-06)* — documents the ADR log as an append-only record with a `Proposed`/`Accepted`/`Superseded` status field and a supersede-and-link pattern; it does **not** itself prescribe a periodic re-scan cadence.
  → mine (extrapolation, not a direct WAF claim): treating "revisit the ADR log" as a *scheduled* activity — the same posture as the suite's other repo-shaped audits — is this lens's own inference from the status-field/supersede-link model, consistent with WAF's structure but going beyond what it explicitly recommends.
- **ThoughtWorks Technology Radar — Adopt / Trial / Assess / Hold** (see #29) — a technology's ring position changes over time (rising, or moving toward **Hold**).
  → mine: an ADR that adopted a technology now sitting on `Hold` or nearing end-of-life is a currency signal a sweep can check against an external feed, independent of any human noticing.
- **RFC 8594 — Sunset HTTP Header Field** (see #29) — deprecation is a *dated* activity.
  → mine: applied to the record itself: a revisit-trigger with no date or measurable condition ("revisit periodically" vs. "revisit if write volume > 10k/s") can't be swept for currency at all — the sweep's first finding on many repos will be "no checkable trigger was ever recorded."
- **`endoflife.date` (API) / Renovate's `endoflife-date` datasource** (see #33) — machine-readable lifecycle signals for an adopted runtime/dependency.
  → mine: cross-referencing an ADR's named technology against an EOL feed turns "has this decision aged out" from a manual re-read into a checkable signal.
