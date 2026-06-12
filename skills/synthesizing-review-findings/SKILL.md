---
name: synthesizing-review-findings
description: 'Merges the findings of several code-quality-atlas lenses into one review:
  deduplicates issues raised by more than one lens, reconciles lenses that pull opposite
  ways (e.g. restraint vs. coverage, cache vs. profile), ranks by severity, and ends
  on a single block/approve verdict. Use after running 2-4 review lenses on a change,
  when assembling multi-lens output into one report, or when overlapping reviewers''
  findings need deduplicating and prioritizing.'
provenance:
  taxonomy_version: v0.3
  built_from: []
---

# synthesizing-review-findings

## When to use

Merges the findings of several code-quality-atlas lenses into one review: deduplicates issues raised by more than one lens, reconciles lenses that pull opposite ways (e.g. restraint vs. coverage, cache vs. profile), ranks by severity, and ends on a single block/approve verdict. Use after running 2-4 review lenses on a change, when assembling multi-lens output into one report, or when overlapping reviewers' findings need deduplicating and prioritizing.

**Shape: composition.** Runs after `choosing-review-lenses` has picked the lenses and you have each lens's findings in hand; it produces the single review a human or agent actually reads. It adds no new checks of its own — it only merges.

## Fan-out model

Fan-out is **advisory by default**: you run each lens the router named, collect its findings, then apply the steps below to merge them. The finding shape is fixed (see *Finding contract*) so a harness that can invoke lenses in parallel may **mechanize** the same merge — the dedupe and ranking rules are deterministic. Automated or by hand, the output is identical.

## How to synthesize

1. **Collect** — gather every lens's findings, tagging each with the lens that raised it. A lens that reported "No findings" contributes nothing; do not pad the report on its behalf.
2. **Dedupe** — two findings at the **same location with the same root cause** are one finding. Keep the most specific wording and attribute it to the category's **primary owner** (named in each lens's *Shared categories* note); list the other lens only if it adds a distinct angle. Never report a shared finding twice.
3. **Reconcile** — when two lenses pull opposite ways, do not silently drop one. Surface the tension and apply the default below, noting the trade-off so the author can override with evidence.
4. **Rank** — order by severity (**Blocker** > **Major** > **Minor** > **Nit**). A Blocker-level finding floats to the top no matter which lens raised it; correctness, security, and data-loss findings outrank style and nits.
5. **Verdict** — one line at the top: **block**, **approve with changes**, or **approve**. A single Blocker is enough to block; only nits left means approve. If every lens found nothing, the whole report is "No findings" — do not manufacture a harsher verdict than the findings justify.

## Reconciling lens tensions

When the change trips one of these known opposing pairs, apply the default and state the trade-off:

| Tension | About | Default resolution |
|---|---|---|
| `checking-restraint` ↔ `reviewing-module-design` | a new abstraction or boundary — one lens brakes, one wants the seam | Favor the simplest design the current requirements justify; add the boundary only once a second concrete consumer exists. Restraint wins until then. |
| `checking-restraint` ↔ `reviewing-performance-and-efficiency` | hand-optimization without a profile | No optimization lands without a profile showing the hot path. Performance wins only on measured evidence; otherwise keep the simple version. |
| `checking-restraint` ↔ `reviewing-test-quality` | how much test coverage is enough | Cover the behavior and a regression test for any fixed bug; stop at coverage that only pins implementation detail. More tests is not automatically better. |
| `checking-restraint` ↔ `reviewing-api-contract-safety` | new validation or surface "to be safe" vs. leaving it out | "When in doubt, leave it out" — minimal new public surface wins; add validation only on surface that actually ships now. |
| `reviewing-performance-and-efficiency` ↔ `reviewing-naming-and-readability` | a fast but cryptic form vs. a clear but slower one | Keep the readable form unless a profile proves the clear version is the bottleneck; if the fast form must stay, require a comment explaining why. |

For a tension not in this table, prefer the **safer and simpler** option, and say what evidence would change the call.

## Finding contract

Normalize every lens finding to this shape before merging — it is what makes dedupe and ranking mechanical:

- **location** — file and line/range (the dedupe key, with root cause)
- **severity** — one of the levels above
- **lens** — which lens raised it (the primary owner after dedupe)
- **finding** — what is wrong, concretely
- **fix** — the suggested change, or the evidence needed to decide

## Output format

```
Verdict: <block | approve with changes | approve> — <one-line reason>

Blocker
- <location> — <finding> (<lens>). <fix>

Major
- <location> — <finding> (<lens>). <fix>

Tensions
- <lens> ↔ <lens>: <how it was resolved here>
```

Omit any severity section with no findings. Keep each finding to one or two lines; the detail lives in the originating lens's output, not restated here.

## Reviewer discipline

Synthesis must not inflate. Do not raise a finding no lens reported, do not upgrade a severity to seem thorough, and do not turn "No findings" into a verdict with changes. The merged report is exactly the union of real lens findings, deduplicated and ordered — nothing added.

## Going deeper

- [choosing-review-lenses](../choosing-review-lenses/SKILL.md) — the front half: picks which lenses to run before you synthesize their output.
