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
§7's pending open questions, whose answers are not recorded yet. Nothing
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
  repo (`service_admit.py`). No label, branch, or schedule filter exists.
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
only repo-file surface is C's two lines.

**E. Code constants exposed nowhere**: the post limit
`MAX_COMMENT_CHARS = 65_000` (`service_post.py`), D38's 16,384-character
picker/conversation caps, the 8,192-character controller reserve (D67), the
round-log record cap (D74), D68's derivation defaults, and the depth-mode
breadths.

## 2. Proposed user-facing surface

**Precedence principle: user config tightens, operator config bounds — and
the per-review ceiling is the one value a repo may raise, within the
operator's max (D81, Q2 and its update).** A user may lower a budget, raise
a floor, or narrow what triggers a review; D81 keeps D68's semantics, so a
repo's `review_ceiling_usd:` may also raise its own per-review ceiling —
but the effective value is clamped to the operator's **max per review**,
one of the two per-tenant spend bounds the owner added on 2026-11-18
(3:39 PM CT): an operator max per review and a per-repo daily budget.
Nothing in user config can change the model, providers, or data policy,
widen network, secret, or Sprite access, or enlarge the set of events the
service acts on beyond the operator's envelope — and the one exception to
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
Every posted error names the key, the rejected value, and the default that
stands.

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
instead, pending §7's answers; every operator secret; the Sprite
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
conversation): the intake surface is operator-hosted, and the recommended
path is a **settings page authenticated as the installation's admin via
GitHub** (an org owner or the account owner, per GitHub's own
installation-admin notion), with rotation, revocation, and deletion on the
same page (§7 Q1; alternatives there). Storage: encrypted at rest under an
operator-held key; never logged, never in a post, never passed to Sprites,
cloud agents, or child environments beyond the one model-call client; on
uninstall the stored secret is deleted (§4's bullet, §7 Q8). A
user-supplied base URL is user-controlled egress — its trust rules are §4's
newest bullet. **This needs installation-level state, which D81's Q4 answer
("repo-level only for now") did not build; the conflict is flagged as §7's
Q9, not overridden silently.** The open questions live in §7; the slice is
S10.

## 3. Candidate settings

| Setting | Default | Bounds / rule | Owner | Today |
|---|---|---|---|---|
| Lens include/exclude | none (guideline decides) | lens-shaped names only; never widens the depth mode; never touches the critical tier; exclude wins | user | exists (D69, `REVIEW.md`) |
| Severity floor for posted findings | post everything (the service posts one COMMENT per head, not rounds) | a repo may raise its floor; floor-tier lenses' findings are never silently suppressed — the manifest tier split and the overlay's `acknowledge` rule carry over unchanged | user (floor level), engine (tier rule) | not read by the service; the protocol's `REVIEW.md` defines it |
| Path include/exclude, generated-file handling | none | **ordering and depth only, never exclusion** — whether anything may be excluded from review at all is Q25's undecided question; a user path filter re-ranks and names what it deprioritized | user (ordering); any true exclusion waits on Q25 | not built (`diffs.risk_tier` ranks by path alone) |
| Per-review budget | the repo's own `review_ceiling_usd:` line, or `ATLAS_REVIEW_CEILING_USD` ($10) when absent | the repo sets its own ceiling, up or down — D68's semantics, kept by D81 Q2 — but the **effective** value is clamped to the operator's max per review (D81's update; out-of-range → named fallback, D68's pattern); the ceiling actually used is named in the post (D68's ceiling note) | user (the repo's ceiling), operator (the max) | the read exists (D68); the operator max does not |
| Per-repo daily budget | a working default of $100 per repo per UTC day, pending the owner's number | operator-set (`ATLAS_REPO_DAILY_BUDGET_USD`, proposed name); once a repo has spent its day's budget, further reviews are refused at admission and re-checked at preflight; the record says plainly "skipped: daily budget reached" and never reads as a clean review; the total resets at the UTC day boundary | operator | not built |
| Head-change policy | `keep` (D79) | keep | operator | exists, env |
| When to review | non-draft; `opened`/`synchronize`/`ready_for_review`; allowlisted repos | a repo may narrow on **inputs a PR author cannot control** — the base branch, the event type, the draft state; never widen past the operator's envelope. The config is read from the repo's **default branch** (§4), not the PR's base ref or merge-base, both of which an author can move in same-repo or stacked PRs; the base-retarget dodge (open against an excluded base, then retarget via `edited`) is S4's consideration to close. Label- and head-branch-based rules are author-controlled (the head branch's name and the PR's labels are the author's or triage's to set, so a skip rule matching either is an author-controlled opt-out) and sit behind the deferred PR-level-overrides decision (D81 Q5), not in S4. Any rule-based skip is recorded with a one-line reason, so a skipped review is distinguishable from the service being down | user (narrowing), operator (envelope) | admission exists (`service_admit.py`); filters not built |
| Post format and verbosity | the current post body (D75) | verbosity may be lowered only; the Findings section, the coverage note and the REVIEW INCOMPLETE banner are never suppressible | user | not built |
| #734 tool allow-lists | deny-all; structured `run_tests`/`mutate` with bridge-built argv | a repo's requested additions are **proposals** that become operator-approval requests (the #734 decision: approval may apply within the same run, bounded by the wall and dollar limits); never auto-granted | operator approves, user proposes | #734 not started |
| Coding guidelines / AGENTS.md ingestion | none | delivered as fenced untrusted context blocks under the D67/D73 room budget, like the conversation and CI blocks; never instructions | user (content), engine (delivery) | not built |
| Quiet hours / rate limits | none | an operator ceiling per repo per day; a user may only opt into quieter | user narrows, operator bounds | not built |
| BYOK endpoint and key | none — the operator's key and endpoint serve every review | supplied by the installation's admin through the intake surface (§2, §7 Q1), never through `REVIEW.md`, any repo file, or a PR conversation; an HTTPS-only base URL that passes §4's egress checks; encrypted at rest, never logged or posted, never past the one model-call client | installation admin (supply), operator (intake, store, egress rules) | not built |
| BYOK model choice | the operator's model | whether a BYOK installation may also choose models is §7 Q5; if allowed, the D68 budget shape (calls, turns, walls) stays and the dollar budgets resolve from the price table when the model is known — unknown pricing is §7 Q6 | user (choice), operator (bounds) | not built |

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
    the depth mode or touch the critical tier, so the strongest lenses
    (the floor-tier set) cannot be excluded away. The migration of these
    two reads to the default branch is the safer end-state and is a
    candidate follow-up; until then their author-influence is stated here
    rather than claimed away.
  - **The base-retarget dodge is S4's consideration to close.** A PR
    opened against an excluded base branch passes admission at `opened`,
    then retargets — GitHub delivers `pull_request.edited` with a
    `base` change and no new `opened` event — and a rule keyed on the
    base branch would then be stale. Since S4's read source is the
    default branch, a base-retarget cannot change the admission answer
    through the config; the remaining surface is rules that compare the
    PR's own base branch, which S4 must either re-evaluate on `edited`
    events or define against the default branch so retargeting cannot
    move the answer.
- **Schema-validated, bounded, fail-open with named notes.** Every value
  carries a range the schema enforces; out-of-range or unparseable input
  falls back to the default and names itself, generalizing D68's
  unusable-ceiling-line pattern. The 64 KiB read bound stays.
- **Config values are untrusted data everywhere they reach a model.** Lens
  names are validated lens-shaped at parse (D69); guideline and
  AGENTS.md-derived content travels nonce-fenced like every other block
  (D65's per-review nonce, D52/D67/D73's assembly rules); config never
  enters trusted controller text.
- **No config key can widen network, secret, or Sprite access.** The
  Sprite's deny-all credential-free policy, the child's env allowlist, and
  the model/data-policy variables sit outside the config schema by
  construction; the schema is a closed set, not a pass-through.
- **The per-tenant spend bounds sit outside repo control (D81 Q2 and its
  update).** D68's semantics stay: a repo may raise or lower its own
  `review_ceiling_usd:`, and the ceiling a review actually used is named in
  the draft and the post (D68's ceiling note) — but the effective value is
  clamped to the operator's **max per review** (proposed name
  `ATLAS_REPO_CEILING_MAX_USD`, a working default of $25 pending the
  owner's number; out-of-range → named fallback, D68's pattern). The
  second bound is the **per-repo daily budget**: once a repo has spent its
  day's budget, its further reviews are refused at admission and re-checked
  at preflight, the record says plainly "skipped: daily budget reached",
  and nothing about the refusal can read as a clean review. The reset
  boundary is the UTC day, and the running total lives where the service's
  durable state already lives — the state root on the Fly volume
  (`ATLAS_REVIEWER_STATE_DIR`), as one append-only
  `<state root>/spend/<repo flattened>-<UTC date>.jsonl` file per repo per
  day, the same pattern D74's per-PR round logs use; the date in the file
  name makes the UTC reset structural, and a lost file loses only the
  day's total, the way a lost round log loses only prior-round context.
  `ATLAS_KEY_CEILING_USD` stays what it is — a cap on the shared key's
  *total* credit limit, not a per-repo bound — which is exactly why the
  per-tenant bounds exist alongside it.
- **BYOK keys are never repo content.** The intake surface is
  operator-hosted (recommended: a settings page authenticated as the
  installation's admin via GitHub — §7 Q1), never `REVIEW.md`, never a repo
  file, never a PR conversation. A stored key is encrypted at rest under an
  operator-held key; it is never logged, never quoted in a post or draft,
  and never passed to Sprites, cloud agents, or child environments beyond
  the one model-call client — the review child's env allowlist gains one
  variable the same way it already holds `ATLAS_OPENROUTER_API_KEY`, and
  the Sprite receives neither. Rotation and revocation live on the same
  intake page; on uninstall (`installation.deleted`) the installation's
  stored secret is deleted, with a retention sweep catching a missed event
  (§7 Q8).
- **A user-supplied base URL is user-controlled egress.** The service makes
  outbound requests to it, which is an SSRF surface: HTTPS only; private,
  link-local, loopback and metadata addresses blocked at connect time with
  the resolved IP pinned for the connection (DNS rebinding); redirects
  re-checked against the same rules; the model client's existing timeouts
  and response caps apply; responses are model replies — already untrusted
  under the existing pipeline, never trusted instructions. **Data policy:**
  the operator's ZDR and safety-retention settings are operator policy for
  the operator key; on a BYOK review the PR diff goes to the installation's
  own endpoint by definition — that is the point of BYOK — so the intake
  page states what is sent (§7 Q3 covers the consent form) and the draft
  and post record which endpoint class served the review. The operator's
  key is never used for a BYOK installation's review except under an
  explicit fallback policy, default off (§7 Q7); a BYOK key failure — an
  auth error, quota, or endpoint down — fails the review with the failure
  named plainly, never a clean-looking "Findings: None".

## 5. Sequencing (issue-sized slices)

| Slice | What | Files | Against the parity track | Order |
|---|---|---|---|---|
| S1 | The config parse module (`atlas_reviewer/repo_config.py`): the two existing `REVIEW.md` lines move onto it unchanged; new keys parse as unsupported with named notes | new module, `review_wide.py` call sites, tests | **concurrent with the parity track** — verified against the code: #750's fix is reservation accounting (`budget.py`'s per-call pricing and `derive_review_wide`'s derived, ceiling-clamped reservation) plus the budget-stopped headline (`coordinator.py`'s `_headline` and the post path), all of which *consume* the resolved ceiling; none of it plausibly changes the `REVIEW.md` ceiling read S1 refactors (`CEILING_LINE`, `review_md_ceiling`, `_lens_preferences`, `resolve_ceiling`'s precedence). Same-file caveat: both edit `review_wide.py`, so a rebase may still be needed if hunks land adjacently | first |
| ~~S2~~ | **Dropped by D81** — Q2 keeps D68's repo-set ceiling, so there is no ceiling direction to change | — | — | dropped |
| S3 | Severity floor + post verbosity | `service_run.py`, `service_post.py`, README | concurrent — disjoint from #734/#713/#708's files | after S1 |
| S4 | When-to-review admission — narrowing on the inputs a PR author cannot control: the base branch, the event type, the draft state. Config read from the repo's **default branch** (#756's approach — §4's corrected rule), not the PR's base ref or merge-base; the base-retarget dodge (`pull_request.edited` retargeting after an excluded-base `opened`) is considered and closed here. Label- and head-branch-based rules are author-controlled opt-outs and sit behind Q5's deferred PR-level overrides, not here; every rule-based skip records a one-line reason | `service_admit.py`, `service.py`, README | **free** — can start now, concurrently with the whole parity track | first available |
| S5 | Path re-ranking + generated-file handling (ordering only) | `diffs.py` | rebase-check against the D79 PRs' delta work before starting | after S1 |
| S6 | AGENTS.md / coding-guideline ingestion as fenced context blocks | `cli.py`, `conversation.py` | **hot files** — `cli.py` is in #734's and the #654/#655 drafts' edit sets; wait for #734 | after #734 |
| S7 | The #734 allow-list and in-run operator approval | `bridge_args.py`, `bridge.py`, service glue | **depends on #734 (D80) landing** | after #734 |
| S8 | Installation-level defaults, quiet hours / per-repo rate limits | `service.py`, `service_queue.py`, new store | **deferred by D81** (Q4: repo-level only; Q7: quiet hours deferred) | deferred |
| S9 | The per-tenant spend bounds (D81's update): the operator max per review clamps the repo's effective ceiling (out-of-range → named fallback, D68's pattern), and the per-repo daily budget refuses further reviews at admission and re-checks at preflight; the record says plainly "skipped: daily budget reached" and never reads clean; UTC-day reset, total on the state volume | `review_wide.py` (the clamp beside the ceiling resolution), `budget.py` (the day's committed-spend accounting), `service_admit.py` + `service.py` (the refusal), README, tests | **against the parity track:** touches `review_wide.py`, where #750's reservation accounting also lands — rebase-check against #750; and it rides S1's parse module (the operator max is a config-bounded value) and S4's admission surface, so it follows both | after S1 and S4; **precondition for opening the App beyond the operator's allowlisted repos** |
| S10 | BYOK: the installation-supplied model endpoint and key — the intake surface, the encrypted store, the model-call client's endpoint/key resolution, the egress checks of §4, the failure-named fallback rule | the intake page (new, outside the package), a secrets-store module (new), `providers.py` + `openrouter.py` (endpoint/key resolution), `service.py` (child env assembly), README, tests | **against the parity track:** mostly disjoint from #734/#750/#713/#708's edit sets, but `tool_model.py` sits beside the #654/#655 drafts' edit set — rebase-check; gated on §7's answers and after S9 (the spend bounds define what a BYOK review clamps to) | last; **prereq: the installation-storage decision (§7 Q9)** |

Recommended order: S4 immediately (touching nothing the parity track
touches), then S1 (concurrent with the parity track, same-file caveat
against #750 noted above), then S3 and S5, then S9 once S1 and S4 have
landed (rebase-checked against #750), then S6 and S7 once issue #734 has
landed, then S10 last once §7's answers are in. S2 is dropped and S8 is
deferred by D81.

## 6. Decisions (D81)

Brandon answered all eight on 2026-11-18 at 3:28 PM CT; the record is
**D81** in [`../open-questions.md`](../open-questions.md), which quotes his
answer to Q2. Summary:

1. **File.** Extend `REVIEW.md` — no new `.atlas.yml`-style file (as the
   plan recommended).
2. **Ceiling direction.** "Let each repo set its own limits": D68's
   semantics stay — a repo's `review_ceiling_usd:` may raise or lower its
   per-review ceiling. The plan's clamp recommendation was **not taken**;
   the operator backstop outside repo control is `ATLAS_KEY_CEILING_USD`,
   and a repo-set ceiling is still named in the post (D68's ceiling note).
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

## 7. Open questions — BYOK (pending; answers not recorded yet)

Brandon's BYOK requirement (2026-11-18, 3:41 PM CT) is recorded above and
in D81's update note; these questions are his to answer, and the parent
will relay the answers. Each with a recommended default.

1. **Intake path.** Operator-hosted settings page authenticated as the
   installation's admin via GitHub (recommended — the key never transits
   repo content or a PR conversation, the admin identity is verifiable
   through GitHub's own installation-admin notion, and rotation, revocation
   and deletion get one natural home), an operator-run manual intake
   (a ticket or form the operator enters into the store by hand), or
   something else?
2. **Endpoint scope.** Any HTTPS host that passes the private-range and
   rebinding checks of §4 (recommended — BYOK's point is the user's own
   provider), or an operator allow-list of endpoint providers only
   (e.g. OpenRouter, a direct Anthropic-compatible host)?
3. **Data disclosure at intake.** An explicit consent statement the
   installation admin must acknowledge before the first BYOK review —
   naming that the PR diff is sent to the installation's own endpoint
   (recommended; it is their key and their content, but the disclosure
   belongs at intake) — or send-by-default with the statement posted for
   information only?
4. **Spend bounds on BYOK reviews.** Keep both bounds applying to the
   installation's own key — they protect the user's money and the
   service's load — with the installation able to lower them and the
   operator max as the outer bound (recommended), or exempt BYOK reviews
   from the per-repo daily budget? `ATLAS_KEY_CEILING_USD` is operator-key
   only either way.
5. **Model choice.** May a BYOK installation also choose the model its
   reviews run on, within what its own endpoint serves (recommended — the
   endpoint and key are theirs; D68's budget shape stays), or is the
   model the operator's choice even on a BYOK key?
6. **Unknown pricing.** If model choice is allowed, refuse models with no
   price-table entry (recommended — the dollar budgets need a price source,
   and the D68 reservation math would otherwise be ungrounded), or accept
   them with the operator max as the only bound?
7. **Fallback policy.** Never fall back to the operator key; a BYOK
   failure fails the review with the failure named plainly (recommended,
   default off — running someone's review on the operator's key without
   their say-so is a cost and consent surprise), or an operator opt-in
   fallback for outage resilience?
8. **Key retention after uninstall.** Delete the installation's stored
   secret on the `installation.deleted` webhook, with a retention-window
   sweep catching a missed event (recommended), or immediate deletion only?
9. **Installation-level storage (the Q4 conflict).** BYOK needs
   installation-level state that D81's Q4 ("repo-level only for now")
   did not build. Recommended default: amend Q4 narrowly — installation
   state for *credentials only*, review configuration stays repo-level —
   or build a general installation-level store now?
