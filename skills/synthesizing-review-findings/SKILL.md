---
name: synthesizing-review-findings
description: 'Merges the findings of several code-quality-atlas lenses — and of any
  other review method run alongside them (the built-in code-review skill, a framework
  review like BMAD, linter output, or human notes) — into one review: deduplicates
  issues raised by more than one source, reconciles lenses that pull opposite ways
  (e.g. restraint vs. coverage, cache vs. profile), ranks by severity, and ends on
  a single block/approve verdict. Use after running any set of atlas review lenses
  (and any companion reviewers) on a change — typically 3-8 in standard review mode,
  uncapped in comprehensive mode — when assembling multi-source review output into
  one report, or when overlapping findings need deduplicating and prioritizing.'
provenance:
  taxonomy_version: v0.14
  built_from: []
---

# synthesizing-review-findings

## When to use

Merges the findings of several code-quality-atlas lenses — and of any other review method run alongside them (the built-in code-review skill, a framework review like BMAD, linter output, or human notes) — into one review: deduplicates issues raised by more than one source, reconciles lenses that pull opposite ways (e.g. restraint vs. coverage, cache vs. profile), ranks by severity, and ends on a single block/approve verdict. Use after running any set of atlas review lenses (and any companion reviewers) on a change — typically 3-8 in standard review mode, uncapped in comprehensive mode — when assembling multi-source review output into one report, or when overlapping findings need deduplicating and prioritizing.

**Shape: composition.** Runs after `choosing-review-lenses` has picked the lenses and you have each lens's findings in hand; it produces the single review a human or agent actually reads. It adds no new findings of its own about the reviewed change — it only merges lens findings — though it does apply its own reviewer-discipline guards (below) to how that merge and the surrounding claims are made.

## Fan-out model

Fan-out is **advisory by default**: you run each lens the router named, collect its findings, then apply the steps below to merge them. The finding shape is fixed (see *Finding contract*) so a harness that can invoke lenses in parallel may **mechanize** the same merge — the dedupe and ranking rules are deterministic. Automated or by hand, the output is identical. The same fixed finding shape also lets an orchestrator fan out across **many repositories** — one agent per repo emitting findings in this contract — and aggregate them centrally (see the multi-repo runbook under *Going deeper*).

## How to synthesize

