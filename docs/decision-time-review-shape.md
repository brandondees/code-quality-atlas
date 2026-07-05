# Decision-time review — the third shape (design)

**Status:** design, 2026-06-12; §5 items 1 and 4 built 2026-06-12 (`shape: decision`,
`reviewing-decision-lifecycle`, the router's decision route); **§5 item 2 (the shared
decision-record checklist) built 2026-07-05** — see the note after §5. Item 3's
remaining decision-native lenses are unbuilt; see the note.
**Motivation:** the round-2 gap hunt ([`research/taxonomy-gap-hunt-round-2.md`](research/taxonomy-gap-hunt-round-2.md)) found that the single biggest omission is not a topic but a **shape** — see [Q15](open-questions.md#q15). This doc resolves *how* that shape enters the suite, which gates how the proposed #29 (decision lifecycle) is modelled.
**Depends on:** the router (D10), the `design:` flag already in `skills/manifest.yaml`, the synthesizer (D12), the proposed taxonomy v0.3 categories #28/#29.

---

## 1. The gap, stated as a shape

The suite has exactly **two review shapes** today:

- **diff-shaped** — review a change (`shape: diff` lenses): "is this code, as written, correct/safe/clear?"
- **repo/cron-shaped** — audit a whole repository on a schedule (`shape: repo` lenses): "what has rotted across the codebase?"

Round 2 surfaced a **third**: **decision-time** — review *a decision as it is being made*, before (or independent of) the code that implements it. Its artifact is an **ADR, RFC, design doc, adoption PR, deprecation plan, rollout plan, or capacity/DR design**, not a diff of implementation code. The questions it asks have no home in the other two shapes:

> *Is the rationale recorded? Are the assumptions stated — and do they still hold? Is there a revisit-trigger? What is the exit / rollback / sunset? Is this the right thing to adopt at all, vs. a smaller option or building it?*

This shape is where **all of axis C** (adopt / revisit-ADR / retire) and **most of axis E** (DR, capacity, resilience, progressive-delivery) live, plus B3 (model adoption) and D2 (privacy-by-design). These gaps are invisible to a diff *and* to a repo scan because they live in the decision, not the artifact.

## 2. What already exists (don't rebuild it)

The suite is **not** starting from zero on decision-time:

- **`manifest.yaml` has a `design: true` flag** on ~9 lenses (tracing-correctness, module-design, restraint, llm-integration, security, migration-safety, concurrency, api-contract, observability). Marked lenses already claim to work on "design docs / plans," and the router surfaces them with a ◆.
- **The router has a "Design doc / plan / RFC" route** that fans out to the design-capable lenses, with the note *"pick by the design's domain, from design-capable (◆) lenses only."*

So a **nascent** design-time mode exists — but it is *passive*: it reuses diff-lenses' judgment on a design doc. It does **not** ask the decision-native questions in §1 (rationale/assumptions/revisit/exit/adopt-at-all). The gap is that no lens is *built for* the decision as its primary object.

## 3. The options

- **(a) A new lens family** — dedicated decision-review lenses that trigger on ADR/RFC/adoption artifacts (e.g. `reviewing-adoption-and-exit`, `auditing-decision-records`, `reviewing-operational-design`).
- **(b) A mode on existing lenses** — formalize the `design:` flag into a real "decision-record" mode: each design-capable lens gets an explicit decision-time checklist, not just its diff checklist applied loosely.
- **(c) Its own cluster** — a 7th taxonomy cluster, "Decisions & their lifecycle."

## 4. Recommendation — hybrid: **shape is orthogonal to topic**

The cleanest model separates two things the question conflates:

- **Decision-time is a *shape*** (like diff and repo) — a cross-cutting *mode* that can apply to many topics. Formalize it as **(b)**: promote `design: true` into a first-class `shape: decision` capability, where a marked lens carries an explicit **decision-record checklist** (rationale recorded? assumptions stated & current? revisit-trigger? exit/rollback/sunset? alternatives weighed?) layered on top of its topical judgment. This reuses the router's existing design-doc route and the synthesizer, and honours D7 portability (it's just another checklist section, no new machinery).
- **Some topics are decision-*native*** and need **(a)**, a small number of dedicated lenses, because no diff-lens covers them at all: **adoption & exit** (build-vs-buy, lock-in), **decision-record audit** (does an accepted ADR still hold? — a `shape: repo` *cron* over ADRs, not diff), and **operational design** (#28: scale/recover/degrade). These are new lenses, not modes on old ones.

Reject **(c)** (its own cluster): decision-time cuts *across* clusters (a security decision, an architecture decision, an operational decision), so a single cluster would re-create the double-booking G1 warns against. The shape is orthogonal to the existing topic-clusters, exactly like "diff vs repo" already is.

### Topic vs. shape — resolving #29

This dissolves the "is #29 a category or a shape?" tension from Q15:

- **#29 "Decision lifecycle" is a *topic* category** (choose → adopt → revisit → retire) — it belongs in the taxonomy alongside the other 27, in Cluster VI.
- **`shape: decision` is the *shape*** that #29 (and parts of #27, #28, #25) are reviewed in.

A topic and its natural shape are different axes — the same way #21 (maintainability) is a *topic* whose natural *shape* is `repo` (G7). #29 is simply the topic whose natural shape is `decision`.

## 5. Concrete proposal (feeds v0.3 + the manifest)

1. **Add `shape: decision` to the manifest vocabulary** (alongside `diff`/`repo`). The existing `design: true` lenses are re-expressed as "diff-shaped, also decision-capable"; the decision-native lenses below are `shape: decision`.
2. **A shared `decision-record checklist`** (rationale / assumptions-still-valid / revisit-trigger / exit-rollback-sunset / alternatives) that every decision-capable lens appends — generated once, reused, like the synthesizer's finding contract.
3. **New decision-native lenses** (gated on the v0.3 category decisions): adoption-&-exit (#29), decision-record audit (#29, `shape: repo` cron over ADRs), operational-design review (#28).
4. **Router:** upgrade the thin "design doc / RFC" route into a decision-time *family* selector, and add routes for adoption-PRs, deprecation plans, and capacity/DR designs.

## 5a. §5 item 2 — built 2026-07-05

The shared decision-record checklist landed as a generator-level addition rather
than a research section: `tooling/generate.py`'s `_scope_line` now appends it to
every `design: true` lens's scope line (`skill.design` branch) — *"When the design
doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan),
also run the shared decision-record checklist: is the rationale actually recorded
(not just the outcome); are the stated assumptions still current; is there a
revisit-trigger; is an exit, rollback, or sunset path defined; were real
alternatives weighed, not just the chosen option justified after the fact?"* — and
states the finding is reported the same way as a topical one, not a separate
report. This closes §2's original complaint that design-capable lenses applied
their diff judgment to a decision "passively," without asking the decision-native
questions.

Chosen as generator prose (mirroring the existing "Reviewer discipline" and
"Mechanizing these checks" blocks) rather than a `built_from` research section,
because it is cross-cutting infrastructure applying uniformly to all 15
design-capable lenses, not a topic owned by one taxonomy category — the same
precedent as the router and synthesizer (`built_from: []`). It required no
manifest schema change: every design-capable lens already regenerates it for
free. Two representative lenses named in the router's decision route —
`tracing-correctness-and-invariants` and `checking-restraint` — gained a new eval
scenario each (an ADR input) demonstrating the checklist firing alongside the
lens's own topical finding; `python -m tooling.cli generate`/`drift`/`eval` and
the full pytest suite are clean. **Not yet cross-model re-gated** (no local model
runtime available in the building session) — pending per the
[regeneration runbook](runbooks/regenerating-skills.md)'s cross-model gate before
the next release lands; the remaining 13 design-capable lenses did not get a new
eval scenario (their existing scenarios are unaffected since none target decision
input) and can gain one opportunistically as decision-shaped review gets used.

§5 item 3's `decision-record-audit` (a `shape: repo` cron over existing ADRs — does
an accepted decision still hold?) and a standalone `adoption-&-exit` lens remain
unbuilt; `reviewing-decision-lifecycle` currently folds adoption/exit judgment and
one-off staleness review into a single decision-shaped lens rather than splitting
them. Operational design shipped as `reviewing-resilience-and-scalability`, but as
`shape: diff` + `design: true` (not `shape: decision`) — it reviews a concrete
system or its design doc, not a decision record, so it now also carries the
decision-record checklist via this same mechanism when applied to a design doc.

## 6. Open sub-questions

- Does the decision-record audit (does an ADR still hold?) live as a `shape: repo` cron lens, or as a decision-time lens re-run? (Lean: cron — it's a periodic sweep, like the other repo audits.)
- How does `shape: decision` interact with the team-preferences overlay (Q13) — can a team set which decisions *require* a recorded ADR?
- Granularity of the decision-record checklist: one shared section, or per-domain variants? (Lean: one shared, per D7's single-default-approach rule.)
- Does the synthesizer (D12) need a decision-specific verdict vocabulary (e.g. *adopt / adopt-with-conditions / revisit-by-date / reject*) distinct from block/approve?
