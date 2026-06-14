# Product, Experience & Value — reopening the scope boundary

**Status:** synthesized 2026-06-14. **Candidate — provisional, owner-gated.** A scope-principle revision (G23) plus a candidate seventh topic cluster (G24). No `taxonomy.md` edit yet.
**Motivation:** the owner challenged the recurring "product / UX is out of scope" boundary (round 2 axis D; round 3 §scope-boundaries; round 3 G18 "end-user usability out of scope"). The challenge is correct, and it exposes a new gap-finding method: **audit the exclusions themselves** — when something was fenced off, was it fenced on the right axis?

## The method — re-audit the scope boundary

Rounds 1–3 found gaps *inside* the map's scope. This pass questions the *edge* of the scope. The atlas has excluded "product / UX / value" with phrases like *"out-of-scope (governance/legal/product, not code-review)"* and *"end-user product validation out of scope."* Pulling on that thread reveals the exclusion was drawn on the **wrong axis**.

> **The conflation (G23).** "Out of scope" bundled two independent questions: **(1) Is it visible/reviewable at review time?** and **(2) Who has the authority to decide it?** Product/UX/value findings often answer *no* to (2) — an engineer shouldn't unilaterally decide a product trade-off — but *yes* to (1): a confusing error message, a missing empty-state, a deceptive default, an un-instrumented feature whose success can't be measured are all **right there in the diff.** The map already owns the resolution for exactly this shape: **G8 detect-and-escalate** — the compliance/licensing lens *surfaces* legal exposure with evidence and *routes the decision to a human*, never adjudicating law itself.

**Generalize G8 into a standing principle — detect-and-route.** A holistic review **surfaces** a finding with evidence and **routes the decision to the right stakeholder** (PM, designer, legal, leadership), tagged by who decides. Surfacing is not deciding. Under this principle the only things truly out of scope are those with **no artifact at review time at all** (market sizing, pricing strategy, org politics) — and even those, once written into an ADR/RFC, become #29 decision-shaped.

This is consistent with the project's own founding rationale ([`overview.md`](../overview.md)): *"a narrow 'intrinsic only' map would push the most expensive failure modes out of scope."* The same logic extends one step further — **product/UX/value failures are often the *most* expensive of all** (a shipped feature nobody can use, a default that erodes trust, a flow that loses users), and the maximal-scope mandate (D2) should cover them too. The exclusion was under-reach dressed as restraint.

## G23 — Detect-and-route: surfacing ≠ deciding (the scope-principle fix)

Promote G8 from a compliance-lens footnote to a **map-wide disposition primitive**. Every lens may carry findings whose *decider* is not the engineer; those are surfaced at review time, marked with a **route** (`route: product` / `design` / `legal` / `leadership` / `eng`) and never silently dropped for "not our call." The synthesizer (D12) already ranks and routes by severity; add a **decider/route axis** alongside severity so product/UX/value findings land in the report addressed to the right owner rather than being filtered out. This is the enabling mechanism for G24.

**Disposition (lean): adopt** as a cross-cutting principle (low-risk, additive; it formalizes existing G8 behavior and the D12 contract). Confidence: high.

## G24 — Candidate Cluster VII: Product, Experience & Value

The six existing clusters are all about **the code and its lifecycle** (does it work / can humans read it / is it well-designed / runtime qualities / the system around it / evolution & process). **None is about the product as experienced and valued by the humans who use it.** That is a topic-cluster-sized hole — not a shape or a unit (rounds 2–3), a genuine *topic* axis the map never carved. Below, each candidate lens with its external completeness model, shape, overlap, and detect-and-route disposition. All carry **skip-when: no user-facing surface** (backend/CLI/lib/infra), mirroring the existing a11y/LLM skip-clauses.

