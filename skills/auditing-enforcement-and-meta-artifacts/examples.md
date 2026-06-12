# Examples — auditing-enforcement-and-meta-artifacts

This is a **repo-shaped** audit: it scans the *machinery around the code* — suppressions, monitoring config, generated artifacts — for accretion and drift across the whole tree, not a single diff. Findings name the meta-artifact and the trend, not a line of product logic.

## Bad → finding (suppression hygiene)

**Input:** `src/legacy/parser.js` opens with a file-wide `/* eslint-disable */`; the detekt baseline grew from 1,011 to 1,204 entries this quarter; 17 eslint-disable directives report as unused.

**Finding:**
> **Major — enforcement is being opted out of, not satisfied.** `parser.js`'s file-wide `/* eslint-disable */` silences *every* rule for the whole file, including ones it isn't violating yet — any future bug introduced there is invisible. Scope it to the specific rules with a reason. Separately, the baseline is **growing** (1,011 → 1,204): a ratchet is only healthy while it shrinks, so new code is silently being allowed to add violations. Gate the baseline count as non-increasing in CI, and sweep the 17 unused disable directives — each masks the next real violation at its location.

## Bad → finding (monitoring-config)

**Input:** alert `HighCPU: cpu_pct > 0.8` with no `for:`, no runbook, no labels; three "API health" dashboard panels query `http_requests_total_v1`, renamed to `_v2` last quarter; monitors are edited by hand in the Grafana UI.

**Finding:**
> **Major — alerting trains responders to ignore it.** `HighCPU` is cause-based (a raw gauge), fires instantly with no `for:`, and links no runbook — it can't be acted on, so it becomes noise. Alert on a user-visible **symptom** (SLO/error-budget burn) with a `for:` window, severity, and a runbook link; run `pint`/`promtool` over the rules. The three dashboard panels point at the dead `http_requests_total_v1` metric — they render empty and give false confidence; repoint or remove them. Move monitors into version control (monitoring-as-code) so this drift is reviewable and restorable.

## Good → "No findings"

**Input:** suppressions all rule-scoped with an issue link, baseline shrinking 420 → 380, zero unused; alerts symptom-based with runbooks and `pint`-clean; CI runs `make generate && git diff --exit-code`.

**Finding:**
> **No findings.** Suppressions are scoped, justified, and trending down; alerts are actionable and lint-clean; generated artifacts are drift-gated in CI. The enforcement apparatus is healthy.

## Output format

- **Severity** (Blocker / Major / Minor / Nit) — **the meta-artifact and location** (the suppression file:line, the alert rule, the generated path) — what's unhealthy, as a *trend or standing condition*, not a one-off — the fix (scope+justify the suppression / make the alert symptom-based + runbooked / add the regenerate-and-diff gate).
- A healthy apparatus gets **"No findings"** — do not invent suppression or drift issues where the scan is clean.
- This audit reviews the *enforcement machinery*; product-logic findings belong to the diff lenses, not here.