1. **Collect** — gather every lens's findings, tagging each with the lens that raised it. Fold in findings from any **companion reviewer** run alongside the atlas lenses — the built-in code-review skill, a framework review (e.g. BMAD), linter or scanner output, or human notes — tagging each with its source so the merge is non-exclusive rather than atlas-only. A source that reported "No findings" contributes nothing; do not pad the report on its behalf.
2. **Dedupe** — two findings at the **same location with the same root cause** are one finding. Keep the most specific wording and attribute it to the category's **primary owner** (named in each lens's *Shared categories* note); list the other lens only if it adds a distinct angle. Never report a shared finding twice.
3. **Reconcile** — when two lenses pull opposite ways, do not silently drop one. Surface the tension and apply the default below, noting the trade-off so the author can override with evidence.
4. **Rank** — order by severity (**Blocker** > **Major** > **Minor** > **Nit**). A Blocker-level finding floats to the top no matter which lens raised it; correctness, security, and data-loss findings outrank style and nits.
5. **Verdict** — one line at the top: **block**, **approve with changes**, or **approve**. A single Blocker is enough to block; only nits left means approve. **Valence governs the verdict, not route.** A `defect` sets the verdict per its severity *even when its remediation decision is routed elsewhere* — a GPL-incompatible dependency is a blocking defect **and** a `route: legal` escalation, not an "approve" that quietly defers to legal. Route only changes *who decides the fix*, never whether the diff has a problem. Only `improvement` nits and **non-defect** routed findings (a product, design, or leadership judgment call with no defect behind it) are surfaced and escalated without setting the engineering verdict. Likewise a `pre-existing` defect noticed in touched code is surfaced and routed to the implementer *without* setting this PR's verdict — the diff did not introduce it. Same for a floor-tier finding the repo's `.code-quality-atlas/preferences.md` has `acknowledge`d (Q13): it still appears in the report, tagged `acknowledged deviation: <reason>`, but the acknowledgement alone does not drive the verdict to block — the team recorded and accepted it. A `suppress`ed preference-tier finding never reaches this report at all; only `acknowledge` (floor-tier) leaves a visible trace. If every lens found nothing, the whole report is "No findings" — do not manufacture a harsher verdict than the findings justify.
6. **State coverage & limitations** — close the report with what the review did *not* establish: which lenses ran and which the router did not select, anything that could not be verified from the diff alone (needs runtime behavior, production data, or repo-wide context), and any finding asserted without direct evidence. A confident verdict silent on its own blind spots manufactures false assurance — itself a defect of the review. Name the gaps so the reader knows the review's edges. Keep it to a few lines; if coverage was complete and nothing was unverifiable, say so in one line rather than padding. This block is **always present**, including on a "No findings" report.
7. **Note the process** — close with 0-3 one-line observations on the *review process itself*, never on the reviewed code: a lens that should have run per the router's own criteria but didn't, a finding two lenses disagreed on with no entry in the tensions table above, or output that broke the finding contract. This is the suite's own self-improvement signal — every lens carries a one-line prompt to report a misfire here instead of inventing its own feedback format. When the process worked, write exactly "Process: clean" and stop — the same anti-invention discipline the lenses apply to findings, never a note manufactured to fill the section.

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
| `checking-restraint` ↔ `reviewing-conceptual-integrity` | whether a change is "too much" versus whether it fits the product's existing model | Different questions, and they are usually on the same side. Restraint asks whether to build this at all; conceptual integrity asks, given that it ships, whether the product still says one thing. A small, requested, well-scoped change clears restraint and can still add a second noun for an existing idea — that finding stands and restraint does not suppress it. Where both fire on the same addition they agree: report it once, under whichever lens's evidence is concrete, and route the decision. Where they genuinely diverge, restraint's "don't build it" is the cheaper fix and goes first. |
| `reviewing-conceptual-integrity` ↔ `reviewing-usability-and-interaction` | a second way of doing something — a mechanics mismatch or a model mismatch | Split by what the user trips on. A control that behaves differently from its siblings is #42's: the user trips on it in the moment, and the fix is to make it behave like the others. Two concepts covering one job is #44's: the user trips on it when choosing between them, and no amount of making them behave alike helps. A change can carry both, and then both report — but neither restates the other's finding. |
| `reviewing-conceptual-integrity` ↔ `reviewing-api-contract-safety` | an endpoint that is safe and well-formed but invents its own resource model | #13 owns whether the contract is compatible, paginated, and hard to misuse; #44 owns whether it fits the model the rest of the API already teaches. A new endpoint can pass every #13 check and still be the second way to fetch the same resource. Conversely, matching the house model does not excuse an unversioned breaking change. Both stand on their own evidence, and neither lens's ownership sets the verdict: rank them by the severity each reported, exactly as every other pair is ranked. #13's finding is usually the blocking one because #44's is usually routed — an observation about the common case, not a rule that outranks a #44 defect. |
| `reviewing-observability-and-operability` ↔ `auditing-compliance-and-provenance` | how much to log for operability vs. keeping PII and secrets out of logs | Log enough to operate and debug, but never PII, secrets, or regulated data in the clear — redact or tokenize at the logging boundary. Privacy wins on any field that could identify a person; add scrubbed, structured fields rather than dropping the observability. |
| `sweeping-for-security` ↔ `reviewing-usability-and-interaction` | protective friction (a confirmation, a re-auth, a rate limit) vs. a flow the user can actually complete | Friction that defends a real, named threat stands — say which threat, and the usability finding becomes a request to make the friction cheaper, not to remove it. Friction with no threat behind it is an unconsidered flow and #42 wins. Where the trade-off is genuine (how many confirmations, where the step sits), surface both readings and route the call to design rather than settling it in an engineering review. Distinct from the security ↔ ethical-design pair: that one is about friction someone benefits from, this one about friction nobody does. |
| `checking-restraint` ↔ `reviewing-usability-and-interaction` | designing a screen for every state vs. not building surfaces nobody hits | Handle the states the code can actually reach — if the fetch can fail, the error state is reachable and its absence is a defect, not gold-plating. Restraint wins on states the code cannot produce and on polish beyond a plainly handled state. On a fourth variant of an existing pattern the two lenses agree rather than compete: restraint says don't build another one, #42 says users were taught the existing one — so the finding still surfaces with its evidence and the decision routes to design. Restraint never suppresses a consistency finding; it argues against adding surface. |
| `checking-restraint` ↔ `reviewing-outcome-instrumentation` | instrumenting the change vs. adding telemetry and flags nobody reads | Instrument the outcome the change actually claims, and nothing else. Restraint wins by default on telemetry unrelated to that claim: a refactor or bug fix owes no hypothesis, "track everything" is its own failure mode, and each event carries cost and a PII surface (#27). Where a claimed benefit has no observation at all, name the **smallest missing signal** — often one event, sometimes an existing event or dashboard that already covers it, in which case there is no finding. The exception is an experiment or rollout: assignment and exposure records, the losing condition, the relevant guardrails, and flag ownership are what make the result interpretable at all, so restraint does not trade them away as surplus telemetry. |
| `reviewing-ethical-design` ↔ `reviewing-outcome-instrumentation` | a metric the change moves vs. whether a reasonable user would have chosen the behavior that moves it | Goodhart's seam. A win on a proxy metric (clicks, session length, DAU) that a reasonable user would not have chosen is not a win — surface both readings together, name the proxy and what it stood for, and route the call to product. Neither lens adjudicates it: #36 does not veto a shipped metric and #43 does not certify one as success. If the mechanism moving the metric is itself a dark pattern, that is #36's finding on its own terms and keeps its severity. |
| `reviewing-performance-and-efficiency` ↔ `reviewing-accessibility-and-i18n` | a leaner/faster UI vs. accessible markup and assistive-tech support | Accessibility is a correctness requirement, not an optimization to trade away. Keep the accessible markup and hit the performance target another way (lazy-load, code-split, cache). Drop a11y only against a measured budget proving no other path exists — which is almost never. |
| `checking-restraint` ↔ `reviewing-install-and-upgrade-experience` | backward-compat shims and deprecation windows for consumers vs. removing the old path now | Keep the old path working for one deprecation window with a warning that names the replacement whenever the project has external consumers; remove in place only for internal-only or never-released surface. Consumer smoothness wins while real adopters exist; restraint wins when there are none. |
| `checking-idioms-and-consistency` ↔ `finding-maintainability-hotspots` | matching the existing pattern vs. changing it to reduce future churn | Stay consistent with the established idiom by default; diverge only when the current pattern is a demonstrated maintenance hotspot (high change-amplification or repeated edits) and the new form measurably lowers that cost. Consistency wins until evolvability has evidence. |
| `checking-restraint` ↔ `reviewing-data-transformations-and-contracts` | how much data-test and data-contract ceremony a new model or event schema needs | Require the tests that pin the model's grain and the columns consumers actually read, and a versioned contract only where a real consumer outside this change exists; skip blanket per-column expectation suites and contract machinery on an internal, single-consumer model. Restraint wins on breadth — but a missing grain/uniqueness test on a fanned-out join, or a consumer-breaking schema change with no compatibility gate, is a defect rather than gold-plating and stands. |
| `sweeping-for-security` ↔ `reviewing-ethical-design` | added friction or a confirmation step — a protective safety control vs. manipulative obstruction | Keep friction that protects the user or prevents abuse (confirmations on destructive or irreversible actions, step-up auth on high-consequence operations, a cooling-off period); cut friction that serves the business against the user's clear intent (hard-to-cancel, buried opt-out, roach-motel flows). Security's protective friction wins; obstruction does not — the test is whose interest the friction serves, not its presence. |

For a tension not in this table, prefer the **safer and simpler** option, and say what evidence would change the call.

## Finding contract

Normalize every lens finding to this shape before merging — it is what makes dedupe and ranking mechanical:

- **location** — file and line/range, or a design-time `boundary:<from>→<to>` / `component:<name>` reference when a finding lives at an architecture boundary rather than a code line (the dedupe key, with root cause — two findings at the same location and root cause merge regardless of which lens raised them)
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

Non-blocking (advisory) — below the floor, not actionable
- <severity> · <location> — <one-clause description> (<lens>)

Tensions
- <lens> ↔ <lens>: <how it was resolved here>

Coverage & limitations
- Lenses run: <names>. Not selected: <names, or "none">.
- Not verifiable from this diff: <what needs runtime, data, or repo-wide context to confirm, or "nothing">.

Process notes
- <one-line process observation>, or exactly "Process: clean" if none.
```

Omit any **findings** section with nothing in it — including **Routed**, **Improvements**, **Pre-existing** (the last two are absent entirely unless the team opted into improvement-valence / Boy-Scout surfacing), and **Non-blocking (advisory)**. **Coverage & limitations** and **Process notes** are the exceptions: both are always present, even on a "No findings" report. Keep each finding to one or two lines; the detail lives in the originating lens's output, not restated here.

**Non-blocking (advisory) is not a dumping ground for every below-floor observation** — it is specifically the findings a floor (mode or round) dropped from the ranked sections above; a mode with no floor configured (`manifest.modes` empty) never populates it. List each as *severity · location · one clause* — never restate a finding already ranked above at its full detail. This section is informational only: it never sets the verdict, is never posted as an inline review thread, and the implementer may apply, defer, or ignore each item freely.

## Severity floor by mode

The merged report's severity floor depends on the active depth mode. Below the floor, a finding is dropped from the ranked, verdict-setting sections — not from the report: it still surfaces in the Non-blocking (advisory) list (see Output format below).

| Mode | Floor | Effect |
|---|---|---|
| **triage** | Major | pinned at Major — ranked sections report everything down to Major; below that, the advisory list only |
| **review** | escalating | round-based escalation — later re-review rounds raise the floor |
| **comprehensive** | Nit | pinned at Nit — ranked sections report everything down to Nit; below that, the advisory list only |

## Reviewer discipline

Synthesis must not inflate. Do not raise a finding no lens reported, do not upgrade a severity to seem thorough, and do not turn "No findings" into a verdict with changes. The merged report is exactly the union of real lens findings, deduplicated and ordered — nothing added.

**Check standing disputes before affirming a claim.** Before **affirming** any claim you did not independently re-derive — your own earlier reasoning, a lens's conclusion, or a statement under review — scan the PR's existing comment threads and prior review rounds for a standing dispute of that exact claim. If one exists, treat the claim as **unresolved**, not settled: say so and re-derive it, rather than repeating it as correct. A standing dispute does not make the disputing comment automatically right either — you still adjudicate, you just may not skip the adjudication. This targets a sharper failure than a lens silently missing a check: a *confident, positive affirmation* of something already on the record as disputed, which reads as more authoritative than a miss and is easy to mistake for verification.

## Going deeper

- [choosing-review-lenses](../choosing-review-lenses/SKILL.md) — the front half: picks which lenses to run before you synthesize their output.
- [multi-repo audit runbook](https://github.com/brandondees/code-quality-atlas/blob/main/docs/runbooks/multi-repo-audit.md) — fan the suite out across many repositories with background agents and aggregate their findings through this contract.
- [self-improvement loop](https://github.com/brandondees/code-quality-atlas/blob/main/docs/self-improvement-loop.md) — why Process notes exist, the opt-in feedback tiers a repo can turn on to keep them (`.code-quality-atlas/preferences.md`), and where the signal goes from there.
