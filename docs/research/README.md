# Research notes

Per-cluster research filed against [`../taxonomy.md`](../taxonomy.md). Each file gathers, **per taxonomy category**, the references, tooling rules, and reviewable heuristics we'd draw on when designing the skill suite.

## Method & format (read by every research agent)

For **each** taxonomy category in scope, produce three sections:

- **Key references** — books, papers, canonical posts, standards. Format `author/org — title` + a stable URL **only when confident it's correct** (else omit, or mark `(verify)`). Each gets a one-line `→ mine:` note: the specific heuristic/idea we'd take from it.
- **Tooling rules worth lifting** — *specific, real* rule identifiers from real static-analysis tools / linters / scanners that map onto the category (e.g. ESLint `no-floating-promises`, RuboCop `Metrics/AbcSize`, Reek `FeatureEnvy`, Bandit `B602`, Semgrep registry rules, CWE IDs, SonarQube rule squids, golangci-lint linters, dependency-cruiser/ArchUnit rules, axe-core rule ids). Give tool + id + one-line meaning. These are pre-validated, real-world heuristics — the point is to learn what experienced teams decided was worth flagging.
- **Reviewable heuristics (skill-checklist seeds)** — concrete, checkable criteria a reviewer or agent could apply to a diff, phrased as crisp checks. These seed the eventual skill checklists.

**Hard rules:** No fabrication — never invent URLs, quotes, or rule IDs; mark uncertainty `(verify)` or omit. Accuracy over completeness. Ground claims in real sources via web research.

## Standing authoring rules

Scoped to **every authored artifact in this repo**, not only the research files: `skills/manifest.yaml` prose, hand-written `examples.md` and `evals/eval.json`, `docs/`, and this file. They exist because each was learned the expensive way — a reviewer caught the defect after it shipped — and because none of them is mechanically checkable in the part that matters. `drift` verifies that generated files match their sources, and `tests/test_examples_conventions.py` verifies that an `examples.md` has an intro and spells its headings the house way — but no test verifies that a sentence is true, or that an intro agrees with the examples beneath it. The form is checkable; the content is why these rules are written down.

### 1. Behavioral claims need the same grounding as identifiers — and don't get it by default

The rule above governs *identifiers* (URLs, quotes, rule IDs), and a section can satisfy it completely while still being wrong: correct tool name, correct doc link, incorrect assertion about what the tool *does*. Treat every claim of the form **"tool X does Y"**, **"format Z permits/forbids W"**, or **"operation V is safe"** as a factual claim requiring its own check against that tool's own documentation at authoring time. Two habits carry most of the weight:

- **State the condition when behavior is conditional.** Most third-party behavior is gated on a setting, a mode, or a field property. Write the gate ("only once column mapping is enabled", "only when the field carries no default"), not the common case as though it were universal.
- **Don't generalize from the worked example.** A heuristic derived from one scenario tends to inherit that scenario's special case as an absolute. Check the general rule separately from the example that motivated it.
- **Check the absolute, not only the claim.** *(added 2026-08-07)* The two habits above catch claims that are **false**. The failure mode that survives them is a claim that is **incomplete** — true in the case that motivated it, wrong as written because its precondition is missing. Asking "is this true?" returns yes and the check passes; the question that catches it is **"is this true unconditionally?"** Superlatives and mechanism claims are the tell — *strictly better*, *always*, *no X permits*, *makes it a compile error*. Each is a promise about every case, and each is cheap to falsify by finding one.

Where a behavioral claim can't be confirmed, `(verify)` applies to it exactly as it does to a rule ID.

*Why this rule exists (2026-08-04).* Categories #40/#41 shipped **four** behavioral claims that were wrong, and the identifier rule could not have caught any of them — every one had a correct tool name and a correct citation:

| Claim as written | What is actually true |
|---|---|
| `long` → `double` is a type change "no compatibility mode permits" | Avro permits numeric promotion: the change is backward-compatible and forward-*in*compatible |
| deleting a field is backward-compatible and forward-incompatible | only when the field carries **no default**; a defaulted field is compatible both ways |
| `dbt build` / `dbt test` described as one behavior | `build` interleaves models and tests and skips downstream resources on an `error`-severity failure; `test` builds nothing |
| "Iceberg and Delta Lake track columns by ID, which makes a **rename** safe" | Iceberg intrinsically; Delta **only** once `delta.columnMapping.mode` is enabled |

Three of the four generalized a worked example's special case into an absolute. All four were caught by external reviewers rather than by the atlas's own review pass, which reads structure and convention reliably and has no step forcing a docs check per behavioral claim. The practice itself is not new — the [G33](../map-gaps.md) pass already corrected "Farley's *seven* properties, not the eight some third-party summaries cite" — it simply was not standing.

*Why the third habit exists (2026-08-07).* Category #42 shipped **two** claims that satisfied the first two habits and were wrong anyway. Both were caught by an external reviewer; the rule as written asked whether they were false, and neither was:

