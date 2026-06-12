# Map gaps & cross-cutting findings

Surfaced during the phase-1 research pass (2026-06-08). These are **structural** observations about the taxonomy that feed **phase 2 (skill-suite architecture)** — especially the granularity decision (Q1). Kept separate from `open-questions.md` because each is a concrete design constraint, not an open question.

## G1 — Concerns that are double/triple-booked → each needs ONE canonical owner

Several factors legitimately appear under multiple categories. For the *map* that's fine (it's a graph). For *skills* it's a hazard: two skills flagging the same issue produces duplicate, possibly-conflicting findings. Each concern below needs one owning skill; the others reference it.

| Concern | Appears in | Proposed owner (TBD phase 2) |
|---|---|---|
| Dependency / CVE / supply-chain | #14 security, #18 deps, #25 (LLM03) | #18, with #14 deferring to it |
| PII / sensitive-data handling | #14 security, #16 logging, #27 compliance | #27 detects, #14/#16 enforce at their boundary |
| Feature-flag hygiene & lifecycle | #12 arch, #16 operability, #26 config | #26 (lifecycle/cleanup), #12 (architecture only) |
| Graceful startup/shutdown | #16, #26 | #16 |
| Money / units / measurement | #4 correctness, #23 i18n | split: value-correctness → #4, formatting → #23 |
| AI-generated code provenance | #25, #27 | #27 |
| Doc-drift vs comment-rot | #22 (doc drift), #7 (comment rot) | boundary: in-code comments → #7, external docs → #22 |

**Principle to adopt:** detection has a single owner; other categories may *enforce* at their boundary but don't re-report.

## G2 — Candidate promotion: "Excessive Agency" / agentic tool-use safety

OWASP LLM Top 10 **LLM06 (Excessive Agency)** + Simon Willison's **"lethal trifecta"** (private-data access + untrusted-content exposure + exfiltration/action ability) may be big enough to pull out of #25 into its own category. It cross-cuts #14 (security) and #13 (API/contract design, since it's about what actions a tool surface permits). Decision deferred; flagged as the most likely *next* promotion after the v0.2 three.

## G3 — Decomposition tension the suite MUST take a stance on

#6 (local readability, Clean-Code lineage: *extract aggressively, many small functions*) directly conflicts with #11/#9 (Ousterhout: *deep modules, don't over-decompose; shallow wrappers are negative-value*). A "split this up" reviewer and a "stop over-abstracting" reviewer will contradict each other on the same diff. The suite needs an explicit **altitude/decomposition policy** before either skill ships. Relates to counterweight enforcement (Q5).

## G4 — Readability coverage seam

#5 (naming = intention-revealing *meaning*) and #8 (consistency = *uniformity*, casing/convention) overlap on naming rules. Split cleanly: **meaning → #5, uniformity → #8.**

## G5 — Where LLM judgment is the ONLY tool (build here first)

These factors have little or no static-analysis coverage, so an LLM reviewer adds unique, non-redundant value — and they should be prioritized in phase 2 *because* tools don't already do them:
- altitude/abstraction-level mixing (#6)
- symmetry of expression (#6)
- premature abstraction / the wrong abstraction (#11) — counterweight
- premature optimization (#15) — counterweight
- naming *quality* beyond casing (#5)
- agent-native parity (#24)
- caller ergonomics / "pit of success" (#9)

Corollary: where mature linters already cover a category well (formatting, basic complexity, many security/a11y rules), the skill's job is to *orchestrate/triage tool output*, not re-implement it.

## G6 — #8 is probably a *family*, not a skill

Idiom/consistency is inherently per-ecosystem (the `dhh-rails` / `kieran-*` prior-art pattern). #8 likely becomes a language-agnostic core + opt-in idiom packs rather than one generic skill. Drives the language strategy question (Q6).

## G7 — Some skills need git history, not just the diff

#21 (maintainability) is meaningfully **VCS-history-aware**: churn × complexity hotspots, change-coupling, bus factor (CodeScene / Adam Tornhill's *Your Code as a Crime Scene*). These can't be assessed from a single diff. Implies a class of **repo/history-shaped** skills distinct from **diff-shaped** ones (relates to Q8: are some skills cron-shaped?).

## G8 — Detection vs. adjudication boundary (esp. #27)

Several #27 checks (regulatory interpretation, license-law compatibility) should **escalate to a human**, not be adjudicated by the agent. The agent's job is *detection + flagging with evidence*, not legal judgment. Generalize: every skill should know which findings it can resolve vs. which it must escalate. Matches Q9.

## G9 — Factor-level propagation gap: category ownership is complete, factor *surfacing* leaks

Full taxonomy-vs-skills sweep (2026-06-12). **All 27 categories have an owning skill** — no orphaned research, no un-skilled area. But ~10 categories are only *partially* surfaced at the **factor** level: a factor lives in `taxonomy.md` (often also in the skill's `heuristics.md`) yet never reaches a top-level inlined check, so it almost never produces a finding. The originating observation was that the suite emits **no naming findings** in practice despite #5 being owned.

Three mechanisms drive the leak:

1. **Router under-selection.** A lens only fires when `choosing-review-lenses` picks it, and the 2-4 cap means soft lenses run on few change shapes — `reviewing-naming-and-readability` appears in just **3 of ~20 routes** (feature, refactor, UI). On bug fixes, migrations, async, API, security, perf, LLM, config, and every repo audit it is never invoked. *(This is the router-intent problem — see Q14.)*
2. **Bundle + ~8-check budget.** Multi-category skills split a single ~8-check inlined budget, crowding out the junior category's factors: `#5 naming + #6 readability + #7 comments`, `#9 module + #10 type-modeling`, `#19 build + #26 config/portability`, `#18 deps + #27 compliance`.
3. **Severity trimming.** The synthesizer (D12) floats correctness/security to the top and ranks `Nit` last, so the readability class sinks and gets trimmed from the merged report even when produced.

**Dropped** (absent even from `heuristics.md`): `#12` scalability-of-the-design; `#12` feature-flag *architecture* (runtime flags are in #16; flag *design* is nowhere); `#15` cloud-cost / FinOps *(residual candidate)*; `#16`/`#27` telemetry-analytics privacy *(residual candidate)*.

**Thin** (heuristics-only or a single passing line, not a surfaced check): `#26` portability / environment assumptions (OS/arch, hardcoded paths, locale/encoding/timezone); `#16` SLO / error-budget instrumentation; `#6` symmetry of expression & altitude mixing; `#21` change-amplification & onboarding cost; `#24` agent-native parity & CODEOWNERS; `#9` caller ergonomics ("pit of success") & composition-vs-inheritance; `#4` numeric overflow / counter wraparound.

**Irony vs. G5.** Several of the thin factors — altitude, symmetry, naming quality beyond casing, agent-native parity, caller ergonomics — are *exactly* the ones G5 flagged as **build-here-first** because LLM judgment is the only tool that covers them. The propagation gap hit the highest-unique-value factors hardest: the parts of the map that most justify an LLM reviewer are the parts most likely to go silent.

**Fix surface** (spans three layers): the **manifest** (promote dropped/thin factors into inlined checks; rebalance the bundled-category budgets), the **research docs** (the two genuinely-missing #12 factors need research before they can be a check), and the **router** (stop the under-selection — Q14). Diff-shaped factors regenerate from the manifest; #12 scalability/feature-flag-design need a research pass first.
