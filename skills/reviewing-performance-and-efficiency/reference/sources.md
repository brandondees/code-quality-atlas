# References to mine — reviewing-performance-and-efficiency

## Contents
- From category #15

## From category #15

### Key references
- **Brendan Gregg — Systems Performance (and the USE method)** — http://www.brendangregg.com/usemethod.html → mine: measure before optimizing; for each resource check Utilization, Saturation, Errors. Anchors the "profile, don't guess" discipline reviews should enforce.
- **Donald Knuth — "Structured Programming with go to Statements" (1974)** → mine: the actual provenance of "premature optimization is the root of all evil (97% of the time)" — and its often-dropped corollary: *do* optimize the critical 3%. Use to keep the counterweight balanced, not absolutist.
- **Martin Fowler — "Yet Another Optimization Article" / refactoring + performance writing** → mine: optimize against a measured performance profile, not intuition; keep code clean first because clean code is easier to make fast.
- **Brendan Gregg — Flame Graphs** — https://www.brendangregg.com/flamegraphs.html → mine: hot-path identification is visual and data-driven; a review claiming a perf problem should be able to point at a profile, not a vibe.
- **web.dev — Core Web Vitals (LCP, INP, CLS)** — https://web.dev/articles/vitals/ → mine: the canonical, user-centric frontend perf budget, judged at the **p75** of real users. Thresholds: **LCP ≤ 2.5s** (loading), **INP ≤ 200ms** (responsiveness — **replaced FID on 2024-03-12**), **CLS ≤ 0.1** (visual stability). Bundle/startup work should be justified against these.
- **AWS / FinOps Foundation — FinOps Framework** — https://www.finops.org/ → mine: cloud-cost as a first-class efficiency axis (right-sizing, egress, idle resources, per-request cost) — the FinOps facet of #15.
