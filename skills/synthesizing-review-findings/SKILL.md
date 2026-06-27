---
name: synthesizing-review-findings
description: 'Merges the findings of several code-quality-atlas lenses — and of any
  other review method run alongside them (the built-in code-review skill, a framework
  review like BMAD, linter output, or human notes) — into one review: deduplicates
  issues raised by more than one source, reconciles lenses that pull opposite ways
  (e.g. restraint vs. coverage, cache vs. profile), ranks by severity, and ends on
  a single block/approve verdict. Use after running 2-4 review lenses (and any companion
  reviewers) on a change, when assembling multi-source review output into one report,
  or when overlapping findings need deduplicating and prioritizing.'
provenance:
  taxonomy_version: v0.8
  built_from: []
---

# synthesizing-review-findings

## When to use

Merges the findings of several code-quality-atlas lenses — and of any other review method run alongside them (the built-in code-review skill, a framework review like BMAD, linter output, or human notes) — into one review: deduplicates issues raised by more than one source, reconciles lenses that pull opposite ways (e.g. restraint vs. coverage, cache vs. profile), ranks by severity, and ends on a single block/approve verdict. Use after running 2-4 review lenses (and any companion reviewers) on a change, when assembling multi-source review output into one report, or when overlapping findings need deduplicating and prioritizing.

**Shape: composition.** Runs after `choosing-review-lenses` has picked the lenses and you have each lens's findings in hand; it produces the single review a human or agent actually reads. It adds no new checks of its own — it only merges.

## Fan-out model

Fan-out is **advisory by default**: you run each lens the router named, collect its findings, then apply the steps below to merge them. The finding shape is fixed (see *Finding contract*) so a harness that can invoke lenses in parallel may **mechanize** the same merge — the dedupe and ranking rules are deterministic. Automated or by hand, the output is identical. The same fixed finding shape also lets an orchestrator fan out across **many repositories** — one agent per repo emitting findings in this contract — and aggregate them centrally (see the multi-repo runbook under *Going deeper*).

## How to synthesize

1. **Collect** — gather every lens's findings, tagging each with the lens that raised it. Fold in findings from any **companion reviewer** run alongside the atlas lenses — the built-in code-review skill, a framework review (e.g. BMAD), linter or scanner output, or human notes — tagging each with its source so the merge is non-exclusive rather than atlas-only. A source that reported "No findings" contributes nothing; do not pad the report on its behalf.
2. **Dedupe** — two findings at the **same location with the same root cause** are one finding. Keep the most specific wording and attribute it to the category's **primary owner** (named in each lens's *Shared categories* note); list the other lens only if it adds a distinct angle. Never report a shared finding twice.
3. **Reconcile** — when two lenses pull opposite ways, do not silently drop one. Surface the tension and apply the default below, noting the trade-off so the author can override with evidence.
4. **Rank** — order by severity (**Blocker** > **Major** > **Minor** > **Nit**). A Blocker-level finding floats to the top no matter which lens raised it; correctness, security, and data-loss findings outrank style and nits.
5. **Verdict** — one line at the top: **block**, **approve with changes**, or **approve**. A single Blocker is enough to block; only nits left means approve. **Valence governs the verdict, not route.** A `defect` sets the verdict per its severity *even when its remediation decision is routed elsewhere* — a GPL-incompatible dependency is a blocking defect **and** a `route: legal` escalation, not an "approve" that quietly defers to legal. Route only changes *who decides the fix*, never whether the diff has a problem. Only `improvement` nits and **non-defect** routed findings (a product, design, or leadership judgment call with no defect behind it) are surfaced and escalated without setting the engineering verdict. Likewise a `pre-existing` defect noticed in touched code is surfaced and routed to the implementer *without* setting this PR's verdict — the diff did not introduce it. If every lens found nothing, the whole report is "No findings" — do not manufacture a harsher verdict than the findings justify.
6. **State coverage & limitations** — close the report with what the review did *not* establish: which lenses ran and which the router did not select, anything that could not be verified from the diff alone (needs runtime behavior, production data, or repo-wide context), and any finding asserted without direct evidence. A confident verdict silent on its own blind spots manufactures false assurance — itself a defect of the review. Name the gaps so the reader knows the review's edges. Keep it to a few lines; if coverage was complete and nothing was unverifiable, say so in one line rather than padding. This block is **always present**, including on a "No findings" report.

## Reconciling lens tensions

When the change trips one of these known opposing pairs, apply the default and state the trade-off:

