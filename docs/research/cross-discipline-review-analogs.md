# Cross-discipline review-analog sweep

**Status:** synthesized 2026-06-14. **Candidate — provisional, owner-gated.** No `taxonomy.md` edit yet.
**Method (new):** code review is one instance of a broad family of *review/inspection/assurance* disciplines. Sweep the mature ones — clinical peer review, aviation, financial audit, scientific peer review, manufacturing QA, civil-engineering inspection — and ask, for each: *what reviewable discipline does it have that the atlas lacks?* This is the inverse of the ISO/Nielsen external-model sweep (which imports a *quality model*); here we import a *review practice*.

## The discipline → atlas map

| Discipline | Signature practice | Atlas status |
|---|---|---|
| **Financial audit** | **Segregation of duties / maker-checker / four-eyes**; materiality & sampling; internal controls; audit trail | SoD **absent** (→ G27); materiality → **feeds Q14**; audit trail partly #16/#32 |
| **Scientific peer review** | **Claims-vs-evidence**; reproducibility; methodology soundness; falsifiability | claims↔evidence **thin** (only the perf lens) → G28; reproducibility covered (#1/#19) |
| **Manufacturing QA** | **Root-cause / 5-whys** (vs symptom); **poka-yoke** (mistake-proofing); tolerances/SPC | root-cause **thin** → G29; poka-yoke **strongly covered** (#9/#10) — validates |
| **Clinical / medical** | **Differential diagnosis** (alternative hypotheses); contraindications; second opinion; blameless M&M | diff-diagnosis → **feeds G19**; contraindications → G22; M&M → Q17/G15 |
| **Aviation** | **Checklist discipline**; challenge-response / four-eyes on irreversible ops; sterile cockpit; just culture | checklists **validate the whole approach**; four-eyes → G27/#24; sterile-cockpit → #24 scope-creep |
| **Civil-eng inspection** | **Safety factor / margin**; code-compliance; licensed sign-off | margin → **sharpen #28/G21**; compliance → G18; sign-off → #24 CODEOWNERS |

The headline: the sweep mostly **confirms the atlas is well-grounded** — poka-yoke maps cleanly to #9/#10, adversarial review to #14/#32, the checklist discipline *is* the suite's whole form (surgical checklists cut deaths ~47%, [Gawande](https://cpafma.org/articles/lessons-learned-checklist-manifesto-things-right)). The net-new yield is three sharp, reviewable disciplines plus several "feeds an existing question" notes. Restraint held: this is mostly add-factors + validation, **not** a new cluster.

## Findings

**G27 — Segregation of duties / dual-control (maker-checker, four-eyes) in authorization logic.**
From financial-audit internal controls. Reviewable in code: can the **same principal both initiate and approve** a high-consequence action (payment, refund, role/permission grant, data deletion, deploy)? Are sensitive operations gated by **dual-authorization / maker-checker** (two distinct actors)? This is distinct from #14, which owns authn, IDOR, and least-*privilege* — SoD is the orthogonal control that **no single actor completes a sensitive workflow alone**, a business-logic authorization *pattern*, not an access-control bug. SOX §404-mandated; the canonical anti-fraud and anti-collusion control. Prior art: [maker-checker](https://en.wikipedia.org/wiki/Maker-checker) ("4-Eyes"); [SoD for SOX](https://www.securends.com/blog/segregation-of-duties-for-sox-compliance/).
**Disposition (lean): add-factor #14** (or a dedicated check), **detect-and-route** (security/compliance; the *policy* of which ops need dual-control is a business call). Confidence: high — recognized, reviewable, currently unowned.

**G28 — Claims-vs-evidence verification (generalized).**
From scientific peer review. Every PR *claim* — "fixes X", "makes it faster", "no behavior change", "closes #123" — should be **checkable against evidence in the diff**: a regression test for a fix, a benchmark for a speed claim, genuine non-functionality for a "pure refactor". The atlas already does this in exactly **one** place — `reviewing-performance-and-efficiency` *"demands a profile before accepting optimization claims."* Generalizing that move into a cross-cutting principle: **an unsupported claim is itself a finding.** Overlaps #1 (code-vs-stated-*intent* — but that checks the code against the spec, not the PR's *assertions* against *evidence*), G12 (acceptance criteria), and #17 (regression test for a fix), without any of them owning the general claim↔evidence discipline.
**Disposition (lean): a cross-cutting factor / synthesizer principle** (mirror the perf lens's profile-demand across lenses; pairs with G12 and G19). Confidence: med-high.

**G29 — Root-cause vs symptom (band-aid detection).**
From manufacturing 5-whys + clinical differential diagnosis. For bug fixes: does the change address the **root cause** or paper over a **symptom** — catch-and-ignore the error, special-case the one failing input, add a retry around a flaky call, bump a timeout? The existing lenses verify a fix is *correct*; none asks whether it is at the *right level*. `hunting-silent-failures` is adjacent (it dislikes swallowing errors) but band-aid detection generalizes to *"is this masking the problem rather than resolving it?"*
**Disposition (lean): add-factor** to `tracing-correctness-and-invariants` / `hunting-silent-failures` and the bug-fix router route. Confidence: medium (a real, distinct judgment; partly subjective — pairs with G28's "is the cause evidenced?").

## Feeds an existing question (cross-discipline, not new gaps)

- **Materiality & sampling** (audit) → the concept **Q14** (review-depth modes) is missing a name for: focus review effort proportional to blast radius; sample low-risk surface rather than exhaustively. Record as the conceptual backbone of Q14's depth axis.
- **Differential diagnosis** (clinical) → **G19** (reviewer epistemics): before concluding a root cause, enumerate alternative explanations — reduces false positives and wrong-cause findings. A reviewer-discipline refinement.
- **Safety factor / margin** (civil-eng) → sharpen **#28 / G21**: does the change operate with headroom, or at the redline (capacity, rate budget, buffer)? Margin as an explicit check.
- **Four-eyes / elevated review for irreversible ops** (aviation/audit) → **#24** process: some change *classes* (one-way doors, prod data, auth) warrant two approvers / elevated review — a process meta-finding, partly covered.
- **Blameless postmortem / M&M** (clinical/aviation) → **Q17** self-improvement + **G15** runtime-evidence.

## Validations (the sweep confirms existing strengths)

- **Poka-yoke (mistake-proofing)** ≡ #9/#10 "hard-to-misuse interfaces / make illegal states unrepresentable" — the atlas already embodies the strongest manufacturing-QA principle.
- **Checklist discipline** (Gawande) ≡ the suite's entire form — externally validated (surgical checklists −47% deaths; aviation's disciplined challenge-response).
- **Adversarial review** ≡ #14/#32 security.
- **Reproducibility** ≡ #1 determinism + #19 hermetic builds.

## Synthesis

1. **A review-practice sweep complements the quality-model sweep.** ISO/Nielsen import *what good looks like*; this imports *how mature fields review*. The two are orthogonal and both belong in the standing toolkit.
2. **The strongest net-new is an internal-control concept, not a code property.** G27 (segregation of duties) is a *workflow-authorization* discipline finance has owned for decades and software review has not named — high-value (fraud/SOX), cleanly reviewable, currently homeless.
3. **Restraint held, strongly.** Most signature practices of other disciplines were already present (poka-yoke, checklists, adversarial, reproducibility) — evidence the atlas's first-principles construction did not miss the *form* of good review, only a few specific *practices*.

## Disposition summary (provisional — owner-gated)

| ID | Candidate | Source discipline | Lean | Confidence |
|---|---|---|---|---|
| **G27** | Segregation of duties / dual-control in authz logic | financial audit | add-factor #14, detect-and-route | high |
| **G28** | Claims-vs-evidence verification (generalized) | scientific peer review | cross-cutting factor / synthesizer principle | med-high |
| **G29** | Root-cause vs symptom (band-aid detection) | manufacturing 5-whys / clinical | add-factor (#1 / hunting-silent-failures) | medium |

Plus: materiality → Q14; differential-diagnosis → G19; safety-margin → #28/G21; four-eyes-on-irreversible → #24; M&M → Q17/G15. **Net: 1 strong add-factor (G27) + 2 principles (G28/G29) + 5 feeds-existing — no new cluster.**

## Sources

- Maker-checker / four-eyes — <https://en.wikipedia.org/wiki/Maker-checker>; segregation of duties for SOX — <https://www.securends.com/blog/segregation-of-duties-for-sox-compliance/>; SoD as fraud prevention — <https://www.alvarezandmarsal.com/insights/segregation-duties-simple-idea-prevent-fraud>
- The Checklist Manifesto (Gawande) — <https://cpafma.org/articles/lessons-learned-checklist-manifesto-things-right>; aviation's lessons for audit — <https://www.mercia-group.com/mercia-news-and-blog/aviation-s-lessons-for-audit-the-difference-a-checklist-can-make/>
