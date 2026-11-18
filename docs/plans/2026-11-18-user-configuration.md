# Plan: letting the GitHub App's users configure the Atlas reviewer service

**Status: decided 2026-11-18 — D81 records the owner's answers; docs only,
nothing implemented.** Brandon asked for this plan on 2026-11-18 ("plan out
some additions for allowing the github app's users to configure the service,
some of which I suspect can be progressing concurrently with the review
parity work") and answered its open questions the same day at 3:28 PM CT;
the answers are recorded as **D81** in
[`../open-questions.md`](../open-questions.md) and as §6 below (D80 stays
with #734's slice). Nothing in this plan was run live: no model call, no
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
the per-review ceiling is the one value a repo may raise (D81, Q2).** A user
may lower a budget, raise a floor, or narrow what triggers a review; D81
keeps D68's semantics, so a repo's `review_ceiling_usd:` may also raise its
own per-review ceiling, backstopped outside repo control by the key-level
spend guard (`ATLAS_KEY_CEILING_USD`) rather than by an operator clamp.
Nothing in user config can change the model, providers, or data policy,
widen network, secret, or Sprite access, or enlarge the set of events the
service acts on beyond the operator's envelope.

**Layer order (first hit wins):** PR-level overrides (none for now — D81
Q5) > the repo file > installation-level defaults (not built — D81 Q4) >
operator env > code default. Values are schema-bounded on both sides; a
clamp or an out-of-range rejection is recorded in the draft like any other
controller note, and a repo-raised ceiling is named in the post through
D68's ceiling note.

**The repo file: extend `REVIEW.md` rather than add `.atlas.yml`.** The read
seam already exists (merge-base tarball, 64 KiB bound, fail-open notes), the
protocol already documents `REVIEW.md` as the repo-facing policy file, and
one file keeps the authoring surface — and the base-ref security rule — in
one place. A second file would split that surface and duplicate the
security rule the copied-parallel-way the standing authoring rules warn
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

**Operator-only, never user-controlled:** `ATLAS_KEY_CEILING_USD`, which is
the spend backstop that stays outside repo control under D81 Q2; the model,
provider, ZDR and safety-retention variables; every secret; the Sprite
policy (deny-all, credential-free, create retries/concurrency); service
concurrency and deadline; the review-repo allowlist and admission envelope;
`ATLAS_HEAD_CHANGE_*`. `ATLAS_REVIEW_CEILING_USD` stays the operator-set
*default* the repo's `review_ceiling_usd:` line overrides, per D68.

## 3. Candidate settings

| Setting | Default | Bounds / rule | Owner | Today |
|---|---|---|---|---|
| Lens include/exclude | none (guideline decides) | lens-shaped names only; never widens the depth mode; never touches the critical tier; exclude wins | user | exists (D69, `REVIEW.md`) |
| Severity floor for posted findings | post everything (the service posts one COMMENT per head, not rounds) | a repo may raise its floor; floor-tier lenses' findings are never silently suppressed — the manifest tier split and the overlay's `acknowledge` rule carry over unchanged | user (floor level), engine (tier rule) | not read by the service; the protocol's `REVIEW.md` defines it |
| Path include/exclude, generated-file handling | none | **ordering and depth only, never exclusion** — whether anything may be excluded from review at all is Q25's undecided question; a user path filter re-ranks and names what it deprioritized | user (ordering); any true exclusion waits on Q25 | not built (`diffs.risk_tier` ranks by path alone) |
| Per-review budget | the repo's own `review_ceiling_usd:` line, or `ATLAS_REVIEW_CEILING_USD` ($10) when absent | the repo sets its own ceiling, up or down — D68's semantics, kept by D81 Q2; the operator's value is the default, and the backstop outside repo control is `ATLAS_KEY_CEILING_USD`; the ceiling actually used is named in the post (D68's ceiling note) | user (the repo's ceiling), operator (default + key guard) | exists (D68) |
| Head-change policy | `keep` (D79) | keep | operator | exists, env |
| When to review | non-draft; `opened`/`synchronize`/`ready_for_review`; allowlisted repos | a repo may narrow on **inputs a PR author cannot control** — the base branch, the event type, the draft state; never widen past the operator's envelope. Label- and head-branch-based rules are author-controlled (the head branch's name and the PR's labels are the author's or triage's to set, so a skip rule matching either is an author-controlled opt-out) and sit behind the deferred PR-level-overrides decision (D81 Q5), not in S4. Any rule-based skip is recorded with a one-line reason, so a skipped review is distinguishable from the service being down | user (narrowing), operator (envelope) | admission exists (`service_admit.py`); filters not built |
| Post format and verbosity | the current post body (D75) | verbosity may be lowered only; the Findings section, the coverage note and the REVIEW INCOMPLETE banner are never suppressible | user | not built |
| #734 tool allow-lists | deny-all; structured `run_tests`/`mutate` with bridge-built argv | a repo's requested additions are **proposals** that become operator-approval requests (the #734 decision: approval may apply within the same run, bounded by the wall and dollar limits); never auto-granted | operator approves, user proposes | #734 not started |
| Coding guidelines / AGENTS.md ingestion | none | delivered as fenced untrusted context blocks under the D67/D73 room budget, like the conversation and CI blocks; never instructions | user (content), engine (delivery) | not built |
| Quiet hours / rate limits | none | an operator ceiling per repo per day; a user may only opt into quieter | user narrows, operator bounds | not built |

## 4. Security and trust

- **Read from the merge-base / base ref only, never the PR head.** This is
  D68's and D69's existing rule for `REVIEW.md` and the protocol's step-3
  rule for both policy files ("a policy file changed by the PR under review
  does not take effect for that review"). A PR author cannot move their own
  review's budget, floor, or filters.
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
- **The spend backstops sit outside repo control (D81 Q2).** D68's semantics
  stay: a repo may raise or lower its own `review_ceiling_usd:`, and the
  ceiling a review actually used is named in the draft and the post (D68's
  ceiling note). The operator's backstop is not a ceiling clamp but the
  key-level guard `ATLAS_KEY_CEILING_USD`, which refuses an OpenRouter key
  whose own credit limit exceeds the operator's bound before any inference.

## 5. Sequencing (issue-sized slices)

| Slice | What | Files | Against the parity track | Order |
|---|---|---|---|---|
| S1 | The config parse module (`atlas_reviewer/repo_config.py`): the two existing `REVIEW.md` lines move onto it unchanged; new keys parse as unsupported with named notes | new module, `review_wide.py` call sites, tests | **concurrent with the parity track** — verified against the code: #750's fix is reservation accounting (`budget.py`'s per-call pricing and `derive_review_wide`'s derived, ceiling-clamped reservation) plus the budget-stopped headline (`coordinator.py`'s `_headline` and the post path), all of which *consume* the resolved ceiling; none of it plausibly changes the `REVIEW.md` ceiling read S1 refactors (`CEILING_LINE`, `review_md_ceiling`, `_lens_preferences`, `resolve_ceiling`'s precedence). Same-file caveat: both edit `review_wide.py`, so a rebase may still be needed if hunks land adjacently | first |
| ~~S2~~ | **Dropped by D81** — Q2 keeps D68's repo-set ceiling, so there is no ceiling direction to change | — | — | dropped |
| S3 | Severity floor + post verbosity | `service_run.py`, `service_post.py`, README | concurrent — disjoint from #734/#713/#708's files | after S1 |
| S4 | When-to-review admission — narrowing on the inputs a PR author cannot control: the base branch, the event type, the draft state. Label- and head-branch-based rules are author-controlled opt-outs and sit behind Q5's deferred PR-level overrides, not here; every rule-based skip records a one-line reason | `service_admit.py`, `service.py`, README | **free** — can start now, concurrently with the whole parity track | first available |
| S5 | Path re-ranking + generated-file handling (ordering only) | `diffs.py` | rebase-check against the D79 PRs' delta work before starting | after S1 |
| S6 | AGENTS.md / coding-guideline ingestion as fenced context blocks | `cli.py`, `conversation.py` | **hot files** — `cli.py` is in #734's and the #654/#655 drafts' edit sets; wait for #734 | after #734 |
| S7 | The #734 allow-list and in-run operator approval | `bridge_args.py`, `bridge.py`, service glue | **depends on #734 (D80) landing** | after #734 |
| S8 | Installation-level defaults, quiet hours / per-repo rate limits | `service.py`, `service_queue.py`, new store | **deferred by D81** (Q4: repo-level only; Q7: quiet hours deferred) | deferred |

Recommended order: S4 immediately (touching nothing the parity track
touches), then S1 (concurrent with the parity track, same-file caveat
against #750 noted above), then S3 and S5, then S6 and S7 once issue #734
has landed. S2 is dropped and S8 is deferred by D81.

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
