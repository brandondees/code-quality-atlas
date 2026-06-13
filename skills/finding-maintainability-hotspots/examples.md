# Examples — finding-maintainability-hotspots

This skill is repo-shaped: its input is repository history/scan data (churn,
complexity, authorship, co-change), not a single diff. Report each distinct issue
as its own numbered finding. When the scan is healthy, the entire response is exactly this skill's no-finding sentence given in the decision rule below — never a numbered list of findings for a healthy scan.

## Bad → finding

**Input (repo scan, last 12 months):**

```text
file                          commits  authors  cognitive-complexity  todo/hack
billing/invoice_engine.py        87       1            142               9
api/routes.py                    41       6             18               0
models/user.py                   12       4              9               1
```

**Expected finding:**

1. **Hotspot:** `billing/invoice_engine.py` — highest churn × highest complexity;
   refactoring it pays for itself fastest.
2. **Bus factor 1:** a single author owns 87 commits of a 142-complexity file —
   require a second reviewer and knowledge-spreading.
3. **Untracked debt:** nine `TODO/HACK` markers with no linked issues — link them
   to tracked issues or schedule them.
4. `api/routes.py` churns a lot but is simple and shared — fine; not a hotspot.

## Bad → finding

**Input (repo scan, co-change analysis):**

```text
pair                                          co-change rate   import link?
orders/checkout.py <-> email/templates.py          91%              no
orders/checkout.py <-> orders/cart.py              74%              yes
```

**Expected finding:**

1. **Hidden coupling:** `checkout.py` and `email/templates.py` change together in
   91% of commits with no code-level dependency — an implicit contract, likely
   duplicated order-summary formatting. Name the contract and make it explicit
   (shared type or template input builder) so a checkout change can't silently
   break emails.
2. The `checkout <-> cart` coupling is expected — they share a declared import.

## Good → no finding

**Input (repo scan, last 12 months):**

```text
file                          commits  authors  cognitive-complexity  todo/hack
api/handlers.py                  23       5             11           1 (linked #482)
core/pricing.py                  18       4             14           0
lib/utils.py                      9       6              6           0
```

**Expected finding:** None — churn is spread across files with multiple authors,
complexity is modest everywhere, and the one TODO is tracked against an issue.
Report "No findings: no maintainability hotspots in this scan". Do NOT invent a
hotspot from the merely-highest number in a healthy table — hotspot means churn AND
complexity AND concentration compounding, not "something has to be worst."

**Decision rule (apply before naming any hotspot):** a file is a hotspot only when
risk factors *compound* — e.g. cognitive complexity well above a healthy bound
(roughly ≥ 40–50) **together with** heavy churn, or ownership concentrated in 1–2
authors, or a pile of untracked debt markers. A file with modest complexity
(≤ ~20), several authors, and tracked TODOs is healthy **even if it has the highest
numbers in the table** — every table has a maximum row; a maximum is not a finding.
When asked "what should we act on?" and the scan is healthy, the correct,
complete answer is "No findings: no maintainability hotspots in this scan" — do not
pad it with refactoring recommendations for the biggest healthy file.
