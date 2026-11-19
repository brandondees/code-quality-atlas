# Plan: letting the GitHub App's users configure the Atlas reviewer service

**Status: decided 2026-11-18 — D81 records the owner's answers; docs only,
nothing implemented.** Brandon asked for this plan on 2026-11-18 ("plan out
some additions for allowing the github app's users to configure the service,
some of which I suspect can be progressing concurrently with the review
parity work") and answered its open questions the same day at 3:28 PM CT;
the answers are recorded as **D81** in
[`../open-questions.md`](../open-questions.md) and as §6 below (D80 stays
with #734's slice). **Added after D81, 2026-11-18 3:41 PM CT:** Brandon's
BYOK requirement — "I need the github app to allow individuals or orgs to
supply their own api endpoints and keys" — carried below as §2's BYOK
paragraph, §3's two BYOK rows, §4's two new bullets, slice **S10**, and
§7's decisions, recorded when Brandon accepted all nine recommendations
(4:15 PM CT). **Added in the later fix rounds:** the BYOK-bounds mechanism
(§4's operator-side accounting — the operator-observed-floor variant
withdrawn once the 5:13 answers made tenant keys required), the
tier-coverage correction and its 5:13 answer (§4's merge-base bullet; all
five floor-tier lenses protected), the S4 event-type decision (4:54 PM CT,
recorded in §6), the tenant-supplied-keys naming note (§2), the
invite-only gate (§2), and **§8** — Q1–Q3 and Q5 decided (5:13/5:51 PM
CT; Q5's answer amends §7 decision 9 to hold the installation admin's
daily cap), **Q4 open** (how to keep operator compute for tenants at or
near zero). Nothing
in this plan was run live: no model call, no
GitHub write, no Fly or secret change, no deployed setting touched.

The deployed service (Fly `atlas-reviewer-service`, the GitHub App
`code-quality-atlas`) is configured almost entirely by operator environment
variables plus two repo-level `REVIEW.md` lines. A user who installs the App
on their repository can tune none of it. This plan inventories what is
configurable today, proposes the user-facing surface and its precedence,
lists candidate settings with defaults and owners, states the security rules,
and slices the work so some of it runs concurrently with the parity track
(#734, #750, #713, #708).

## 1. What is configurable today

**A. Operator env, service level** (`atlas_reviewer/service.py`,
`service_admit.py`, `service_run.py`, `service_queue.py`,
`service_post.py`, `head_change.py`;
`atlas_reviewer/deploy-service.md`, `fly.service.toml`):

- Which repositories are reviewed at all: `ATLAS_REVIEW_REPOS`
  (`service.py`, default `brandondees/code-quality-atlas`).
- When a review happens at all: admission is a non-draft `pull_request`
  event of `opened`, `synchronize`, or `ready_for_review` on an allowlisted
  repo (`service_admit.py`), and the repo's default-branch narrowing filters
  exist since #756 merged (`review_base_include:`/`review_base_exclude:`
  and `review_skip_events:`). No label or schedule filter exists.
- A push that lands mid-review: `ATLAS_HEAD_CHANGE_POLICY` and
  `ATLAS_HEAD_CHANGE_CANCEL_FRACTION` (D79, default `keep`).
- Child execution: `ATLAS_SERVICE_MODE` (`agentic` default, D70),
  `ATLAS_SERVICE_DEADLINE_S` (60–14,400 s), `ATLAS_REVIEW_CONCURRENCY`
  (1–32; the constant `MAX_CONCURRENCY = 32` is code).
- Posting identity and the dedupe marker: `ATLAS_GITHUB_APP_SLUG`.
- Secrets and credentials: `ATLAS_GITHUB_APP_ID`, `ATLAS_GITHUB_APP_PRIVATE_KEY`,
  `ATLAS_GITHUB_INSTALLATION_ID`, `ATLAS_GITHUB_WEBHOOK_SECRET`,
  `ATLAS_SPRITES_TOKEN`, `ATLAS_OPENROUTER_API_KEY`. The review child receives
  only an env allowlist (the model key, the Sprites token, a read-only
  installation token, and the model/data-policy variables); it never receives
  the webhook secret or the App private key (`atlas_reviewer/README.md`,
  "The child process receives only an allowlist").
- Telemetry and state: `ATLAS_OTEL_ENDPOINT`/`_HEADERS`/`_EXPORT_BODIES`,
  `ATLAS_REVIEWER_STATE_DIR`; the one-off Fly path's `ATLAS_EVENT_JSON`,
  `ATLAS_HOLD_SECONDS` (`atlas_reviewer/deploy-fly.md`).

**B. Operator env, review level** (`atlas_reviewer/agentic_config.py` `ENV`,
the README's variable table): the model and data policy — `ATLAS_MODEL`,
`ATLAS_PROVIDERS`, `ATLAS_ALLOW_SAFETY_RETENTION`, `ATLAS_REQUIRE_ZDR` — the
spend guard `ATLAS_KEY_CEILING_USD`, the D68 per-lens budgets
(`ATLAS_PER_LENS_CALLS`, `ATLAS_PER_LENS_USD`) and ceiling
(`ATLAS_REVIEW_CEILING_USD`), the walls (`ATLAS_LENS_WALL_S`,
`ATLAS_REVIEW_WALL_S`), the pool (`ATLAS_POOL_SIZE`), the per-lens discipline
knobs (`ATLAS_NO_PROGRESS_TURNS`, `ATLAS_DUPLICATE_CALLS`,
`ATLAS_QUOTE_REPAIRS`, `ATLAS_QUOTE_TOLERANCE`, `ATLAS_CALL_RETRIES`), the
per-call token caps, `ATLAS_DIFF_PREFIX_SHARE` (D65), and the Sprite create
caps (`ATLAS_CREATE_RETRIES`, `ATLAS_CREATE_CONCURRENCY`). The one-shot
`review` command ignores these: its 3 calls, $3, and 200,000 input tokens are
D25's code constants.

**C. Repo file** — the reviewed repo's **merge-base** `REVIEW.md`
(`atlas_reviewer/review_wide.py`, read bound `MAX_CHECKED_BYTES` = 64 KiB,
read from the merge-base tarball so a PR cannot move its own values — D68,
D69):

- `review_ceiling_usd:` (D68) — **today it wins over the operator's
  `ATLAS_REVIEW_CEILING_USD` outright**, in either direction.
- `review_lens_include:` / `review_lens_exclude:` (D69) — applied by the
  controller; never widens the depth mode, never touches the critical tier;
  exclude wins over include.
- A seen-but-unusable line fails open to the default with a named note
  (D68's pattern); names are validated lens-shaped at parse so `REVIEW.md`
  cannot inject into the picker's trusted instructions (D69).

**D. Skill bundle** (`collapsed/skills/`, generated from `skills/` +
`skills/manifest.yaml`): the picker's guideline — the default breadth and the
auto-include shapes (D69) — plus the manifest's `tier: floor | preference`
split, which is what keeps a repo preference from silently suppressing a
floor-tier lens. The team-preferences overlay
(`.code-quality-atlas/preferences.md`, `docs/team-preferences-overlay.md`,
the six directive kinds with `suppress` bounded by tier) is read by the
generated lens `SKILL.md`s and by the Claude Code protocol
(`commands/atlas-review-pr.md` step 3 reads it, and the full convergence
policy, from the **base ref**), but **the service reads neither today** — its
repo-file surfaces are C's two merge-base lines plus #756's default-branch
admission lines (a different read source, per §4's two-tier rule).

**E. Code constants exposed nowhere**: the post limit
`MAX_COMMENT_CHARS = 65_000` (`service_post.py`), D38's 16,384-character
picker/conversation caps, the 8,192-character controller reserve (D67), the
round-log record cap (D74), D68's derivation defaults, and the depth-mode
breadths.

## 2. Proposed user-facing surface

**Precedence principle: user config tightens, operator config bounds — and
the per-review ceiling is the one value a repo may raise, within the
operator's max (D81, Q2 and its update).** A user may lower a budget, raise
a floor, or narrow what triggers a review — and narrowing itself splits into
two kinds (D81's 4:54 PM CT update): what a PR author cannot exploit (the
default-branch read, and no head-branch or label keys), and **repo-owner
opt-outs that knowingly reduce coverage**, of which `review_skip_events` is
the first; D81 keeps D68's semantics, so a
repo's `review_ceiling_usd:` may also raise its own per-review ceiling —
but the effective value is clamped to the operator's **max per review**,
one of the two per-tenant spend bounds the owner added on 2026-11-18
(3:39 PM CT): an operator max per review and a per-repo daily budget.
Nothing in user config can change the model, providers, or data policy,
widen network, secret, or Sprite access, or enlarge the set of events the
service acts on beyond the operator's envelope — where the envelope itself
has exactly one planned widening, the owner's #758 decision below (admit
base-change `edited` events), which is an operator decision and never a
repo-config surface — and the one exception to
"the model" is not config at all: BYOK, below, is an installation-level
credential surface, not a `REVIEW.md` key.

**Layer order (first hit wins):** PR-level overrides (none for now — D81
Q5) > the repo file > installation-level defaults (not built — D81 Q4) >
operator env > code default. Values are schema-bounded on both sides; a
clamp or an out-of-range rejection is recorded in the draft like any other
controller note, and a repo-raised ceiling is named in the post through
D68's ceiling note.

**The repo file: extend `REVIEW.md` rather than add `.atlas.yml`.** The read
seam already exists (merge-base tarball, 64 KiB bound, fail-open notes), the
protocol already documents `REVIEW.md` as the repo-facing policy file, and
one file keeps the authoring surface — and the read-source security rule —
in one place. The read source becomes per key (§4): admission-class keys
read the repo's **default branch**, while D68's and D69's existing lines
keep the merge-base read their semantics were decided against, their
author-influence bounded and their migration to the default branch noted as
the safer end-state. A second file would split that surface and duplicate
the security rule the copied-parallel-way the standing authoring rules warn
against. A `.atlas.yml`-style file remains the alternative if the key set
grows past what one line-per-key grammar reads cleanly; the parse module of
S1 should be written so the file name is one constant, not a design
commitment.

**Validation.** Keys grow from two to a dozen, so the per-line fail-open
pattern generalizes into a schema-validated parse with bounded ranges: an
unknown key, a wrong type, or an out-of-range value fails open to the
default and is named. Where the error surfaces: **in the review's own draft
and post** (controller text, like D68's ceiling note and D76's recovery
note), not as separate comment bursts on every PR a misconfigured repo
produces; the one dedicated COMMENT is on the PR that *introduced* the
broken line — the diff touching the config file is already something the
protocol reports in its coverage line, and the service can do the same.
Every posted error names the key, the condition, and the default that
stands — **never the raw rejected value.** The value is unvalidated input,
and merge-base `REVIEW.md` is author-controllable in same-repo and stacked
PRs (§4), so echoing it raw into the App's post would be an injection
surface into the reviewer's own comment — the class #739's round-3 fixes
removed from the posted label echo. The notes follow the D68/D69 pattern
they generalize (`review_wide.py`'s `_UNUSABLE_NOTE`): a constant
description naming the condition ("a `review_ceiling_usd:` line that is not
a positive dollar amount; it is ignored and the configured ceiling
(default $10) stands"), with schema-validated *numbers* the only values
that may be named, and any echoed text length-bounded and escaped or
repr'd like every other untrusted field.

**Skipped reviews are recorded, not silent.** A rule-based skip (S4's
narrowing) records a one-line reason — which rule matched, on which input —
in the service's telemetry and the run's state, so a skipped review can be
told apart from the service being down. Whether a skip also posts a visible
note on the pull request: recommend **not by default** — the visible note
would land on exactly the PRs the repo asked the service to be quiet on,
recreating the noise the narrowing exists to remove, while the reason stays
durable and auditable in telemetry where an operator debug mode can surface
it; revisit toward a visible note only if operators report misreading a
skip as the reviewer being broken.

**Installation-level defaults and PR-level overrides** are real surfaces but
both depend on infrastructure that does not exist (an operator-side store;
an attacker-bounded label grammar); D81 keeps both out of this track (Q4:
repo-level only; Q5: none), so neither is designed in detail here.

**Operator-only, never user-controlled:** the per-tenant spend bounds — the
operator **max per review** and the **per-repo daily budget** (D81's
update) — plus `ATLAS_KEY_CEILING_USD`, which stays what it is: a cap on
the *shared key's total* credit limit, not a per-repo bound; the model,
provider, ZDR and safety-retention variables **for the operator's key** —
BYOK (next paragraph) gives an installation its own endpoint and key
instead, decided in §7; every operator secret; the Sprite
policy (deny-all, credential-free, create retries/concurrency); service
concurrency and deadline; the review-repo allowlist and admission envelope;
`ATLAS_HEAD_CHANGE_*`. `ATLAS_REVIEW_CEILING_USD` stays the operator-set
*default* the repo's `review_ceiling_usd:` line overrides, per D68.

**Bring-your-own endpoint and key (BYOK).** Brandon, 2026-11-18 3:41 PM CT:
"I need the github app to allow individuals or orgs to supply their own api
endpoints and keys." Scope: a GitHub App installation — a user account or an
org — supplies a model API endpoint (an OpenAI- or OpenRouter-compatible
base URL) and an API key, and its reviews run on that key instead of the
operator's. **Keys never go in `REVIEW.md` or any repo file** (nor a PR
conversation): the intake surface is operator-hosted, and the decided
path is a **settings page authenticated as the installation's admin via
GitHub** (an organization owner, who manages an org's App installations, or
the user-account owner — GitHub defines no separate "installation admin"
role), with rotation, revocation, and deletion on the
same page (§7's decision 1). Storage: encrypted at rest under an
operator-held key; never logged, never in a post, never passed to Sprites,
cloud agents, or child environments beyond the one model-call client; on
uninstall the stored secret is deleted (§4's bullet, §7's decision 8). A
user-supplied base URL is user-controlled egress — its trust rules are §4's
newest bullet. **This needs installation-level state, which D81's Q4 answer
("repo-level only for now") did not build; §7's decision 9 resolves the
conflict by amending Q4 narrowly — installation-level state for
credentials only, review configuration stays repo-level.** And the 5:13
PM CT answers add the requirement that completes this surface: **beyond
the operator's allowlisted repos a tenant-supplied key is required — there
is no operator-key path for tenant installations** — so the tenant path's
dollar bounds are the tenant's own spend protection (§4), a
**per-installation daily cap** joins S9's bounds (S9/S10), **configured by
the installation admin on the S10 settings page** (the 5:51 PM CT answer,
§8 Q5 decided — decision 9 amended to hold it) — and the operator-compute
question is §8 Q4, open. The
decisions
live in §7; the slice is S10. **A naming note:** this plan's "BYOK" — the
installation supplies its own endpoint and key, the surface this record
also calls **tenant-supplied keys** — is **not** OpenRouter's account-level
BYOK, which already exists on main (`usage.is_byok`, `ByokRefusedError`,
recorded in D41) and stays what it is for the operator's key; S10 leaves
that existing handling untouched and the two never share a code path.

**The allowlist is the invite-only gate.** Brandon, 5:17 PM CT: *"I was
intending to set up a cost based billing system and roll out access on an
invite only basis initially."* The App is public and anyone can install
it; what decides today is the existing repo allowlist —
`ATLAS_REVIEW_REPOS`, checked in `service_admit.admit` — and a
non-allowlisted delivery is acknowledged (HTTP **202**, the receiver's
ignored path — `service.py:264`; 200 is the queued path) and ignored
**before any review, Sprite, or model call**, so an
uninvited installation costs the operator nothing but a webhook
acknowledgement. Opening the App beyond the allowlist means **adding
invited installations** to `ATLAS_REVIEW_REPOS` — never removing the
gate — and (per the 5:13 answers) each such installation supplies its own
key.

## 3. Candidate settings

| Setting | Default | Bounds / rule | Owner | Today |
|---|---|---|---|---|
| Lens include/exclude | none (guideline decides) | lens-shaped names only; never widens the depth mode; never touches the critical tier; exclude wins | user | exists (D69, `REVIEW.md`) |
| Severity floor for posted findings | post everything (the service posts one COMMENT per head, not rounds) | a repo may raise its floor; floor-tier lenses' findings are never silently suppressed — the manifest tier split and the overlay's `acknowledge` rule carry over unchanged | user (floor level), engine (tier rule) | not read by the service; the protocol's `REVIEW.md` defines it |
| Path include/exclude, generated-file handling | none | **ordering and depth only, never exclusion** — whether anything may be excluded from review at all is Q25's undecided question; a user path filter re-ranks and names what it deprioritized | user (ordering); any true exclusion waits on Q25 | not built (`diffs.risk_tier` ranks by path alone) |
| Per-review budget | the repo's own `review_ceiling_usd:` line, or `ATLAS_REVIEW_CEILING_USD` ($10) when absent | the repo sets its own ceiling, up or down — D68's semantics, kept by D81 Q2 — but the **effective** value is clamped to the operator's max per review (D81's update; out-of-range → named fallback, D68's pattern); the ceiling actually used is named in the post (D68's ceiling note) | user (the repo's ceiling), operator (the max) | the read exists (D68); the operator max does not |
| Per-repo daily budget | $100 per repo per UTC day (decided 5:13 PM CT) | operator-set (`ATLAS_REPO_DAILY_BUDGET_USD`, proposed name); once a repo has spent its day's budget, further reviews are refused at admission and re-checked at preflight; the record says plainly "skipped: daily budget reached" and never reads as a clean review; the total resets at the UTC day boundary. On the operator-key path it bounds operator spend; on the tenant-supplied path it is the **tenant's own spend protection** (§4) | operator | not built |
| Head-change policy | `keep` (D79) | keep | operator | exists, env |
| When to review | non-draft; `opened`/`synchronize`/`ready_for_review`; allowlisted repos | a repo may narrow in two kinds (D81's 4:54 PM CT update). **Author-safe narrowing:** delivery properties where a skip cannot land unreviewed changes on a branch the repo reviews — the base branch (the skip and the landing coincide: the repo's narrowing *is* the choice of where reviews happen); the patterns matched against come from the default branch (§4), and there are no head-branch or label keys, so a PR cannot write its own admission. **Repo-owner opt-outs that knowingly reduce coverage:** `review_skip_events` is one — skipping `synchronize` lets later pushes land unreviewed (a draft-opened PR's state is still reviewed at its ready transition, which reviews the whole diff), and skipping `ready_for_review` loses the review only when a draft-opened PR becomes ready and merges with no further push (a later push is admitted as `synchronize` and reviews the whole diff); the owner-facing docs must say plainly what each skippable event costs in coverage. The draft state is not a narrowing input: drafts are already excluded by the operator envelope (`service_admit.py` skips them), so a draft filter would be vacuous. A head-branch or label skip has no author-safe property — the author names the head branch or sets the label and can still merge into the protected base — so those sit behind the deferred PR-level-overrides decision (D81 Q5), not in S4. The config is read from the repo's **default branch** (§4), not the PR's base ref or merge-base, both of which an author can move in same-repo or stacked PRs. The base-retarget dodge — a PR opened against an excluded base (skipped at `opened`), then retargeted into a should-review base via an `edited` event — is the gap #756 documents and #758 closes (the owner's 4:28 PM CT decision admits base-change `edited` events). Any rule-based skip is recorded with a one-line reason, so a skipped review is distinguishable from the service being down | user (author-safe narrowing), repo owner (coverage-reducing opt-outs), operator (envelope) | ****landed — merged as #756** (`cd243249`); the remaining work is #758 only |
| Post format and verbosity | the current post body (D75) | verbosity may be lowered only; the Findings section, the coverage note and the REVIEW INCOMPLETE banner are never suppressible | user | not built |
| #734 tool allow-lists | deny-all; structured `run_tests`/`mutate` with bridge-built argv | a repo's requested additions are **proposals** that become operator-approval requests (the #734 decision: approval may apply within the same run, bounded by the wall and dollar limits); never auto-granted | operator approves, user proposes | #734 not started |
| Coding guidelines / AGENTS.md ingestion | none | delivered as fenced untrusted context blocks under the D67/D73 room budget, like the conversation and CI blocks; never instructions | user (content), engine (delivery) | not built |
| Quiet hours / rate limits | none | an operator ceiling per repo per day; a user may only opt into quieter | user narrows, operator bounds | not built |
| BYOK endpoint and key | none — the operator's key and endpoint serve every review | supplied by the installation's admin through the intake surface (§2, §7's decision 1), never through `REVIEW.md`, any repo file, or a PR conversation; an HTTPS-only base URL that passes §4's egress checks (§7's decision 2: any such host, not an operator allow-list); encrypted at rest, never logged or posted, never past the one model-call client | installation admin (supply), operator (intake, store, egress rules) | not built |
| BYOK model choice | the operator's model | a BYOK installation may choose the model within its own endpoint (§7's decision 5); the D68 budget shape stays and the dollar budgets resolve from the price table, so models with no price-table entry are refused (§7's decision 6) — zero-priced models are allowed (5:13 PM CT), with the per-review call caps and walls as their bound | user (choice), operator (bounds) | not built |

## 4. Security and trust

- **Read from the repo's default branch for the settings a PR should not
  influence; from the merge-base only where the existing semantics keep
  it.** The plan's earlier blanket rule — merge-base/base ref, never the
  PR head — had a hole #756's protocol review caught: the PR's `base.ref`
  and its merge-base are **author-controllable** in same-repo and stacked
  PRs, because the author can commit configuration to the branch they
  target, and the merge-base then carries it. So:
  - **Admission-class settings — S4's when-to-review rules, and any other
    setting a PR must not influence — read from the repo's default
    branch** (#756's approach). The default branch is the repo
    maintainers' controlled surface: what governs a review cannot be
    written by the PR being reviewed.
  - **D68's ceiling line and D69's lens include/exclude keep their
    existing merge-base read**, and they **do share the weakness**: in a
    same-repo or stacked PR the author can put a `review_ceiling_usd:`
    line or lens preference on the branch they target and have the
    merge-base carry it. The exposure is bounded, not zero — the ceiling
    raise is clamped by S9's operator max (and a lowered ceiling only
    cheapens the author's own review), and the lens lists can never widen
    the depth mode or touch the **critical tier** — the four lenses
    `picker.py`'s `CRITICAL_TIER` protects from `review_lens_exclude:`
    (tracing-correctness-and-invariants, sweeping-for-security,
    reviewing-migration-and-data-safety, reviewing-concurrency-and-async)
    — so those four cannot be excluded away. The manifest's **floor tier is
    one larger**: it adds `hunting-silent-failures`, and the merge-base
    lens preference **can** exclude it on main today, because the
    preference application protects only the critical tier. Which set the
    configuration surface protects was **decided 5:13 PM CT** (§8 Q2,
    recorded on D69's own 5:13 update): **all five floor-tier lenses are
    protected**, and the plan's S1 implements it — the excludability named
    here is main's behavior until S1 lands. The migration of these
    two reads to the default branch is the safer end-state and is a
    candidate follow-up; until then their author-influence is stated here
    rather than claimed away.
  - **The base-retarget dodge is a real gap: #756 documents it, and #758
    closes it.** A PR opened against an excluded base branch is *skipped*
    at `opened`, then retargets — GitHub delivers `pull_request.edited`
    with a `base` change and no new `opened` event — and no review ever
    re-evaluates: that is the merge-before-any-review path #756's body
    records as "documented, not widened", because admitting the `edited`
    event would widen the operator's envelope, which is an operator
    decision. Two things are now separated. Retargeting cannot move the
    *config's* answer — the read source is the default branch, so the
    patterns a rule matches against do not move with the retarget — but a
    rule whose *matched value* is the delivery's base branch does move,
    and that is the gap. **The owner decided it (Brandon, 2026-11-18
    4:28 PM CT): "Yes, admit base-change edited events as a follow-up."**
    The service will admit `pull_request` `edited` deliveries only when
    `changes.base` is present, re-running admission against the new base,
    with config still read from the default branch — an explicit, narrow
    widening of the operator event envelope, tracked as **issue #758**, a
    follow-up to #756. Until #758 lands, the gap stands as #756 documents
    it, named rather than claimed closed.
- **Schema-validated, bounded, fail-open with named notes.** Every value
  carries a range the schema enforces; out-of-range or unparseable input
  falls back to the default and names itself, generalizing D68's
  unusable-ceiling-line pattern. The 64 KiB read bound stays.
- **Config values are untrusted data everywhere they reach a model.** Lens
  names are validated lens-shaped at parse (D69); guideline and
  AGENTS.md-derived content travels nonce-fenced like every other block
  (D65's per-review nonce, D52/D67/D73's assembly rules); raw config
  **text** never enters trusted controller text — schema-validated values
  may be named, per §2's rule and D68's own ceiling note.
- **No config key can widen network, secret, or Sprite access.** The
  Sprite's deny-all credential-free policy, the child's env allowlist, and
  the model/data-policy variables sit outside the config schema by
  construction; the schema is a closed set, not a pass-through.
- **The per-tenant spend bounds sit outside repo control (D81 Q2 and its
  update).** D68's semantics stay: a repo may raise or lower its own
  `review_ceiling_usd:`, and the ceiling a review actually used is named in
  the draft and the post (D68's ceiling note) — but the effective value is
  clamped to the operator's **max per review** (proposed name
  `ATLAS_REPO_CEILING_MAX_USD`, **$25 — decided 5:13 PM CT**; out-of-range
  → named fallback, D68's pattern). The
  second bound is the **per-repo daily budget**: once a repo has spent its
  day's budget, its further reviews are refused at admission and re-checked
  at preflight, the record says plainly "skipped: daily budget reached",
  and nothing about the refusal can read as a clean review. The reset
  boundary is the UTC day, and the running total lives where the service's
  durable state already lives — the state root on the Fly volume
  (`ATLAS_REVIEWER_STATE_DIR`), as one append-only
  `<state root>/spend/<owner>-<repo>-<UTC date>.jsonl` file per repo per
  day, where **`<owner>` and `<repo>` are each percent-encoded with every
  byte outside `[A-Za-z0-9]` escaped** (so `a-b/c` and `a/b-c` become
  distinct files, and the join `-` is unambiguous because a literal `-`
  inside a segment always appears as `%2D`), the same append-only pattern
  D74's per-PR round logs use; the date in the file
  name makes the UTC reset structural, and a lost file loses only the
  day's total, the way a lost round log loses only prior-round context.
  **The check-then-act race is named and bounded.** Two concurrent
  deliveries for the same repo can both pass admission (and preflight)
  before either commits spend — the queue's one-active-job rule is per
  pull request, not per repo, and the append-only total is read, not
  locked. The plan accepts the bounded overshoot explicitly rather than
  adding a per-repo lock: the worst case is the repo's in-flight reviews
  each spending up to the operator max past the day's budget — at the
  decided values that number is 32 in-flight reviews × the $25 operator
  max = **$800 past a $100 daily budget**, bounded by the operator's own
  concurrency setting (`ATLAS_REVIEW_CONCURRENCY`, 1–32) — the
  refusal applies to the *next* admission after the total is committed,
  and the overshoot is visible in the same telemetry the total comes
  from. A per-repo lock is the alternative if the operator wants the
  overshoot eliminated, at the cost of serializing a repo's reviews;
  the record states which behavior a deployment has.
  `ATLAS_KEY_CEILING_USD` stays what it is — a cap on the shared key's
  *total* credit limit, not a per-repo bound — which is exactly why the
  per-tenant bounds exist alongside it.
- **BYOK bounds are computed on the operator side — and on the
  tenant-supplied path they are the tenant's own spend protection.** §7's
  decision 4 keeps both spend bounds applying to a BYOK review; the 5:13
  PM CT answer (Q1) adds the fact that reshapes their meaning: **beyond
  the operator's allowlisted repos a tenant-supplied key is required, and
  there is no operator-key path** — so on that path every dollar figure
  the bounds count is the **tenant's own money**. The counted spend is
  **token counts × the operator's price table** (one accounting, one price
  source; decision 6 still refuses models with no price-table entry, and
  per the 5:13 answer zero-priced models are allowed — dollar bounds
  accumulate nothing for them, so the per-review call caps and walls are
  what bound them). Because no dollar bound on the tenant path counts
  operator money any more, **a tenant-reported figure can inflate or
  deflate only the tenant's own budgets**: the per-review ceiling's clamp
  is applied to the *reservation*, which is computed from the operator's
  price table and the operator-set caps (never from a tenant report); the
  per-review call caps, turns and walls (D68's derivation) and the
  concurrency cap are operator-set numbers that consume no reported
  figure; and the daily budget and per-installation cap a deflated count
  stretches are the tenant's own. The **operator-observed-floor spec the
  previous fix round added is accordingly withdrawn** — it existed to
  stop a tenant endpoint deflating operator-paid dollars, and no such
  bound remains — and D82's settle applies on both paths as recorded
  (#757). What tenant-reported figures still cannot touch is the
  operator's money (none is spent on a tenant review) and the operator's
  hard limits. What they **can** still drain is the operator's **compute**
  — every review costs Fly time, Sprite creation and model-independent
  work, which conflicts with "it shouldn't cost me anything" and is not
  papered over: the non-dollar controls that bound it today are the
  per-review call caps and walls and the concurrency cap, and **whether to
  keep operator compute cost for tenants at or near zero — a
  per-installation review-count cap or a charge — is §8 Q4, an open
  question for Brandon**, not decided here. S10 leaves the existing
  OpenRouter-BYOK handling untouched on the operator-key path — an
  unreadable upstream account-level BYOK charge still keeps its
  reservation (D41) — and never reads `usage.cost` or
  `cost_details.upstream_inference_cost` on the tenant-supplied path; the
  token-counts × price-table accounting above is what it uses instead.
- **BYOK keys are never repo content.** The intake surface is
  operator-hosted (the decided path: a settings page authenticated as the
  installation's admin via GitHub — §7's decision 1), never `REVIEW.md`, never a repo
  file, never a PR conversation. A stored key is encrypted at rest under an
  operator-held key; it is never logged, never quoted in a post or draft,
  and never passed to Sprites, cloud agents, or child environments beyond
  the one model-call client — the review child's env allowlist gains one
  variable the same way it already holds `ATLAS_OPENROUTER_API_KEY`, and
  the Sprite receives neither. Rotation and revocation live on the same
  intake page; on uninstall (`installation.deleted`) the installation's
  stored state — the secret and the installation admin's daily cap — is
  deleted, with a retention sweep catching a missed event (§7's decision
  8).
- **A user-supplied base URL is user-controlled egress.** The service makes
  outbound requests to it, which is an SSRF surface: HTTPS only; private,
  link-local, loopback and metadata addresses blocked at connect time with
  the resolved IP pinned for the connection (DNS rebinding) — over IPv4
  *and* IPv6, the blocked set naming ULA `fc00::/7`, link-local
  `fe80::/10`, `::1`, and IPv4-mapped IPv6 `::ffff:0:0/96`, since a
  pinned-IP check that only parses IPv4 is the classic rebinding bypass;
  redirects
  re-checked against the same rules; the model client's existing timeouts
  and response caps apply; responses are model replies — already untrusted
  under the existing pipeline, never trusted instructions. **Data policy:**
  the operator's ZDR and safety-retention settings are operator policy for
  the operator key; on a BYOK review the PR diff goes to the installation's
  own endpoint by definition — that is the point of BYOK — so the intake
  page states what is sent — the consent statement §7's decision 3 requires
  before the first BYOK review — and the draft
  and post record which endpoint class served the review. The operator's
  key is never used for a BYOK installation's review: §7's decision 7 keeps
  the fallback policy off, and a BYOK key failure — an
  auth error, quota, or endpoint down — fails the review with the failure
  named plainly, never a clean-looking "Findings: None".

## 5. Sequencing (issue-sized slices)

| Slice | What | Files | Done when | Parity-track pointers | Order |
|---|---|---|---|---|---|
| S1 | The config parse module (`atlas_reviewer/repo_config.py`): the two existing `REVIEW.md` lines move onto it unchanged; new keys parse as unsupported with named notes; the merge-base lens preference protects **all five** manifest floor-tier lenses (the 5:13 PM CT answer, recorded as D69's update) | new module, `review_wide.py` call sites, `picker.py`'s protection set, tests | both existing lines parse identically through the new module (no behavior change); unknown/out-of-range keys yield named fail-open notes that never echo the raw rejected value (§2's rule); the 64 KiB read bound preserved; **an exclude naming `hunting-silent-failures` is refused the way the critical four are** (D69's 5:13 PM CT update), pinned by a test | **concurrent** — the #750 fix is open as **#757 (D82)** and its file list (`budget.py`, `openrouter.py`, `service_post.py`, `tool_model.py`) includes neither `review_wide.py` nor `coordinator.py`, so S1's refactor of the ceiling *read* (`CEILING_LINE`, `review_md_ceiling`, `_lens_preferences`, `resolve_ceiling`) is disjoint; this plan's earlier same-file prediction was wrong and is corrected here — and no open PR (#752/#753/#756/#757) touches `picker.py`, so S1's protection-set change is disjoint too | first |
| ~~S2~~ | **Dropped by D81** — Q2 keeps D68's repo-set ceiling, so there is no ceiling direction to change | — | — | — | dropped |
| S3 | Severity floor + post verbosity | `service_run.py`, `service_post.py`, README | floor keys honored and named in the post; floor-tier lenses' findings never silently suppressed (the tier rule carries over); lowering-only pinned by tests | **rebase-check against #757 (D82)** — its file list includes `service_post.py`, which S3 edits | after S1 |
| S4 | When-to-review admission — narrowing in two kinds (D81's 4:54 PM CT update): **author-safe narrowing** on delivery properties where a skip cannot land unreviewed changes on a branch the repo reviews (the base branch — and the patterns matched against come from the repo's **default branch** per §4's rule, with no head-branch or label keys, so a PR cannot write its own admission), and **repo-owner opt-outs that knowingly reduce coverage** (`review_skip_events`), with the owner-facing docs stating each skippable event's coverage cost; the draft state is vacuous as a narrowing input (the operator envelope already skips drafts); the base-retarget dodge is the gap #756 documents and #758 closes; label- and head-branch-based rules sit behind D81's Q5 deferred PR-level overrides; every rule-based skip records a one-line reason | `service_admit.py`, `service.py`, `github_api.py`, README | retargeting cannot change the config's answer (the default-branch read); no skip key matches a head branch or a label; the per-event coverage costs are stated in the carrier #756's README provides (head ced3c412) — stated precisely, per #756's r3 correction of the draft path: skipping `synchronize` means only the opening state is ever reviewed for a non-draft PR (a draft-opened PR's state is still reviewed at its ready transition, which reviews the whole diff), and skipping `ready_for_review` loses the review only when a draft-opened PR becomes ready and merges with no further push (a later push is admitted as `synchronize` and reviews the whole diff); skipping `opened` defers the first review to a later push; skipping all three means the repo is never reviewed — S4's work keeps that text current and precise rather than writing a second copy; a retarget into a should-review state is re-evaluated under #758's envelope extension or, until #758 lands, recorded as the named gap #756 documents; skips carry their one-line reason | **landed — merged as #756** (`cd243249`, "Config slice S4: repo-narrowed review admission (#755)"); the remaining work is **#758** only | landed; #758 open |
| S5 | Path re-ranking + generated-file handling (ordering only) | `diffs.py` | no path is ever dropped from review by user config; re-ranking is recorded in the draft; Q25 untouched | no open PR touches `diffs.py` — the merged D79 delta work touched `delta.py` and `head_change.py`, not `diffs.py`; rebase onto main before starting | after S1 |
| S6 | AGENTS.md / coding-guideline ingestion as fenced context blocks | `cli.py`, `conversation.py` | the blocks reach every lens fenced and budgeted; omissions are named; injected content stays inside the fence | **concurrent** — corrected against the open #734 PRs' actual file lists: #752/#753 (D80) touch `bridge.py`, `bridge_args.py`, `bridge_staging.py`, `interpreter.py`, `lens_loop.py`, `attestation.py`, `coordinator.py`, `ports.py`, `tool_model.py` — **not** `cli.py` or `conversation.py`, so the earlier "hot files" premise (based on the pre-#752 prediction) was wrong; rebase-check only | after S1 |
| S7 | The #734 allow-list and in-run operator approval | `bridge_args.py`, `bridge.py`, service glue | a blocked command routes to an operator-approval request; an approved addition applies within the same run only inside the wall and dollar bounds; an unapproved gap is named by the review | **depends on #734 (D80) landing** — #752/#753 are open and their file sets include S7's own `bridge_args.py`/`bridge.py` | after #752/#753 land |
| S8 | Installation-level defaults, quiet hours / per-repo rate limits | `service.py`, `service_queue.py`, new store | — | **deferred by D81** (Q4: repo-level only — amended for credentials only by §7's decision 9, which is S10's store, not a general defaults store; Q7: quiet hours deferred) | deferred |
| S9 | The per-tenant spend bounds (D81's update; values decided 5:13 PM CT): the operator max per review ($25) clamps the repo's effective ceiling (out-of-range → named fallback, D68's pattern), and the per-repo daily budget ($100) refuses further reviews at admission and re-checks at preflight; the record says plainly "skipped: daily budget reached" and never reads clean; UTC-day reset, total on the state volume. On the operator-key path the bounds bound operator spend; on the tenant-supplied path they are the tenant's own spend protection (§4). The **per-installation daily cap** (the 5:13 answer to §8 Q1, its configurer decided 5:51 PM CT: **the installation admin sets it on the S10 settings page**) reuses this same counting machinery and is enforced **alongside the per-repo daily budget — the stricter of the two wins** each admission; when no cap is set, none applies and the per-repo budgets remain the bound. Its store side is S10's installation store, and uninstall removes the cap with the credentials | `review_wide.py` (the clamp beside the ceiling resolution), `budget.py` (the day's committed-spend accounting), `service_admit.py` + `service.py` (the refusal), README, tests | a repo-raised ceiling cannot pass the operator max and the clamp is named; a repo over its daily budget is refused with the plain record and never a clean-looking post; **two distinct owner/repo pairs never share a spend file** (the percent-encoding of §4); the bounded overshoot is pinned by a test (concurrent admissions over-commit by at most the in-flight reviews × the operator max — 32 × $25 = $800 past the $100 budget at the decided values, and past the installation's cap by the same bound); the total survives a restart and resets at the UTC boundary; **an installation over its admin's cap is refused the same way, the stricter of cap and budget governs each admission, and an unset cap means none applies** | **rebase-check against #757 (D82)** — its file list includes `budget.py`, which S9's daily-total accounting edits; follows S1 (the operator max is a config-bounded value) and S4 (the refusal rides its admission surface, merged as #756) | after S1 and S4; with S10, the **precondition for opening the App beyond the operator's allowlisted repos — which now requires a tenant-supplied key, and means adding invited installations to `ATLAS_REVIEW_REPOS`, never removing the invite-only gate (§2)** |
| S10 | BYOK: the tenant-supplied model endpoint and key — **required beyond the operator's allowlisted repos, with no operator-key path for them** (the 5:13 PM CT answer); the intake surface, the encrypted store, the per-installation daily cap (**set by the installation admin on the settings page** — the 5:51 PM CT answer to §8 Q5, stored with the credentials and removed on uninstall), the model-call client's endpoint/key resolution, the egress checks of §4, the failure-named fallback rule | the intake page (new, outside the package), a secrets-store module (new), the per-installation cap's per-installation config, `providers.py` + `openrouter.py` (endpoint/key resolution), `service.py` (child env assembly), README, tests | a BYOK installation's reviews run on its own key end to end, and a non-allowlisted installation **cannot review on the operator's key at all** — no fallback, no operator-key path; no key can leak into a repo file, log, post, or Sprite; a hostile base URL cannot reach the blocked set over IPv4 *or* IPv6 (§4's list); a key failure names itself; **the per-installation daily cap is enforced — set and editable by the installation admin on the settings page under the same installation-admin authentication that guards the key, removed on uninstall with the credentials, and combined with the per-repo daily budget by the stricter-wins rule**; the tenant path's dollar accounting is the tenant's own protection, and **no operator-protective bound consumes a tenant-reported figure** (tests pin: the per-review clamp and hard limits are computed from operator inputs; a deflated reported count changes only the tenant's own settled total); zero-priced models are allowed and the call caps and walls bound them; the OpenRouter-BYOK handling on the operator-key path is untouched (D41) | **rebase-check against #757 (D82)** — its file list includes `openrouter.py` and `tool_model.py`, which S10 edits — **and against #752 (D80)** (`tool_model.py`); this plan's earlier "#654/#655 drafts" pointer was stale (both merged; #655 re-landed as merged #740); **decided in §7** (Brandon accepted all nine recommendations) and after S9 (the spend bounds define what a BYOK review clamps to) | last; the §7-Q9 prereq is decided — the installation-level credential store is in scope |

Recommended order: S4 has landed (merged as #756; its retarget
follow-up is issue #758), then S1 (concurrent with the parity track), then S3 and S5, then S9
once S1 and S4 have landed (rebase-checked against #757), then S6, then S7
once #752/#753 have landed, then S10 last (its §7 decisions are recorded; it
still follows S9). S2 is dropped and S8 is deferred by D81.

## 6. Decisions (D81)

Brandon answered all eight on 2026-11-18 at 3:28 PM CT; the record is
**D81** in [`../open-questions.md`](../open-questions.md), which quotes his
answer to Q2. Summary:

1. **File.** Extend `REVIEW.md` — no new `.atlas.yml`-style file (as the
   plan recommended).
2. **Ceiling direction.** "Let each repo set its own limits": D68's
   semantics stay — a repo's `review_ceiling_usd:` may raise or lower its
   per-review ceiling. The plan's clamp recommendation was **not taken**;
   the operator backstop outside repo control is `ATLAS_KEY_CEILING_USD`
   *(superseded — see the 3:39 PM CT update below, which replaces this
   backstop with the per-tenant bounds)*, and a repo-set ceiling is still
   named in the post (D68's ceiling note).
   S2 is dropped.
3. **Severity floor.** As recommended: default post everything, a repo may
   raise its floor, the manifest tier split and the overlay's
   `acknowledge` rule govern suppression.
4. **Installation-level defaults.** Repo-level only for now (as
   recommended); S8 loses its installation half.
5. **PR-level overrides.** None for now (as recommended).
6. **Path exclusion.** Ordering-only until Q25 decides whether anything may
   be excluded from review at all (as recommended).
7. **Quiet hours / rate limits.** Deferred; S8 is deferred whole.
8. **AGENTS.md ingestion.** In scope as S6 (as recommended).

**Update (2026-11-18, 3:39 PM CT — the per-tenant spend bound).** Resolving
the round-2 Major that fix round 1 held, Brandon decided: **"Add both an
operator max per review and a per-repo daily budget."** Q2's answer stands —
repos set their own limits, within the operator's bound: the effective
ceiling is clamped to the operator max (out-of-range → named fallback,
D68's pattern), and the per-repo daily budget refuses further reviews at
admission and re-checks at preflight, with the record saying plainly
"skipped: daily budget reached" and never reading as a clean review; the
reset boundary is the UTC day and the running total lives on the state
volume (§4). This adds slice **S9** and is a **precondition for opening the
App beyond the operator's allowlisted repos**. The plan's earlier claim
that `ATLAS_KEY_CEILING_USD` was the spend backstop is corrected: it caps
the shared key's total, not a per-repo bound.

**Update (2026-11-18, 4:28 PM CT — the base-change `edited` envelope).**
Resolving the retarget gap (Major 1 of PR #751's round-1 protocol review —
the gap issue #756 documents as "documented, not widened"), Brandon
decided: **"Yes, admit base-change edited events as a follow-up."** The
service will admit
`pull_request` `edited` deliveries only when `changes.base` is present,
re-running admission against the new base, with config still read from the
default branch — an explicit, narrow widening of the operator event
envelope (the one widening §2's invariant names), tracked as the
follow-up **issue #758** to #756. Until #758 lands, the gap stands named,
the way issue #756 documents it.

**Update (2026-11-18, 4:54 PM CT — the S4 event-type invariant).**
Resolving the round-5 Major the S4 event-type question raised: Brandon
decided, **"Keep review_skip_events as a repo-owner opt-out and document
that it reduces coverage."** The event type is not a property where a skip
cannot land unreviewed changes — skipping `synchronize` lets later pushes
land unreviewed (a draft-opened PR's state is still reviewed at its ready
transition, which reviews the whole diff), and skipping `ready_for_review`
loses the review only when a draft-opened PR becomes ready and merges with
no further push (a later push is admitted as `synchronize` and reviews the
whole diff; the draft-path overstatement corrected after #756's r3
review). The S4 invariant now
separates two kinds of narrowing: what a **PR author cannot exploit** (the
default-branch read, no head-branch or label keys), and **repo-owner
opt-outs that knowingly reduce coverage**, of which `review_skip_events`
is the first, with the owner-facing docs stating each skippable event's
coverage cost (carried by #756's README, head ced3c412). No other decision
changes.

**Update (2026-11-18, 5:13 PM CT — the §8 answers, the tenant-key
requirement, and S9's numbers).** Brandon answered the plan's §8 questions.
**Q1, verbatim:** *"A cap should be configurable per installation, but it
shouldn't cost me anything since I'm not sharing my own key with other
users, they'll have to provide their own."* Three decisions follow: a
**per-installation daily cap, configurable per installation**, is added
(S9/S10); a **tenant-supplied key is required beyond the operator's
allowlisted repos, and there is no operator-key path for them** —
consistent with the existing never-fallback rule, so on the tenant path
the dollar bounds are the **tenant's own spend protection**, not operator
protection (§4 states what that makes tenant-reported figures able to
touch, and withdraws the operator-observed-floor spec as far as that is
true); and the operator-**compute** cost a tenant review still costs is
**not** papered over — the non-dollar controls bounding it are named (the
per-review call caps and walls, the concurrency cap) and the question of
keeping it at or near zero (a review-count cap or a charge) is **§8 Q4,
open**. **Q2:** protect **all five** manifest floor-tier lenses, including
`hunting-silent-failures`, from the merge-base `review_lens_exclude:` —
recorded as **D69's 5:13 PM CT update** and implemented in S1 with a test.
**Q3:** **allow zero-priced models** — the dollar bounds accumulate
nothing for them, so the per-review call caps and walls are what bound
them. **S9:** the working defaults are now the values — the operator max
per review stays **$25** and the per-repo daily budget stays **$100**.

**Update (2026-11-18, 5:17 PM CT — the rollout gate and the billing direction).** He added the rollout shape: *"I was intending to set up a cost based billing system and roll out access on an invite only basis initially."* — the existing repo allowlist is the invite-only gate (§2), and cost-based billing is the intended direction for covering operator compute (§8 Q4), to be designed later and out of scope for this plan.

**Update (2026-11-18, 5:51 PM CT — the cap's configurer).** He answered §8 Q5: *"Installation admins set their own daily cap on the settings page"* — decision 9 is amended so installation-level state holds the credentials **plus the installation admin's daily cap**, enforced by S9's machinery alongside the per-repo daily budget with the stricter of the two winning each admission, unset meaning none applies.

## 7. BYOK decisions (D81 — Brandon accepted all nine recommendations, 2026-11-18 4:15 PM CT)

Brandon's BYOK requirement (2026-11-18, 3:41 PM CT) is recorded above and in
D81's update notes; at 4:15 PM CT the same day he answered: **"Accept all 9
BYOK recommendations."** The nine decisions, each the recommendation §7
proposed, are recorded in D81:

1. **Intake path.** An operator-hosted settings page authenticated as the
   installation's admin via GitHub — the key never transits repo content or
   a PR conversation, the admin identity is verifiable through GitHub's own
   installation-admin notion, and rotation, revocation and deletion get one
   natural home.
2. **Endpoint scope.** Any HTTPS host that passes §4's private-range and
   rebinding checks — BYOK's point is the user's own provider.
3. **Data disclosure at intake.** An explicit consent statement the
   installation admin must acknowledge before the first BYOK review, naming
   that the PR diff is sent to the installation's own endpoint.
4. **Spend bounds on BYOK reviews.** Both per-tenant bounds apply to the
   installation's own key — with the installation able to lower them and
   the operator max as the outer bound; `ATLAS_KEY_CEILING_USD` stays
   operator-key only. **Amended by the 5:13 PM CT answers:** a
   tenant-supplied key is *required* beyond the operator's allowlisted
   repos (no operator-key path), so on that path these bounds are the
   **tenant's own spend protection** — §4 states what that does and does
   not make tenant-reported figures able to touch; a per-installation
   daily cap, configurable per installation, is added (S9/S10) —
   **configured by the installation admin on the settings page** (5:51 PM
   CT, §8 Q5 decided; decision 9 amended to hold it).
5. **Model choice.** A BYOK installation may choose the model its reviews
   run on, within what its own endpoint serves; D68's budget shape stays.
6. **Unknown pricing.** Models with no price-table entry are refused — the
   dollar budgets need a price source, and the D68 reservation math would
   otherwise be ungrounded. **Amended by the 5:13 PM CT answer (Q3):**
   zero-priced models are **allowed** — the dollar bounds accumulate
   nothing for them, so the per-review call caps and walls are what bound
   them.
7. **Fallback policy.** Never fall back to the operator key (default off);
   a BYOK failure — an auth error, quota, or endpoint down — fails the
   review with the failure named plainly, never a clean-looking review.
8. **Key retention after uninstall.** Delete the installation's stored
   secret on the `installation.deleted` webhook, with a retention-window
   sweep catching a missed event.
9. **Installation-level storage (the Q4 conflict).** Q4 is **amended
   narrowly**: installation-level state for *credentials only*; review
   configuration stays repo-level. **Amended again (5:51 PM CT, Q5's
   answer):** installation-level state now holds **credentials plus the
   installation admin's daily cap**, entered on the S10 settings page
   under the same installation-admin authentication — review
   configuration still stays repo-level.

## 8. Open questions — Q1–Q3 and Q5 decided 5:13/5:51 PM CT; Q4 open

1. **The per-installation operator-load bound — DECIDED (5:13 PM CT).**
   Brandon: *"A cap should be configurable per installation, but it
   shouldn't cost me anything since I'm not sharing my own key with other
   users, they'll have to provide their own."* A **per-installation daily
   cap, configurable per installation**, is added (S9/S10) — and the same
   answer requires a **tenant-supplied key beyond the operator's
   allowlisted repos, with no operator-key path for them** (§4, S10). The
   part of the old question that remains open is the operator-*compute*
   cost, which dollars on tenant keys cannot bound — that is **Q4 below**.
2. **Which tier the merge-base lens preference protects — DECIDED (5:13
   PM CT).** All **five** manifest floor-tier lenses, `hunting-silent-
   failures` included, are protected from the merge-base
   `review_lens_exclude:`. This changes D69's recorded behavior and
   `picker.py`'s protection set; it is recorded as **D69's 5:13 PM CT
   update**, which this plan cites, and the implementation is **S1's
   Done-when**, pinned by a test.
3. *Zero- or nonpositive-priced models under BYOK — DECIDED (5:13 PM CT):
   **allowed.*** The dollar bounds accumulate nothing for such models, so
   the per-review **call caps and walls** are what bound them (§7's
   decision 6 carries the amendment).
4. **Keeping operator compute cost for tenants at or near zero — OPEN.**
   Every tenant review costs the operator Fly time, Sprite creation and
   model-independent work, and the dollar bounds on tenant keys no longer
   bound that (a tenant-reported figure stretches only the tenant's own
   budgets — §4). Today's non-dollar controls are the per-review call caps
   and walls and the concurrency cap. How to keep the operator's compute
   cost at or near zero — a per-installation **review-count** cap (counted
   in reviews, not dollars, so no reported figure can move it) or a
   charge — is Brandon's call. Recommended default: the count-based
   per-installation cap (it bounds exactly the thing dollars stopped
   bounding, and cannot be gamed by any reported figure). **Not decided
   here.** **Brandon's intended direction for covering it** (5:17 PM CT):
   *"I was intending to set up a cost based billing system and roll out
   access on an invite only basis initially"* — cost-based billing with an
   invite-only rollout; **designing that billing system is out of scope
   for this plan** — this question stays open for the mechanism that lands
   before billing does.
5. **Who configures the per-installation daily cap — DECIDED (5:51 PM
   CT).** Brandon: *"Installation admins set their own daily cap on the
   settings page."* The installation admin configures it, on S10's
   settings page under the same installation-admin authentication that
   guards the key — and **§7 decision 9 is amended accordingly**:
   installation-level state now holds **credentials plus the
   installation admin's daily cap**. The cap is the installation's own
   bound on its own spend (its keys' spend), enforced by S9's machinery
   alongside the per-repo daily budget — **the stricter of the two wins**:
   a repo's admission is refused when either the repo's day-budget or the
   installation's day-cap is spent. **When no cap is set, none applies** —
   the per-repo daily budgets remain the bound (a stated default, not an
   owner decision; §8 Q4's mechanism may later add one). Deleting the
   installation's state on uninstall (`installation.deleted`) removes the
   cap with the credentials.
