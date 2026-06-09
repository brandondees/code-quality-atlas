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
