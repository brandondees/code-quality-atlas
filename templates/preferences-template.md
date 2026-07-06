<!-- code-quality-atlas team-preferences overlay template. Copy this file to
`.code-quality-atlas/preferences.md` in the repo it describes (not into this
plugin repo) and edit the sections that apply. See docs/team-preferences-overlay.md
for the full design and docs/open-questions.md Q13 for status.

READ THIS FIRST — the one guardrail that matters:

Every entry below must be a considered choice a human on the team actually made,
not a pattern an agent noticed and wrote down on your behalf. A vibe-coded or
haphazard codebase can *look* like it encodes deliberate decisions when each one
was really an unconsidered approve-click — inferring preferences from "what the
code already does" would launder those accidents into ratified standards, which
is the worst failure mode a quality suite can have. So: hand-author this file, or
if an agent proposes entries from observed patterns, ratify each one individually
(edit its wording, confirm the rationale is real) before it counts. An entry with
no `decided:` line is not yet in effect.

Tiered precedence (do not skip): a finding is either PREFERENCE-tier (the code is
merely suboptimal by a contestable standard — naming, module shape, restraint
thresholds, idiom, doc depth, PR size, a11y priority for an internal tool) or
FLOOR-tier (the code is wrong or unsafe — it will break, corrupt, leak, expose, or
lose data; security, correctness, migration/data safety, and concurrency-safety
findings are always floor-tier). You can silently `suppress` a preference-tier
finding. You can never silently `suppress` a floor-tier finding — the strongest
move available on one is `acknowledge`, which keeps it visible in every report,
tagged `acknowledged deviation: <reason>`, and marks it non-blocking rather than
making it disappear. This split is enforced by every lens; nothing in this file
can turn it off. -->

# Team preferences — <repo name>

<!-- ============================================================
     1. LENS SELECTION / WEIGHTING
     Verb: set. Preference-tier only (re-ranks/mutes within the router's
     depth-mode breadth; it never lifts the cap or disables a floor lens's
     detection).
     ============================================================ -->

## Lens selection

<!--
- disable: reviewing-accessibility-and-i18n
  decided: 2026-01-01, @alice
  reason: internal-only admin tool, no external users, revisit if that changes
- weight: checking-restraint = always-run
  decided: 2026-01-01, @alice
  reason: this codebase has a history of premature abstraction; keep the brake
    pedal in every review regardless of the change shape
-->

<!-- ============================================================
     2. THRESHOLD TUNING
     Verb: set. Per-check numeric knobs (function length, complexity,
     coverage, PR size, etc).
     ============================================================ -->

## Thresholds

<!--
- check: reviewing-naming-and-readability / function length
  value: 120 lines (default guidance is "screenful-ish")
  decided: 2026-01-01, @bob
  reason: this service's handler functions interleave a lot of domain-specific
    validation that doesn't decompose cleanly; revisit if a function exceeds 200
-->

<!-- ============================================================
     3. HOUSE CONVENTIONS
     Verb: suppress (preference-tier findings only). Judgment-level idiom
     rulings that override a lens's generic taste.
     ============================================================ -->

## House conventions

<!--
- convention: fat service objects are intentional here — do not suggest
    extracting collaborators unless a second concrete caller exists
  decided: 2026-01-01, @carol
  reason: team explicitly chose a transaction-script style over DDD for this
    service; checking-restraint and reviewing-module-design should not nudge
    toward it
- convention: no dependency injection framework — constructor args only
  decided: 2026-01-01, @carol
  reason: matches the rest of the org's Go services; DI-framework suggestions
    are house-style noise here
-->

<!-- ============================================================
     4. SCOPED EXEMPTIONS
     Verb: suppress for preference-tier findings in the scoped path;
     acknowledge for floor-tier findings in the scoped path (still surfaces,
     still non-blocking).
     ============================================================ -->

## Scoped exemptions

<!--
- path: legacy/**
  effect: preference-tier findings suppressed; floor-tier findings acknowledged
    (still reported, non-blocking)
  decided: 2026-01-01, @dave
  reason: frozen code slated for deletion in Q3 2026, not worth active cleanup;
    see TICKET-1234
- path: generated/**
  effect: not reviewed (codegen output)
  decided: 2026-01-01, @dave
  reason: output of the OpenAPI codegen step; edit the spec, not this directory
-->

<!-- ============================================================
     5. STANDING ACKNOWLEDGEMENTS
     Verb: acknowledge. Known, accepted floor-tier deviations with a recorded
     rationale. The finding still surfaces in every report, tagged
     "acknowledged deviation: <reason>" — this never makes it invisible, only
     non-blocking.
     ============================================================ -->

## Standing acknowledgements

<!--
- finding: sweeping-for-security / homegrown crypto in src/legacy_signing.go
  decided: 2026-01-01, @eve (security lead)
  reason: predates the org's approved-crypto-library policy; migration tracked
    in TICKET-5678, targeted for the next major version. Accepted risk, not a
    false positive — do not re-litigate this in every review until the ticket
    lands.
  review_by: 2026-12-31
-->

<!-- ============================================================
     6. IMPROVEMENT-VALENCE VERBOSITY
     Verb: set (preference-tier). Every lens is defect-only by construction
     (the guard "do not suggest changes to code that is already correct").
     This dial opts a review up into nit-level, route: implementer tidyings on
     already-correct code (reorder for cohesion, remove dead code, bump a
     stale-but-working dep). Floor-tier defects are unaffected either way.
     ============================================================ -->

## Improvement-valence verbosity

<!--
mode: defects-only          # the default — preserves "clean PR -> No findings"
# mode: improvements-opt-in  # surface improvement nits too (route: implementer;
#                              apply, defer, or ignore each one)
decided: 2026-01-01, @alice
reason: team wants review noise low by default; individual reviewers can still
  ask for improvement-valence findings on a specific PR when they want them
-->