| Tension | About | Default resolution |
|---|---|---|
| `checking-restraint` ↔ `reviewing-module-design` | a new abstraction or boundary — one lens brakes, one wants the seam | Favor the simplest design the current requirements justify; add the boundary only once a second concrete consumer exists. Restraint wins until then. |
| `checking-restraint` ↔ `reviewing-performance-and-efficiency` | hand-optimization without a profile | No optimization lands without a profile showing the hot path. Performance wins only on measured evidence; otherwise keep the simple version. |
| `checking-restraint` ↔ `reviewing-test-quality` | how much test coverage is enough | Cover the behavior and a regression test for any fixed bug; stop at coverage that only pins implementation detail. More tests is not automatically better. |
| `checking-restraint` ↔ `reviewing-api-contract-safety` | new validation or surface "to be safe" vs. leaving it out | "When in doubt, leave it out" — minimal new public surface wins; add validation only on surface that actually ships now. |
| `reviewing-performance-and-efficiency` ↔ `reviewing-naming-and-readability` | a fast but cryptic form vs. a clear but slower one | Keep the readable form unless a profile proves the clear version is the bottleneck; if the fast form must stay, require a comment explaining why. |
| `checking-restraint` ↔ `reviewing-resilience-and-scalability` | defensive resilience machinery (retries, circuit breakers, multi-region, extra replicas) vs. simplicity | Add resilience in proportion to the availability/scale target and the failure modes the system will actually face; do not engineer for scale or failures with no stated requirement. Restraint wins absent an SLO or scale target — but a real unbounded queue, missing timeout, or untested restore is a correctness/operability defect, not gold-plating, and stands. |
| `reviewing-observability-and-operability` ↔ `auditing-compliance-and-provenance` | how much to log for operability vs. keeping PII and secrets out of logs | Log enough to operate and debug, but never PII, secrets, or regulated data in the clear — redact or tokenize at the logging boundary. Privacy wins on any field that could identify a person; add scrubbed, structured fields rather than dropping the observability. |
| `reviewing-performance-and-efficiency` ↔ `reviewing-accessibility-and-i18n` | a leaner/faster UI vs. accessible markup and assistive-tech support | Accessibility is a correctness requirement, not an optimization to trade away. Keep the accessible markup and hit the performance target another way (lazy-load, code-split, cache). Drop a11y only against a measured budget proving no other path exists — which is almost never. |
| `checking-restraint` ↔ `reviewing-install-and-upgrade-experience` | backward-compat shims and deprecation windows for consumers vs. removing the old path now | Keep the old path working for one deprecation window with a warning that names the replacement whenever the project has external consumers; remove in place only for internal-only or never-released surface. Consumer smoothness wins while real adopters exist; restraint wins when there are none. |
| `checking-idioms-and-consistency` ↔ `finding-maintainability-hotspots` | matching the existing pattern vs. changing it to reduce future churn | Stay consistent with the established idiom by default; diverge only when the current pattern is a demonstrated maintenance hotspot (high change-amplification or repeated edits) and the new form measurably lowers that cost. Consistency wins until evolvability has evidence. |
| `sweeping-for-security` ↔ `reviewing-ethical-design` | added friction or a confirmation step — a protective safety control vs. manipulative obstruction | Keep friction that protects the user or prevents abuse (confirmations on destructive or irreversible actions, step-up auth on high-consequence operations, a cooling-off period); cut friction that serves the business against the user's clear intent (hard-to-cancel, buried opt-out, roach-motel flows). Security's protective friction wins; obstruction does not — the test is whose interest the friction serves, not its presence. |

For a tension not in this table, prefer the **safer and simpler** option, and say what evidence would change the call.

## Finding contract

Normalize every lens finding to this shape before merging — it is what makes dedupe and ranking mechanical:

