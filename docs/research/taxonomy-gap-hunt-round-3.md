# Round-3 gap hunt — extrapolation, re-orientation, and holistic perspectives

**Status:** synthesized 2026-06-14. **Candidate findings — provisional, for owner disposition before any taxonomy edit.** No `taxonomy.md` change and no version bump yet (cf. round 2, which was adopted as v0.3 only after the owner's call).
**Motivation:** rounds 1–2 closed the *propagation* gaps (G9) and the *framing/shape* gaps (G10/G11 → the meta-layer, the decision-time shape). This pass asks the next question: now that the map has 32 categories across 6 clusters and four review shapes (diff / repo / decision / artifact), **what is still off it — and what new gap-finding *method* would reveal it?** The round-2 lesson was that the highest-value gaps are invisible to a taxonomy-vs-skills diff; round 3 extends that by deliberately using gap-finding methods the project has not used before.

## What is new about round 3's method

Round 2 hunted framing gaps by re-asking *what kinds of reviewable surface exist*. That is a powerful but **self-referential** move — it reasons outward from the map's own categories. Round 3 adds three methods that reason from *outside* the map, plus one that extends round 2's most productive axis:

1. **External completeness model (new).** Sweep an independent, standards-grade quality model — **ISO/IEC 25010:2023** — characteristic by characteristic, and find the ones with no owner. A self-grown taxonomy cannot see its own blind spots; an external model can. (This is the single most productive new method: it surfaced two unowned characteristics with one pass.)
2. **Stakeholder-vantage rotation (new).** The atlas reviews through the eyes of the maintainer (clusters II/III/VI), operator (#16/#28), attacker (#14/#32), and consumer (#13). Rotate to vantages it never takes: the **end user as a subject of the software's behavior** (not as a buyer), and the **reviewer's own epistemics**.
3. **Substrate sweep (new).** "Software" is not only application code in a repo. Extend to substrates the map treats as edge cases: machine-authored code, the data/analytics plane, notebooks.
4. **Shape-axis extrapolation (extends round 2).** The decision-time shape was round 2's headline. Ask again: what *vantage/temporality* of review is still missing after diff / repo / decision / artifact?
5. **Failure-grounded completeness model (added in continuation, 2026-06-14).** ISO 25010 is *attribute*-grounded. Complement it with a *failure*-grounded model — the corpus of what actually causes outages (post-mortem collections, SRE retrospectives) — which catches recurring failure modes that are not a "quality attribute" but a specific way systems detonate.
6. **Adversarial / inversion (added in continuation, 2026-06-14).** Instead of "what does quality look like," design the defect that most easily *evades this suite*, then name the assumption that let it through.

## Evaluation rubric (reused from round 2, to avoid re-flagging covered facets)

For each candidate omission, answer:

1. **Already covered?** Cite the category/factor that arguably owns it, or state "absent." (Grep `taxonomy.md` + `docs/research/` before claiming absence — distinguish *absent* (framing gap) from *thin-but-present* (G9 propagation).)
2. **Distinct review behavior?** Does it imply a question no existing lens asks? If it collapses into an existing lens's judgment, it is a *facet*, not a gap.
3. **Shape** — diff / repo-or-cron / decision-record / artifact / **a shape the suite does not yet have**.
4. **Prior art** — who already treats this as reviewable (frameworks, standards, linters, checklists)? Web-verified and cited below. Weak prior art is itself signal: either genuinely novel, or not actually a quality concern.
5. **Disposition** — **promote** / **add-factor** / **fold** / **out-of-scope** (with the G8 detect-and-escalate boundary where relevant). Provisional, owner-gated.

## Findings

Candidates G14–G22, grouped by the method that surfaced them, plus weaker/fold candidates and scope boundaries that deserve to be *written down*. (G20 and G21–G22 were added in continuation on 2026-06-14, applying methods 5–6 and the agent-vantage rotation.)

### Method 1 — External completeness model (ISO/IEC 25010:2023)

The 2023 edition defines **nine** product-quality characteristics: functional suitability, performance efficiency, **compatibility**, interaction capability, reliability, security, maintainability, flexibility, and **safety** (the 2023 revision replaced usability→interaction capability and portability→flexibility, and **added safety** as a new top-level characteristic). Mapping the atlas onto all nine, every characteristic has an owner **except two**.

| ISO 25010:2023 characteristic | Atlas owner | Verdict |
|---|---|---|
| Functional suitability (completeness/correctness/appropriateness) | #1 (+ G12 for appropriateness/validation) | covered (G12 already logged) |
| Performance efficiency | #15 | covered |
| **Compatibility (co-existence + interoperability)** | — | **absent → G18** |
| Interaction capability (was usability) | #23 (a11y) + #9 (dev-UX) | partial; end-user usability **reopened → G24 Cluster VII** (was "out of scope") |
| Reliability | #2, #28 | covered |
| Security | #14, #32 | covered |
| Maintainability | #9–#12, #21, #17 | covered |
| Flexibility (adaptability/scalability/installability/replaceability) | #26 (portability), #28 (scalability) | covered |
| **Safety (fail-safe, hazard warning, risk identification, operational constraint)** | — | **absent → G18 (safety arm)** |

**G18 — Interoperability and Safety: the two ISO-25010 characteristics with no owner.**

- **Interoperability / compatibility** — the missing "-ility." #13 reviews the contract *we design and publish*; #8 reviews idiom. Nothing reviews whether the code **correctly speaks an external standard or protocol**: HTTP caching/conditional-request/idempotency semantics, OAuth/OIDC flows, semver discipline, RFC-defined formats (date/email/URI), Unicode normalization & encoding edges, cron syntax, OpenTelemetry semconv, standard file formats. Currently scattered as factor-notes across #4/#8/#13/#26. *Co-existence* (resource-sharing without detriment to co-located software) is even thinner.
- **Safety** (distinct from #14 *security* — harm-prevention vs. attacker-prevention): fail-safe defaults (fall back to a state that prevents harm), safe-mode-on-error, operational constraints/guardrails on dangerous actions, hazard warnings to the user, and *risk identification* for state that could cause real-world harm. #2 owns fail-*loud* vs. graceful degradation and #28 owns graceful degradation under overload, but neither asks "if this goes wrong, does it fail toward *harm* or toward *safe*?" The diff-visible slice (fail-safe defaults, harm-state guards, confirmation/undo on destructive actions) is reviewable; full hazard analysis (SFTA/SFMEA, ISO 26262 / IEC 61508 / DO-178C) is domain governance → **detect-and-escalate (G8)**.

Prior art: [ISO/IEC 25010:2023](https://www.iso.org/standard/78176.html); [arc42 quality model update](https://quality.arc42.org/articles/iso-25010-update-2023); software-safety lineage — [Leveson, *Software Safety*](https://student.cs.uwaterloo.ca/~cs492/LevesonSafety.pdf), [NASA SW Safety & Hazard Analysis handbook](https://swehb.nasa.gov/display/SWEHBVD/8.58+-+Software+Safety+and+Hazard+Analysis).
**Disposition (lean):** interoperability → **promote** (lens or consolidated factor across #4/#8/#13/#26); safety → **add-factor to #2/#28 + a detect-and-escalate boundary**, with the deep-hazard slice **out-of-scope**. Confidence: med-high (interoperability), medium (safety — boundary-drawing).

### Method 2 — Stakeholder-vantage rotation

**G16 — Ethical / responsible-design defects in non-ML code** *(vantage: the end user as a subject of behavior).*
Today ethics is reviewed **only** where it is *legal* (#27 compliance) or *ML-output* (#25 harmful-output eval). The whole class of **diff-visible, code-level** ethical defects has no owner: dark patterns and deceptive flows, manipulative defaults (pre-checked consent, asymmetric opt-out), obstruction/sneaking/forced-action in ordinary control flow, and **discriminatory business logic baked into plain conditionals** (a hardcoded threshold that disadvantages a group — no model anywhere). This is *not* governance hand-waving: there are operational taxonomies and live regulation.
Prior art: [Mathur et al., *Dark Patterns at Scale*](https://www.researchgate.net/publication/337134584_Dark_Patterns_at_Scale_Findings_from_a_Crawl_of_11K_Shopping_Websites) (7-category taxonomy: scarcity, urgency, social proof, misdirection, obstruction, sneaking, forced action); [EDPB deceptive-design guidelines](https://www.sciencedirect.com/science/article/pii/S2212473X25000975) (6 families / 16 subcategories); detection tooling exists but caps <50% coverage ([ESORICS/EuroUSEC 2024](https://dl.acm.org/doi/10.1145/3688459.3688475)). The framing recurs even in AI-generated UI ([*Deception at Scale*, arXiv 2502.13499](https://arxiv.org/pdf/2502.13499)).
**Disposition (lean):** **promote, detect-and-escalate** (G8) — flag the pattern with evidence; the consent-as-legal facet defers to #27, the pure-product-judgment facet escalates to humans. Confidence: medium-high.

**G19 — Review-coverage transparency / known-unknowns** *(vantage: the reviewer's own epistemics).*
The synthesizer (D12) emits a verdict but never states **what the review did *not* examine** — which lenses were skipped and why, which areas it could not verify, what it had no evidence for. A confident-looking review silent on its own gaps manufactures false assurance, which is itself a quality defect *of the review*. This is the meta-analog of #30 (review the apparatus, not just the code) turned on the suite's own output.
Prior art: weak as a named practice (signal: novel) — nearest analogs are audit "scope & limitations" statements and model/eval "known limitations" sections.
**Disposition (lean):** **fold into the synthesizer** as a required contract field (a "coverage & limitations" block), not a new category. Confidence: high (low-risk, additive).

### Method 3 — Substrate sweep

**G14 — Characteristic defects of AI-authored code** *(substrate: machine-authored code; also reflexive — this suite is AI-built).*
The suite reviews code that **calls** an LLM (#25) and tracks AI **provenance markers** (#27), but has no lens for the *failure signature of machine-authored code itself*, independent of who/what wrote it. Empirical prior art makes this concrete and severe:

- ~**20%** of packages recommended by code LLMs are **non-existent** (hallucinated), **43%** of those recur across prompts → predictable **slopsquatting** targets; commercial-model hallucination ~5.2% vs open ~21.7% ([Spracklen et al., arXiv 2406.10279](https://www.scribd.com/document/849543564/A-Comprehensive-Analysis-of-Package-Hallucinations-by-Code-Generating-LLMs-2406-10279); [Help Net Security summary](https://www.helpnetsecurity.com/2025/04/14/package-hallucination-slopsquatting-malicious-code/)).
- A taxonomy of **LLM-code hallucinations beyond functional correctness** (misused/invented APIs, plausible-but-wrong logic, inconsistent state) exists: [*Beyond Functional Correctness*, arXiv 2404.00971](https://arxiv.org/pdf/2404.00971).
- Security: ~**45%** of LLM-produced code carried security flaws in a 100+-model Veracode analysis ([ActiveState summary](https://www.activestate.com/blog/is-ai-generated-code-poisoning-your-software-supply-chain/)).

These are characteristic, recurring, **diff-reviewable** defects (verify every imported package exists and is the intended one; distrust confident-looking constants/APIs; watch for over-helpful unrequested additions — ties to `checking-restraint`). Distinct from #25 (code that *uses* AI) and #27 (a provenance *marker*).
**Disposition (lean):** **promote (diff lens)** with a sharp boundary — the *package-hallucination* leg cross-refs #18 supply-chain; the *plausible-but-wrong* and *over-helpful* legs cross-ref #1 and `checking-restraint`. Confidence: high — strong prior art, high present-day base rate, reflexively relevant.

**G17 — Data-engineering & data-contract quality** *(substrate: the data/analytics plane).*
The atlas is OLTP-app-centric. #20 owns migration/persistence *safety*; #13 owns *service* API contracts. Nothing owns the **data plane**: SQL/dbt transformation correctness, data tests (freshness / completeness / uniqueness / distribution), and especially **producer↔consumer data contracts** for events and analytics schemas — the silent break when an upstream field changes and three downstream pipelines rot. Mature, standardizing prior art: [data contracts (DataHub)](https://datahub.com/blog/the-what-why-and-how-of-data-contracts/), schema-registry compatibility (Confluent / Avro / Protobuf / JSON Schema), and CI-enforced quality via [dbt tests + Great Expectations](https://astrafy.io/the-hub/blog/technical/implementation-of-the-data-contracts-with-dbt-google-cloud-great-expectations-part-1) / Soda.
**Disposition (lean):** **promote** — likely a diff lens (transformation correctness + data-test adequacy) paired with a repo/cron arm (contract drift across producers/consumers), mirroring how #13/#20 split. Confidence: med-high; scope to data-as-code in the repo (warehouse-governance escalates).

### Method 4 — Shape-axis extrapolation

**G15 — Production-evidence / runtime-informed review** *(a candidate fifth shape).*
All four existing shapes are **source-derived** — diff, repo, decision, artifact. None consumes the **running system's own signals** as a review input: error-rate deltas on the changed path, slow-query/trace evidence, real metric cardinality, actual usage of the code being modified. The suite reviews observability *code* (#16) but never *reads telemetry to find defects that only exist at runtime.* Prior art validates the underlying premise (telemetry as ground truth) but mostly **shift-left** — [observability-driven development](https://opensource.com/article/22/10/observability-driven-development-opentelemetry), [trace-based testing](https://tracetest.io/learn/top-9-tools-for-observability-driven-development) — and SRE **Production Readiness Reviews** shift-right but as a pre-launch checklist. The specific move — *feeding live production evidence back into the review of a change* — has thin prior art (signal: genuinely novel, while ODD confirms the value of the underlying signal).
**Disposition (lean):** **promote as a shape** (`shape: runtime` / "production-informed"), sibling to diff/repo/decision/artifact — the same kind of result as round 2's decision shape. Lower priority than the topic gaps (needs a telemetry-access substrate, an orchestration concern like D12's advisory fan-out). Confidence: medium (high novelty, higher build cost).

### Method 2 (revisited) — the agent vantage (owner-surfaced, 2026-06-14)

The vantage rotation above stopped at the *end user* and the *reviewer's own epistemics*. It missed the rotation that matters most to a suite whose own users are agents: **the AI agent as a first-class reader/operator.** Rotating to it splits cleanly into two roles, with very different coverage.

**G20 — The codebase/repo as a working environment for AI maintainers** *(vantage: the agent as code-owner/reader).*
Cluster II of the taxonomy is titled *"Can humans understand it?"* — the entire readability/clarity axis (#5–#8) was never rotated to *"Can an **agent** understand, navigate, and safely modify this within a context budget?"* The per-item check:

| Concern | Coverage | Verdict |
|---|---|---|
| LLM-centric readability | #5–#8 are human-framed | **absent** |
| Context-window economy of the *reviewed* code (self-containment, depth-first-sliceability, no whole-repo load to understand a change) | exists in-repo **only** as the suite's *own* design tax (artifact-scoped-lenses.md: RAG-MCP, lost-in-the-middle) — never as a property of reviewed code | **absent as a review behavior** |
| Discoverability / navigability for agents (structure, naming, retrieval surfaces the right chunk) | human onboarding/navigability in #21/#22 | **absent (agent-framed)** |
| RAG / retrieval-friendliness | "RAG" appears only re: routing the suite's own tools | **absent** |
| Agent config/instruction files (AGENTS.md / CLAUDE.md) present, accurate, scoped | **drift** covered (#22/#24); **authoring quality** designed-unbuilt (#30 / D15 / G11) | **partial** — "does the repo *provide good, scoped* agent onboarding" (the agent analog of #22's README front-door) is thin |

Two reasons to promote rather than fold: **(1)** it is the **mirror image of G14** — G14 is *quality of AI-**authored** code*; G20 is *quality of code **for** AI readers* — same axis, opposite direction, neither subsumes the other; **(2)** it is **the G11 pattern again** — the project already optimizes its *own* artifacts for agent-legibility (D7: progressive disclosure, context budget, model-portability) but never made agent-legibility a **review behavior** for the codebases it reviews ("we hold ourselves to it but never review for it"). Prior art: ["AI-friendly codebases"](https://medium.com/@dconsonni/creating-ai-friendly-codebases-82cb3203c118); [coding-agents-as-a-first-class project-structure concern](https://dev.to/somedood/coding-agents-as-a-first-class-consideration-in-project-structures-2a6b) (the "40% context rule," depth-first slices, self-contained modules, AST-grounded agent interfaces); the empirical finding that LLM code is "superficially clean but intrinsically complex."
**Disposition (lean): promote** — a vantage-rotation of cluster II into an agent-legibility lens: a **diff arm** (is this change agent-legible and context-economical?) + a **repo arm** (is the tree agent-navigable; AGENTS.md/CLAUDE.md present/accurate/scoped; an `llms.txt`-style index present?). Distinct from G14, #32, and the operator surface below. Confidence: med-high (genuine framing gap; strong emerging prior art).

**The operator role (agent as user of the *product*) — mostly mapped, do not over-promote.** The restraint check passes here: the suite *did* anticipate agents-as-operators, just thinly and scattered.

| Concern | Coverage | Action |
|---|---|---|
| UI parity for agents ("any action a user can take, an agent can too") | **#24 agent-native parity** — surfaced check in `reviewing-pr-and-process-hygiene`, but G9-flagged **thin** | **G9 deepen** (thin → surfaced) |
| SKILL.md / MCP tool surfaces | authoring quality → #30 + `shape: artifact` (D15/G11), **unbuilt**; safety → #32, **unbuilt** | **build the already-mapped lenses** |
| LLM-accessible UI surfaces / affordances | oblique only — #23 a11y (semantic markup/ARIA doubles as agent affordance) + #24 | **add-factor #23/#24** |
| Product/docs discoverability for agents | none — `llms.txt` is an emerging standard ([Anthropic requested it; Google A2A includes it](https://buildwithfern.com/learn/docs/ai-features/llms-txt)) | **add-factor #22/#24** |

**Disposition (operator role): no new category** — a **G9-class deepening** (#24 parity) + **build the mapped-but-unbuilt** #32/#30 lenses + **two add-factors** (`llms.txt` discoverability; LLM-accessible UI affordance). Calling this a second framing gap would over-reach.

### Method 5 — Failure-grounded completeness model (incident corpus)

ISO 25010 (method 1) is *attribute*-grounded — it asks what good looks like. A complementary external model is *failure*-grounded: the corpus of what actually takes systems down ([danluu post-mortem collection](https://github.com/danluu/post-mortems) and [its lessons](https://danluu.com/postmortem-lessons/), SRE retrospectives). It catches a class the attribute model structurally misses — recurring **failure modes** that aren't a quality attribute but a specific way systems detonate. Sweeping the canonical outage-cause list against the map:

**G21 — Operational time-bombs & exhaustion classes (latent "correct-now, broken-later" defects).**

| Incident class (frequency) | Atlas coverage | Verdict |
|---|---|---|
| **Config change** (~50% of severe outages — "config bugs, not code bugs, cause the worst outages") | #26 config validation/parity/safe-defaults | covered; *reinforces* #26 surfacing (G9-deepen) — the outage-frequency framing is the lesson |
| **Expired TLS certs / OAuth tokens / API keys; missing rotation/renewal path** (Microsoft, Spotify, Google, Bank of England) | #14 = *hardcoded* secrets; NIST note = password rotation | **absent** — the single most preventable major-outage class has no home |
| **Calendar/clock time-bombs** (leap year/second, DST transitions, epoch-2038, year rollover) | #4 has timezone/UTC/monotonic | **thin** — not enumerated as detonation triggers |
| **Retry storms / thundering herd / cache stampede; retry budgets** | backoff+jitter (cluster-1:74), #28 backpressure | **partial** — the named coordinated-failure patterns + retry *budget* are not surfaced |
| **Resource exhaustion** (disk-full, file-descriptor/socket, ephemeral-port, connection-pool) | pool bounded (cluster-1:147), #4 leaks, #28 unbounded | **partial** — specific exhaustion classes not enumerated |

The cohesion worth noting: several share a **temporal signature — correct at merge, detonates later** by the passage of time (expiry, calendar) or accumulation (quota/capacity creep). No current lens asks *"will this be fine today and page someone in 90 days?"* (the #29 ADR-assumption-expiry and #30 suppression-expiry checks are the same shape, narrowly applied).
Prior art: [SSL-expiry outage retrospectives](https://www.configclarity.dev/incidents/ssl-expiry-outages/); [danluu post-mortems](https://github.com/danluu/post-mortems); cert-renewal-window misconfig → retry storm ([Let's Encrypt rate-limit postmortem](https://johal.in/postmortem-lets-encrypt-rate-limit-prevented-certificate-renewal/)).
**Disposition (lean):** primarily **add-factors** — credential/cert **expiry & rotation** → #14/#26; **calendar/clock time-bombs** → #4; **coordinated-retry patterns + retry budget** → #2/#28; **exhaustion classes** → #4/#28 (restraint: facets of existing categories, not a cohesive new behavior). **Flag the cohesive option:** a "latent / time-delayed defect" thread that asks the *correct-now-broken-later* question explicitly. **Method note:** run the failure-grounded sweep *alongside* the attribute-grounded ISO sweep — they catch disjoint classes. Confidence: high (the thin/absent items are real and high-frequency).

### Method 6 — Adversarial / inversion

Design the defect that most easily *evades this suite*, then name the assumption that let it through. The suite's load-bearing assumption is **the diff is the unit of review.**

**G22 — Diff-isolation blindness: interaction & composition defects.**
The suite reviews a single diff (diff-lenses) or repo *state* (cron audits); neither reviews the **composition of multiple changes across time and space.** Evasive defect classes:

- **Semantic / logical merge conflicts** — two independently-correct changes that break *when combined*: textually merge-clean, behaviorally broken. Explicitly noted in the literature as "hard to detect through typical quality-assurance practices like code review and testing" ([Detecting Semantic Conflicts with Unit Tests, arXiv 2310.02395](https://arxiv.org/pdf/2310.02395); [logical merge conflicts](https://medium.com/@elischleifer/what-is-a-logical-merge-conflict-c6525acead85)).
- **Assumption invalidation across in-flight changes** — change A is correct against an assumption a parallel/recent change B silently breaks.
- **Load-bearing deletions** — a removal that is locally fine but breaks a caller/relier *outside the diff* (diffs foreground additions; removals are under-scrutinized).

This is a **unit/granularity gap** — the change-set across time/space is an un-owned review *unit*, the analog of round 2's decision *shape* gap (a missing unit rather than a missing topic). Relates to G7 (some skills need history, not just the diff) and #21 change-coupling, but neither owns *cross-change interaction at review time*.
**Disposition (lean): promote (scoped).** The deep detection is tool-territory (variability-aware execution, static/pointer analysis); the LLM-review slice is *"trace the ripple of deletions and assumption-changes beyond the diff, and flag where this change interacts with concurrent/recent ones"* — orchestrate/escalate the heavy detection (G8). Confidence: medium (real gap, strong prior art, detection partly tool-owned).

### Weaker / fold candidates (logged; not recommended for promotion)

| Candidate | Nearest owner | Disposition |
|---|---|---|
| Quality-as-trajectory / debt thermodynamics (is quality trending up or down; debt accreting faster than paid — Lehman's laws) | #21 (level, not derivative) | **fold → the open Q4** (scores/trends); a *derivative* view of #21, not a new topic |
| Domain-model fidelity / DDD (bounded-context integrity, ubiquitous-language faithfulness) | #5 / #9 / #10 | **add-factor** at most; high overlap risk |
| Non-app substrates (Jupyter hidden-state/out-of-order exec, spreadsheets-as-software, low-code) | D15 `shape: artifact` | **instances of the artifact shape**, not new topics |
| Publishing / library-author's-eye quality (packaging, types shipped, install footprint, tree-shakeability) | #13 + #24 | **fold** (factors) |
| Build→run provenance/integrity (SLSA, signing, reproducible-build attestation for what *we* ship) | #18 / #19 / #27 | **fold** (factors); cf. round-2 B7 |
| Risk-proportionality of verification (match rigor to blast radius — Cynefin) | — | **not a lens — an argument for the open Q14** review-depth modes |

### Scope boundaries worth *writing down* (decisions, not silent omissions)

Round 2 fenced governance explicitly with detect-and-escalate; these deserve the same treatment so they are recorded decisions rather than invisible holes:

- **End-user product validation** beyond G12's acceptance-criteria traceability ("is this the *right feature* / does it move the metric") — ~~the upstream edge where engineering review stops~~ **REOPENED 2026-06-14 (owner): in scope via detect-and-route → G23 + G24 (Cluster VII / [`product-experience-value-cluster.md`](product-experience-value-cluster.md)).** The exclusion was drawn on the wrong axis (who-decides vs reviewable); only concerns with *no artifact at review time* (market sizing, pricing) stay out.
- **Functional-safety certification** (ISO 26262 / IEC 61508 / DO-178C, full hazard analysis) — domain-specific; the diff-visible fail-safe slice is G18, the certification machinery escalates.
- **Org/team-level measures** (DevEx-as-a-system, delivery velocity, build-vs-buy TCO) — already held out of scope in round 2; consolidate the statement.

## Cross-axis synthesis — what round 3 actually found

1. **An external completeness model earns its keep.** One ISO-25010 pass surfaced two unowned characteristics (interoperability, safety) that the self-referential framing-hunt of rounds 1–2 had missed — including a characteristic ISO itself only promoted in 2023 (safety). **Recommendation: adopt the external-model sweep as a standing method**, re-run on each major revision of an external quality standard.
2. **The substrate is widening faster than the map.** Two of the strongest finds (G14 machine-authored code, G17 the data plane) are not new *topics* so much as **the map's app-code-in-a-repo assumption breaking down**. AI-authored code is now the median diff; the data/analytics plane is a first-class engineering discipline. The map should state its substrate assumptions and where they end.
3. **A fifth shape is plausible but not yet forced.** G15 (production-evidence) is the round-3 analog of round 2's decision shape — a whole vantage that is absent — but unlike decision-time it lacks a flood of strong prior art and carries a real substrate cost (telemetry access). Log it; do not rush it.
4. **The human-axis discipline check passed again.** As in round 2, the socio-technical sweep mostly resolved to *covered* or *escalate* — except **G16**, which is genuinely diff-visible and genuinely unowned. The restraint counterweight held: the real gaps are structural (an external characteristic, a substrate, a shape, a vantage), not ideological.
5. **The agent vantage is the suite's own blind spot (G20).** The most consequential rotation for an agent-run suite — *the AI agent as reader/operator* — was nearly missed and only the owner's prompt surfaced it. The **code-owner role is a genuine framing gap** (cluster II was never rotated off "Can humans understand it?"), and it mirrors G14 exactly (quality *of* AI-authored code ↔ quality of code *for* AI readers). The **operator role**, by contrast, was already anticipated (#24/#32/#30) — confirming the suite under-reached on the agent *as reader*, not the agent *as user*. Methodological note: vantage rotation must explicitly enumerate *all* reader/operator classes, agents included, or it stops at the human.
6. **Failure-grounded and attribute-grounded models catch disjoint classes (G21).** The ISO-25010 sweep finds missing *quality attributes*; the incident-corpus sweep finds missing *failure modes* (cert expiry, calendar time-bombs, exhaustion) that no attribute-model names because they are not attributes. Both external sweeps belong in the standing toolkit, and they do not overlap.
7. **The diff is an unexamined unit assumption (G22).** Round 2 found a missing *shape* (decision-time); the adversarial method finds a missing *unit* — the change-set across time/space. The suite's three units (diff / repo-state / decision) all assume a single change in isolation; defects of *composition* (semantic conflicts, assumption invalidation, load-bearing deletions) fall between them. Unit, like shape, is an axis orthogonal to topic.

## Disposition summary (provisional — owner-gated)

| ID | Candidate | Method | Shape | Lean | Confidence |
|---|---|---|---|---|---|
| **G14** | AI-authored-code defects | substrate | diff | **promote** (lens; xref #18/#1/restraint) | high |
| **G15** | Production-evidence / runtime-informed review | shape | **new `runtime` shape** | **promote** (shape; lower priority) | medium |
| **G16** | Ethical / responsible-design (non-ML) | vantage | diff | **promote, detect-and-escalate** | med-high |
| **G17** | Data-engineering & data-contract quality | substrate | diff + repo/cron | **promote** (paired lens) | med-high |
| **G18** | Interoperability + Safety (ISO 25010:2023) | external model | diff (+ escalate) | interop **promote/consolidate**; safety **add-factor + escalate** | med-high / medium |
| **G19** | Review-coverage transparency / known-unknowns | vantage (meta) | synthesizer | **fold into synthesizer contract** | high |
| **G20** | Codebase/repo as a working environment for AI maintainers | vantage (agent-as-reader) | diff + repo/cron | **promote** (cluster-II rotation; mirror of G14). Operator role → G9-deepen #24 + build #32/#30 + add-factors | med-high |
| **G21** | Operational time-bombs & exhaustion classes (cert/credential expiry & rotation, calendar/clock time-bombs, coordinated retries, exhaustion) | failure-grounded model | diff (+ cron) | **add-factors** (#4/#14/#26/#28); flag a cohesive "latent / time-delayed defect" thread | high |
| **G22** | Diff-isolation blindness — interaction & composition defects (semantic/logical merge conflicts, assumption invalidation, load-bearing deletions) | adversarial / inversion | a missing **change-set unit** | **promote (scoped)** — LLM ripple-trace; escalate heavy detection | medium |

**Recommendation.** The two highest-value, lowest-controversy moves are **G14 (AI-authored-code defects)** — high base rate, strong prior art, and reflexively important to a suite that is itself AI-built — and **G19** (a synthesizer coverage block, near-free). **G17** and **G16** are strong but widen scope (a new substrate; a detect-and-escalate ethics surface) and want their own design pass. **G18-interoperability** is a clean consolidation of existing factor-notes; **G18-safety** is boundary-drawing. **G15** is the most intellectually significant (a fifth shape) but the least forced — log and revisit. Net candidate surface: **3–5 new behaviors + 1 new shape + ~2 add-factors/folds**, all gated on the owner's restraint call, exactly as v0.3 was.

## Sources

- ISO/IEC 25010:2023 product quality model — <https://www.iso.org/standard/78176.html>; arc42 2023 update — <https://quality.arc42.org/articles/iso-25010-update-2023>
- Leveson, *Software Safety* — <https://student.cs.uwaterloo.ca/~cs492/LevesonSafety.pdf>; NASA Software Safety & Hazard Analysis — <https://swehb.nasa.gov/display/SWEHBVD/8.58+-+Software+Safety+and+Hazard+Analysis>
- Spracklen et al., *A Comprehensive Analysis of Package Hallucinations by Code-Generating LLMs* (arXiv 2406.10279); *Beyond Functional Correctness: Exploring Hallucinations in LLM-Generated Code* — <https://arxiv.org/pdf/2404.00971>; package-hallucination / slopsquatting — <https://www.helpnetsecurity.com/2025/04/14/package-hallucination-slopsquatting-malicious-code/>; Veracode/AI-code security — <https://www.activestate.com/blog/is-ai-generated-code-poisoning-your-software-supply-chain/>
- Mathur et al., *Dark Patterns at Scale* — <https://www.researchgate.net/publication/337134584_Dark_Patterns_at_Scale_Findings_from_a_Crawl_of_11K_Shopping_Websites>; regulation review — <https://www.sciencedirect.com/science/article/pii/S2212473X25000975>; deceptive-design detection — <https://dl.acm.org/doi/10.1145/3688459.3688475>; *Deception at Scale* (arXiv 2502.13499) — <https://arxiv.org/pdf/2502.13499>
- Data contracts (DataHub) — <https://datahub.com/blog/the-what-why-and-how-of-data-contracts/>; dbt + Great Expectations data contracts — <https://astrafy.io/the-hub/blog/technical/implementation-of-the-data-contracts-with-dbt-google-cloud-great-expectations-part-1>
- Observability-driven development — <https://opensource.com/article/22/10/observability-driven-development-opentelemetry>; trace-based testing tools — <https://tracetest.io/learn/top-9-tools-for-observability-driven-development>
- Agent-as-reader: AI-friendly codebases — <https://medium.com/@dconsonni/creating-ai-friendly-codebases-82cb3203c118>; coding-agents-as-first-class project structure — <https://dev.to/somedood/coding-agents-as-a-first-class-consideration-in-project-structures-2a6b>; `llms.txt` — <https://buildwithfern.com/learn/docs/ai-features/llms-txt>
- Incident corpus: danluu post-mortems — <https://github.com/danluu/post-mortems> and lessons — <https://danluu.com/postmortem-lessons/>; SSL-expiry outages — <https://www.configclarity.dev/incidents/ssl-expiry-outages/>; Let's Encrypt rate-limit postmortem — <https://johal.in/postmortem-lets-encrypt-rate-limit-prevented-certificate-renewal/>
- Interaction defects: Detecting Semantic Conflicts with Unit Tests (arXiv 2310.02395) — <https://arxiv.org/pdf/2310.02395>; logical merge conflicts — <https://medium.com/@elischleifer/what-is-a-logical-merge-conflict-c6525acead85>
