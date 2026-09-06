# Eval-hardening campaign log

This is the full, chronological narrative of the Q21 suite-wide eval-hardening
campaign (risk-tiered rollout across the floor tier and all 35 preference-tier
lenses, cross-model re-gating, tuning passes, and the model-baseline research
along the way) — moved out of [`open-questions.md`](open-questions.md) on
2026-09-06 (#426), where it had grown to occupy roughly 700 lines of the
"Genuinely still open (undecided)" section, crowding out the handful of lines
that were actually still-open items. Nothing here was trimmed or summarized in
the move — it's a verbatim relocation.

**Where the current status lives:** `open-questions.md`'s own `### Q21`
section carries the disposition, the still-open scope (extending this same
A-E adversarial pattern to any new lens or shape added after this pass), and
the campaign's later chapters (floor-tier hardening, wave-1-first, wave 2,
the first wave-3 lens, the cross-model-re-gate methodology, the eventual
`qwen3.5:4b` floor-of-record promotion). **What's here:** the wave-3
per-lens hardening detail (each remaining preference-tier lens's A-E scenario
breakdown and cross-model re-gate result) that the top-level doc's own
"Genuinely still open" paragraph had accumulated but the `### Q21` section
itself doesn't separately restate, plus the map-taxonomy gap-hunt recap
(G12-G32 — full detail and disposition now lives in
[`map-gaps.md`](map-gaps.md) instead) and one resolved pending-re-gate note.
See [`session-log.md`](session-log.md) for the even-more-granular
session-by-session account this narrative itself points to throughout.

---