| Claim as written | What is actually true |
|---|---|
| a discriminated union over the UI states "makes the missing branch a compiler error" | only **with an exhaustiveness check** — a `switch` whose `default` hands the value to `assertNever(x: never)`. An `if`/`else if` chain over the same union compiles fine with a variant unhandled |
| "prefer undo over confirmation — strictly better than any dialog" | not when the effect leaves the system as it fires: a delete that propagates to an external index, one that starts a retention or legal-hold workflow, or anything that **revokes** authorization. A 10-second undo on "revoke API key" keeps a compromised key live for ten more seconds |

Both appeared in a lens's **recommended fix**, which is where a half-right claim costs most: it sends the reader to a mechanism that doesn't mechanize.

### 2. A summary must agree with what it summarizes

A preamble, a boundary note, a cross-lens tension line, a heading — anything that describes content living elsewhere in the same artifact — gets written from what that content *should* say and then not read against what it does say. Nothing mechanical catches this: the generator verifies that a heading exists and that a count matches, never that a preamble is consistent with the examples underneath it. On one PR this was **three of the last five findings**.

The habit: **when you write or edit a summary, re-read the thing it summarizes, then decide whether the sentence is still true.** A summary written to satisfy a convention ("every `examples.md` opens with its reporting convention") is especially exposed, because it is composed from the convention rather than from the file.

Two shapes recur, and both read as perfectly reasonable in isolation:

- **The summary is narrower than the content.** *"'No findings' when the flow handles its states"* — while that lens's own fourth example is a routed judgment on a flow that handles every state it reaches. The preamble would have suppressed the example printed two screens beneath it.
- **The summary contradicts the content.** A manifest tension line asserting that `checking-restraint` wins on a case the other lens's `examples.md` surfaces as a routed finding.

### 3. A convention deviation is a session's habit, not a file's slip

When a review flags a convention deviation, **check the pattern across all siblings before fixing the file that was flagged.** These conventions live only in the existing files, so they drift a whole authoring session at a time: the two files under review on PR #208 had both deviations, and sweeping the other 40 found the same pair in a third file merged hours earlier. Fix the set, and prefer mechanizing the convention over rediscovering it — `tests/test_examples_conventions.py` is what that looks like, and it found four pre-existing deviations the moment it was written.

**The rule applies to repairs, not only to originals** *(added 2026-08-07, after it was broken twice in one PR)*. A correction is itself a change, and it drifts the same way: fixing the file the reviewer named leaves every sibling carrying the defect, and now they disagree with the one copy that is right — which is worse than uniform wrongness, because a reader cannot tell which is current. Both cases on that PR were a fix applied at the reported site and nowhere else: an attribution corrected in one of three documents, and a route added to one of the two rows that needed it. **After making a fix, ask what class it belongs to and sweep that**, exactly as you would for the original.

## File template & verification status

File header template:

```text
# Research — Cluster N: <Name>
> Part of code-quality-atlas phase-1 research (see ../taxonomy.md). Generated 2026-06-08 via web research. Citations best-effort; uncertainty flagged inline.

## #n <Category>
### Key references
### Tooling rules worth lifting
### Reviewable heuristics (skill-checklist seeds)
...
## Open threads   (gaps / mis-placements / sub-topics worth deeper research)
```

**Status:** all 6 cluster files written and **web-verified from the main loop (2026-06-09)**; categories promoted since then (see the Index for current membership) are verified at promotion time under the rules above rather than by that sweep. Cluster I is the exemplar (extra-deep). Each file ends with an *Open threads* section feeding [`../map-gaps.md`](../map-gaps.md) and phase-2 design. Residual `(verify)` tags mark niche or fast-moving tool rule IDs, and — per the behavioral-claims rule above — any third-party behavior that could not be confirmed against its own documentation.

## Index

| File | Cluster | Categories |
|---|---|---|
| [`cluster-1-correctness.md`](cluster-1-correctness.md) | I — Correctness & Robustness *(exemplar/template, extra-deep)* | #1–#4 |
| [`cluster-2-readability.md`](cluster-2-readability.md) | II — Readability & Clarity | #5–#8, #35 |
| [`cluster-3-structure.md`](cluster-3-structure.md) | III — Structure & Architecture | #9–#13 |
| [`cluster-4-runtime.md`](cluster-4-runtime.md) | IV — Cross-cutting runtime | #14–#16, #25, #28, #32, #34, #36–#38 |
| [`cluster-5-verification.md`](cluster-5-verification.md) | V — Verification & Supply | #17–#20, #26, #30–#31, #40–#41 |
| [`cluster-6-evolution.md`](cluster-6-evolution.md) | VI — Evolution & humans | #21–#24, #27, #29, #33, #39 |
| [`cluster-7-product.md`](cluster-7-product.md) | VII — Product, Experience & Value *(opened v0.12; G24)* | #42–#44 |

Not a taxonomy cluster, but filed alongside them: [`competitor-landscape.md`](competitor-landscape.md) — a product-landscape pass on commercial AI-native review products (CodeRabbit, Copilot code review, Greptile), feeding [`../map-gaps.md`](../map-gaps.md) G34.
