# Research notes

Per-cluster research filed against [`../taxonomy.md`](../taxonomy.md). Each file gathers, **per taxonomy category**, the references, tooling rules, and reviewable heuristics we'd draw on when designing the skill suite.

## Method & format (read by every research agent)

For **each** taxonomy category in scope, produce three sections:

- **Key references** — books, papers, canonical posts, standards. Format `author/org — title` + a stable URL **only when confident it's correct** (else omit, or mark `(verify)`). Each gets a one-line `→ mine:` note: the specific heuristic/idea we'd take from it.
- **Tooling rules worth lifting** — *specific, real* rule identifiers from real static-analysis tools / linters / scanners that map onto the category (e.g. ESLint `no-floating-promises`, RuboCop `Metrics/AbcSize`, Reek `FeatureEnvy`, Bandit `B602`, Semgrep registry rules, CWE IDs, SonarQube rule squids, golangci-lint linters, dependency-cruiser/ArchUnit rules, axe-core rule ids). Give tool + id + one-line meaning. These are pre-validated, real-world heuristics — the point is to learn what experienced teams decided was worth flagging.
- **Reviewable heuristics (skill-checklist seeds)** — concrete, checkable criteria a reviewer or agent could apply to a diff, phrased as crisp checks. These seed the eventual skill checklists.

**Hard rules:** No fabrication — never invent URLs, quotes, or rule IDs; mark uncertainty `(verify)` or omit. Accuracy over completeness. Ground claims in real sources via web research.

File header template:

```
# Research — Cluster N: <Name>
> Part of code-quality-atlas phase-1 research (see ../taxonomy.md). Generated 2026-06-08 via web research. Citations best-effort; uncertainty flagged inline.

## #n <Category>
### Key references
### Tooling rules worth lifting
### Reviewable heuristics (skill-checklist seeds)
...
## Open threads   (gaps / mis-placements / sub-topics worth deeper research)
```

**Status:** all 6 cluster files written and **web-verified from the main loop (2026-06-09)**. Cluster I is the exemplar (extra-deep). Each file ends with an *Open threads* section feeding [`../map-gaps.md`](../map-gaps.md) and phase-2 design. Residual `(verify)` tags mark only niche/fast-moving tool rule IDs.

## Index

| File | Cluster | Categories |
|---|---|---|
| [`cluster-1-correctness.md`](cluster-1-correctness.md) | I — Correctness & Robustness *(exemplar/template, extra-deep)* | #1–#4 |
| [`cluster-2-readability.md`](cluster-2-readability.md) | II — Readability & Clarity | #5–#8 |
| [`cluster-3-structure.md`](cluster-3-structure.md) | III — Structure & Architecture | #9–#13 |
| [`cluster-4-runtime.md`](cluster-4-runtime.md) | IV — Cross-cutting runtime | #14, #15, #16, #25 |
| [`cluster-5-verification.md`](cluster-5-verification.md) | V — Verification & Supply | #17–#20, #26 |
| [`cluster-6-evolution.md`](cluster-6-evolution.md) | VI — Evolution & humans | #21–#24, #27 |