**Genuinely still open (undecided):**
Q24 (should we restructure routines/triggers, or move to a different
agent-orchestration tool, for more control over the review-enforcement
environment than Claude Code cloud currently allows — open, no disposition yet;
Q23 resolved **yes** in the meantime, which narrows but does not close this
question — see Q24's own entry),
Q22 (does the atlas's own review pass *execute* the checks it cites — three
instances where it named the rule that would have caught a defect and
cleared it anyway, all three then caught by an external reviewer; Phase 1
(the standing-dispute check) ✅ shipped 2026-09-01, Phase 2 (falsification
attempts) stays owner-gated pending signal),
Q21 (suite-wide eval comprehensiveness — risk-tiered rollout + the opt-in `eval_min`
mechanism ✅ built 2026-07-18; **all five floor-tier lenses now hardened**
(`sweeping-for-security`, `tracing-correctness-and-invariants`,
`reviewing-migration-and-data-safety`, `reviewing-concurrency-and-async` — the
last of which surfaced the campaign's worst floor-of-record gap yet, ~71%
missed — and `hunting-silent-failures`, the fifth and final one); the
preference-tier rollout is now underway, wave-1-first: `reviewing-module-design`,
`checking-restraint`, `reviewing-naming-and-readability`,
`reviewing-llm-integration`, and `finding-maintainability-hotspots` hardened
(wave-1-first sub-wave complete), and **wave 2 opened 2026-08-07 with
`reviewing-accessibility-and-i18n`** (3 → 25, the widest scope-to-coverage gap
left in the wave: one baseline suite covering two whole domains) followed by
**`reviewing-test-quality`** (5 → 24 — the lens whose false negatives compound,
since a missed test-quality defect lets every other lens's regression net rot)
and closed 2026-08-08 by **`reviewing-performance-and-efficiency`** (4 → 26),
which leaves **every lens in waves 1 and 2 hardened, 11 of 11**; wave 3 opened
2026-08-09 with **`auditing-config-and-build-hygiene`** (3 → 28, and the first
suite re-gated against the floor of record in the same session it was authored —
13/28, which is what a bar looks like); **wave 3 continued 2026-08-14 with
`reviewing-install-and-upgrade-experience`** (4 → 28, re-gated the same
session — recall 11/21, precision 5/7; see session-log for the fabricated
support-window figure and the fourth instance of the not-applicable-vs-"No
findings" gap) **and `auditing-documentation-health`** (3 → 23, re-gated the
same session — recall 16/17, precision 4/6, the campaign's best
floor-model recall on any lens yet; see session-log for the fifth instance
of the not-applicable gap, in a sharper "confidently indicts from absence of
evidence" shape rather than a silent pass); **wave 3 continued again
2026-08-15 with `checking-idioms-and-consistency`** (3 → 21, re-gated the
same session — recall 12/15, precision 4/6; see session-log for the
counterweight check failing its own dedicated test, the exemption-claim-vs-
correctness-claim split behind two of the three misses, a reproducible
model-cold-start bug now fixed with a warm-up request in the runbook, and
the sixth instance of the not-applicable gap) **and again the same day with
`auditing-compliance-and-provenance`** (3 → 22, re-gated the same session —
recall 11/16, precision 5/6, the campaign's best recall on this lens's
classic license/PII/copyleft checks but a clean miss on every check added
purely by hardening (SPDX-header-only gaps, accessibility-as-legal); see
session-log for a self-review-caught factual error in the eval's own DEP5-glob
claim (fixed pre-merge), a full deference to a false compliance-skip
exemption over real employee PII, and the seventh instance of the
not-applicable gap); 22 preference-tier lenses remain. **A same-day tuning
experiment then targeted the not-applicable gap directly** (owner request,
after 7 straight instances of "recording the gap without attempting to close
it") — a worked "Not applicable: ..." example added to three already-hardened
lenses across both shapes, full re-gate on all three: all three target
scenarios fixed, plus two unplanned bonus fixes on the exemption-claim axis,
aggregate recall 34/52→39/52 and precision 14/19→15/19, alongside two newly
discovered regressions (see [`runbooks/cross-model-re-gate.md`](runbooks/cross-model-re-gate.md)
and session-log for the full reconciliation and the still-open regressions).
Tuning still has headroom on this substrate — the owner's own stated
criterion for pivoting to a floor-model search was "if it doesn't help,"
and it did, so no pivot yet). **A same-day follow-up attempted to fix the
tuning experiment's own two regressions and got a mixed, mostly negative
result** — the idioms fix was inert (kept, harmless, didn't move the eval
scenario), and the install-upgrade fix was reverted after it caused a
*different*, previously-correctly-graded scenario to enter a non-terminating
runaway generation (diagnosed by isolating the exact request outside the
harness and watching `n_decoded` climb past 2,400 tokens with no stop). Both
regressions remain open; see
[`runbooks/cross-model-re-gate.md`](runbooks/cross-model-re-gate.md) and
session-log for the full diagnosis. **A follow-up session (2026-08-16)
tried both open regressions again (four more attempts across the two —
three on `checking-idioms-and-consistency` scenario 12, one on
`reviewing-install-and-upgrade-experience` scenario 26; still open — see
session-log for the full attempt-by-attempt account) and finished the
not-applicable rollout on the remaining lenses**: fixed on
`auditing-config-and-build-hygiene` (clean, +1 hit/0 new misses) and
`auditing-documentation-health` (fixed on a second attempt, after a first
attempt's fix over-corrected into a new false "Not applicable" on a
proportionate-documentation scenario — a second worked example fixed both
together); already passing on `reviewing-accessibility-and-i18n` (no
change needed); still open on `reviewing-performance-and-efficiency`
(two placements tried, neither moved the target scenario at all). On the
two interventions this session that isolated decision-rule-only prose
(no new example) — install-upgrade scenario 26's only attempt, and
documentation-health's second attempt (aimed at fixing the first attempt's
scenario-14 over-correction) — neither moved its target, while a worked
example did move both documentation-health's target and (in isolation,
before a full re-gate showed it net-negative elsewhere) idioms scenario 12's.
This is an observation about those specific attempts, not a claim that no
decision-rule wording could ever work or that a worked example always
succeeds — the performance-efficiency attempts show a worked example
failing to move its target too. A single isolated-scenario check is not
reliable evidence either way on this substrate (an identical request
returned a clean pass and a fabricated finding on consecutive calls at
`temperature: 0`), so every verdict in that session came from a full-suite
re-gate. **Wave 3 continued the same day with `auditing-dependencies-and-supply-chain`**
(3 → 22, picked as one of five lenses tied for the widest scope-to-coverage gap
in the wave — full re-gate the same session: recall 10/18, precision 4/4; see
session-log for the A-E breakdown and a fabrication pattern distinct from what
this campaign has documented elsewhere — the floor model inventing CVE IDs and
license names that appear nowhere in the scan, not just misreading ones that
do, on 4 of the 8 misses); **wave 3 continued 2026-08-17 with
`reviewing-pr-and-process-hygiene`** (6 → 31, the widest scope-to-coverage gap
yet in the wave — 29 checks across two full categories on 6 baseline
scenarios, highest `eval_min` in the suite. **Cross-model re-gate: resolved
2026-08-20 — 18/27 recall, 4/4 precision.** See the 2026-08-20 (fifteenth
follow-up) session-log entry: two claims-vs-evidence scenarios testing a
"pure refactor / no behavior change" claim against a smuggled real change
(a new dependency; a silently-flipped soft-delete filter default) both
return flat "No findings," accepting the false claim outright. One scenario
directly violates an explicit "do not fault the size here" instruction
rather than merely missing a finding. Two scenarios drop one half of a
two-part finding (an unrequested-scope "no more" half; a second,
equally-required stale-doc gap). One scenario drops the single most
specific, most important part of a multi-part claim (a conditional
operator smuggled inside a "pure refactor"). Every other adversarial-
pressure scenario held. See session-log for the A-E breakdown and an
initial-pass miscount of the checklist caught and corrected before shipping);
**wave 3 continued the same day with `reviewing-ai-authored-code`** (4 → 20 —
18 owned checks on 4 baseline scenarios, the widest remaining gap once
`reviewing-pr-and-process-hygiene` shipped; deliberately skips a parallel
B-axis sweep of the 9 checks it shares with the already-hardened
`auditing-dependencies-and-supply-chain` per G1's single-owner principle,
concentrating instead on this lens's own AI-authorship-signature territory
and its unusually large six-target delegate surface. **Cross-model
re-gate: resolved 2026-08-20 — 12/16 recall, 4/4 precision.** See the
2026-08-20 (sixth follow-up) session-log entry: two complete blanks on
the suite's own adversarial traps (scenario 12's inverted permission
check missed despite no framing pressure at all; scenario 15's "ship
today... rubber-stamp" framing suppressing the public-read-write S3
ACL finding), a dropped `reviewing-test-quality` handoff on an
otherwise-correct catch (scenario 10), and a template misapplied
wholesale — a fabricated issue-tracker citation (scenario 7) diagnosed
as a package/slopsquat risk and routed to
`auditing-dependencies-and-supply-chain`, a lens with nothing to do
with the actual defect. See session-log for the A-E
breakdown and a factual claim about a real AWS S3 canned ACL value caught
and corrected during authoring, before shipping); **wave 3 continued
2026-08-18 with `reviewing-observability-and-operability`** (3 → 20 —
one of four lenses tied for the widest remaining gap, 10 checks on 3
baseline scenarios, picked over the other three since it directly
answers a logging/telemetry coverage question raised earlier the same
session; `design: true`, so this pass adds an A-group design-doc
scenario unlike the diff-only lenses hardened earlier in the wave;
cross-model re-gate deferred, no Ollama in this container; see
session-log for the A-E breakdown and its three delegate scenarios,
each grounded in a documented ownership boundary — two in
`map-gaps.md`'s G1 table, one in a target lens's own documented scope).
**Cross-model re-gate: resolved 2026-08-20 — 11/16 recall, 4/4
precision.** See the 2026-08-20 (fourteenth follow-up) session-log
entry: three delegate scenarios self-adjudicate instead of routing
(10 never mentions auditing-compliance-and-provenance; 11 and 12 both
give their own specific fixes instead of routing to
auditing-config-and-build-hygiene and
auditing-enforcement-and-meta-artifacts respectively), one scenario
drops a third, separately-named required finding (2's missing purge
metric), and one is a sharp misdiagnosis via template reuse — scenario
9's already-correctly-structured log line gets scenario 1's
"unstructured, ungreppable log" finding text reused almost verbatim,
missing the real hot-loop-volume defect entirely. Every
adversarial-pressure scenario held, and precision was perfect (4/4).
See session-log for the full breakdown); **wave 3 continued the same day with `reviewing-api-contract-safety`**
(3 → 20 — tied for the widest remaining gap, picked over its ties as
this campaign's own most frequently cited foundational lens rather than
by a topical tie-breaker; `design: true`, A-group included; its three
delegate scenarios are grounded in the lens's own heuristics
cross-references — cross #3, #8, #2 — to reviewing-concurrency-and-async,
checking-idioms-and-consistency, and hunting-silent-failures
respectively. **Cross-model re-gate: resolved 2026-08-20 — 10/15 recall,
4/5 precision.** See the 2026-08-20 (third follow-up) session-log entry:
all three C-group delegate scenarios drop the routing half even with the
owned finding caught (scenario 9 adjudicates a race it should route to
`reviewing-concurrency-and-async`; scenario 10 recommends its own fix
instead of routing to `checking-idioms-and-consistency`; scenario 11 never
routes its robustness-nuance finding to `hunting-silent-failures`), two
partial catches each missing one of two co-equal named findings (scenarios 1, 5),
and a false-positive precision failure fabricating a breaking change on a
textbook-correct field deprecation (scenario 17). Three adversarial-claim
defenses held (scenarios 12, 15, 16) and a distractor-buried breaking
rename was found among eight non-breaking changes (scenario 13).) **and
again the same day with `auditing-architecture-conformance`** (3 → 20 — one of the
four-way tie this wave opened with; picked over its tied peer
`auditing-infrastructure-as-code` since its defects don't require
fabricating cloud-provider specifics, lower risk on this campaign's
recurring factual-accuracy concern; repo-shaped, so its A group supplies
raw import statements across real files rather than a pre-digested scan,
the same input-shape gap `auditing-config-and-build-hygiene`'s A group
found; its three delegate scenarios are grounded in the lens's own
heuristics cross-references — cross #26, #13, #3/#15 — to
auditing-config-and-build-hygiene (feature-flag architecture vs.
lifecycle, per `map-gaps.md`'s G1 split), reviewing-api-contract-safety,
and reviewing-concurrency-and-async / reviewing-performance-and-efficiency
respectively; **CodeRabbit caught two real issues pre-merge** — an
arrow-chain rule notation that literally implied the flagged edge was
allowed, and two precision scenarios not requiring this lens's own exact
documented no-finding sentence — both fixed same-PR (#256). **Cross-model
re-gate: resolved 2026-08-20 — 9/16 recall, 4/4 precision.** See the
2026-08-20 (second follow-up) session-log entry: a cycle mischaracterized as
two different, both-incorrect
non-cycle violations (scenario 5), a response that correctly identifies
three real violations then contradicts itself with a closing "No findings:
conforms" line (scenario 7), two failures of the lens's own "don't trust a
green tool result" check (scenarios 8, 17), and a not-applicable
misclassification on a scenario that actually required deriving a finding
from non-import data (scenario 10). Precision held perfectly (4/4),
including an exact-match not-applicable response.) **and again the same
day with `auditing-infrastructure-as-code`** (3 → 20 — the last of the four-way
tie, closing it; repo-shaped, its A group supplies a raw `.tf` file and
raw Kubernetes YAML rather than a pre-digested scan; its three delegate
scenarios are grounded in the lens's own heuristics cross-references —
cross #20, #18, #30 — to reviewing-migration-and-data-safety (a
destructive RDS replace's own migration mechanics), auditing-dependencies-
and-supply-chain (a pinned module's own CVE status), and
auditing-enforcement-and-meta-artifacts (an unscoped wildcard scanner
suppression); two scenarios (one C-group, one D-group) were rewritten
mid-authoring after a self-caught accuracy concern — a `storage_type`
change that wouldn't actually force a Terraform replace, and CVE/default-
value claims against real, specific public Terraform Registry modules —
both replaced with technically-sound or fictional-internal-module
equivalents before this ever reached review, the same failure class Q22
tracks; CodeRabbit's independent review then caught a real Terraform
syntax error in the rewritten module (a `ref` argument instead of the
`?ref=` query-string form git-sourced modules actually use to pin,
leaving it effectively unpinned) plus the "D-group" mislabeling above,
both fixed same-PR; see session-log for the
full A-E breakdown and the rewrite details. **Cross-model re-gate:
resolved 2026-08-20 — 8/15 recall, 4/5 precision.** See the 2026-08-20
(eighteenth follow-up) session-log entry: an outright fabrication that
inverts a stated fact (scenario 10 calls a version-pinned module "not
pinned by version"), two scenarios dropping half or more of a
multi-part finding (5, 7), two dropped required routings to a sibling
lens on otherwise-caught findings (9, 11), one verbatim-reused remedy
that's technically wrong for the actual defect (16, an RDS
`publicly_accessible` flag "fixed" by a security-group ingress change
copied from a different scenario), a genuinely correct catch buried
under a flat self-contradicting "No findings" closer (13), and a
finding-shaped-header precision failure on a well-formed suppression
(19).) **This closes wave 3's
original four-way tie** — the next preference-tier pick needs a fresh
scope-to-coverage recompute rather than an existing tie; **wave 3 continued
the same day with `reviewing-resilience-and-scalability`**, picked by direct
user request rather than a recomputed tie (6 → 23 — 13 owned checks against
6 baseline scenarios, already denser than the usual 3-scenario baseline;
`design: true`, so this pass adds an A-group design-doc scenario; its three
delegate scenarios are grounded in the lens's own heuristics
cross-references — cross #3, #16, #26 — to reviewing-concurrency-and-async,
reviewing-observability-and-operability, and
auditing-config-and-build-hygiene respectively; see session-log for
the full A-E breakdown. **Cross-model re-gate: resolved 2026-08-20 —
12/18 recall, 5/5 precision.** See the 2026-08-20 (nineteenth
follow-up) session-log entry: a severe content-bleed (scenario 14's
response is scenario 5's verbatim, discussing an attacker and a
fraud-scoring check that don't exist in scenario 14's actual query),
two scenarios mislabeled "single-writer bottleneck" — the category
`expected_behavior` explicitly rules out — applied to a fairness/
isolation gap (10) and a correctly-functioning per-tenant limit whose
real issue is config lifecycle (15), and three scenarios reciting the
lens's full nine-item checklist mechanically, burying a correct catch
under a fabricated finding (9), a mislabeled and unrouted catch closing
with "Expected finding: None" (13), and a real catch immediately
contradicted by a flat "No findings" closer (19). Precision held
perfectly (5/5).); **wave 3 continued with a fresh scope-to-coverage recompute,
picking `auditing-enforcement-and-meta-artifacts`** (4 → 20 — tied with
`reviewing-decision-lifecycle` at the widest remaining gap, 10 owned
checks against 4 baseline scenarios each; picked over its tie for being
repo-shaped with strong direct wave-3 precedent rather than the
untested decision-shaped eval-authoring pattern; repo-shaped, so its A
group supplies raw source-file suppressions and a raw Prometheus rule
file with no scan digest supplied, the same input-shape gap this
wave's other repo-shaped lenses found; this lens's own
`reference/heuristics.md` carries no literal "cross #N" markers, so its
three delegate scenarios are grounded instead in the reciprocal
cross-references from sibling lenses that cite #30, plus
`map-gaps.md`'s G1 table — a hygienic suppression over a real SQL
injection → sweeping-for-security (#14), a healthy codegen-freshness
gate over a breaking unversioned spec change → reviewing-api-contract-
safety (#13), a correctly-marked vendored dependency over a reported
CVE → auditing-dependencies-and-supply-chain (#18, per G1's documented
"#18 deps, #30 codegen" split); see session-log for the full A-E
breakdown. **Cross-model re-gate: resolved 2026-08-20 — 9/15 recall,
5/5 precision.** See the 2026-08-20 (twentieth follow-up) session-log
entry: a severe template-reuse that contradicts the given facts
(scenario 8's runbook-linked, well-formed-except-for-`for:` alert gets
the "no runbook" boilerplate verbatim from two genuinely runbookless
scenarios), a response dropping two of three named suppression
instances while also garbling the given baseline numbers (1), a
correctly-caught surface defect missing both of its required judgment
calls (7), and all three of this lens's own delegate scenarios missing
their required routing — the SQL-injection-under-a-justified-
suppression case graded "valid" outright (9), the breaking-spec-change
case verdicted clean via a self-contradicting "Finding:.../No
findings" header (10), and the CVE'd vendored dependency adjudicated
directly instead of routed (11). Precision held perfectly (5/5).);
**wave 3 continued with `reviewing-decision-lifecycle`** (4 → 18 — its earlier
tie partner now hardened, leaving it alone at the widest remaining gap,
10 owned checks against 4 baseline scenarios; `shape: decision`, which
turned out to need no separate A-group input-shape gap since every
scenario is already a decision-record text block; its three delegate
scenarios are grounded in the lens's own heuristics.md cross-references
— cross #11/#18, #1/#13, #27 — to checking-restraint, reviewing-api-
contract-safety, and auditing-compliance-and-provenance respectively;
**this repo's own automated atlas-review routine, watching its own PR,
caught a real not-applicable-vs-no-findings inconsistency between two
E-group scenarios testing the same "no decision content" case on
different input shapes — fixed same-PR**. **Cross-model re-gate:
resolved 2026-08-20 — 6/13 recall, 3/5 precision.** See the 2026-08-20
(sixteenth follow-up) session-log entry: a single "unjustified
adoption, no exit" template recurs verbatim across seven of thirteen
defect scenarios, correct on three but wrong or incomplete on four —
twice ignoring a switching-cost estimate the query explicitly states
(6, 9), once contradicting a well-formed ADR's own described content
(7), once missing a required right-sizing cross-link to
checking-restraint (1). A different confirmed-correct template
(scenario 3's clean deprecation-plan write-up) gets reused verbatim on
scenario 8, missing that scenario's silently-changed financial field
and its required routing to reviewing-api-contract-safety. One
scenario misses the specific claim-verification test underneath an
otherwise-correct finding (5). Two precision failures: a format
substitution ("No findings" for the required "Not applicable:") and
an unwarranted demand for more evidence on a decision that already
clears both of this lens's checks. See session-log for the full breakdown);
**wave 3 continued with `reviewing-agentic-safety`** (4 → 22 — a
three-way tie at the widest remaining gap with
`reviewing-agent-legibility` and `reviewing-ethical-design`, all 9
owned checks against 4 baseline scenarios; picked for direct thematic
relevance to this session's own agentic PR-review tooling rather than
a topical or historical tie-breaker; `design: true`, so this pass
includes an A group; its three delegate scenarios are grounded in the
lens's own documented cross-references — the trifecta-framing/
mitigation split, "cross #16", and "the tool contract to #13" — to
reviewing-llm-integration, reviewing-observability-and-operability,
and reviewing-api-contract-safety respectively. **Cross-model re-gate:
resolved 2026-08-20 — 12/17 recall, 3/5 precision.** See the 2026-08-20
(fourth follow-up) session-log entry: all three C-group delegate
scenarios missed, each a different shape (dropped second finding and
inverted routing direction on scenario 11; ownership claimed instead of
routed on scenario 12; a fabricated least-privilege violation replacing
the real finding entirely on scenario 13), plus a fourth mis-routing
failure on scenario 8 (a defect this lens owns outright, deflected to
`sweeping-for-security` with no delegate framing in the query), a
fifth recall miss on scenario 17 (the real hazard is caught, but a
fabricated finding on an unrelated cosmetic hunk also gets reported,
missing the requirement not to be distracted), and two precision
failures — scenario 20 fabricates a finding on a memory write the
query shows is already validated, provenance-tagged, and expiring,
and scenario 22 opens with a finding-shaped header before its own
body concedes the pinned, validated MCP server needs no scrutiny;
see session-log for the full
breakdown); **wave 3 continued with `reviewing-agent-legibility`**
(4 → 21 — a two-way tie at the widest remaining gap with
`reviewing-ethical-design`, both 9 owned checks against 4 baseline
scenarios; picked as the technically lower-risk of the two and a
continuation of the prior pick's agent-tooling theme; `shape: diff`,
not design-capable, so no A group; its three delegate scenarios are
grounded in the lens's own heuristics.md cross-references — the
"why-not-what" #7 boundary, "xref #21" change-amplification, and #22
doc-drift — to reviewing-naming-and-readability, finding-
maintainability-hotspots, and auditing-documentation-health (#22's
documented primary owner) respectively. **Cross-model re-gate:
resolved 2026-08-20 — 9/16 recall, 5/5 precision.** See the 2026-08-20
(seventh follow-up) session-log entry: three complete blanks on core
checks (6's constant-with-no-local-rationale, 10's what-vs-why comment
distinction, 13 falling for a "no context needed, fully
self-explanatory" suppression comment), three scenarios wrongly
dismissed as "Not applicable" when squarely in scope (8's missing
do-not-touch guardrail on a new generated directory, 9's missing
llms.txt-style index on a README that markets AI-assistant
consumption, 12's cross-document contradiction between an
otherwise-accurate AGENTS.md and README.md), and a wrong-lens routing
(11 routes the repo-wide duplication pattern to
checking-idioms-and-consistency instead of the named
finding-maintainability-hotspots). Every adversarial-pressure scenario
held (14's unverifiable "already updated elsewhere" claim, 15's
deadline framing, 16's cosmetic-hunk distraction). See session-log for
the full breakdown);
**wave 3 continued with `reviewing-ethical-design`** (4 → 21 — its
earlier tie partner now hardened, leaving it alone at the widest
remaining gap, 9 owned checks against 4 baseline scenarios; its three
delegate scenarios are grounded in this lens's own documented routing
boundaries — "route the protective-control side to #14", the
consent-as-law/#27 boundary applied to a distinct regulatory facet
(under-13 age-gating) than the 4 originals already exercise, and a
second, distinct a11y-mechanics instance (contrast vs. keyboard
operability) — to sweeping-for-security, auditing-compliance-and-
provenance, and reviewing-accessibility-and-i18n respectively.
**Cross-model re-gate: resolved 2026-08-20 — 9/16 recall, 4/5
precision.** See the 2026-08-20 (eighth follow-up) session-log entry:
a "manipulative default" finding gets recited verbatim on three
scenarios (1, 6, 13) regardless of fit — correct on 1 and 13, but
misapplied on 6, where the actual defect is the distinctly-named
**consent theater** category (a correctly-recorded preference the send
path never checks), and the same template also misfires on 7 (mislabeled,
a nonsensical GDPR routing) — then goes missing entirely on 16, the
suite's own cosmetic-hunk trap hiding the identical default pattern
the model recites unprompted elsewhere in the same run. Two complete
blanks on this lens's own vulnerable-user and security-boundary checks
(10's CSRF-vulnerable confirmation link, 11's missing age-gate on a
collected birthdate). Two accessibility-as-exclusion scenarios split on
one distinguishing requirement — 9 caught, 12 missing the "both
controls are structurally accessible" distinction from 9's different
defect type. Every adversarial-pressure scenario held. See
session-log for the full breakdown); **wave 3 continued with
`auditing-decision-record-currency`** (5 → 20 — the widest gap among
the 9 remaining lenses that fit the established shape:diff/repo A-E
pattern (10 owned checks against 5 baseline scenarios);
`reviewing-artifact-conventions` scored a nominally wider raw gap but
is `shape: artifact` (presence-activated, single-rubric), a taxonomy
this campaign hasn't adapted yet, so it was set aside rather than
forced into this pass; `shape: repo`, not design-capable, so no A
group; its three delegate scenarios are grounded in this lens's own
closing heuristic ("escalate the judgment call... route to the
decision's owner") — two fresh revisit-trigger/EOL instances to
reviewing-decision-lifecycle (#29, its documented pairing partner) and
one archive-index-drift instance to auditing-documentation-health
(#22, the discoverability analog). **Cross-model re-gate: resolved
2026-08-20 — 7/15 recall, 4/5 precision.** See the 2026-08-20
(seventeenth follow-up) session-log entry: three complete blanks (a
status-graph contradiction, a silent supersession, and a real finding
lost among eight records), a dropped second finding riding alongside a
correctly-caught orphaned record, a real-but-unverifiable revisit
trigger wrongly called clean, a certainty-overstating "EOL or on Hold"
conflation, an incomplete duplicate-ID finding missing its required
routing, a missed adversarial claim-verification check (accepting a
record's own "reviewed and reconfirmed" note at face value), and a
precision failure reusing a genuinely-correct "stalled proposed
record" template on a two-week-old proposal still in active
discussion; **wave 3 continued with `reviewing-interoperability`** (4 → 21 — the
widest gap among the 8 lenses remaining after the recompute corrected
an off-by-one in the running tally (8 owned checks against 4 baseline
scenarios); `shape: diff`, not design-capable, so no A group; its
three delegate scenarios are grounded in this lens's own documented
defer list ("defers the contract we author to #13, internal
correctness to #4, ... config to #26") — a correctly major-bumped
breaking change whose field-shape ambiguity routes to
reviewing-api-contract-safety (#13), a correctly RFC-3339-formatted
timestamp whose wall-clock duration measurement routes to
tracing-correctness-and-invariants (#4), a hardcoded-port co-existence
finding whose configuration-practice verdict routes to
auditing-config-and-build-hygiene (#26); see session-log for the full
breakdown. **Cross-model re-gate: resolved 2026-08-20 — 8/16 recall,
4/5 precision.** See the 2026-08-20 (twenty-first follow-up)
session-log entry: three scenarios get an identical, nonsensical
"route to sweeping-for-security (#14)" clause tacked onto findings
that have nothing to do with security — a habit picked up from the two
scenarios where that routing genuinely fits — including one (scenario
10) that invents a SemVer violation on a change that was *already*
correctly major-bumped, missing the actual required field-ambiguity
finding entirely; two scenarios reuse the RFC 3339 "space separator,
no offset" template on code whose timestamp formatting is already
correct, missing the real defects underneath (a non-IANA timezone
label, a non-BCP-47 locale tag, and a wall-clock duration measurement
that should route to #4); one correct catch is undercut by a
fabricated RFC 4180 quoting claim that contradicts its own required
distinguishing point; a real PUT-idempotency violation buried among
five cosmetic hunks got a complete blank; and the sole precision
failure reuses a hardcoded-port template on a port that's actually
externally configurable via an environment variable. **This closes the
Q21 preference-tier cross-model re-gate backlog** — every lens left
deferred from the wave-3 hardening pass now has a recorded result.);
**wave 3 continued with `reviewing-data-transformations-and-contracts`**
(12 → 28 — explicitly deferred to this exact campaign at its G17 build
time rather than picked purely by widest-gap; `design: true`, so this
pass includes an A group (an RFC exercising both a topical gap and the
shared decision-record checklist); its three delegate scenarios route
to reviewing-api-contract-safety (#13, named in the lens's own
description but not yet exercised), and fresh second instances of
reviewing-migration-and-data-safety (#20) and
auditing-compliance-and-provenance (#27). **Cross-model re-gate:
resolved 2026-08-20 — 9/22 recall, 4/6 precision.** See the 2026-08-20
(twelfth follow-up) session-log entry: the dominant failure is a
"not applicable" template misapplied to five separate pipeline/
data-plane scenarios squarely in scope (6, 9, 13, 18, 19 — including
one that self-contradicts within its own sentence, "adds a new SQL
model but does not touch any SQL"), plus a second, separate canned
"data-diff is exactly the evidence" positive-verdict template that
bleeds from its one genuine origin (11) into four scenarios where no
data-diff was ever mentioned (15, 23, 25, 27 — two of them real misses,
two clean scenarios reaching the right verdict for a fabricated
reason). Two more complete blanks on textbook incremental-model
patterns (4, and 20's adversarial version, which explicitly notes "No
unique_key is configured" before wrongly excusing it). Two delegate
scenarios drop the required routing (17 never names #13; 5 fabricates
a uniqueness test the query never states exists). See session-log for
the full breakdown); **wave 3 continued with `auditing-data-pipeline-health`** (12 → 25 —
the scheduled repo-audit companion to the lens just hardened, same G17
build; picked as the closest sibling in shape rather than by an
explicit deferral note (a round-1 atlas-review finding on the prior PR
caught an earlier draft overstating this lens's own comment as
carrying "the identical deferral note" — it does not); `shape: repo`,
no A group; a pre-existing baseline-wording bug was also caught and
fixed — the kept "no data plane" scenario said "no findings" where
this lens's own discipline requires "Not applicable:"; its three
delegate scenarios route to auditing-compliance-and-provenance (#27,
a dedicated PII-inventory scenario distinct from the kept baseline's
combined stale-ownership case), reviewing-test-quality (#17, named in
this lens's own heuristics but never yet exercised), and a fresh
instance of reviewing-migration-and-data-safety (#20). **Cross-model
re-gate: resolved 2026-08-20 — 13/20 recall, 3/5 precision.** See the
2026-08-20 (thirteenth follow-up) session-log entry: two scenarios
drop a distinct, separately-named finding while catching another in
the same audit (3 misses the sharper of two freshness-config defects
plus its required delegations; 5 misses that 3 of 7 registry subjects
are set to `NONE`). Two delegate scenarios drop the required routing
and one fabricates a lens name that doesn't exist — `reviewing-data-
classification-and-retention (#17)` in place of the actual
`reviewing-test-quality` (16). One scenario softens a required "do not
recommend X" instruction into an either/or (4). One trend scenario
gets the headline direction right but drops both of its sharper,
specifically-required points (10). Two precision failures, two
different mechanisms: 25 reuses another scenario's confirmed-correct
template almost verbatim, asserting a `datacontract test` job and
contracts the query explicitly says don't exist; 24 wraps a clean
result in a self-generated "Findings:"/`severity: None` wrapper, the
same finding-shaped-header confusion seen on two other lenses earlier
this session, not borrowed content. See
session-log for the full breakdown); **wave 3 continued with
`reviewing-outcome-instrumentation`** (10 → 23 — widest gap among the
lenses fitting the established pattern (11 owned checks against 10
baseline scenarios), though the baseline was unusually rich already;
`design: true` had never actually been exercised despite the lens
being design-capable, so this pass added the missing A-group RFC
scenario; its three delegate scenarios route to
auditing-compliance-and-provenance (#27, a dedicated PII-in-event-
properties instance), reviewing-ethical-design (#36, a second Goodhart/
proxy instance distinct from the kept baseline's autoplay case), and
reviewing-data-transformations-and-contracts (#40, a breaking event
rename mid-measurement, distinct from the kept baseline's simple new-
event case). **Cross-model re-gate: resolved 2026-08-20 — 12/19
recall, 3/4 precision.** See the 2026-08-20 (tenth follow-up)
session-log entry: a Goodhart-problem template fires correctly twice
(5, 14) then misapplies twice more — once to an actual PII-in-event
scenario (13, missing the #27 routing entirely) and once to a
guardrails-deferred-under-pressure scenario (18, missing the
guardrails finding entirely); the same pattern recurs with a
"not applicable" template, correct on a genuine internal refactor (6)
but misapplied to a scenario built to test exactly that mistake (19,
five cosmetic files hiding one real instrumentation gap). One complete
blank (8's tracking-plan conformance check) and one confidently wrong
"yes" on a falsifiability question that should be no (9). One false
positive reusing a neighboring scenario's diagnosis without checking
it applies (21). Two scenarios drop the outcome-instrumentation-
specific angle for a generic finding (11's decision-record
alternatives-weighing gap; 15's event-rename recommendation pointing
the wrong direction). See session-log for the full breakdown); **wave 3 continued with
`reviewing-conceptual-integrity`** (10 → 22 — tied with
`reviewing-usability-and-interaction` on raw scope (9 owned checks / 10
baseline scenarios each); broke the tie on what was actually still
uncovered rather than the raw count — this lens's baseline already had
its A-group covered but left the release-note-duplication-cost proxy
unexercised, and offered richer unused delegate grounding
(reviewing-module-design, checking-idioms-and-consistency, a second
checking-restraint instance) than usability's two already-exercised
cross-refs; usability is now the clean next pick with a single,
well-defined gap (no A-group scenario despite being design-capable).
**Cross-model re-gate: resolved 2026-08-20 — 7/16 recall, 4/6
precision.** See the 2026-08-20 (eleventh follow-up) session-log
entry: the sharpest single failure is a content-bleed, not a wrong
judgment — scenario 9 (adding sharing to Reports, expected "No
findings") gets a Major-defect response about deleting a different
resource and orphaned rows, verbatim scenario 2's subject matter.
A CLI-flag-accretion template correctly fires once (3) then bleeds
leftover CLI-specific phrasing (`` `--help` will list both ``) into
two non-CLI scenarios (10, 17). Scenario 7 skips the bounded-context
counterweight entirely, reporting a same-word collision as a finding
without checking whether the two meanings ever meet on a surface a
user sees. Two adversarial design-doc scenarios (8, 19) and two more
standard-pattern scenarios (13, 18) are complete blanks. Two precision
failures: scenario 9's content-bleed (above) counts as one; scenario
21 additionally contradicts its own stated reasoning in the same
sentence. See
session-log for the full breakdown); **wave 3 continued with
`reviewing-usability-and-interaction`** (10 → 22 — the clean pick left
from that tie; the baseline already covered all 9 checklist bullets,
so this pass added only the missing A-group scenario plus the
standard C/D/E groups; its three delegate scenarios route to
reviewing-accessibility-and-i18n (#23, named in the lens's own
description but never yet exercised), reviewing-performance-and-
efficiency (#15, a second instance distinct from the kept baseline's
upload-progress case), and reviewing-ethical-design (#36, a second
instance distinct from the kept baseline's undismissable-modal case).
**Cross-model re-gate: resolved 2026-08-20 — 8/18 recall, 3/4
precision.** See the 2026-08-20 (ninth follow-up) session-log entry:
two scenarios agree with the exact false premise they're built to
correct (6 accepts "a CLI doesn't need usability review" outright; 7
accepts "intentional, don't want abandonment" as a reason to withhold
a controllability finding), four complete blanks on core checks (1's
unhandled states, 10's recognition-over-recall, 16's suppression
comment, 18's bulk-delete buried among cosmetic files), two dropped
routing halves in opposite directions (13 self-adjudicates a defect
that should route to reviewing-performance-and-efficiency; 14 never
routes its obstruction verdict to reviewing-ethical-design), two
partial catches missing a co-equal named element (2, 11), and one
precision failure that reaches the right verdict by the wrong,
content-bled reasoning (20). See
session-log for the full breakdown); **wave 3 closed with two lenses
that didn't fit the standard pattern.** `reviewing-threat-model`
needed no new scenarios at all — it already shipped its own native
21-scenario adversarial suite from original authorship (this lens's
own A-E-equivalent taxonomy, predating and independently converging
on the campaign's, per [`threat-modeling-design-time-security.md`](threat-modeling-design-time-security.md)
§5), so this pass only added the `eval_min: 21` floor that had never
been recorded. **Cross-model re-gate: resolved 2026-08-20 — 8/18
recall, 2/3 precision.** This is the `qwen2.5-coder:7b` floor-of-record
run originally deferred at this lens's own 2026-06-27 authorship gate
(three attempts aborted on a model-specific harness timeout back then;
`qwen2.5:7b`/`llama3.1:8b` both ran clean). See the 2026-08-20 (fifth
follow-up) session-log entry: that original gate's verdict — the 7-8B
tier is genuinely below this lens's reliable floor for lethal-trifecta
composition and delegation/escalation routing — is confirmed and
sharpened here by a systemic mechanism underneath, template-recitation
over analysis (the same failure class documented on the floor-tier
`reviewing-migration-and-data-safety` re-gate): a near-identical
STRIDE skeleton recurs regardless of scenario shape, producing wrong
sibling-lens routing (6, 8), two skipped human-escalation predicates
for custom crypto and third-party-auth (14, 15), two misdiagnoses that
dismiss the actually-relevant threat (9, 10), two core findings buried
under template noise (7's missing audit trail, 16's self-contradicting
"No findings" headline), two complete blanks including a failed
injection trap (2, 3), and a precision failure from the same template
firing on a fully-mitigated design (4). `reviewing-artifact-conventions`
(4 → 19) was the
genuine holdout: `shape: artifact`, presence-activated, reviewing one
artifact against a single published rubric (9 heuristics) rather than
a diff or design doc, so no prior A-E pass fit it directly — this
pass adapted the pattern instead of copying it (no A group; B 6 for
the six of nine rubric heuristics the baseline left untested; C 2,
both of and only the cross-references this lens's own description
names — auditing-documentation-health (#22) and reviewing-agentic-
safety (#32) — not a third, unverified target; D 5 adversarial; E 4,
including a fix to a pre-existing baseline bug where the not-applicable case
said "No findings"); see session-log for the full breakdown. **This
closes the preference-tier rollout at 35 of 35**, alongside the five
already-hardened, cross-model-re-gated floor-tier lenses.
**Cross-model re-gating the preference tier, left open by this pass,
completed 2026-08-20** — all 35 lenses now carry a recorded result;
see the Q21 detail entry below for the closing lens
(`reviewing-interoperability`) and the full per-lens breakdown in
session-log. Still open: adapting the A-E pattern to any *new* lens or
artifact shape added after this one;
Q17 (self-improving loop — stage 1 ✅ built 2026-07-18 (D17); stages 2-5 still design-only),
Q13 (team preferences overlay — Wave A built 2026-07-06, inference bootstrap
built 2026-07-18; finer-grained tiering still open),
Q6 (idiom packs),
Q8 (proactive/cron-shaped maintenance — partially built as the repo audits; the
Q3 residue — auto-application of flagged tidyings — lives here too),
and the Q2 residual low-priority candidates. Two new framing-class gaps were
also logged this pass ([`map-gaps.md`](map-gaps.md) **G12** validation-vs-verification /
stakeholder-intent — disposition: in-scope; **G13** *Tidy First?* economics &
proactive tidying mode — disposition open). A **round-3 gap hunt** (2026-06-14,
[`research/taxonomy-gap-hunt-round-3.md`](research/taxonomy-gap-hunt-round-3.md))
then added **G14–G19** via gap-finding methods that reason from outside the map
(external completeness model, stakeholder-vantage rotation, substrate sweep,
shape-axis extrapolation): G14 AI-authored-code defects, G15 production-evidence
review (a candidate 5th shape), G16 ethical/responsible-design, G17
data-engineering & data-contracts, G18 the two unowned ISO-25010:2023
characteristics (interoperability, safety), G19 review-coverage transparency, and
G20 the codebase/repo as a working environment for AI maintainers (the agent
vantage — a cluster-II rotation, mirror of G14; the agent-as-*operator* role is
mostly already mapped via #24/#32/#30), G21 operational time-bombs & exhaustion
classes (a failure-grounded sweep — cert/credential expiry & rotation, calendar/
clock time-bombs; add-factors), and G22 diff-isolation blindness (interaction /
composition defects — a missing change-set *unit*) — all **provisional,
owner-gated**, web-verified. A scope re-audit (2026-06-14, owner) then added
**G23** (detect-and-route: surfacing ≠ deciding — generalize G8; product/UX/value
findings are surfaced and routed to the right decider, not excluded) and **G24**
(candidate **Cluster VII — Product, Experience & Value**: usability, perceived
quality, UX consistency/content, inclusion, value/outcome instrumentation, trust/
transparency, conceptual integrity, i18n-of-experience, feature-value lifecycle —
[`research/product-experience-value-cluster.md`](research/product-experience-value-cluster.md)),
**G25** (re-audit of the rest of the exclusion pile — most exclusions held on the
no-artifact axis; sustainability + FinOps upgraded to routed #15 factors), and
**G26** (detect-and-suggest ≠ apply, defect ≠ improvement — the suite is
defect-only by a guard in every lens; improvement-suggestion is review-time;
refines Q3, narrows Q8). The recurring meta-lesson: reviewability is orthogonal
to authority (G23), reader identity (G20), and application-timing/valence (G26). A
**cross-discipline review-analog sweep** (importing mature review *practices* from
audit / science / manufacturing / clinical / aviation —
[`research/cross-discipline-review-analogs.md`](research/cross-discipline-review-analogs.md))
then added **G27** (segregation-of-duties / maker-checker dual-control in authz —
add-factor #14), **G28** (claims-vs-evidence verification, generalized from the
perf lens), and **G29** (root-cause vs symptom / band-aid detection); plus
feeds-existing notes (materiality → Q14; differential-diagnosis → G19;
safety-margin → #28/G21). The sweep mostly *confirmed* the atlas (poka-yoke maps
to #9/#10; checklists ≡ the whole form), so it yielded add-factors, not a new
cluster. Re-running shape-extrapolation on *security* and auditing the
synthesizer's own apparatus then added **G30** (threat modeling — STRIDE / DFD /
trust boundaries / abuse cases — as a *design-time* security discipline, distinct
from #14's diff-time vuln sweep; a strong instance of the Q15 decision shape) and
**G31** (the synthesizer's tension table is restraint-centric; enrich it with
cross-quality pairs like observability↔privacy, security↔usability). A final
**deliberate conflation audit** (enumerate every axis `X` for which
reviewability⊥X) then returned one net-new gap, **G32** (reviewability ⊥
*attribution* — pre-existing defects in touched code suppressed by the diff-only
filter; the Boy-Scout / opportunistic-surfacing principle, detect-and-route,
scope-bounded), and otherwise **confirmed the prior axes are covered** — a closure
signal that the framing seam is largely mined and the bottleneck is shifting from
finding to deciding. The pile is now consolidated into a ranked, dependency-
sequenced **synthesis** ([`research/gap-hunt-synthesis.md`](research/gap-hunt-synthesis.md))
— four build waves (foundations → add-factors → new lenses → bigger bets), with
the G23/G26 primitives and Q13/Q14/Q15 flagged as the upstream enablers most of
the high-value lenses depend on. A factor-level coverage audit
([`map-gaps.md`](map-gaps.md) G9) also found ~10 categories only partially
surfaced at the factor level — fixable through the manifest/research, with the
router half tracked as Q14. Everything else here is historical context kept for
provenance.

**Pending follow-up → RESOLVED (2026-06-12, local re-gate).** The cross-model
eval re-gate for the research-expansion additions ran on a laptop with Ollama.
All six skills whose heuristics changed since the expansion
(`reviewing-llm-integration`, `reviewing-decision-lifecycle`,
`auditing-enforcement-and-meta-artifacts`, `auditing-config-and-build-hygiene`,
`auditing-documentation-health`, `reviewing-pr-and-process-hygiene`) **pass** on
the 7-8B tier (`qwen2.5:7b`); the two new v0.3 skills were cross-confirmed on a
second family (`llama3.1:8b`). Every clean/healthy scenario correctly returned
"No findings" — no over-flagging regression. The only gaps observed are the
already-documented 7B ceilings (top-findings-only recall on dense audit scans;
cosmetic format-leak on qwen — a trailing "No findings:" sentence after real
findings, absent on llama). Per the runbook these are model-capability limits,
not heuristic regressions, so no tuning was applied. See the session-log entry
of the same date.