| # | Candidate lens | What it surfaces (diff-visible) | External model / prior art | Overlap | Disposition |
|---|---|---|---|---|---|
| **VII-A** | **Usability & interaction quality** | Confusing flows, no system-status feedback, no undo on destructive actions, recognition-vs-recall failures, inconsistent controls, poor error-recovery UX | **Nielsen's 10 usability heuristics** (the canonical UX completeness model; heuristic eval is "the default method for surfacing usability issues") | net-new (≠ #23 a11y mechanics) | **promote (lens), route: design/product** |
| **VII-B** | **Experiential / perceived quality** | Missing empty/loading/error/zero-data states, spinner instead of skeleton, no optimistic UI, janky transitions, perceived slowness | perceived-performance / optimistic-UI literature (spinners now an anti-pattern) | distinct from #15 *measured* perf | **promote or add-factor, route: design** |
| **VII-C** | **UX consistency & design-system conformance** | Bespoke component instead of the design-system one, off-token spacing/color/type, a second interaction pattern for an existing task | design-system / atomic-design practice | UI analog of #8 idiom | **add-factor (#8 UI arm) or lens** |
| **VII-D** | **Content & UX writing** | Unhelpful/blaming error copy, jargon, inconsistent voice/tone, high reading level, untranslated-intent microcopy | UX-writing / plain-language guidelines | net-new | **add-factor, route: content/design** |
| **VII-E** | **Inclusion & equitable access** | Cognitive-accessibility load, low-end-device / low-bandwidth / offline failure, data-cost/affordability, exclusionary assumptions | **ISO 25010:2023 inclusivity** (accessibility split into inclusivity + user assistance); WCAG cognitive | **extends #23** | **add-factor #23** |
| **VII-F** | **Product value & outcome instrumentation** | Change with no stated user/business outcome; success not measurable (no metric/event/experiment hook); hypothesis not falsifiable | lean / hypothesis-driven development; "build-measure-learn" | overlaps **G12** (acceptance criteria) + #16 (but *outcome* metrics ≠ *ops* metrics) | **promote, route: product** |
| **VII-G** | **Trust, transparency & user-facing accountability** | No "why am I seeing this", unexplained automated decisions, opaque data use, dishonest defaults, deceptive patterns | GDPR Art. 22 (automated-decision explanation); deceptive-design taxonomies | overlaps **G16** (ethics) + #27 (privacy) | **promote, detect-and-route: product/legal** |
| **VII-H** | **Conceptual integrity / product coherence** | A third way to do X for users; feature sprawl; a change that fragments the product's mental model | **Brooks, *The Mythical Man-Month*** — conceptual integrity, "the most important consideration in system design" | product analog of #11 restraint / #12 architecture | **promote (design-shaped), route: product/eng** |
| **VII-I** | **Internationalization of experience** | Cultural inappropriateness; locale-incorrect flows (name/address/payment); incomplete RTL *flow* (not just strings); poor localization quality | i18n/L10n practice | **extends #23** (beyond string extraction) | **add-factor #23** |
| **VII-J** | **Feature value lifecycle** | Unused/dead *features* (product analog of dead code), abandoned experiments, low-value surfaces never retired | product analytics; sunset practice | product analog of #1 dead-code; cross #29 retire | **add-factor (repo/cron), route: product** |

**Shape:** mostly **diff** (frontend/user-facing changes), with VII-F/VII-G/VII-H also **decision**-shaped (they belong in RFC/design-doc review), and VII-J **repo/cron**. The cluster is not monolithic — like the existing clusters it spreads across shapes.