- **location** — file and line/range (the dedupe key, with root cause)
- **severity** — one of the levels above
- **valence** — `defect` (something is wrong) or `improvement` (a correct thing could be better). Defects are the default and drive the verdict; improvements are opt-in, `nit`-severity, and `route: implementer`.
- **route** — who decides: `eng` (the default — engineering owns it), `implementer` (the change's author applies/defers/ignores), or `product` / `design` / `legal` / `leadership` when the decision authority sits outside engineering.
- **attribution** — `introduced` (the default — this change caused it) or `pre-existing` (a real defect already present in the code this PR touches). A `pre-existing` finding is surfaced for the author's awareness, `route: implementer`, and does **not** set this PR's verdict — the diff did not introduce it; keep it scoped to touched code, opt-in, and default-quiet.
- **lens** — which lens raised it (the primary owner after dedupe)
- **finding** — what is wrong, concretely
- **fix** — the suggested change, or the evidence needed to decide

### Surfacing, routing, and valence

Two axes sit alongside severity and govern what the merged report does with each finding:

- **Detect-and-route (surfacing ≠ deciding).** A holistic review surfaces every reviewable finding with its evidence and routes the *decision* to the right owner via `route:`. It never silently drops a finding because "that's not engineering's call," and never adjudicates a call that is not engineering's — legal exposure, a product trade-off, a leadership priority are surfaced under their route and escalated, not decided here. Routing names *who decides the remediation*; it never downgrades a finding's severity or valence. A finding that is both a `defect` and routed (a GPL dependency: `valence: defect, route: legal`) keeps its verdict weight in its severity section **and** carries the route tag for escalation. The only thing that stays out is a concern with no artifact at review time (market sizing, pricing, org politics); it re-enters once written into a decision record.
- **Valence + anti-churn.** `defect` findings carry the strict anti-false-positive bar and set the verdict. `improvement` findings are admissible only when the team has opted up — the default is defect-only — and only as `nit`-severity, `route: implementer` suggestions the author may apply, defer, or ignore. Every improvement must clear a non-configurable **anti-churn floor**: it must genuinely improve (never a merely equivalent alternative) and must converge — no oscillation (A→B then B→A) and no lateral re-ordering once a dimension is as good as it can confidently be made. A team can turn improvement verbosity up; it cannot configure the suite to churn.
- **Attribution (Boy-Scout, scoped).** A genuine defect this change did not introduce, but that sits in the code the PR *touches*, is surfaceable — tagged `pre-existing — not introduced by this change`. Like an improvement it is opt-in and default-quiet, `route: implementer`, and non-blocking: it never sets the verdict, because the diff did not cause it. Keep it scoped to touched code (a repo-wide sweep is the audits' job, not a diff review) and never let it expand the PR's scope; it only informs the author's fix-now / file-a-ticket / ignore call. This is the attribution axis — reviewable is not the same as introduced-here, just as it is not the same as who-decides (route) or defect-vs-improvement (valence).

## Output format

```text
Verdict: <block | approve with changes | approve> — <one-line reason>

Blocker
- <location> — <finding> (<lens>). <fix>

Major
- <location> — <finding> (<lens>) [route: legal]. <fix> — escalate the decision to <owner>

Routed — non-defect decisions outside engineering
- <location> — <finding> (<lens>) [route: product|design|legal|leadership]. <what must be decided, and by whom>

Improvements — opt-in, optional
- <location> — <suggestion> (<lens>) [improvement, route: implementer]. <apply | defer | ignore>

Pre-existing — noticed in touched code, not introduced here
- <location> — <defect> (<lens>) [pre-existing, route: implementer]. <fix now | file a ticket | ignore>

Tensions
- <lens> ↔ <lens>: <how it was resolved here>

Coverage & limitations
- Lenses run: <names>. Not selected: <names, or "none">.
- Not verifiable from this diff: <what needs runtime, data, or repo-wide context to confirm, or "nothing">.
```

Omit any **findings** section with nothing in it — including **Routed**, **Improvements**, and **Pre-existing** (the last two are absent entirely unless the team opted into improvement-valence / Boy-Scout surfacing). **Coverage & limitations** is the exception: it is always present, even on a "No findings" report. Keep each finding to one or two lines; the detail lives in the originating lens's output, not restated here.

## Severity floor by mode

The merged report's severity floor depends on the active depth mode. Below the floor, findings are omitted from the verdict.

| Mode | Floor | Effect |
|---|---|---|
| **triage** | Major | pinned at Major — report everything down to Major, nothing below |
| **review** | escalating | round-based escalation (as today) — later re-review rounds raise the floor |
| **comprehensive** | Nit | pinned at Nit — report everything down to Nit, nothing below |

## Reviewer discipline

Synthesis must not inflate. Do not raise a finding no lens reported, do not upgrade a severity to seem thorough, and do not turn "No findings" into a verdict with changes. The merged report is exactly the union of real lens findings, deduplicated and ordered — nothing added.

## Going deeper

- [choosing-review-lenses](../choosing-review-lenses/SKILL.md) — the front half: picks which lenses to run before you synthesize their output.
- [multi-repo audit runbook](../../docs/runbooks/multi-repo-audit.md) — fan the suite out across many repositories with background agents and aggregate their findings through this contract.