**Restraint guardrails (so the suite doesn't become a PM nag):** (1) every VII lens carries the **skip-when-no-user-surface** clause; (2) findings are **detect-and-route** (G23), tagged for the non-engineer decider, never blocking the engineering merge on a taste call; (3) the synthesizer keeps product/UX findings in a **separate routed section** with their own (non-engineering) severity, so they neither drown nor are drowned by correctness/security blockers; (4) **conceptual integrity (VII-H)** is the cluster's own counterweight — it brakes *product* sprawl the way #11 brakes *code* sprawl.

**Disposition (lean): promote a Cluster VII**, built incrementally (VII-A usability + VII-F value-instrumentation are the highest-leverage starts; VII-E/VII-I fold into #23; VII-C folds toward #8). Net: a new topic cluster of ~4 net-new lenses + ~3 add-factors to #23/#8, all under G23's detect-and-route. Confidence: med-high that the *cluster* is a real hole; the *granularity* (how many lenses vs factors) is the open call, exactly as Q1 was for the original map.

## Cross-cutting synthesis

1. **The exclusion audit is a new standing method.** Gaps hide not only in what the map never conceived (framing), but in what it **deliberately fenced off on the wrong axis**. Re-audit every "out of scope" with the two-question test (reviewable? vs who-decides?) — most "product" exclusions fail it.
2. **Detect-and-route unlocks a whole quadrant.** Once surfacing is decoupled from deciding (G23), the entire human-value half of software — usability, trust, coherence, outcomes — becomes reviewable without the suite overstepping into product authority. This is the single largest scope expansion since the v0.2 maximal-scope decision.
3. **Conceptual integrity is the missing top-level value.** The map embeds two *code* counterweights (premature abstraction #11, premature optimization #15) but no *product* counterweight. Brooks's conceptual integrity (VII-H) is that brake, and it argues the cluster is not just additive surface but a coherence discipline.

## G25 — Re-auditing the rest of the exclusion pile with the two-axis test

G23's test (*reviewable at review time?* vs *who decides?*) must be applied to **every** prior exclusion, not just product — otherwise the reframe is special-pleading. Result: most prior out-of-scope calls were in fact drawn on the right axis (no artifact at review time), and only two were mis-folded.

| Prior exclusion | Reviewable at review time? | Re-audit verdict |
|---|---|---|
| **Sustainability / green-software** (was: "a carbon *label* on #15") | **Yes** — inefficient queries, egress, over-provisioning are diff-visible and carry carbon/cost weight | **Upgrade** — a *routed* factor (route: eng/leadership), more than a label |
| **FinOps / cloud cost** (#15 residual, thin) | **Yes** — per-request cost, egress, over-provisioned resources | **Upgrade thin→surfaced** — first-class routed factor under #15 |
| Contributor **DevEx as a system** | **No** (the *system metric* has no review artifact); diff-visible dev-friction already in #19/#21 | **Boundary held** (right axis — no-artifact) |
| **Deep model-fairness auditing** | **No** for the dataset/metric audit; **Yes** for diff-visible fairness smells (protected attr in a decision, hardcoded demographic threshold) | **Split confirmed** — smells → G16/detect-and-route (in); auditing → out (no artifact) |
| **Build-vs-buy TCO / procurement** | **No** (TCO numbers have no diff artifact); the decision record is #29 | **Boundary held** (right axis); ADR slice already #29 |

**Net:** the reframe *sharpens* the boundary rather than erasing it — restraint preserved. Only **sustainability** and **FinOps** were mis-folded (under-surfaced, not mis-axised) and get upgraded to routed factors; the genuine no-artifact exclusions stand. **Disposition (lean): upgrade green + FinOps to routed #15 factors; confirm the rest out.** Confidence: high.

## What remains genuinely out of scope (boundary now drawn on the right axis)

Only concerns with **no artifact visible at review time**: market/TAM sizing, pricing strategy, headcount/org-political decisions, and other pure-business calls that never touch a diff, repo, ADR, or design doc. The moment any of these is *written down* as a decision record, it re-enters as #29 (decision-shaped). Authority-only concerns (an engineer can't decide it) are **in scope via detect-and-route**, not out.

## Sources

- Nielsen's 10 usability heuristics — <https://www.nngroup.com/articles/ten-usability-heuristics/>
- Fred Brooks, conceptual integrity (*The Mythical Man-Month*) — <https://warwick.ac.uk/fac/sci/dcs/research/em/teaching/cs405-0708/conceptual_integrity.pdf>
- Optimistic-UI / perceived-performance patterns — <https://simonhearne.com/2021/optimistic-ui-patterns/>
- ISO/IEC 25010:2023 (interaction capability, inclusivity) — <https://quality.arc42.org/articles/iso-25010-update-2023>
