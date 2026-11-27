# atlas_reviewer — manual Code Quality Atlas review service

An operator-triggered controller, and a webhook receiver that posts one
advisory review. You give the controller one PR event (repo, PR number,
head SHA). It collects CI evidence for that exact SHA, runs extra review tools
in a fresh Sprite with no credentials, runs the review through this repo's
collapsed `reviewing-a-change` skill bundle, and writes a **review draft** to
stdout or a file.

The operator CLI (`review`, `sweep`, `probe-runner`) never writes to GitHub:
no reviews, comments, check runs, labels, or issues. It has no queue of its
own and runs one review at a time in its state directory.
`python -m atlas_reviewer.service` is the webhook receiver (D48) and posts
one COMMENT review (D46, which amends D48's no-publish rule). It verifies
the delivery, queues one review per commit, and posts that review with
event COMMENT. It never sends APPROVE or REQUEST_CHANGES.
Design and decision record:
[`docs/plans/2026-11-06-manual-reviewer-service.md`](../docs/plans/2026-11-06-manual-reviewer-service.md)
(D24-D30, D32, D33, D35 and D36 in
[`docs/open-questions.md`](../docs/open-questions.md)).
D37 is the Fly one-off deploy. When a draft's `APPROVE` may be submitted
to GitHub is the parity gate in
[`docs/plans/2026-11-12-reviewer-parity-gate.md`](../docs/plans/2026-11-12-reviewer-parity-gate.md).
D45 is where the eval traces should live. Other follow-ups are in that
plan's "Follow-ups" section.

## Deploy on Fly

The operator CLI can run as one Fly Machine per review: no public service
and no standing Machine. That one-off app has no webhook and no queue.
The webhook receiver is D48, a separate process. The image is
`python:3.12.16-slim-bookworm` pinned by digest, installed from
`requirements.txt` with `--require-hashes`, and run as uid 10001. Fly
secrets supply `ATLAS_GITHUB_APP_ID`, `ATLAS_GITHUB_APP_PRIVATE_KEY`,
`ATLAS_GITHUB_INSTALLATION_ID`, `ATLAS_SPRITES_TOKEN`, and
`ATLAS_OPENROUTER_API_KEY`. Every Fly command runs with a token scoped
to the Fly org `personal` and names the app or org. A review Machine
writes the draft and telemetry to its own disk and is held after the
review exits. The operator copies both off with `fly ssh sftp` and then
destroys the Machine. `fly apps destroy` does not remove Sprites; a
runner left behind is destroyed by name with
`sweep --event --force-live`. Stage the secrets with
`fly secrets import --stage`. Do not run `fly secrets deploy`. If the
Depot builder fails, publish again with `--depot=false`. Start
`fly logs` before the run. flyctl's exit means the Machine started; poll
the exit-code file the entrypoint writes. Once the hold ends or the
Machine stops, the code is also the logs line
`Main child exited normally with code: N` and `exit_code=N` on
`fly machine status <id>`. If the app name is taken, pass `--app <name>`
on each command and leave `fly.toml` unchanged. The exact commands are
in [`deploy-fly.md`](deploy-fly.md). This repository does not create the
app.

One operator deploy of app `atlas-reviewer` (org `personal`) ran an
offline-provider review of #605, in the earlier `fly machine run --rm`
shape with the draft on stdout. The no-service `fly.toml` was accepted,
the pinned base image was pulled, the process ran as uid 10001 and exited
4, the Sprite was destroyed and then absent, and `fly logs` showed no
secrets. A stream started late would have lost the start of the draft,
which is why a review now writes it to disk.

## Webhook service

`python -m atlas_reviewer.service` listens for GitHub App `pull_request`
deliveries (`opened`, `synchronize`, `ready_for_review`). A draft is
ignored. One `edited` delivery is admitted too: a retarget, whose
`changes` carries `base` — the PR was moved onto another base branch,
and admission is re-run against the branch it now targets. A title or
body edit carries no `changes.base` and is ignored. The HMAC is
`X-Hub-Signature-256` over the raw body with
`ATLAS_GITHUB_WEBHOOK_SECRET` (at least 16 characters). The repository
must be on `ATLAS_REVIEW_REPOS` (default `brandondees/code-quality-atlas`).
A second delivery of a head SHA whose review already finished does nothing.
A head whose review failed can be queued again. A newer head SHA
cancels the review of the previous one, and that cancelled review is not
posted — unless the head-change policy below decides to keep it.

### A repo's own narrowing of when it is reviewed

A repository may narrow — never widen — when the service reviews it, with
lines in its `REVIEW.md` read from the **default branch** — the branch
that changes only through reviewed merges, so a PR cannot move its own
admission. The PR's own base branch and the PR head are never read for
this: in a same-repo or stacked pull request the author controls both,
and a config read from either would let the author opt their own PR out
of review (round-1 review of #756, Major 1). The keys:

```text
review_base_include: <branch>[, <branch>...]    # only PRs targeting these base branches are reviewed
review_base_exclude: <branch>[, <branch>...]    # ...unless the base branch matches one of these: exclude wins
review_skip_events: <event>[, <event>...]       # deliveries to skip: a coverage-reducing opt-out, see below
```

Every key is one line whose value is a comma-separated list, running to a
`#` comment or the end of the line, the same value grammar the file's
review-side settings use. A branch entry may end with one `*`, which
matches any branch with the prefix before it (`release*` matches
`release-1`); no other glob character is read. Two consequences of that
grammar: a branch name containing `#` or `,` — both legal in git ref
names — cannot be expressed (the text from there on reads as a comment
or the next entry, which can only match differently, never wider than
the operator envelope), and a leading byte-order mark is not prose — it
is stripped, so a BOM'd first key line still parses or is still named.
These are this schema's
own bounds, not GitHub's: an entry is at most 64 characters, a line
carries at most 32 entries, and a `review_skip_events:` entry must be one
of the four skippable event names — the three accepted actions
(`opened`, `synchronize`, `ready_for_review`) plus `edited`, the
retarget.

**`review_skip_events` is a coverage-reducing opt-out, and the repo owner
is the one opting out.** A skipped event's deliveries produce no review,
so the coverage that event alone would have provided is lost and can
land unreviewed — this key is an opt-out, not a safety feature, and the
consequence differs per event:

- skipping `synchronize` means the reviews that do run see the state at
  `opened` — or, for a PR opened as a draft, at `ready_for_review`;
  every push after that, up to and including what merges, lands
  unreviewed;
- skipping `ready_for_review` defers a draft-opened PR's first review to
  its first push after becoming ready — that review covers the whole
  diff, so the draft's work is still reviewed; a PR that becomes ready
  and merges with no further push is never reviewed;
- skipping `opened` defers a non-draft PR's first review to its first
  push (that review covers the whole diff, not just the delta); a
  draft-opened PR's first review lands at the ready transition;
- skipping `edited` suppresses the retarget-triggered review only: a PR
  moved onto an included base is not reviewed for the retarget and waits
  for its next push, which arrives as `synchronize` — a PR that
  retargets and merges with no further push is never reviewed on its new
  base;
- skipping all four means the repository is never reviewed.

The owner decides; the service records every skip with its reason so the
decision's effect is visible in the telemetry.

Narrowing runs after the operator's envelope has passed — the delivery is
a non-draft `pull_request` event of the three accepted kinds, or a
retarget (`edited` with `changes.base`), on an allowlisted repo — and the
checks run in a fixed order: skip event, then
the base branch (an include list the delivery's base branch does not
match, or an exclude match, skips it; exclude wins). The patterns come
from the default branch; what they match is the delivery's base branch,
which the author chose but cannot rewrite — the config's source, not the
match target, is what keeps an author from opting out. A skipped delivery is recorded on
the `review skipped` telemetry event with its fixed reason — carried on
the operator log line too — and nothing is queued or posted for it: a
skip acts on the delivery only, and neither cancels a review already
running nor supersedes a queued one, which finish under the envelope they
were admitted under. The skip is a log record, not a comment; the service
posts nothing for a PR it did not review.

**A base retarget re-enters admission.** A PR retargeted onto another
base branch arrives as an `edited` delivery whose `changes` carries
`base`; the service admits exactly that shape — a title or body edit is
ignored — and re-runs the same admission path against the `base.ref` the
payload now carries, reading the config from the default branch as
always. A retarget onto an included (or unexcluded) base starts the
usual review of the current head, deduplicated against any in-flight or
settled review of that head by the queue's key. A retarget onto an
excluded base is skipped with the usual `repo-base-branch` reason, and
the skip acts on the delivery only: a review already running for the
head was admitted under the base it was reviewed against and is
advisory, so it finishes and posts, and nothing new is queued or
posted. A retarget is also a skippable event: `review_skip_events:
edited` suppresses the retarget-triggered review (see the opt-out's
coverage note above). A retarget can no longer move a PR out of review
without a record: every retarget delivery is either reviewed,
deduplicated, or logged with its skip reason.

There are deliberately no label-based or head-branch-based filters: the
PR author controls both, so a skip rule matching either would let an
author opt their own PR out of review — the shape the user-configuration
plan's answer on PR-level overrides rules out. Those filters are deferred
with that question; only inputs the author cannot control narrow here.

The config values are untrusted data and the parse is bounded and
fail-open, the way the review-side settings are: a line that is present
but not usable — no value, an entry outside its key's grammar, more
entries than the cap, or a key that appears twice — falls back to that
key's default, which narrows nothing, and is named on a `repo admission`
telemetry event. The file is read under the same 64 KiB bound the
review's merge-base copy is. A repository with no `REVIEW.md` on its
default branch is the ordinary unconfigured case: the operator's envelope
stands, silently. A read that fails — credentials unusable, a fetch past
its budget, a file over the read bound — also stands on the operator's
envelope, with the gap on a `repo admission` event, because narrowing
only ever removes reviews and a missing read widens nothing. When the
payload does not carry the default branch's name, one read-only lookup
(`github_api.get_repository`) recovers it, and a lookup that fails is
that gap. A deployment
whose App credentials are absent or unusable has no admission reader at
all; its boot log says so once, and every delivery runs on the envelope
alone. The narrowing uses a read-only App client
built from the same credentials and the same read-only scope as the
head-change classifier's (`github_api.get_file`); like the
classification, the
read runs in a helper thread, and **all** of the handler's GitHub reads
on one delivery — the admission read and, when a review is running, the
classification — share one overall read budget, so however many run they
cannot together hold the handler past GitHub's response window.

Only these three keys are read at admission. The repo's two post settings
(`review_severity_floor:`, `review_post_verbosity:` — the next section)
are read from the same default branch, at post time. The file's
review-side settings (`review_ceiling_usd:`, `review_lens_include:`,
`review_lens_exclude:`, `review_path_include:`, `review_path_exclude:`,
`review_generated_files:`) are the review child's, read from the
merge-base
tree it already fetches through the shared parse module
(`repo_config.py`, config slice S1); an unknown key — including a
label-filter line from an earlier draft of this surface — is not named
here. On the review-side reads the shared parser names unsupported keys
itself: a `review_`-namespaced line its schema does not carry is ignored
fail-open with a named note. This admission read keeps its own narrower
parse until the two reads unify on one module.

### What the service posts: the repo's severity floor and post verbosity

Two more `REVIEW.md` lines are the repo's say over what the service
posts — config slice S3, read from the **default branch** like the
admission keys above, and for the same reason: the floor decides which
findings reach the post and the dial decides which sections it carries,
so a config read from a surface the PR's author controls — the PR head,
or the merge-base a same-repo or stacked PR can carry lines onto — would
let the PR quiet or suppress its own review on the only surface a human
reads. The default branch changes only through reviewed merges. The
value that governed a post is the one the default branch carried when
the post was written, fetched at post time and parsed through the shared
parse module's schema (`repo_config.parse_post_config`, D84). The read
costs **two uncached read-only calls per post attempt** — the
default-branch lookup plus the file read — under the App installation
token, bounded by the same 8-second read budget the admission read uses;
the source is read after the poster's dedupe checks, so an
already-posted head spends none, and there is no per-repo cache between
posts (r1 review of #770, Nit 3).

```text
review_severity_floor: <severity>    # blocker | major | minor | nit — post findings at or above this severity
review_post_verbosity: <dial>        # full (the default body) | brief — the one position below it
```

**The floor's default posts everything.** The service posts one COMMENT
per head, not converging rounds, so with no floor line every verified
finding is posted. A repo may raise its floor. Findings below it from
preference-tier lenses are held in the draft and named by the count the
post's Findings section carries — never silently — and the post names
the `review_severity_floor:` key and the level that took effect.

**A floor-tier lens's finding is never held, whatever its severity.**
The manifest's `tier: floor` split carries over unchanged (D81 Q3): the
five floor-tier lenses' findings post at any severity under any floor —
the same protection the merge-base lens preference's exclude cannot
cross. The team-preferences overlay's `acknowledge` rule carries over
with it: the service reads no overlay today, so the floor is the only
suppression this post path applies, and it applies only to
preference-tier findings.

**The verbosity dial may be lowered only.** `brief` drops the lens
bookkeeping (Lenses run, Lenses not run, Lens decisions) and the Cost
section, and keeps the Findings section, the coverage note, the Limit
stops, and a delta review's resolved and carried sections. One
exception, from the #757 composition (r1 review of #770): on an
**incomplete** review the brief post keeps `Lenses not run` too, because
the REVIEW INCOMPLETE banner and the Findings section's incomplete note
point the reader at that section by name — the pointer resolves, never
dangles. The Findings section and the coverage note are never
suppressible at any verbosity; there is no value above `full`, so no
setting can make the post more verbose than the body the service already
sends.

**An unusable line fails open to its key's default and is named.** A
`review_severity_floor:` line that is not one of the four severity names
(lowercase — the enum's own spelling, not the protocol prose's
capitalization), a `review_post_verbosity:` line that is not `brief` or
`full`, or a key that appears twice is ignored — the keys independent,
each with its own default — with a note on a `post config` telemetry
event that names the key, the condition and the default that stands and
never the rejected value; the post itself carries the note. A read that
fails, or a file over the same 64 KiB bound, also leaves the default
standing — the protective direction, since a lost read can only make
the post more complete, never less — with the gap on the telemetry; the
post is never held for it. A repository whose default branch carries no
`REVIEW.md` is the ordinary unconfigured case: the defaults stand,
silently.

**A floor is a coverage-reducing choice, and the repo owner is the one
choosing it** — stated the same way `review_skip_events`' cost is
stated: a below-floor preference-tier finding lands in the draft only,
so a human reading only the post does not see it. The draft — the
record the service keeps on its volume — carries every finding either
way.

### A push that lands mid-review (#702, D79)

When a newer head arrives while a review of the previous head is still
running, the service decides per push whether to keep that review or
cancel it. The policy is `ATLAS_HEAD_CHANGE_POLICY`: `keep` (the
default) decides per push; `cancel` restores the blanket supersede this
policy replaced. The decision compares the push against the running
review's progress, which the review child records into its events file
after every settled lens and once when its lens loop ends (`progress`
records: lenses settled of the planned count, spend against the derived
reservation, and the paths still being read):

- a push that only merges the base branch, or only touches docs or
  tests, or touches no file a lens without a clean run is still
  reading, keeps the review however late it lands;
- a push that changes code under review cancels a review that is still
  early — early meaning under `ATLAS_HEAD_CHANGE_CANCEL_FRACTION` (a
  fraction, default `0.5`) on **both** the lenses settled and the budget
  spent — so cancelling stays the narrow exception. The spend measure
  alone cannot tell an early review from a cheap one (a review whose
  every lens has settled can sit far under its derived worst-case
  reservation), so either measure alone would cancel completed work
  (round-1 review of #747, F1);
- otherwise the review is kept and a follow-up review of the new head
  queues behind it.

The classification reads GitHub's comparison of the two heads plus the
pull request's base (`classify_delivery` in `head_change.py`), and the
benign kinds are claimed only on evidence: a failed fetch, a cut commit
list (a comparison at GitHub's files cap may be cut, and a comparison
with no `files` array is refused outright), or a merge whose base side
cannot be identified reads as code; an empty, untruncated range changes
nothing the review reads and is benign. A push no evidence classified
at all keeps the review — the owner's default — and the gap is on the
decision's telemetry with an error status: a deployment whose App
credentials are absent or unusable has no classifier, and its boot log
says so once while every such decision carries the gap (round-1 review
of #747, F3). A review that is already posting is never cancelled. The
classification's evidence comes from the same party the review judges —
a crafted merge commit can present a code push as a merge of the base —
and every consequence of that lands on the keep side, since the
follow-up reviews the new head regardless (round-1 F18).

A kept head does not hold a queue slot while it waits: the queue records
it as the pull request's pending follow-up, and queues it when the
running review settles — as a delta review building on the settled head
when that review succeeded, as an ordinary review when it failed. A
pending head can be stranded — the process dying between the review's
settle and the materialization, a failed materializing save, a full
queue at materialize time — and a redelivery of a stranded head is
answered duplicate, so the queue recovers one: at boot, and on every
worker pass, a pending head whose pull request has no active job is
queued as an ordinary review and named on the `follow-up queued` event
(round-1 review of #747, F7). The decision is the `head change`
telemetry event (both heads, the kind, the fractions, the reason, the
decision's duration, and a `timed_out` flag when a classification read
ran past its transport timeout — round-1 F8), the costs are `review
cost` events (from the
draft's cost lines when the review finished, from the last progress
record when it was cancelled, `measured: unknown` when neither exists),
and the queued follow-up is a `follow-up queued` event — all in
`service.jsonl`, tagged with the heads, so the numbers the threshold is
tuned on can be read against each decision.

The follow-up review of a kept head is a **delta review** (`delta.py`).
Its subject is still the whole pull request at the new head — the
earlier review's verdict covered the whole changeset, and so does this
one's — but the payload carries only the **incremental diff**: the
range `delta_from..head`'s own per-file patches, the new material since
the earlier review. Context the earlier review already established is
not re-sent, which keeps D68's cost goals. A merge-only push yields an
empty delta, and the review then exists to carry the earlier findings
forward.

The coordinator judges **each planned lens** before any of them runs
(D83): one bounded, tool-less call — over the incremental diff, the
fresh evidence blocks the lenses get (newer CI results, newer comments)
and the lens names with their one-line concern summaries — decides, per
lens, whether to re-run it or reuse the earlier review's settled
result. The decision is the coordinator's judgment over the incoming
changes, not a fixed path-intersection rule; uncertainty resolves
toward re-running, a lens whose earlier findings cite files the
incremental diff touches is flagged to the judgment and the flag is
recorded with the decision, and each decision and its reason are
recorded in the telemetry, in the round record, and in the draft and
post. A lens the earlier review did not settle clean has no settled
result to reuse and re-runs structurally. A
**re-run lens** runs on the whole pull request's diff — the
incremental diff highlighted in its first turn as the new material —
and may report findings anywhere in the pull request, unchanged content
included. A **reused lens** does not run: its earlier findings stand,
carried forward and re-assessed against the new evidence (D73), and the
files it would have read are covered by the reused settled result —
"complete coverage" means every file in the pull request is covered,
either by a re-run or by a reused settled result that read it, not
every delta file. One accounting rule keeps that honest (round-1 review
of #760, Major A): a file the delta added or modified cannot have been
read by any reused result — the delta-admission gate guarantees only
that the earlier review read the pull request at ITS head — so every
delta-touched path must be read by a lens that ran this round, or it is
unreviewed and the review cannot approve. And D73 binds the reuse path
exactly as it binds the ledger's (round-1 review of #760, Major B): a
reused lens whose evidence snapshot moved since the earlier review — or
whose record carries no digest — earns its one bounded re-assessment
after the carry-forward composes, the same `_reassess_call` the
ledger-reuse path runs, recorded on the decision.
When the delta could not be established there is no
incremental diff to judge from, so no lens is reused and no decision
call is made; an empty established delta (a merge-only push, or an
established comparison whose files carry no readable patch) reuses
every eligible lens without a call — the patchless case's touched paths
still gate coverage, so a file they name that no ran lens read holds
the review at COMMENT. A failed or refused decision call
falls back to re-running every lens, the safe direction — a reuse is
never silently invented, and never silently kept on a broken reply.

The scope carries a **resolution gate that fails closed**
(`DeltaScope.resolution_paths`): the paths a resolution may be accepted
for, empty whenever the delta could not actually be established — an
unfetchable range, a diverged history after a rebase or force-push (the
comparison's file list is then measured from the wrong base), or a file
list that is malformed, holds unreadable entries, or is cut at GitHub's
comparison cap. With the gate empty, no resolution is accepted however
the assessor proposes it, and every prior finding is carried.

After the delta's lenses settle, one bounded, tool-less **carry-forward
call** judges the earlier review's findings — the round log's records at
`delta_from`, labeled `P1`, `P2`, ... — against the incremental diff:

- a finding the carry-forward re-states is quote-checked against the new
  head's files exactly like an ordinary finding's, and a verified
  restatement is carried into the findings set under its `P` label;
- a finding the new commits fixed is marked **resolved** only on real
  evidence: the proposal's `evidence` must quote code that is among the
  **range's own removed lines** for that file — read from the
  comparison's per-file patches (`delta_from..head`), with each line's
  old-side position — not the pull request's net diff, where a delta
  commit's deletion of PR-added code is invisible and a pre-delta PR
  removal sits in the pool (round-2 review of #748, Major A); and every
  quoted line must sit within the finding's cited span widened by the
  quote tolerance, so any removed line in the file does not clear the
  gate (round-2 a2) — alongside the file being one the established delta
  touched. A withdrawal without that evidence is recorded as the proposal
  it is and the finding stands carried — a withdrawal never removes a
  finding on the model's say-so alone, the D73 path's rule;
- the carry turn shows the range's own patches, so the assessor quotes
  what the commits between the heads actually changed; a comparison with
  no readable merge base is untrusted like every other malformed shape
  (round-2 a1), and an incremental diff over its cap is cut with the
  truncation marker (round-2 a4);
- everything else is carried as the record stored it, in the draft's
  `Carried, not re-verified` section and back into the round record, so
  the next review re-offers it — including a line that does not parse,
  which travels as the record's raw text verbatim (round-1 review of
  #748, M3), and a record whose finding lines did not fit the record
  cap, whose `findings_omitted` count the draft states rather than
  reading as "no findings recorded" (round-1 M5) — and that rides into
  this review's own round record, so the omission stays in the durable
  chain across hops instead of dying with the draft (round-2 Major B).
  A carried finding
  that did not re-anchor still counts for the verdict — a prior Blocker
  can never become an approval because its quote moved (round-1 M4);
  an unreadable round log names the read failure instead of claiming
  nothing was recorded (round-1 m1).

A finding identical to a carried one (same re-anchored location and
text) is posted once, as the carried copy; two records at the same
`delta_from` carrying the same finding are carried once too. The carry
assessor adds no findings: the instructions ask for dispositions only,
and an entry with no `revises` label is dropped and named (round-1 m5).
The delta review's post cites the review it builds on — the post says
"Follows the review of" the head — and shows the lens decisions, the
resolved and carried sections. The decision call and the carry-forward
call each spend against the review's own derived limits and the dollar
ceiling (D68) like every other call; the carry-forward's failure — a
contract refusal, a transport error, a spent-out review — falls back to
carrying every prior finding as recorded, with the failure named.

The review child follows the service mode, one at a time unless
`ATLAS_REVIEW_CONCURRENCY` says otherwise (1 to 32; 32 is a startup refusal
so a bad value cannot start an unbounded pool, not a cost cap).
`ATLAS_SERVICE_MODE` selects the command: `agentic` (the default, D70)
runs `python -m atlas_reviewer agentic-review`, and `oneshot` runs the
one-shot `review` command. An unknown value refuses to start the service
instead of silently picking one. The one-shot mode stays a complete,
callable command — D25's ceilings apply: 3 calls, $3, and 200,000 input
tokens — while the agentic child reads
the agentic limits and derives its review-wide limits from the planned
lens count under the per-review dollar ceiling (D68). The parent's
wall-clock deadline around one child follows the mode: oneshot keeps
1,200 seconds; agentic defaults to the 14,400-second upper bound,
because there the parent deadline is a backstop, not the real limit —
the child's own derived wall and D68's dollar ceiling are what stop a
review. The condition to know: a plan's derived wall can reach
`ATLAS_LENS_WALL_S × ⌈planned lenses ÷ pool⌉` (D68 raises the configured
wall to that, never lowers it), and the parent cannot see the plan
before the picker runs. `ATLAS_SERVICE_DEADLINE_S` sets the deadline
between 60 and 14,400 seconds; an explicit value below the child's
*configured* wall refuses to start, and an operator who expects
multi-wave plans sets it to cover the walls those plans derive. At pool
1, plans of 13 or more lenses derive more than even 14,400 seconds
(1,200 × 13); raise `ATLAS_POOL_SIZE` or lower `ATLAS_LENS_WALL_S` for
those — and a configured `ATLAS_REVIEW_WALL_S` above that ceiling
refuses to start, since no in-bounds deadline can cover it. D69 removes
the picker's fixed 8-lens cap, so a plan with more lenses is now an
ordinary outcome of the guideline, not a misconfiguration; the same two
levers cover it, and no lens-count cap was added to keep plans inside
the deadline. A review the
parent kills at the deadline posts nothing: the job
fails, the failure is a telemetry
event, and the review child's own stop has already destroyed its Sprite.
A later push of the same head can queue it again. The child
process receives only an allowlist: the OpenRouter key, because it calls
the model, the Sprites token, because it creates and destroys the Sprite,
a read-only installation token, `ATLAS_MODEL`, `ATLAS_PROVIDERS`,
`ATLAS_ALLOW_SAFETY_RETENTION`, `ATLAS_REQUIRE_ZDR`,
`ATLAS_KEY_CEILING_USD`, the agentic limit variables (D68's per-lens
knobs and `ATLAS_REVIEW_CEILING_USD` included; the one-shot command
ignores them), and the process basics.
It does not receive the webhook secret, the App private key, or a Fly API
token. Exit 0, 4 and 5 are finished
reviews and are posted. Any other exit posts nothing; the failure is a
telemetry event.

The post is one pull-request review whose event is COMMENT. The body says
the review is advisory and not a substitute for the full Claude Code
protocol review, then lists the draft's verified findings -- each finding
line exactly as the controller rendered it in the draft (every
model-authored field already an inert code span, the line uncapped so a
long finding's `Fix:` and `Evidence:` survive), placed right after the
recommendation; a comment cut to the post limit drops whole findings
from the end (the draft lists them most severe first) and names the
drops in the Findings section, rather than slicing a finding mid-span --
then the lenses
that ran, the lenses that did not,
the controller's file-coverage note, the limit stops, and the cost. A
review whose coverage is not complete -- or that the draft's status line
cannot show complete -- carries a "REVIEW INCOMPLETE -- not a clean
review" banner above the findings, and its empty Findings section names
the incompleteness instead of the bare "None." (issue #750): a
budget-stopped review cannot be mistaken for a clean one. The
draft's own APPROVE or REQUEST_CHANGES line is quoted as a recommendation
and is not sent. A retry of the same commit does not post a second time:
the key `repo#pr#sha` is stored after GitHub accepts the review, and a
review is reused only when it carries that marker, its `commit_id` is this
SHA, and its author is this App's bot (`ATLAS_GITHUB_APP_SLUG` plus
`[bot]`). Another App's bot does not count. The posting token asks
for `pull_requests: write` and for no other write. The App installation
has to grant that permission or the post fails and nothing is published.

`ATLAS_SERVICE_PROVIDER` defaults to `openrouter`, and the process refuses
to start until `ATLAS_ALLOW_LIVE_INFERENCE=1` is set, so a booted service
does not post reviews a model never ran. `ATLAS_SERVICE_PROVIDER=offline`
is the explicit no-model setting. The deploy shape is a second Fly app,
[`fly.service.toml`](../fly.service.toml), always on, in org `personal`.
The one-off `fly.toml` above is unchanged. Commands:
[`deploy-service.md`](deploy-service.md). D53.

## The per-tenant spend bounds (config slice S9, D81)

Two operator-set bounds sit outside repo control, and a third joins them
per installation:

- **The operator max per review** — `ATLAS_REPO_CEILING_MAX_USD`, default
  $25. D81 Q2 keeps D68's semantics: a repo's `review_ceiling_usd:` line
  may raise or lower its per-review ceiling. A raise is clamped to the
  operator max — a repo-raised ceiling cannot pass it — and the clamp is
  named in the draft's ceiling note beside the ceiling itself, the way
  D68 names the ceiling the review ran under. The operator's own
  configured ceiling (`ATLAS_REVIEW_CEILING_USD`) and the default are the
  operator's own choices and are never clamped by this variable.
- **The per-repo daily budget** — `ATLAS_REPO_DAILY_BUDGET_USD`, default
  $100 per repo per UTC day. Once a repo's day has spent that much
  committed model spend, further reviews are refused at admission and
  re-checked at preflight (a delivery admitted while the day had room is
  refused in the worker before its review starts). The refusal is
  recorded with the fixed reason `daily-budget` and the plain text
  "skipped: daily budget reached" — never a clean-looking review; nothing
  is posted for it.
- **The per-installation daily cap** — set by the installation admin on
  S10's settings page, enforced alongside the per-repo budget with the
  stricter of the two governing each admission. When no cap is set, none
  applies and the per-repo budgets remain the bound. Its value is S10's
  installation store (see the next section); the store-backed provider
  replaces S9's always-none one wherever the store is configured, and a
  store it cannot read refuses the check outright ("skipped: installation
  store unavailable") instead of reading as an unset cap.

## funding-spend

`python -m atlas_reviewer funding-spend --repo owner/name` prints one
UTC day's settled model spend, grouped by the funding source that paid
it. A line with no source prints as `(unset)`. `--day YYYY-MM-DD`
selects another day; omitted, the command reads today. A missing file
prints nothing and exits 0. An unreadable ledger exits 2, and a
`--day` that is not a date exits 2. The command reads the ledger and
does not write it, and it does not call a model.

## The installation store and the tenant-supplied endpoint (config slice S10, part A)

A GitHub App installation (a user account or an org) can supply its own
model API endpoint and key, and its reviews then run on them. Part A is
the backend: the encrypted store, the tenant model-call path, the egress
guard, the retention rules. The settings page the installation admin
uses — the intake surface, rotation, revocation, consent acknowledgement,
the cap dial — is part B, which calls the store's API; no page exists yet.

**The store.** One encrypted record per installation at
`<state dir>/installations/<installation id>.json`, encrypted at rest
under the operator-held key `ATLAS_INSTALLATION_STORE_KEY` (a Fernet key;
`cryptography`'s authenticated encryption — already in the lock for
`PyJWT[crypto]` — not hand-rolled crypto). The record holds the tenant
credentials (endpoint base URL, key, chosen model), the installation
admin's daily cap, and the consent acknowledgement, with a private 0700
directory, 0600 files, atomic writes, and a per-installation advisory
`fcntl.flock` held across every read-modify-write, delete and sweep step —
the service process and part B's settings-page process serialize on it,
so a concurrent consent write cannot be lost under a rotation and a
rotation cannot resurrect a record the `installation.deleted` webhook
just deleted. Every read fails closed: a store that is unreadable,
corrupt, or encrypted under the wrong key raises with the reason named,
the review fails with that reason, and nothing falls back — no
operator-key path opens for a record this service cannot read. A
deployment that never set the store key and has no records on disk is not
a failure: no installation has credentials, so no tenant path exists and
no cap applies. A key that is gone while records remain on disk **is** a
failure, because the records it cannot read may hold credentials. The
retention sweep skips any directory entry that is not a valid record
name — a crash's leftover `<id>.json.writing` temp, a stray file, or a
record-shaped name that fails the store's own id validation (`0.json`,
an over-long digit string) — naming the count instead of halting on it,
and deletes only what it wrote: the skip is the id's whole validation,
so no name the store did not write can stop the sweep or be removed by
it.

**The routing rule.** An allowlisted repo whose installation has no
tenant credentials is reviewed on the operator's key, as today. A repo
whose installation has tenant credentials is reviewed on them. A tenant
review never falls back to the operator's key on any failure. The
`ATLAS_REVIEW_REPOS` allowlist stays the invite-only gate; a
non-allowlisted installation cannot review on the operator's key at all.

**The tenant model-call path.** The review child receives the tenant
credentials through three environment variables — `ATLAS_TENANT_MODEL_KEY`
(the key; the one credential variable the child env allowlist gains, the
way it holds `ATLAS_OPENROUTER_API_KEY`), and the settings
`ATLAS_TENANT_BASE_URL` and `ATLAS_TENANT_MODEL` — and a tenant-path
child **does not receive the operator's key**. The tenant client speaks
an OpenAI-compatible chat completions shape at the installation's base
URL, with no OpenRouter routing document and no key-credit preflight.
`ATLAS_KEY_CEILING_USD` stays operator-key only. Pricing comes from the
operator's price table — the OpenRouter public catalog entry for the
chosen model, read without any credential: a model with no entry there is
refused with the reason named; a zero-priced model is allowed, and the
per-review call caps and walls bound it. The settle reads only reported
token counts priced at that table; the tenant path never reads
`usage.cost` or `cost_details.upstream_inference_cost`, so a
tenant-reported figure can move only the tenant's own settled total,
never a reservation and never an operator-protective bound. The existing
OpenRouter-BYOK handling on the operator-key path (`usage.is_byok`,
`ByokRefusedError`, D41) is untouched, and the two never share a code
path. The draft's cost line, and the posted Cost section, record which
endpoint class served the review — the operator's, or the installation's
own.

**The egress guard.** A user-supplied base URL is user-controlled egress.
The tenant transport is HTTPS-only and refuses a URL with userinfo. At
connect time every address the hostname resolves to is checked against
the blocked set — the plan §4 list (the RFC 1918 ranges, `127.0.0.0/8`,
`169.254.0.0/16`, `0.0.0.0/8`, `100.64.0.0/10`, ULA `fc00::/7`,
link-local `fe80::/10`, `::1`, `::`, all IPv4-mapped IPv6
`::ffff:0:0/96`) **and beyond it** (the round-1 call): the
IPv4-embedding IPv6 forms an HTTPS model API has no business on —
IPv4-compatible `::/96`, 6to4 `2002::/16`, NAT64 `64:ff9b::/96` and
`64:ff9b:1::/48`, Teredo `2001::/32` — plus the discard-only `100::/64`,
IPv6 multicast `ff00::/8`, and the IPv4 multicast, benchmarking and
reserved ranges. The check runs over IPv4 and IPv6 alike, and any blocked
address refuses the whole host — the connection never races a round-robin
resolver — then the socket connects to the checked address itself while
the TLS handshake still presents the original hostname, so a DNS
rebinding double has nothing to rebind to, and a failed connect closes
its socket before re-raising. Redirects are never followed and are
refused by name. The existing timeouts and response caps apply, and the
responses are untrusted model output.

**Failure rule.** An auth error, quota error, endpoint down, egress
refusal, unknown price, or store failure fails the review with the
failure named plainly in fixed phrases — never a clean-looking
"Findings: None" — and the key is never echoed in any of them.

**Retention.** The `installation.deleted` webhook deletes the
installation's stored state — credentials, cap and consent. A delivery
the service cannot honor right now (a store it cannot read) is answered
500, which GitHub re-delivers, so the deletion is retried rather than
lost, with the gap named on the telemetry. A retention-window sweep at
boot deletes records unrefreshed past `ATLAS_INSTALLATION_RETENTION_DAYS`
(default 30), catching a missed webhook.

**Not yet set in any deployment.** `ATLAS_INSTALLATION_STORE_KEY`,
`ATLAS_INSTALLATION_RETENTION_DAYS`, and the three `ATLAS_TENANT_*`
variables are documented here and configured nowhere; no tenant
credential exists on the deployed service, and the settings page that
would set them is part B (below).

**What is counted.** The committed spend is the review child's own
accounting — reported token counts priced at the operator's price table —
taken from the finished draft's cost line, or from the last progress
record when a review did not finish; a review with no figure in either
records nothing and the gap stays on the cost telemetry, because the
amount is never guessed. No tenant-reported dollar figure is ever
consumed. A review whose process crashed before the worker could settle
it is backfilled from the progress figure its own run left in the run
directory. The events file is append-only across a head's attempts (the
telemetry sink opens `O_APPEND` and nothing clears the directory), so
the figure is scoped to the crashed attempt's own span — its run-start
line plus its progress records — and a retry that appended its startup
events and died before its first progress record has no figure of its
own: the previous attempt's stale tail is not re-counted. The backfill
is deduplicated in the ledger itself by that attempt-scoped key, once
per crashed attempt however many recoveries repeat; it runs before the
preflight check, so the crashed spend counts against the bounds the
retry is admitted under. An over-count, were one ever to land, fails
safe — it makes the bounds refuse earlier, never later — while every
under-count path is fail-closed or named on the telemetry. A recovery
that crosses the UTC boundary backfills into the recovery day's ledger,
the day the retry is admitted under — the same safe direction. A crash
whose run directory holds no readable progress figure records nothing,
and the gap is named on the recovery's telemetry.

**Where the total lives.** One append-only
`<state dir>/spend/<owner>-<repo>-<UTC date>.jsonl` file per repo per
UTC day, where the owner and repo segments are percent-encoded with every
byte outside `[A-Za-z0-9]` escaped — so `a-b/c` and `a/b-c` are distinct
files, and the joining `-` is unambiguous because a literal `-` inside a
segment always reads `%2D`. The date in the file name makes the UTC reset
structural, and a lost file loses only that day's total. The files are
kept indefinitely — there is no retention or cleanup, one file per repo
per day accumulating for as long as the deployment runs — the same
append-only pattern as the per-PR round logs, and the same trade: the
operator can prune old days by hand when the volume matters. A file the
service cannot parse holds the budget (the total reads unknown and the
refusal stands) until it is repaired, with the gap named on the record —
a ledger the service cannot read never opens the budget.

**The race is named and bounded, not locked.** Two concurrent deliveries
for one repo can both pass admission (and preflight) before either
commits spend — the queue's one-active-job rule is per pull request, not
per repo. The refusal applies to the next admission after the total is
committed, and the overshoot past the day's budget is at most the
in-flight reviews times each one's per-review ceiling: at the decided
values, 32 in-flight reviews × the $25 operator max = $800 past a $100
budget, bounded by `ATLAS_REVIEW_CONCURRENCY` (1-32), and past the
installation's cap by the same bound. The overshoot is visible in the
same telemetry the total comes from. A per-repo lock would eliminate the
overshoot at the cost of serializing a repo's reviews; D81 accepts the
bound instead. `ATLAS_KEY_CEILING_USD` stays what it is — a cap on the
shared key's total credit limit, not a per-repo bound.

## The execution-tool allow-list and operator approval (config slice S7, D88)

A repo may **propose** additions to the #734 execution-tool allow-list:
declared test commands a lens's `run_tests` call can run instead of the
built-in pytest entry. The line is `review_test_commands:` in the
`REVIEW.md` on the repo's **default branch** — the same read source the
S3 post settings and the S4 admission narrowing use, never the PR head
and never the merge-base, because a proposal a same-repo or stacked PR
could carry would name commands into its own review's execution surface.

**A proposal is a request, never a grant.** The value is a
comma-separated list of commands, each one program token plus optional
fixed argument tokens separated by spaces — `review_test_commands: make
check, sh run.sh`. The grammar is a closed set: tokens over a
conservative charset with no shell metacharacter, quote, expansion or
separator in them, the program's path held to the bridge's own
workspace-relative path rule, at most 8 commands of at most 8 tokens
each. Any unusable value — an empty value, a token outside the grammar,
too many commands or tokens, the same command twice, the key more than
once — fails open to deny: nothing is proposed, and the review's note
names the key, the condition, the count and the default that stands,
never the rejected text.

**How an approved command runs.** When a lens's `run_tests` call names a
proposed command, the bridge routes one approval request through the
`ApprovalChannel` port (`approval.py`) and grants **only an explicit
approval** — every other outcome denies: a denial, no answer, a channel
error, and the run's wall or dollar limit being reached while the request
waits. The wait is bounded by the shorter of the run's remaining wall
clock and a 30-second cap (provisional, pending the owner), so one wait
cannot park the whole review wall, and it counts against the run's wall
because it is the calling lens's own elapsed time. An approved addition
lives in run-scoped state that dies with the lens run's runner: it is
never carried to another lens's runner, another run, another PR, or any
state on the volume.

**The channel is decided: pre-approval, not live approval.** Brandon
decided on 2026-11-19 at 12:05 PM CT (D88's update): **installation admins
pre-approve a repo's extra commands on the S10 settings page (part B), and
there is no live approval during a review.** The run reads that
pre-approved, installation-scoped set once at run start; a proposal the
run's allow-list does not carry pre-approved is denied and named as an
unapproved gap, and nothing asks a live operator mid-run. The port stays
as the seam part B backs with that set — until part B lands, nothing is
pre-approved, so the production default (`NeverApproved`) never approves,
and on a deployed service every blocked command is denied and named as an
unapproved gap — an `unavailable` tool
result whose reason carries the counts (how many commands the run's
allow-list proposes, how many are approved) and never the command text.
A review with an unapproved-command gap open cannot approve, the way any
tool gap holds it.

**Bridge-built argv only, nothing widened.** An approved command runs the
proposal's own validated tokens, each shell-quoted, from the same
disposable staged copy under the same `timeout`, output cap and
environment as the built-in pytest entry — no shell string, no selector
appended (a command and a selector are refused together), no environment
change. Those are what the bridge adds to a proposal's own text; they are
not a containment guarantee the grammar makes — a proposal's argument can
name any path shape its charset allows, and an approved program can reach
the runner's filesystem regardless. What bounds a named interpreter (a
shell included) is the operator's approval of the exact argv plus the
deny-all, credential-free runner, named in the next sentence. The grammar
does refuse the traversal-shaped argument tokens (`.` and `..`; an
argument cannot carry `/`), so `pytest --rootdir ..` is dead by grammar
rather than left to the approval to bound. The model cannot smuggle any of
it: the named command is an exact-match lookup against the run's
allow-list, extra arguments are refused, and a name no proposal carries is
refused without an echo. A proposal may itself name a shell interpreter —
`sh run.sh` is the ordinary declared-command shape — but the operator
sees and approves the exact argv, and the runner stays deny-all and
credential-free, so no approval can widen network, secret, credential or
Sprite access. `mutate` never takes a command: its verdict needs pytest's
own summary line, so it runs the built-in entry whatever the repo
proposes. Each lens run's gate records the proposals count on the
telemetry (`run approvals` / `configured`), so a run that proposed nothing
and a run whose proposals never reached the coordinator can be told
apart.

## The runner's setup phase (issue #819, D95)

`run_tests` and `mutate` (D80) need a pytest-capable interpreter, and a
fresh Sprite ships none: the deny-all policy is set before anything
executes, so nothing could be installed, and every execution-tool call
returned "no pytest-capable interpreter was staged for the runner". The
fix is a **setup phase the repo declares**: the `review_setup_commands:`
line in the `REVIEW.md` on the repo's **default branch** — the same read
source the S7 proposals take, never the PR head and never the merge-base,
because a PR that could carry its own setup commands would name installs
into its own review's runner while the network is open.

**The order is the guarantee.** A runner given a setup spec provisions in
a different order: create, resolve the trusted interpreter, run each
declared command bounded (from the neutral directory, still before any PR
content is uploaded or unpacked), **then** set deny-all, read it back
exactly, cap memory, and run the behavioral egress check — whose
`CONNECTED` answer fails the run closed. Every exec of the review — the
staging probe, the tool runs, `run_tests` and `mutate` — happens after
that read-back. Every lens runs this same provisioning on its own
runner. Without a setup spec the
lifecycle is unchanged: deny-all
from the start, and the existing order tests still pin it. The value's
grammar is the S7 proposals' token grammar with one addition: the program
token may be the `{python}` placeholder, substituted with the interpreter
the controller resolved by absolute path — `review_setup_commands: {python} -m pip install pytest`. The same fail-open rules apply: an
unusable value or a repeated key runs no setup phase and is named with a
note that never echoes the rejected text; a command that fails, times out,
or outlives its budget fails the run. A `review_setup_files:` line names
the **default-branch files the setup commands read** — repo-root-relative
paths, each fetched from the same default branch and uploaded into the
runner's setup directory under its own name before the first command, so
`-r requirements.txt` resolves; a file the branch does not hold, or one
over the read bound, leaves no setup phase with the note that says so.

**The shared checkpoint is retired; every lens runs the setup.** The
direction's "pre-baked image with dev dependencies per repo" was first
built as a shared bake: one setup runner per review checkpoints its
post-setup state and every lens runner restores from it. The live Sprite
checks of Nov 25 found the design cannot work on today's API, and the
Nov 25 model-mix rerun showed it failing live — every lens's restore
returned `SBD checkpoint not found` and fell back to the per-lens setup
it was meant to replace: checkpoint ids are scoped to one sprite (a
restore on another sprite fails), checkpoints do not survive their
sprite's deletion, and the API has no create-from-image parameter at all
(OpenAPI 0.1.12, re-fetched Nov 25 — `CreateSpriteRequest` carries `name`
and `url_settings` only). The bake/checkpoint machinery is removed; each
lens runs the setup phase itself on its own runner, the same provisioning
order as above, a few seconds of pip time per lens, measured live. The
design comes back when an image-bearing create parameter or a
create-from-checkpoint path exists; the setup spec needs no change
either way.

**Install where `-I` can see it.** The setup commands run under the
runner's minimal environment with `HOME=/tmp`, and the Sprite's
interpreter tree is not writable by the exec user in the way pip's
writability check expects: a bare `pip install` falls back to a **user
install** into `/tmp/.local`, which `-I` (isolated mode — no user site)
cannot import. The live checks showed the
symptom exactly: staging reported `pytest: none` while a non-isolated
import found `/tmp/.local/.../pytest`. Write the spec's installs with
`--no-user` — `review_setup_commands: {python} -m pip install --no-user
pytest` — which lands in the interpreter's own site-packages, imports
under `-I`, and is what this repo's own `REVIEW.md` sets.

**The execution environment (D80's 2026-11-26 update).** The setup spec
this repo sets installs the repo's **full requirements**
(`{python} -m pip install --no-user -r requirements.txt`, hash-pinned),
not a curated trio: the test files that exercise the webhook and round
paths import PyJWT, PyYAML and the OTLP exporter, and a spec that
installs only pytest left every test file that needs them failing at
import — red baselines, and every mutant on those files INCONCLUSIVE.
The per-command setup bound rises with it (900 seconds; the review wall
still bounds the phase as a whole), and the per-lens setup cost is now
pip's install time for the whole tree, not a few seconds. The test
processes `run_tests` and `mutate` launch never run as root: a
controller-built shim, run by the trusted interpreter staging resolved,
drops a root caller to the standard `nobody` user before the tests
start (a caller that is already not root execs directly), so the access
controls the repo's own tests exercise actually bind — the round log's
locked-file test failed its baseline under a root test process. The
shim adds no binary to the image; a drop that cannot happen exits 126
with the reason named, never a root run. Staging also probes the
environment once per review: `pytest --co -q` runs in a disposable copy
of HEAD as that same user, and a failed collection becomes the named
`the test environment is broken` gap on the execution tools instead of
surfacing as silent INCONCLUSIVE mutants and red baselines the lens
cannot read as evidence. The lenses also gain the **probe tool** (`run_probe`, D80's
2026-11-26 update): the model writes one throwaway test file's source,
the bridge writes it into its own fresh disposable copy of the head tree
(base64-decoded, at the copy's root under a controller-chosen name no
repo file can shadow) and runs it under the same sandbox as `run_tests`
-- the no-root guard, the same clock and output caps, deny-all egress --
and the copy is thrown away, so the file never reaches the repository or
any later call. The call shares `run_tests`'s per-attempt cap and counts
as a run when it produces one. One test process's wall clock is 180 seconds
(was 60: the repo's own full suite takes about 74 seconds, so a
whole-suite baseline under `mutate` — two processes, one call — could
not fit), overridable with `ATLAS_TEST_TIMEOUT_S` (30 to 600).

## The read-only history tools (D80's git-history update)

The lenses can read the pull request's own history now: `git_log` (the
commit range as `git log --oneline`), `git_show` (one commit's patch, or
one path's patch within it), and `git_blame` (who last touched each line
of a cited span, as of the pull request's head — the pre-existing/
introduced context a finding's attribution needs). The history reaches
the runner as a **git bundle** the staging uploads in parts (one exec's
stdin caps at 10 MiB) and fetches into the staged repository, verified
against the pull request's own head SHA; the bundle's cap is
`HISTORY_BUNDLE_MAX_BYTES`. A bundle over the cap, a fetch that fails,
or a bundle whose head is not the pull request's degrades to the named
no-history gap -- the run completes and every other tool is untouched,
never a partial history or a failed run. Because executed code can
rewrite the staged repository, a re-stage (what every call after a run
tool does) re-uploads and re-fetches the controller-held bundle; a
re-fetch that fails there marks the history lost, and the history tools
report the gap naming the failed re-fetch.

Every history tool is read-only — log, show and blame write nothing —
and runs in the same runner sandbox as the other tools: deny-all egress,
the timeout and the byte and line caps. A revision is valid when the
pull request's head or its base tip reaches it — the PR's range, or
anything reachable from base — and the exec's rev guard refuses anything
else before git runs, as a rejected call.

**The acquisition is wired.** The controller builds the bundle once per
review, before the lens fan-out, from the pull request's real commits:
`review_lenses` takes a `history_source` callable (an eval run loads the
fixture's own bundle; a live review fetches the pull request's head ref
over HTTPS with the App's credentials), and every lens's runner gets the
same bundle. The builder verifies the fetched tip is still the head the
review is about (a push landing between the diff's fetch and the
acquisition acquires nothing), names it the ref the staging's fetch
expects, and bases the tools' range on the merge-base the diff was built
against — so the range resolves inside the bundle even when the base
branch has moved. A failed fetch, a moved head, or a bundle over the
runner's cap acquires nothing: the history tools report the named
no-history gap, and the bash copy's git sees the staging repository's
synthetic commits until a bundle stages — the prompt's history claims
are true exactly when a bundle is present. An eval fixture carries its
own history as `history.bundle` (a git bundle whose ref is
`refs/heads/atlas-history`, the name the staging fetches) plus
`history-base.txt` (the merge-base SHA the tools' range is built on);
a fixture that ships neither is the ordinary no-bundle run.

## The grounding pre-pass (the protocol's step 4.3)

Before any lens judges, the controller runs the deterministic tools the
reviewed repository already gates its merges on and hands every lens the
hits as evidence. The command list is **parsed from the target repo's CI
workflows** (Brandon's Nov 26 decision): the merge-base tree's
`.github/workflows/*.yml`/`*.yaml` files' `run:` steps, read line by
line and classified into the lint, type and test families by the tool
each line names (ruff/eslint/shellcheck-style linters, mypy/pyright/tsc
type checkers, pytest/jest-style runners, and a package manager's or
`make` target's own `lint`/`type`/`test` entry point). Lines that
install, fetch or change state are never classified: the pass reproduces
what CI checks, not what it provisions, and nothing is installed that
the repo has not adopted. At most 12 commands run per pass, and the rest
are named past the cap in the evidence block and the coverage lines.

Each command runs in its own disposable copy of the head tree — the same
copy, no-root guard, verified deny-all egress, clock and framing the
`bash` tool uses — without spending the attempt's call budget, because
the pass is the controller's evidence gathering. A chain that installs
or fetches before its check (`pip install x && pytest`) cannot be
reproduced under deny-all egress: the check is named as unreproducible
in the evidence block and the coverage lines, never run with its
provisioning failure reading as the check's own, while offline chains
(`ruff format --check . && git diff --exit-code`) run whole. One command
runs at most 180 seconds (the execution tools' clock, #843); the pass's
whole wall budget is 540 seconds, and a command the remainder cannot
start is a named result, never a silent skip. The commands run with the
setup-provisioned tools' own bin directory on PATH, so a repo whose
setup spec installs its linters resolves them the way CI's environment
does.

The pass runs once per review: the first lens to reach it runs it on its
own runner and the others read the same outcome. Every lens gets the
results as one fenced `tool-evidence` block grouped by family — each
failing command's captured output tail (where pytest's summary and the
linters' hit lists sit), each clean run's exit, every gap named: a
workflow file that did not parse, a command the budget never reached, a
pass that failed outright. The hits are evidence for the owning lens to
confirm, contextualize or dismiss; a clean run clears nothing. A repo
whose workflows declare no lint/type/test command sends no block, and
the draft's coverage section states the empty inventory.

The draft carries the coverage section (**Tool coverage (grounding
pre-pass)**): what ran, what did not and why, which families carry no
configured command, and which changed file types no configured tool
covers — the four coverage facts this pass can state honestly. The
Pending-in-CI fact is the CI evidence's own to state and is not produced
here.

## The parity harness's driver: `eval-run` (issue #713's harness-parity slice)

`python -m atlas_reviewer eval-run --fixture <dir>` runs the product's
own review path over a **recorded fixture**: the directory carries the
event file and the PR snapshot at the anchor — the pull request, its
diff, its comments and review threads, its check runs, and the source
trees — and the review reads everything through the fixture the way a
live review reads GitHub. The live context builders run (the
conversation block, the CI block, the guidelines block, the round log),
so the lenses see what a production review sees, which is the parity the
Nov 25 analysis found missing.

`--lenses picker` (the default) selects as a production review does;
`--lenses owners` runs exactly the parity key's owner lenses for the
fixture's pull request, no picker call; a comma-separated list fixes the
set by name. `--run-file PATH` writes the eval-parity run file from the
completed review — the loader's own schema, with the comparison fields
null — and `--tool-log PATH` logs every tool result, as the model saw it
(rendered and capped), one JSON line each naming the lens that served the
call (the pooled lenses' lines interleave in one file), so a diagnosis
reads what happened instead of inferring it from statuses.

Offline by default: a fixture run without `--allow-live-inference` uses
the scripted or dry model and the in-memory runner, spending nothing.
With it, the run calls the real provider against real Sprites over the
same fixture — real money, the operator's to start — and is what the
parity stage's go/no-go runs on.

The committed parity anchors' fixtures are `fixtures/pr640/` and
`fixtures/pr661/`, each the recorded snapshot at its parity-key anchor
(#640 at `0fe45e5e`, the head the Nov 14 trial reviewed; #661 at
`28854775`, the round-5 head the key re-anchored to), built by the
read-only `snapshot-build` command (`python -m atlas_reviewer
snapshot-build ...`): the one step allowed to touch the network — the
GitHub reads go through `gh api`, the trees, the diff and the
self-contained `history.bundle` come from the local checkout — with the
committed fixture offline afterward. The snapshot filters to what the
anchor's reviewer saw: the anchor's lineage commits, the remarks posted
before the anchor push, the CI at the retained commits with the jobs'
logs where GitHub still serves them. The prior review rounds reach the
eval only through the conversation block — no `rounds.jsonl`, the
owner's 2026-11-26 decision — and the fixture-root `REVIEW.md` and
`agents-md.txt` are the default branch's files as they stand today (the
setup spec is today's, not the anchor-time one); the anchor-time copies
ride in the trees, where the merge-base config read takes them. Each
fixture's `FIXTURE.md` documents its own provenance — #661's
reconstructed round-5 body and rebased-away lineage, #640's current-body
caveat — and the command line that rebuilds it.

## The BYOK settings page (config slice S10, part B1)

Part B1 is the intake surface: a GitHub App installation's admin signs
in with GitHub and manages that installation's tenant-supplied
credentials, consent acknowledgement, and daily cap through part A's
store API. It is the new top-level package `atlas_settings/` — outside
`atlas_reviewer` — running as its own process beside the review
service on the same state volume; every write goes through the store
API, so the per-installation `fcntl.flock` serializes the two
processes. The page is stdlib `http.server` with server-rendered HTML:
no web framework was added, no client-side JavaScript ships, and no
third-party script, font, or CDN is referenced. Run it with
`python -m atlas_settings --host 127.0.0.1 --port 8090`; deployment is
out of scope here.

**Sign-in.** The GitHub App's user-authorization web flow: the page
sends the browser to GitHub with the App's client id, its own redirect
URI, a random `state`, and a PKCE S256 `code_challenge` (GitHub has
supported PKCE for the App user-authorization flow since its
2025-07-14 changelog; only S256 is accepted). State and verifier are
bound to a short-lived pre-login session. The code is exchanged
server-side for a user access token, the token identifies the user
with exactly one read (`GET /user`), and it is then discarded — never
stored, logged, or kept in the session.

**Who counts as the installation admin** (the issue's rule; GitHub has
no separate role):

- a user-account installation: the signed-in user's id equals the
  installation account's id;
- an organization installation: the user's membership in that org is
  `admin` and `active`, checked with the App's installation token
  minted for exactly one permission — Organization **"Members:
  read"** (`members: read`).

The admin check is re-verified on **every** write (and every settings
page read), not only at login, and it fails closed: any API error,
timeout, or unexpected shape refuses the request. **Operator setup
step, not done:** if the App does not carry Organization "Members:
read" today, the org-admin check refuses — the mint fails, the page
refuses, and nothing works around the missing permission. Granting
the permission is an App-settings change the operator makes in
GitHub's UI; this slice does not make it. Until then, org
installations cannot use the page, and user-account installations are
unaffected.

**The invite-only gate.** The page reads the installation's
repositories and refuses — with one fixed phrase — when the
installation covers no repository on `ATLAS_REVIEW_REPOS`, checked at
sign-in and again on every write; never widened or bypassed here. The
coverage read stops at ten pages of one hundred repositories and
treats an exhausted bound as unproven, so the bound can only refuse,
never satisfy, the gate.

**Sessions and request safety.** Server-side sessions behind a signed
cookie (`HttpOnly`, `Secure`) keyed by
`ATLAS_SETTINGS_SESSION_KEY`: the cookie carries a random session id
and an HMAC-SHA256 signature; every other session fact — identity,
CSRF token, the OAuth bindings — stays in the page process. The
signed-in session's cookie is `SameSite=Strict`; the short-lived
pre-login binding is `SameSite=Lax`, because the redirect back from
GitHub's authorize page is a cross-site top-level GET navigation a
`Strict` cookie is not sent on. A signed-in session's TTL is 30
minutes of idle time with a 12-hour absolute cap; a pre-login session
lives 10 minutes. Every
state-changing POST carries the session's CSRF token, only POST
changes state, request bodies are bounded at 8 KiB, and sign-in and
writes are rate limited (per IP on sign-in, per session and per IP on
writes). Every response carries `Content-Security-Policy: default-src
'none'` (plus `style-src 'self'`, `form-action 'self'`,
`frame-ancestors 'none'`), `X-Frame-Options: DENY`, HSTS,
`Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and
`X-Content-Type-Options: nosniff`; the
handler never logs a query string, so the OAuth code and state are in
no log.

**The key is write-only.** The page shows that a key is stored, when
it was last saved (from the page's own audit log), the endpoint, and
the chosen model — never the key, not even partly, after it is saved.
Saving credentials validates the endpoint with part A's rules (HTTPS
only, no userinfo, and the host must pass the egress guard's
resolution check) and the model against the operator's price table
(the same public-catalog read part A's provider runs; no entry
refuses, a zero-priced model is allowed) — and makes **no test model
call**, which would spend the installation's money. Rotation is the
same form again; revocation removes the key (the cap and the consent
survive); deleting everything removes credentials, cap, and consent
together behind a typed confirmation.

**Consent before use.** The settings page shows the plan §7 decision 3
statement — "The PR diff is sent to the installation's own endpoint." —
and records the admin's explicit acknowledgement through the store API.
Saving credentials without the acknowledgement stores nothing and says
why.

**The daily cap.** The installation admin sets or clears it. The value
is a positive dollar amount of at most two decimal places up to
$10,000 (D90's sane upper bound); anything else is refused with one
fixed phrase that never echoes the value. An unset cap means no
installation cap applies, and the page says plainly that S9's
stricter-wins combination and the operator's max per review remain the
outer bounds either way.

**Audit.** Each accepted write appends one JSONL line to
`<state dir>/settings-audit.jsonl` — the action, the installation id,
the GitHub user id, and the UTC time — and never a value: the
append-only record takes none of them as parameters. The page reads it
back only for the credentials' last-saved time.

**Run it.** The page refuses to start unless every variable it needs
is set, naming the missing ones:

| Variable | New here | Purpose |
| --- | --- | --- |
| `ATLAS_SETTINGS_GITHUB_CLIENT_ID` | yes | The App's OAuth client id (the "Client ID" on the App settings page, not the App id) |
| `ATLAS_SETTINGS_GITHUB_CLIENT_SECRET` | yes | The App's client secret, for the server-side code exchange |
| `ATLAS_SETTINGS_SESSION_KEY` | yes | The HMAC key the session cookie is signed under (generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Must be at least 32 characters — shorter is refused at startup |
| `ATLAS_SETTINGS_BASE_URL` | yes | The page's own base URL; `redirect_uri` is `<base>/callback`. Must be https (a loopback http URL is accepted for local testing) |
| `ATLAS_GITHUB_APP_ID` | no (part A) | The App's numeric id, for the App JWT the admin check reads with |
| `ATLAS_GITHUB_APP_PRIVATE_KEY` | no (part A) | The App's PEM private key, for the App JWT and the installation-token mints |
| `ATLAS_GITHUB_INSTALLATION_ID` | no (part A) | The installation this deployment reviews for — the page manages exactly it |
| `ATLAS_INSTALLATION_STORE_KEY` | no (part A) | The store's Fernet key; the page refuses to start without it |
| `ATLAS_REVIEW_REPOS` | no (part A) | The allowlist behind the invite-only gate (default `brandondees/code-quality-atlas`) |
| `ATLAS_REVIEWER_STATE_DIR` | no (part A) | The state directory the page shares with the review service. Set it to the **same absolute path** the service runs with: the default is cwd-relative (`.atlas-reviewer-state`), so two processes started from different working directories would silently open different stores and the per-installation `flock` would no longer serialize their writes |

All of the above are documented here and set in no deployment yet.
`--host` (default `127.0.0.1`) and `--port` (default 8090) are CLI
arguments, not environment variables. A bind failure — the port
already in use, the usual accident of a fixed default port — exits 2
with `atlas_settings: <reason>` on stderr, the same shape a
misconfigured environment gets. Ctrl-C stops the page cleanly; SIGTERM
terminates the process without draining in-flight requests.

**The split.** The per-repo pre-approved command list Brandon decided
for S7 (D88's 12:05 PM CT update) is part B2, a later PR, because it
extends S7's code — the `review_test_commands:` read and the approval
port are S7's, and B2 backs the port with this store. B1 leaves the
seam: the page's write-action dispatch is a table the B2 actions join
beside these, on the same session, admin-check, gate, CSRF, and audit
machinery.

## Run it offline (no credentials)

From the repo root:

```sh
pip install -r requirements.txt   # Python 3.12+, in a virtual environment
python -m atlas_reviewer review --event atlas_reviewer/fixtures/sample-pr/event.json --dry-run
```

`--dry-run` wires a fixture directory as GitHub, the in-memory fake as the
Sprites runner, and the offline provider, which calls no model, so the
draft reports the diff as NOT REVIEWED and its lenses as planned, not run.
No model reviewed any file, so this command's dry run always exits 4,
review incomplete (see Review event and the coverage gate). CI runs this
same command. The `agentic-review` dry run is a different path — it runs
the lenses end to end through a scripted reviewer, and can exit 0, 4 or 5
(see "The agentic dry run reaches and runs the lenses" below). Useful flags:

- `--out draft.md` writes the draft to a file. A missing directory, an
  unwritable path or a dangling symlink is refused (exit 2) before the
  review starts.
- `--expect check_run:NAME` (repeatable) names evidence that must exist. If
  it is absent, the draft reports it as UNKNOWN. Valid kinds: `check_run`,
  `workflow_run`, `job`, `workflow_log`, `artifact`, `runner_tool`.
- `--include-issues` opts in to fetching the issues the PR body closes.
  Off by default.
- `--deadline-seconds N` sets the external runner deadline (default 600).
- `--max-model-calls N` (1 to 3, default 3) caps model calls per review,
  retries included. One goes to the lens picker (except at triage depth,
  with only one call, or when no picked lens could fit), the rest to diff
  parts (see Lenses and Diff coverage).
- `--diff-chars-per-call N` (default 176000, at least 1000) is the most diff
  characters a model call may carry. Each review shrinks it further until
  every planned prompt fits the token bound (see Diff coverage).
- `--depth {triage,review,comprehensive}` (default `review`) is the atlas
  depth mode. Triage runs the critical tier with no picker call.
- `--events FILE` writes lifecycle telemetry as JSONL (see Lifecycle
  telemetry). A dry run writes none without it. A run holds the file for
  its whole duration, so a second run naming the same file, even from
  another state directory, is refused with the usage error (2) and creates
  no telemetry file. The hold is a lock on a sibling `FILE.lock`, which
  stays after the run.
- `--first-frame-seconds N` (default 30, also on `probe-runner`) fails any
  exec that sends no input if no output byte arrives within N seconds (see
  One exec shape).

Tests: `python -m pytest atlas_reviewer/tests -q --cov=atlas_reviewer`.

## The agentic dry run reaches and runs the lenses

```sh
python -m atlas_reviewer --state-dir .atlas-reviewer-state agentic-review \
  --event atlas_reviewer/fixtures/sample-pr/event.json --dry-run
```

`agentic-review --dry-run` is the offline end-to-end path for an
entry-point change: the lens loop, the tool bridge, the quote checks, the
attestation ledger, the synthesis, the verdict, the draft and the exit
code all run as real code, with nothing to stub by hand. What the wiring
substitutes:

- GitHub is the fixture directory (`FixtureGitHub`), as in the one-shot
  dry run.
- The runner lifecycle is `LocalSprites`
  (`atlas_reviewer/local_runner.py`): every exec — bridge staging under
  real git, the `diff_file` and `read_file` tool calls, the task hold —
  runs as a local subprocess under the same `env -i` wrapper. There is no
  network client in the wiring, and the deny-all egress policy is set and
  read back through the fake the same way a live run enforces it; a
  dry run that skipped that hook would not be a dry run of the review.
- The keepalive hold talks to `LocalTasks`, a unix-socket Tasks API under
  the state directory, so a lens hold is created, held and deleted for
  real.
- The model is a scripted reviewer (`atlas_reviewer/lens_script.py`),
  driven by a JSON **lens script**. Its reading behavior is fixed — the
  order the lens instructions themselves ask for, every changed file's
  diff page by page, then a HEAD `read_file` of every file a finding
  cites — and what varies is data in the script: which findings each lens
  reports, and which changed files no lens ever reads (`unread`), for a
  coverage-gap scenario. Each finding entry is validated by the real
  finding-contract parser when the script is loaded, so a malformed
  scenario is refused before a run; an unknown severity loads, because
  dropping it is a scenario (D54).

The default lens script is the fixture's
`atlas_reviewer/fixtures/sample-pr/scenarios/blocker.json`: one verified
introduced Blocker, so the shipped dry run exits 5 with a complete,
approving-coverage review that requests changes, and the draft carries
the finding, the committed-secrets section for the fixture's own planted
key (values scrubbed), and the attested lens table. One scenario per
verdict class ships beside it: `approve.json` (no findings, exit 0),
`comment.json` (a verified Major and a verified removed-line Minor,
COMMENT, exit 0), `gap.json` (`settings.ini` never read, exit 4 with the
file named), and `drop.json` (a finding whose severity matches nothing,
dropped and named, exit 4). A new scenario is a new JSON file in that
directory passed with `--lens-script`, not new code.

The dry run's attestation ledger is a per-run file under a temporary
directory in the state directory, so re-running or editing a scenario
replays from scratch instead of reusing an attempt settled for the same
head and lens body. The runners.ledger and the review lock behave as
live. `--lens-script` is refused without `--dry-run`: a canned reply can
never stand in for a live model. Nothing is read from the environment;
the run works with an empty one, and its test runs the shipped command as
a subprocess with exactly that. A dry run can exit 0, 4 or 5 by the same
table as a live review; the one-shot `review --dry-run` is unchanged and
still always exits 4, because its offline provider reviews no file.

CI runs this path through `test_dry_run_end_to_end.py`, which drives the
real CLI entry for each scenario and asserts the draft's event, the
coverage gate and the exit code, plus one telemetry read-back proving the
egress policy was verified.

The dry run keeps the paged path (D65): its scripted reviewer does not
name an input room, so every review pages through `diff_file`, which is
what keeps the `gap` scenario's coverage gap reachable — on the
shared-prefix path, coverage is attested from the delivered prefix and a
gap of that kind cannot occur. The shared-prefix request layout itself is
pinned by the adapter and lens-loop tests with fake models.

## Score a recorded review

`eval` compares a candidate review with a reference review and prints
JSON. It does not call a model, GitHub, or Phoenix.

```sh
python -m atlas_reviewer eval --fixtures atlas_reviewer/fixtures/eval-score
python -m atlas_reviewer eval --fixtures atlas_reviewer/fixtures/eval-references
python -m atlas_reviewer eval --fixtures atlas_reviewer/fixtures/eval-score --gate
```

`eval-parity` scores a directory of recorded runs against the parity key
and prints the gate. It does not call a model, GitHub, or Phoenix.

```sh
python -m atlas_reviewer eval-parity --runs atlas_reviewer/fixtures/parity-offline
```

`--fixtures` is a directory of JSON files. A file with `output` and no
`candidate` is a reference row (the Phoenix dataset shape: `input`,
`output`, `metadata`). A file with `candidate` is scored. `--gate` exits 1 unless the directory has a passing pair for every
checked-in row under `fixtures/eval-references/`, `--head` names a
commit that one passing pair records, and one passing pair has
`metadata.over_context_window` set. A directory that holds only the
pair for `--head` does not pass. A calibration pair matches `--head`
only at its `reviewed_commit`. A new head passes on its own pair,
which matches `--head` at `head_sha` or `reviewed_commit`. That pair
records lens-fan-out, complete coverage, zero unreviewed files, and a
lens that ran, and it fails when a lens was NOT RUN or failed. It is
not scored for recall. A pair fails when recall of the
reference findings is below 1, a selected lens was NOT RUN or failed,
a lens named by a reference finding was not run, or file coverage is
incomplete. An extra finding, a different verdict,
and a different severity do not fail it. A match is the same path and
a line within five. The hand-built fixture is expected to fail the
gate. The reference directory holds protocol rounds from
PRs #602–#637 and has no candidates, so the gate fails closed. Exit 2
is a fixture that does not parse, including one that is not UTF-8 or
cannot be read.

## OpenTelemetry

Agentic reviews emit OpenInference spans when `ATLAS_OTEL_ENDPOINT` is
set in the controller's environment. Unset, no exporter is built. An
`OTEL_EXPORTER_OTLP_ENDPOINT` left in the environment does not turn
export on. The value is an `https` URL, or `http` to loopback
(`localhost`, `127.0.0.1`, `::1`). A base such as
`https://phoenix.internal:6006` is sent as
`https://phoenix.internal:6006/v1/traces`. `ATLAS_OTEL_HEADERS` is
comma-separated `name=value` pairs (an `Authorization` header belongs
here) and is read only on the controller. Those values are scrubbed
like the other controller credentials. A `Bearer`, `Basic`, or `token`
scheme is split off, and the credential is scrubbed on its own.
`ATLAS_OTEL_EXPORT_BODIES` exports
scrubbed prompt and completion text only when the value is exactly `1`.
An LLM span records cache-read and cache-write prompt tokens when the
reply reports them (`llm.token_count.prompt_details.cache_read` and
`cache_write`), and omits each one that was not reported. It records
the provider that served the call as `atlas.provider` and, when that
name is a known OpenRouter slug, the OpenInference value as
`llm.provider` (`amazon-bedrock` and `Amazon Bedrock` are `aws`, and
`google-vertex/<region>` is `google`). An
unknown name stays on `llm.provider`. `atlas.provider_endpoint` is set
when the reply names a more specific endpoint, and userinfo in that
endpoint is removed through the last `@` before the host. A value
that contains `@` and has no `//` authority is dropped. A region such
as `us-east-1` stays. All three
are scrubbed and cut to 120 characters. This section states those
rules. The span attribute names are in the `tracing.py` module
docstring, which is not a complete field list.
The per-call
reservation is `atlas.reservation_usd`, a decimal string beside
`atlas.cost_usd`.
Tool results are not exported as bodies. A tool argument that does not
fit in 240 characters is replaced with a short JSON object, so
`tool.parameters` stays valid JSON. Every string attribute passes
through the review's redactor before it is set, and the tool span's
name is the fixed name `tool`. The SDK does not record the raw
exception. The scrubbed message is the span status, including when the
review or lens span itself raises. One exporter serves the process. The SDK's own exit hook is off. At
process exit the controller flushes that exporter and waits at most one
second, so a review that exits immediately still exports its spans and
a dead collector does not hold the process open. A lens does
not shut it down, and a provider a review still holds is not replaced
out from under it. A caller that has already opened the review span gets
a lens span under it. A lens that runs on a worker thread has to be
started with `submit_with_review_context`, which copies that span into
the worker. `agentic-review` opens the review span itself, around the
picker and every lens, and sets `atlas.review_event` to the event the
draft ends with, after the not-run lenses count. A lens that is never
started (a halted review, or a queued lens past the deadline) still gets a
lens span with `atlas.lens.state` `NOT RUN` and `atlas.lens.reason`.
The draft status line carries `trace_id` when a span was
recorded. `validate_export` runs at startup, so a bad endpoint or header
stops the process before a review. The JSONL `--events` file is unchanged.

`OTEL_EXPORTER_OTLP_HEADERS` and `OTEL_EXPORTER_OTLP_TRACES_HEADERS` are
removed from the process environment while the exporter is built, so
they are not merged into the request, and then restored. `cli.main`
builds that exporter on the main thread, before the command handler
runs. The only header sent is
`ATLAS_OTEL_HEADERS`.

Spans do not change the parity gate. A review with export configured
and a review with export off reach the same outcome; the status line may add `trace_id`.

## Live mode

```sh
python -m atlas_reviewer agentic-review --event atlas_reviewer/fixtures/sample-pr/event.json --dry-run
python -m atlas_reviewer review --event event.json   # GitHub App + Sprites, offline provider
python -m atlas_reviewer review --event event.json \
  --provider openrouter --allow-live-inference       # plus one capped OpenRouter review
python -m atlas_reviewer probe-runner                # Sprites protocol, tool and stdin check, nothing from a PR
python -m atlas_reviewer probe-runner --sequence review --tarball checkout.tar.gz
                                                     # the review's exact exec sequence on a real checkout, no model
python -m atlas_reviewer sweep --force-live          # destroy runners a crashed review left behind
python -m atlas_reviewer sweep --event event.json --force-live
                                                     # also destroy that event's runner, by name
python -m atlas_reviewer sweep --runner NAME --force-live
                                                     # also destroy this runner, by name
```

A live review names its runner Sprite after the event:
`cqa-rev-pr<PR>-<first 12 of the head SHA>-<8 hex of a SHA-256 over repo,
PR, and SHA>`. It prints `atlas_reviewer: runner Sprite for this review:
<name>` to stderr before creating it, and exits 3 without creating
anything when a Sprite already has that name. That check is only a hint:
the create is the claim. When two reviews of one commit race, Sprites
refuses the second create and that review exits 3. A review deletes only
a runner its own create made, so the loser never touches the winner's
Sprite. A create whose outcome is unknown (a timeout or a 5xx) is not
deleted either; its name stays in the ledger and the review reports
cleanup not verified. That name may now be the runner of a review of the
same commit on another machine. `sweep --event` and `sweep --runner`
record those names in this state directory's ledger and then sweep it, so
a runner recorded only on another machine's disk can still be destroyed
by name. Any sweep that would delete something, by name or from a
non-empty ledger, refuses to run (exit 2) without `--force-live`, which
says you checked that no review that could be using the runner is still
running. `--runner`
accepts only `cqa-rev-` names of lowercase letters, digits, and hyphens.
`--dry-run` keeps the time-stamped random names.

`probe-runner --sequence review` runs the same `run_disposable` exec order a
review uses: tool check, tarball upload, unpack, then a trivial tool
(`--tools trivial`, the default, counts the unpacked files) or the review's
default tools (`--tools review`). It calls no model and gathers no CI
evidence. The source is a local `.tar.gz` (`--tarball`, for example from
`git archive --format=tar.gz --prefix=src/ HEAD`) or the head-SHA tarball
fetched with the GitHub App (`--event`, needing the three `ATLAS_GITHUB_*`
variables). On Fly the image has no checkout tarball, so
`--sequence review` there uses `--event` and `ATLAS_EVENT_JSON` instead
of `--tarball`. Those commands are in
[`deploy-fly.md`](deploy-fly.md). Both sources are held to the review's caps: 9 MiB compressed, and
256 MiB or 50,000 members unpacked, counted from the tar headers across
every gzip member before any runner exists (`source_archive.py`); an
archive past them, or not a gzip tar, is refused. The header walk fails
closed: it reads the blocks itself and accepts only what `git archive`
writes, in a form GNU tar reads the same way. That means plain-octal
header numbers; member types `git archive` writes; a pax global `comment`
and per-member `path`, `linkpath` and `mtime`, each at most once; metadata
entries of at most 1 MiB and 16 MiB in all; paths of plain segments, within
4,096 bytes, 64 deep and 1,000,000 segments in all, each member's parent
directory listed as an entry before it (so unpacking creates no directory
the walk did not count); and zero padding after the end block. Every other
header is refused (D39).

`probe-runner` exits 3 when the runner did not complete or, for the
protocol probe, the stdin round-trip did not come back `ok` or the
outbound-connection check got out (`OPEN`), so a script cannot take an
unusable runner for a ready one. That check tries a bounded TCP connect to
an IP literal and to a hostname; `no outbound connection` means both were
tried and failed, and `UNVERIFIED` that it could not tell (no system
Python, or an attempt that never started, such as a missing `timeout`).
Only a live probe shows whether a real Sprite blocks egress. Its report is
redacted with the controller's own credential values, every installation
token minted during the probe, and the usual secret patterns before it is
printed. The raw exec response sample is scrubbed the same way where the
probe captures it.

`sweep` takes the same single-review lock as `review` and `probe-runner`.
The ledger lists a live review's runner too, so sweeping during a review
would destroy that runner mid-run. While a review holds the lock, `sweep`
exits with the usage error (2) and destroys nothing. The lock is per state
directory, so it does not stop `sweep --runner` on another machine from
destroying a runner a review there is still using, nor a ledger sweep
here from deleting a name another machine's review now owns; that is why
a sweep with anything to delete needs `--force-live`. `sweep` prints one
line per runner, `already absent, nothing deleted (verified absent)` for
one that was gone before the sweep, and exits 3 when any runner's cleanup
could not be verified (its name stays in the ledger for another sweep).

`python -m atlas_reviewer` turns the first SIGINT or SIGTERM into
`KeyboardInterrupt`, even when it was started with SIGINT ignored, so the
`finally` that destroys the runner still runs when the process is stopped.
It ignores later SIGINTs and SIGTERMs, so a second stop cannot cut that
cleanup short. A stop during the final delete waits until the delete is
done. If that delete is already unwinding another error, the error stays
the result. Otherwise the stop ends the review right then, before any
further GitHub or model work. The cleanup budget bounds the delete, and
SIGKILL still ends the process.

`--state-dir DIR` is a top-level option, so it goes before the subcommand.
Every file the controller creates (the `--out` draft, telemetry and an
`--events` file's lock, the runner ledger and the review lock) is created
mode 0600, and every directory it creates 0700, missing parents included.
A file or directory that already exists keeps its mode.
Live inference is off by default. `--provider openrouter` is refused
without `--allow-live-inference`, and refused with `--dry-run`.

Environment variables (names only; never commit values):

| Variable | Held by | Purpose |
| --- | --- | --- |
| `ATLAS_GITHUB_APP_ID` | controller → token minter | GitHub App ID (App 5648875), numeric |
| `ATLAS_GITHUB_APP_PRIVATE_KEY` | controller → token minter | The App's PEM private key. Literal `\n` sequences are accepted for single-line env stores |
| `ATLAS_GITHUB_INSTALLATION_ID` | controller → token minter | Installation ID of the App on the target repo's account, numeric |
| `ATLAS_SPRITES_TOKEN` | controller → Sprites adapter | Sprites org token for the outside control-plane API |
| `ATLAS_OPENROUTER_API_KEY` | controller → OpenRouter adapter | Read only with `--provider openrouter --allow-live-inference`. The key must carry a hard credit limit of at most the configured ceiling |
| `ATLAS_REVIEWER_STATE_DIR` | controller | Runner ledger and single-review lock (default `.atlas-reviewer-state/`, gitignored) |
| `ATLAS_RESERVATION_USD` | agentic lens entry | Dollar reservation for one agentic review (default 5). On `agentic-review`, unset derives it from the per-lens budget and the planned lens count, clamped to the ceiling (D68); a set value wins |
| `ATLAS_MAX_CALLS` | agentic lens entry | Model calls across every lens attempt (default 50). On `agentic-review`, unset derives it from the per-lens budget and the planned lens count plus the picker's calls (D68); a set value wins |
| `ATLAS_MAX_TURNS` | agentic lens entry | Turns of one lens attempt (default 50) |
| `ATLAS_LENS_WALL_S` | agentic lens entry | Seconds for one lens attempt (default 1200) |
| `ATLAS_REVIEW_WALL_S` | agentic lens entry | Seconds for the whole review (default 3600). On `agentic-review`, unset raises it to the lens wall times the planned waves when that is higher (D68); a set value wins |
| `ATLAS_PER_LENS_CALLS` | `agentic-review` | Per-lens model-call budget the review-wide call cap derives from (D68; default 50) |
| `ATLAS_PER_LENS_USD` | `agentic-review` | Per-lens dollar budget the review-wide reservation derives from (D68; default 5) |
| `ATLAS_REVIEW_CEILING_USD` | `agentic-review` | The absolute per-review dollar ceiling the derived reservation clamps to (D68; default 10). The reviewed repo's merge-base `REVIEW.md` may override it with a `review_ceiling_usd:` line |
| `ATLAS_REPO_CEILING_MAX_USD` | `agentic-review` | The operator max per review (config slice S9, D81; default 25): the most a repo's own `review_ceiling_usd:` line may raise the ceiling to. A raise past it is clamped to this value and the clamp is named in the draft's ceiling note. The operator's own configured ceiling and the default are never clamped by it |
| `ATLAS_NO_PROGRESS_TURNS` | agentic lens entry | Consecutive turns that bring a lens nothing new -- no successful tool call the attempt has not made before, no new verified finding -- before one finalize nudge is injected, on the paged and the shared-prefix path alike (D58, D66; default 6) |
| `ATLAS_DUPLICATE_CALLS` | agentic lens entry | Identical tool calls that inject the same finalize nudge at any coverage (D58; default 3) |
| `ATLAS_QUOTE_REPAIRS` | agentic lens entry | Quote-repair turns a failed quote earns per lens attempt, 0 to 3 (D64; default 1) |
| `ATLAS_QUOTE_TOLERANCE` | agentic lens entry | Lines either side of a citation's first line that the quote checker searches, 0 to 8 (D64; default 3) |
| `ATLAS_MAX_INPUT_TOKENS` | agentic lens entry | Per-call input cap. Unset uses the model's context minus the output reserve |
| `ATLAS_MAX_OUTPUT_TOKENS` | agentic lens entry | Per-call output cap. Unset uses a quarter of the endpoint context when the completion limit is larger than that quarter, and the completion limit otherwise. It may be set higher, up to that completion limit |
| `ATLAS_REASONING_MAX_TOKENS` | agentic lens entry | Reasoning hint sent on the request when the selected endpoints list `reasoning`. Unset is half the output cap, so the reply has the other half. It is not a price |
| `ATLAS_POOL_SIZE` | `agentic-review` | Lenses at once, 1 to 16. Unset uses 4 on that command. `review_lens` still defaults to 1 |
| `ATLAS_CREATE_RETRIES` | agentic lens entry | Times a 429'd Sprite create waits and retries before giving up, 0 to 24 (default 6; waits double from 2s, capped at 60s, and a Retry-After is honored up to 120s a wait) |
| `ATLAS_CREATE_CONCURRENCY` | agentic lens entry | Sprite creates one review may have in flight at once, 1 to 64 (default 4) |
| `ATLAS_DIFF_PREFIX_SHARE` | `agentic-review` | Largest share of the model's resolved per-call input cap the shared diff prefix may take (D65). Unset is 0.5; 0 turns the shared prefix off, so every review pages through `diff_file` as before it existed. `--diff-prefix-share` wins |
| `ATLAS_MODEL` | OpenRouter adapter | Model id. Unset is `anthropic/claude-sonnet-5.5`. `--model` wins. A response from any other model is rejected |
| `ATLAS_PROVIDERS` | OpenRouter adapter | Comma-separated `provider.only` slugs. Unset is one endpoint, `google-vertex/global`, for an Anthropic-family model (`anthropic/...`), and `amazon-bedrock,google-vertex/europe,google-vertex/global,google-vertex/us` for any other model (#695, D63). One slug pins that provider. `--providers` wins |
| `ATLAS_ALLOW_SAFETY_RETENTION` | OpenRouter adapter | `true` allows Safety Retention endpoints. Unset or `false` keeps the request on pure zero-data-retention endpoints. `--allow-safety-retention` also turns it on |
| `ATLAS_REQUIRE_ZDR` | OpenRouter adapter | Unset or `true` sends `zdr: true` and selects only the ZDR list. `false` or `--no-require-zdr` drops that requirement and still refuses a tag the ZDR list marks Safety Retention unless the opt-in is on. Caching does not depend on it. `data_collection: deny` stays on either way. The flag wins over the variable |
| `ATLAS_CALL_RETRIES` | agentic lens entry | Times a failed model call is sent again within a turn, 0 to 3. Unset is 1 |
| `ATLAS_TEST_TIMEOUT_S` | `agentic-review` | One test process's wall clock for `run_tests` and `mutate` (D80's 2026-11-26 environment update), 30 to 600 seconds. Unset is 180 — the repo's own full suite takes about 74 seconds on the box, so a whole-suite baseline under `mutate` (two processes, one call) cannot fit under the old 60-second cap; the review's wall clocks still bound everything above this. A value that is not an integer in those bounds fails the lens's run with the variable named |
| `ATLAS_MIN_OUTPUT_TOKENS` | agentic lens entry | Smallest output cap a call is fitted to when the reservation cannot cover its full cap. Unset is 16,000 |
| `ATLAS_KEY_CEILING_USD` | `review` and `agentic-review` | The most the OpenRouter key's own credit limit may be. Unset is $5. A higher key is refused before inference, and the refusal names this variable |
| `ATLAS_HEAD_CHANGE_POLICY` | webhook service | The keep-or-cancel policy for a push that lands mid-review (#702, D79): `keep` (the default) decides per push and queues a kept head as the settled review's follow-up; `cancel` restores the blanket supersede. An unknown value refuses to start |
| `ATLAS_HEAD_CHANGE_CANCEL_FRACTION` | webhook service | The "early" threshold the cancel branch compares the lenses-settled and budget-spent fractions against, 0.0 to 1.0 (default 0.5). A code push under it on both measures cancels the running review |
| `ATLAS_REPO_DAILY_BUDGET_USD` | webhook service | The per-repo daily budget (config slice S9, D81; default $100 per repo per UTC day). Once a repo's day has spent this much committed model spend, further reviews are refused at admission and re-checked at preflight, and the record says plainly "skipped: daily budget reached" -- never a clean-looking review. The total is one append-only `<state dir>/spend/<owner>-<repo>-<UTC date>.jsonl` file per repo per day; see the spend-bounds section below |
| `ATLAS_INSTALLATION_STORE_KEY` | webhook service | The Fernet key the installation store's records are encrypted at rest under (config slice S10, part A; **not yet set in any deployment**). Unset with no records on disk is the unconfigured store: no tenant path, no caps. Unset with records on disk, or set to a value that is not a valid Fernet key, is the broken store: every read raises, reviews refuse, and the cap check refuses with "skipped: installation store unavailable". The key is a service secret and never reaches a child, a Sprite, or the log |
| `ATLAS_INSTALLATION_RETENTION_DAYS` | webhook service | The retention sweep's window in days (config slice S10, part A; default 30; **not yet set in any deployment**). At boot, stored installation state unrefreshed past the window is deleted, catching a missed `installation.deleted` webhook |
| `ATLAS_TENANT_MODEL_KEY` | tenant review child | The installation's own model API key (config slice S10, part A; **not yet set in any deployment**). The one credential variable the child env allowlist gains; it travels only on a tenant-path run, is scrubbed like the other secrets, and never reaches a Sprite |
| `ATLAS_TENANT_BASE_URL` | tenant review child | The installation's own endpoint base URL (config slice S10, part A; **not yet set in any deployment**). HTTPS only; every connection's resolved addresses are checked against the egress blocklist and pinned (see the installation-store section) |
| `ATLAS_TENANT_MODEL` | tenant review child | The model the installation chose, within what its own endpoint serves (config slice S10, part A; **not yet set in any deployment**). Priced from the operator's price table; a model with no entry there is refused, a zero-priced model is allowed |

The credential and state variables above the limit rows never reach a
Sprite, a prompt, or the draft. Each one goes only to the adapter that
uses it. The nineteen `ATLAS_*` limit variables are not credentials.
`limits_for_lens` reads them. The one-shot `review` command does not
accept the matching flags and does not read the variables. `ATLAS_MODEL`,
`ATLAS_PROVIDERS`, `ATLAS_ALLOW_SAFETY_RETENTION`, and
`ATLAS_REQUIRE_ZDR` are not credentials either. The live OpenRouter
path reads them; a dry run does not. The webhook review child receives
those route variables, `ATLAS_KEY_CEILING_USD`,
`ATLAS_REPO_CEILING_MAX_USD` (the per-tenant clamp, config slice S9), and
the agentic limit
variables (the one-shot command ignores those). On a tenant-path run it
instead receives the tenant trio -- `ATLAS_TENANT_MODEL_KEY`,
`ATLAS_TENANT_BASE_URL`, `ATLAS_TENANT_MODEL` -- and **not** the
operator's key. It does not receive
the webhook secret or the App private key. The redactor also scrubs the exact
value of the App key, the Sprites token, the OpenRouter key, the tenant
model key, and every
installation token minted during the review, on top of pattern-based
redaction. That covers the draft, the telemetry, the probe report and the
error message on stderr. The tenant key's parent-side scrub does not come
from the environment -- the key is not in it; it comes from the
run-resolved credentials: the run registers the key with a shared holder
before the child starts, and both the service log's redactor and the
poster's redactor read that holder on every scrub, so a child stderr tail
that reaches a telemetry record (or a report field that reaches a
comment) loses the key even when the child's own scrubbing was incomplete
(r1 review of #776, Major 1). Registered keys are never cleared: a key
stays a value the log never prints after the run that used it.

**GitHub App tokens.** `github_auth.py` signs an RS256 JWT with the App key
(PyJWT with `cryptography`, the only non-stdlib runtime dependency, used by
the controller alone). It exchanges the JWT for an installation token that
asks for `contents`, `checks`, `actions`, and `pull_requests` read, plus
`issues` read only with `--include-issues`, scoped to the event's single
repository. On the operator CLI path, a response that grants any
non-read permission is refused. The webhook poster asks for
`pull_requests` write and refuses every other write permission.
The token is cached until five minutes before its `expires_at`.

**CI evidence ingestion** (`gather.py`, `archive.py`). Every GitHub list
(check runs, workflow runs, the PR's commits, jobs, artifacts) follows
`Link: rel="next"` up to 10 pages. Workflow runs listed by branch name are
kept only at the PR's own commits (GitHub lists at most 250), so a
same-named branch elsewhere adds nothing; head-SHA runs are listed by SHA
too. Check runs are listed at the head SHA and at up to 20 other commits
of the PR, newest first (D38), each item keeping the SHA GitHub reported, so
a failure at an earlier commit that was never re-run stays visible as
stale. A list cut off there, a per-review count cap (5 head-SHA runs
whose jobs are listed, 20 other commits whose runs' jobs are listed --
the bound counts commits, never runs, because one commit usually carries
several runs -- 10 job logs, 5 artifacts), an oversized download (5 MiB per log, 10 MiB per
artifact ZIP), or a rejected or partly skipped archive each appear in the
draft's **Omissions and limits hit** table. Whatever they left unread is
UNKNOWN. Job logs are fetched for every ingested run's jobs, whatever
commit they ran at, failing jobs first within the count cap -- one
shared budget spent once against the whole branch, so an earlier
run's passing jobs cannot crowd a later run's failing job out of it
(the lifted-context decision, 2026-11-26); artifact ZIPs are fetched only for
runs at the head SHA, and only the head SHA's runs have their artifacts
listed. Artifact ZIPs are read in memory with stdlib `zipfile` and never
extracted to disk. An entry is skipped if it has an unsafe path
(absolute, drive, `..`), is a symlink or special file, is encrypted, is
compressed with anything but STORED or DEFLATED, is not on the text-type
allowlist, is binary, or exceeds the size or ratio
caps. The archive as a whole is rejected if it has more than 200 entries.

**OpenRouter limits** (`openrouter.py`, `budget.py`, `pricing.py`). The
model defaults to `anthropic/claude-sonnet-5.5` (`ATLAS_MODEL` or
`--model`). There is no fallback model, no plugins and no web search. A
response is accepted only from the configured id or a dated revision of
it (`<id>-YYYYMMDD`). Provider routing stays pinned: `allow_fallbacks`
false, `require_parameters` true, and `data_collection` deny. Those
three are not configurable. `zdr` is true unless `ATLAS_REQUIRE_ZDR` is
false or `--no-require-zdr` is passed. `max_price` is the highest prompt
and completion price on the selected endpoint rows. `provider.only`
defaults by model: an Anthropic-family route (`anthropic/...`) pins the
single endpoint `google-vertex/global`, so one conversation's
consecutive turns share that endpoint's prompt cache instead of
spreading across every eligible Bedrock and Vertex endpoint (#695, D63
— of the three tags with a `safety_retention: false` ZDR row for both
default Sonnet and Haiku on the list fetched 2026-11-15, it is the
cheapest, at $0.10 cache read and $2.50 cache write per million against
$0.11/$2.75 on `google-vertex/europe` and `amazon-bedrock/eu-west-1`,
and the only region-unbound one; the bare `amazon-bedrock` tag prices
the same for Sonnet but has no Haiku row and expands to regional
endpoints). The old four-slug default refused Haiku outright against
that list, so the single-endpoint default is also what makes a
default-config Haiku route runnable. Any other model keeps the slugs
the 2026-11-07 read of the public provider list named:
`amazon-bedrock`, `google-vertex/global`, `google-vertex/us`, and
`google-vertex/europe`. `ATLAS_PROVIDERS` or `--providers` replaces
either default, and one slug is a valid pin. Before a completion the adapter
reads `GET /api/v1/endpoints/zdr` without the key when ZDR is required,
and both that list and `GET /api/v1/models/{author}/{slug}/endpoints`
when it is not. The full endpoint list has no `safety_retention`
field, so the ZDR list is what marks a tag. A tag the list marks
`safety_retention: true` is refused unless the opt-in is on, in either
mode. An unreadable ZDR list refuses the call. A child that is Safety
Retention refuses the parent, because `provider.only` of the parent
can expand to it. A slug with no exact row is refused, and the error
names child tags when the list has them: `deepinfra` is not a tag,
`deepinfra/fp8` is. Safety Retention (for example Gemini on Vertex)
needs `ATLAS_ALLOW_SAFETY_RETENTION=true` or `--allow-safety-retention`.
`reasoning` is sent only when every eligible row lists it in
`supported_parameters`. `cache_control` is sent on every Anthropic-family
route (`anthropic/...`) even when no row lists it. OpenRouter does not
advertise the parameter, and a ZDR Bedrock endpoint still honors it.
Other models keep the intersection. Turning ZDR off does not change
that. `max_tokens` is always the configured output
cap. `require_parameters` stays true. On the agentic path the unset
output cap is a quarter of the selected endpoints' context when their
completion limit is larger than that quarter, and the completion limit
otherwise. `ATLAS_MAX_OUTPUT_TOKENS` or `--max-output-tokens` overrides
it and may be higher than that quarter, up to the completion limit.
The one-shot path keeps its `CallLimits` cap. `max_price` and the
reservation use the highest prompt and completion rates on the selected
rows, including each row's `pricing.overrides`, and the smallest
context and completion limit. A row's `max_prompt_tokens`, when set,
caps the input as well. The catalog headline is not those numbers. The
provider reads the catalog and the endpoint list once and reuses them
for later completions in that review. The usage line and the completion
span name the selected tags, the minimum context, the minimum
completion limit, and the `max_price` rates.
The usage line and the completion span record whether ZDR was required
and whether `cache_control` was sent. Before any
inference, `preflight()` reads
`GET /api/v1/key` and refuses unless the key has a hard limit of at most
$5 with credit left. A key whose `include_byok_in_limit` is not true is
accepted, and that run is in no-BYOK mode: a model response is used only
when `usage.is_byok` is false. Any other value, including a missing
field, or an HTTP 200 whose body cannot be parsed, stops the review
as a boundary error (exit 3) before another model call, and no draft
is written. When the flag is true, a BYOK
response is accepted, as before. The first completion reads the model's
public catalog entry and fails closed if a price or limit is missing,
unparseable, or a required prompt or completion rate is zero. A
per-million price that is not a finite number is refused the same way.
Later completions in that review reuse the snapshot. It then
checks the input bound (200k tokens), max output (24k) and reasoning
budget (12k), and reserves the call's worst case at the highest listed
price tier. A reservation is refused if it would be the fourth call in the
review (retries included), or if it could push the review past $3.00 or
past the key's remaining credit. The draft's **Model usage** section
records each call's reservation and its actual cost and tokens; a cost
above the call's own reservation is flagged on that record's usage line
(D82's tripwire, round-1 review of #757). The call cap
(`--max-model-calls`, at most 3) is shared by every diff part and every
retry: a retry on part 1 can leave part 3 refused, and that part's files are
then listed as unreviewed.

The key's own usage counter (`GET /api/v1/key`) is read once, by the
preflight, and never after inference. It can lag a completion by about 90
seconds (an owner-reported pilot observation; not checked against
OpenRouter's documentation), so a $0 readback right after a call is expected
and is not a mismatch. Cost is taken from each response's `usage`, never
from that counter. When `usage.is_byok` is boolean false, the settled
amount is `usage.cost` and a reported `cost_details.upstream_inference_cost`
is not added, with two over-counts: an upstream amount larger than
`usage.cost` settles at that amount, and an upstream value that is present,
not null and unreadable keeps the full reservation. A null or absent
upstream settles `usage.cost`. With no usable `usage.cost` the call is
priced from the highest endpoint rates and upstream is still not added.
The settlement line records the raw upstream
value on such a call, cut to 200 characters. This is the controller's
policy, not a confirmed OpenRouter fact. OpenRouter's usage-accounting page
calls `cost` the total charged to the account and `upstream_inference_cost`
the upstream provider's charge
(https://openrouter.ai/docs/cookbook/administration/usage-accounting,
fetched 2026-11-11); that page does not say whether a non-BYOK `cost`
already includes the upstream amount (verify). The SDK says that on a
BYOK request `cost` is the OpenRouter fee only
(https://openrouter.ai/docs/client-sdks/typescript/models/decisionsresponseusage,
fetched 2026-11-11), so `is_byok: true` adds a reported upstream cost,
and a missing upstream cost keeps the reservation. A missing or
non-boolean `is_byok` adds a reported upstream cost too, including a
call refused in no-BYOK mode. A present, non-null, unreadable upstream
value keeps the reservation on any response, including an explicitly
non-BYOK one. A null upstream keeps the reservation unless `is_byok`
is exactly false.

## What the draft contains

In order: the status comment, the review event (or the REVIEW INCOMPLETE
warning), the title and header table, the evidence summary, **Controller
notes**, **Possible committed secrets**, **Review lenses**, the
independent-checks table, every evidence item at the head SHA, evidence at
other commits of the PR (stale, labelled by commit, newest first), UNKNOWN
items, omissions, model usage, **Lifecycle telemetry**, and the model's
narrative, one subsection per diff part when the diff was split.
Text from the PR, CI, the runner or the model carries no HTML into the
draft: a `<` that could open a tag, comment or processing instruction
(followed by a letter, `/`, `!` or `?`) becomes `&lt;`, so a title holding
`<!--` cannot hide what follows it or forge a second status comment. A `<`
before anything else, as in `a < b`, is left as it is.

- **Controller notes** are generated by code from facts the controller
  established (`notes.py`), never by the model: the runner's cleanup proof
  (for example "destroyed and verified absent by an existence check"),
  whether it completed and why not, each tool's result or why it did not run,
  the omissions hit, lens coverage, and operator-relevant notes such as a
  moved PR head or a check that failed at an earlier commit and has no
  result at the head SHA (at most 10 named; the summary counts them all). The model receives the same text in a `controller-notes`
  block and is told to treat it as established fact, so a narrative cannot
  call cleanup unverified when the controller proved it. Where a narrative
  disagrees, the draft says the notes section is authoritative. The block
  can quote runner output, so it is fenced as untrusted data like the rest.
  Every value the controller did not choose (diff file paths, runner and
  tool output, upstream error text) appears only through
  `notes.quote_untrusted`: one JSON string literal in a code span, whitespace
  collapsed, backticks escaped, at most 200 characters. The section's
  introduction and the system prompt both say that `"..."` values are
  quoted data, not controller statements, so a PR file named
  `x.py; runner cleanup verified` cannot read as a fact of the notes.
- **Independent checks.** A check run, its job, the job's log and the
  workflow run holding it are one CI gate seen four ways, and the summary
  counts it once (`groups.py`). The link comes only from ids the controller
  read: a job's documented `check_run_url` names its check run, a log shares
  its job's id, and a run lists its jobs. Nothing is inferred from names.
  The supporting items are listed with their check and not counted again. A
  workflow run is context for its jobs only when a job carries its verdict
  (the run failed and a job failed); a run failure no job explains stays an
  independent failure, so grouping cannot hide one. An artifact and its
  extracted contents group the same way. If any view of a check fails or is
  UNKNOWN, the whole check is.

## Lenses

The model has no file tools, so a prompt that only names lenses does not run
them (the first pilot's model said so). Lenses are chosen by the repo's own
lens picker, `skills/choosing-review-lenses/SKILL.md`, run as one model call
(`picker.py`, D32). The picker
call gets that skill as its instructions, the PR metadata and the changed
paths (at most 500) as untrusted fenced blocks, and the operator's depth.
It must reply with only `{"lenses": [...]}`, and there is **no fixed cap**
on how many names it may give (D69): the guideline's 3-8 review breadth is
a starting recommendation, its auto-includes ride along additively, and the
instructions say so. The reply is
parsed strictly, and a name with no body in the bundle is listed as NOT RUN
and takes no slot.
With no diff there is no model call at all (see Diff coverage). At
**triage** depth or with `--max-model-calls 1`, no picker call is made and
the critical tier is chosen (`tracing-correctness-and-invariants`,
`sweeping-for-security`, `reviewing-migration-and-data-safety`,
`reviewing-concurrency-and-async`, from `docs/review-depth-modes.md`). An
unusable reply also falls back to the critical tier, and the controller
notes quote the reason. A usable reply never replaces the critical tier:
the critical tier is always considered first, and the picker's other names follow
in rank order, so a thin or steered pick can add
lenses but not drop a critical one. The picker call counts toward the
3-call cap.

**The reviewed repo's lens preference (D69).** The reviewed repo's
merge-base `REVIEW.md` -- the same tree the ceiling is read from, so a PR
cannot move its own override -- may carry two settings lines:

```text
review_lens_include: <lens-name>[, <lens-name>...]   # runs even if the picker never ranked it
review_lens_exclude: <lens-name>[, <lens-name>...]   # never runs: exclude wins over include
```

The controller applies the override to the picker's picks itself -- an
exclude drops a ranked pick and also declines the controller-added
process-hygiene lens (D58), which is neither floor-tier nor a cap, so
the repo may turn it off; an include runs even when the picker fell back
or made no call; a name in both lists does not run, because **exclude
wins on every path**; and no lens is ever planned twice -- a repeated
choice is one load and a named NOT RUN line. The manifest's **floor
tier** is the controller's own floor, not the guideline's, so neither
line touches it: all five `tier: floor` lenses are protected from the
exclude (D69's 5:13 PM CT update) -- the four critical-tier lenses
(`tracing-correctness-and-invariants`,
`sweeping-for-security`, `reviewing-migration-and-data-safety`,
`reviewing-concurrency-and-async`) and `hunting-silent-failures` --
so a repo preference cannot silently suppress a floor lens; triage is
never widened. A line that is present but not a comma-separated
list of lens names, or a key that appears twice, is ignored fail-open
with a note in the draft, exactly like an unusable ceiling line; a name
that matches no bundle lens is not silently dropped -- its include shows
up as a NOT RUN line. Any other `review_`-namespaced line in the file --
a key the build's reads (this parse, the admission read, and the
service's post-config read of the repo's severity floor and post
verbosity, S3) do not carry -- is also ignored fail-open and named: the
note says the key,
that this build does not support it, and that the default stands, and
never quotes the rejected value (S1); the scan knows the
admission-class keys by name (`review_base_include:`,
`review_base_exclude:`, `review_skip_events:` -- honored by the service
from the default branch), so a repo that narrows its admission draws no
false note, and it skips fenced code blocks, so a policy file's
documented example of a future key is not read as an attempt to
configure it. The
override is recorded in the Lens selection
note whenever it is present, "nothing needed changing" when the picks
already satisfy it, so an operator can tell applied-and-satisfied from
ignored. `agentic-review` reads these lines; the one-shot `review`
command fetches no merge-base tree and so runs on the guideline alone.

**The reviewed repo's path ranking (config slice S5, D81 Q6).** The same
merge-base `REVIEW.md` may also re-rank the diff's files:

```text
review_path_include: <pattern>[, <pattern>...]   # matching paths are read first
review_path_exclude: <pattern>[, <pattern>...]   # matching paths are read last
review_generated_files: deprioritize             # or `normal` (the default)
```

Ordering only, never exclusion (D81 Q6; whether anything may be excluded
from review at all is Q25's undecided question, untouched): a pattern
never drops a file. `agentic-review` re-orders the changed-file listing
every lens's first turn presents -- include-matched paths first, then
the rest, then the paths the exclude patterns and the generated-file
setting deprioritize, risk order within each group -- and every changed
file is still listed, still held to every lens, and still counts for
coverage exactly as before. The ranking can still cost effective
coverage, and that cost is stated the way `review_skip_events`' is: on
the paged path a lens chooses its own reading order and the ranked
listing nudges it, so under a lens budget that cannot read everything
the deprioritized files are the first candidates to be left unread --
which surfaces as the loud, non-approvable incomplete-coverage state
(D36), never as a silent drop. A repo deprioritizing its riskiest paths
should expect more incomplete reviews, not quieter ones. The
generated-file heuristic is path-shaped
only (build and tool-output directories, vendored and dependency trees,
lockfiles, and common generated-code suffixes such as `*.min.js`,
`*.map`, `*.pb.go`, `*_pb2.py`, `*.generated.*`, `*.snap`); a repo's own
include and exclude patterns override it (an include match wins over the
heuristic, an exclude match wins over an include). Patterns are
glob-lite: `*` and `?` over letters, digits, `/`, `_`, `.`, `-` and
space, matched case-insensitively like the risk tiers, with `*` crossing
`/` (fnmatch's semantics, so `src/**` and `src/*` name the same set);
bracket classes are outside the grammar, and a pattern with no wildcard
must match the whole path exactly -- write `dist/**`, not `dist/`. A
pattern itself never reaches
a model -- only the order it produces does -- and a note in the draft
records the re-ranking, naming what each setting deprioritized (the
paths quoted as data, at most 25 named and the rest counted) and that no
file was dropped. A line that is present but unusable -- a value outside
its key's grammar, a key repeated, more than 32 patterns, or one longer
than 200 characters -- fails open to the risk order with a note naming
the key, the condition and the default that stands, never the rejected
value; the read rides the same 64 KiB bounded parse (`repo_config.py`)
the ceiling and lens lines use. `agentic-review` reads these lines; the
one-shot `review` command fetches no merge-base tree and so runs on the
risk order alone.

**The controller's shape facts (D69 round-1 F4).** The controller also
detects, from the changed paths and the diff it already holds, the change
shapes the guideline auto-includes a lens for -- a decision record or the
decisions log touched (`reviewing-decision-lifecycle`, plus
`auditing-decision-record-currency` when an existing record is edited
rather than a new one authored), an all-documentation diff
(`auditing-documentation-health`), a git rename record (the
restructuring route's `reviewing-module-design` and
`reviewing-naming-and-readability`) -- and states them in the picker's
instructions and in the draft's Lens selection note, each path quoted as
data. The mandated lens names are **enforced by the controller** now, not
left to the picker's ranking: they ride the selection additively ahead of
the picks (in the one-shot plan, ahead of the picks' share of the
character budget, so the budget cannot starve them), on the fallback
paths too, and the note records which were auto-included. A repo
preference's `exclude` still drops one the way it drops the
controller-added process-hygiene lens, and triage is never widened. The
detection is heuristic (the decisions log by its
known path, decision-record directory names and ADR/RFC basenames, the
diff's `rename from`/`rename to` records, an existing record read off the
diff's context and removed lines); a rename a diff serves as
delete-plus-add is not detected, and no shape is stated for it.

`lenses.py` then reads each chosen lens's `reference/lenses/<lens>/body.md`
and inlines it into the trusted system prompt, in priority order, under a
**60,000-character budget**. A lens is never cut:
a lens runs only if its whole body fits what is left of the budget, and
otherwise it is **NOT RUN** and the next one is tried, so a smaller later
lens can still fit. No lens-count cap remains (D69): the budget, not a
count, decides what a one-shot review inlines, and triage's critical tier
-- the one lens-count cap left -- is its depth mode, not a budget. The
draft's **Review lenses** table and the controller
notes list every lens as run whole or NOT RUN, with its size, its tier or
picker rank, and why it did not run, and the prompt tells the model that
only inlined lenses ran.

With today's bodies the critical tier alone does not fit:
`tracing-correctness-and-invariants` (34,750 characters) and
`sweeping-for-security` (15,000) run whole, leaving 10,250, so
`reviewing-migration-and-data-safety` (22,656) and
`reviewing-concurrency-and-async` (10,984) are NOT RUN. The smallest other
lens, `reviewing-test-quality`, is 11,015 characters, so no picked lens could
fit either. When that is so, `select_lenses` makes no picker call, the
controller notes say why, and the call goes to diff review instead (D35).
Every depth runs the same two lenses today. When the picker does run, PR
text can steer the pick, but only within the closed set of lens names in the
bundle.

No instruction text is ever cut: the controller's instructions, the
`reviewing-a-change` review procedure, the `choosing-review-lenses` picker
and its instructions go into their prompts whole, and only the diff and
untrusted data are cut (marked and reported). `reference/synthesis.md` and
`reference/tool-evidence.md` (the bundle's synthesis and tool-evidence
steps) are not inlined at all: the controller gathers the CI and runner
evidence itself, and this one-shot path has no separate synthesis pass.

## Runner tools

The default tools are `python-compileall` only (`{python} -I -m compileall`,
see "One interpreter, chosen by the controller" below). The
pilot found `python3` but neither `ruff` nor `shellcheck` in the Sprite image.
They are dropped from the defaults because egress is deny-all and a Sprite
is never reused, so nothing can be installed into a runner, and a binary the
image lacks can only ever produce UNKNOWN rows. The repo's own CI already
reports lint, so the CI evidence covers it. To add a tool once the image
ships its binary, append a `ToolSpec(name, binary, version_cmd, run_cmd)` to
`DEFAULT_TOOLS` in `runner.py`; `probe-runner` shows which binaries the
image has, and a configured tool whose binary is missing is still reported
UNKNOWN and never executed. A `python3` tool must write the interpreter as
`{python}` in both commands (`ToolSpec` refuses it otherwise); a non-Python
tool runs its bare binary name under the minimal `PATH=/usr/bin:/bin`.

## Diff coverage

The diff is split into files and reviewed in up to `--max-model-calls` parts
of at most `--diff-chars-per-call` characters each, one model call per part
(`diffs.py`). Files are ordered by risk, not by their order in the diff:
security, auth, secrets and redaction first; then CI workflows, dependency
manifests, lockfiles and build hooks (`.github/workflows/`, composite
actions, `requirements*.txt`, `pyproject.toml`, `package.json`, `*.lock`,
`go.sum`, `Dockerfile`, `Makefile`, `conftest.py`, and the like); then the
runner, sandbox, HTTP and model boundary; other code; other config; tests
and fixtures; docs last. Tier is decided by path patterns. CI, dependency
and build files are matched first, so no directory (`tests/`, `docs/`,
`fixtures/`) demotes them; then tests and docs, so
`tests/test_redact.py` is a test and `docs/security.md` a doc; then
security before config, so `config/secrets.yaml` ranks as security. A
rename or copy is ranked by the riskier of its old and new paths, so moving
`src/auth.py` to `docs/changelog.md` still ranks as security. A file's
path is read from its `+++` line (or `rename to` / `copy to`), not split out
of the `diff --git` header, which is ambiguous for a path holding a space
followed by `b/`. A combined diff (`diff --cc`, as for a merge commit) is
not split out: its text stays with the preceding file, so it is still sent,
under that file's name and tier. Parts are
filled first-fit in that order. A file larger than one part is cut at a line boundary into a part of its own and marked cut. A file
that fits nowhere once every part is used is never sent. If the diff cannot
be fetched at all, no model call is made (a review of an empty diff would
read as a clean one): the omissions table has a `fetch failed` row, the
controller notes say `Diff coverage: NOT REVIEWED`, and the narrative
section says no call was made.

Each call gets the same PR, evidence and controller-notes blocks plus its
own part, and a controller note naming the files in that part and saying
that other parts go to separate calls. When coverage is incomplete, the
**Omissions and limits hit** table has a `pull request diff` row: characters
kept, files sent in full, files cut, and the files never sent, grouped by
risk tier, highest first, each path quoted as data; past 100 the rest are
counted. A part whose call fails or is refused (call cap,
cost cap, token bound) gets its own row listing the files sent but not
reviewed. A part that held only the text before the first file header
lists no file: that row says so, since the preamble is not a changed file. A file the diff's headers name that the selection does not
account for gets a `dropped before the model calls` row and makes coverage
PARTIAL. After the calls, a controller note states whether coverage is
complete or PARTIAL and how many files each outcome covers. Nothing short of
every file sent in full with every call returning a review is called
complete, and neither is coverage that could not be determined: that note
gives the call stats and the reason, with no label.

**Part size (D32).** The default part size is the whole prompt room under
the token check, 176,000 characters: `min(200,000 input, 200,000 assumed
context − 24,000 output)` (`budget.prompt_token_room`). The input bound is
one token per UTF-8 byte plus 64 (`input_token_bound`), never an assumed
characters-per-token ratio, so a part can't under-reserve. A diff part
shares the prompt with the instructions, lens bodies, PR, evidence and notes,
so `diffs.fit_diff` measures every planned prompt and shrinks the part size
from the byte-largest actual part until the largest prompt fits, for up to 8
rounds. Multi-byte text gets proportionally fewer characters. The worst case
of one full-room call at the top fixture tier is 176k × $6/M + 24k ×
$22.5/M, about $1.60, under the $3.00 reservation. Two unsettled worst cases
would not fit, so a second call is reserved only after the first settles to
its actual cost.

When the picker is called, review depth sends at most 2 parts. Triage, and
any depth where the picker call is skipped (review depth with today's
bundle), sends up to 3. A diff over that capacity is PARTIAL: the omissions row says "too large
for one review pass", and the coverage note says the cut and unsent files
are listed there, highest risk first. The second pilot's 412,078-character
diff would still be PARTIAL, with the unseen files being the lowest-risk
tiers.

The model gets the PR conversation as one `pull-request` block, unbounded
by default (the lifted-context decision, 2026-11-26, on #821: the full body
and the full conversation, where D38's 65,536/16,384/4,000-character
working caps stood): title, author, branches, draft flag, labels,
requested reviewers and teams, the body whole, every commit subject (200
each, 8,192 in all), and every review, review comment and conversation
comment whole, each labelled
with its id, author, time and the commit it was made at. With a named
budget, commit subjects and remarks keep the newest that fit and every
older one dropped is an omissions row; unbounded, nothing is dropped or
cut. Every list that failed, hit the page cap or held an entry that did not
parse is an omissions row, with dropped remark ids listed; the fit is
checked after the final redaction pass, and a pending review counts as the
newest remark. Commits are ordered by their parents and committer date, not
by GitHub's listing order. Every one-line PR-written field (title, names,
branches, labels, commit subjects) is a JSON string and every body line is
quoted with a leading `>`, split at every line terminator, so no PR text can
forge another remark's heading. The lens picker still sees only the title and body. Each issue
body is cut at 2,000 characters, and each cut is an omissions row too. Omissions are computed before the evidence block is
built, so the model is told what it did not see. An artifact excerpt cut at
4,000 characters is an omissions row, and its unread rest is UNKNOWN. Check
summaries and log tails (the end of the log is kept by design) are capped
too, but those caps are not listed as omissions.

## Review event and the coverage gate

Each diff part's review ends with a proposed GitHub review event,
`Review event: APPROVE`, `COMMENT` or `REQUEST_CHANGES`, parsed strictly
from the reply's last line (`verdict.py`, D36). The controller decides:
APPROVE needs every part to propose it, and any REQUEST_CHANGES wins.
Nothing is posted, so the event is what the draft recommends.

Partial file coverage blocks approval by default. If any changed file was
not reviewed in full, the event is never APPROVE: it becomes COMMENT,
marked review incomplete. That covers a file never sent for lack of room; a
file in a part whose call failed, was refused by the call or cost cap, or
was used up by a retry; a file answered by the offline provider; a file cut
to fit; and a file dropped before the calls. Coverage that cannot be
determined counts as incomplete: no diff tied to the event SHA, a fetched
body that is empty or names no file, or a diff whose file count differs from
GitHub's `changed_files` (or a pull payload with no such count). The count
compared is the one from the pull read made after the diff fetch, and the
status comment reports that count. If it differs from the read before the
fetch while the head SHA stayed the same, the draft says the count moved
rather than that the diff disagrees. Lens NOT RUN status does not trigger
this rule: it is about files only.

- The draft's first line is a machine-readable HTML comment, for example
  `<!-- atlas-review-status: {"review_event": "COMMENT", "proposed_event":
  "APPROVE", "coverage_complete": false, "changed_files": 40,
  "unreviewed_files": 3} -->`. It holds no paths.
- The body opens with the review event, above the title. When coverage is
  incomplete, it opens with a **REVIEW INCOMPLETE -- not approvable**
  warning instead, giving the count and naming the unreviewed files by
  reason, highest risk first, each quoted as data, with at most 100 listed.
- `review`'s exit code is enough for a pipeline with no human reading the
  draft to gate on (Brandon chose these codes on 2026-11-10, via
  delegation):

  | Exit | Meaning |
  | --- | --- |
  | 0 | file coverage complete, and the review approves or comments |
  | 5 | file coverage complete, and the review requests changes |
  | 4 | file coverage incomplete, whatever the model proposed (D36) |
  | 2 | usage error, or another review holds the lock |
  | 3 | boundary error (GitHub, Sprites or OpenRouter refused or failed) |

  No other exit is a review result. An uncaught crash exits 1, a
  malformed command line exits 2 from `argparse` itself, the same code as
  the usage errors above, and a stop ends the process on SIGINT (130 in a
  shell).

  Exit 0 does not tell APPROVE from COMMENT; the status comment's
  `review_event` and the printed summary, `review event: ...;
  coverage_complete=...; unreviewed_files=N`, do. With `--out` the summary goes to stdout; without it,
  stdout is the draft alone and the summary goes to stderr. A failed
  `--out` write prints the draft to stdout and the error to stderr, and
  keeps the exit code of the review, since the review itself finished.

## Lifecycle telemetry

Every step of a review or probe is one structured event (`telemetry.py`):
GitHub evidence and tarball fetches, model preflight, runner ledger record,
create, deny-all set and read-back, memory limit, every exec, the tool
check, upload, unpack, each tool, each model call (and a skipped lens
picker call, with its reason), each delete attempt, the existence check,
and the cleanup outcome. An exec event carries its
purpose, timeout, bytes sent and received, the stream-id bytes seen
(`frames_seen`, for example `0x01:1`), the exit status, and its duration.
The upload event carries the byte count the runner reports writing.

Events go to one `EventSink`. An event recorded after that sink has closed
stays in memory only. Live commands write JSONL to `--events FILE`,
or by default to
`<state dir>/telemetry/<command>-<UTC time to the microsecond>-<random hex>.jsonl`.
A default path is named only once the single-review lock is held and is
unique to that run, so two runs never share one, and a run refused the lock
creates none. An explicit `--events` file is claimed with a sibling
`FILE.lock` for the whole run, so a second run naming it is refused and
creates no telemetry file. `review` and `probe-runner` print the file's path
when they finish (`review` on stderr when stdout is the draft), and on
stderr after the error message when a usage or boundary error ends a run
whose telemetry had started. That line's event count is the number kept
in memory, so it can include an event recorded after the sink closed,
which was not written. Each line is written and flushed on the descriptor
held for the run, so a killed run keeps its events. The draft and `probe-runner` print the same events as a
summary table. Field values are numbers, booleans or controller-chosen
labels (step labels never include branch names or other PR text). Error
text goes through a redactor holding every credential value from the
environment and every installation token minted during the run, plus the
pattern rules, before any sink sees it.

`Telemetry.span` re-raises a failure with its phase and step, how long the
step ran, and how far into the run it failed, for example
`exec / python-compileall version failed after 30.0s (32.2s into the run):
tool python-compileall stage, python-compileall version: silent -- no output
frame for a command that sends no input, not even the start marker (POST
https://api.sprites.dev/v1/sprites/NAME/exec: no response byte within 30s)`.
The innermost step labels the error, so nothing surfaces as a bare timeout.
Exec events also carry their `stage` and `first_frame_s`, and the tool
check's event records where each binary resolved (`path_python3`, for
example `/usr/bin/python3 -> /usr/bin/python3.13`).

## One exec shape

Every exec goes through one builder on each side. `sprites_api.exec_request`
always sends `cmd` (repeated) and `stdin=true` with an octet-stream body that
is exactly the stdin bytes, possibly none, with an explicit `Content-Length`.
`env`, `dir`, `path` and `tty` are never sent (OpenAPI 0.1.12 has no `tty`
parameter; the HTTP exec is non-TTY only). `runner.exec_argv` wraps every
script the same way, and the environment is set by that wrapper, not by the
API's `env` parameter, whose merge-or-replace behaviour the spec does not
state:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 \
  /bin/sh -c 'echo __ATLAS_START__; head -c N | { SCRIPT
}; echo __ATLAS_EXIT__=$?'     # N bytes of input
/usr/bin/env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 \
  /bin/sh -c 'echo __ATLAS_START__; { SCRIPT
} </dev/null; echo __ATLAS_EXIT__=$?'     # no input
```

`env -i` drops everything the Sprite would otherwise pass, including
`/.sprite/bin` on `PATH` and any `PYENV_*` variable. Only the probe's
labelled diagnostics (below) run in the Sprite's default environment, and an
exec event's `env` field says which one each exec used.

So every command reads exactly the bytes sent and then EOF, and none can wait
on the exec channel's own stdin, whose EOF behaviour is undocumented. The
response is read as it streams (`http.UrllibStreamingTransport`, which uses
`http.client` and so ignores proxy variables). A command that sends no input
must produce a first byte within `--first-frame-seconds`, and the start
marker makes that immediate for any command that actually started. A stall
after some output keeps those bytes, and the error names how many arrived,
the frames seen, and the last output. Until a live run shows whether the HTTP
exec streams output or buffers it until exit, a long tool that prints nothing
could trip the window; its error says "silent", and raising the flag tells
the two apart.

The deadline before the body is cumulative. A socket timeout restarts on
every blocking call, so connect, the send and each header line used to get
a fresh one; a server trickling header bytes could hold an exec open far
past its window. A cutoff timer started with the request now shuts the
socket down at the first-byte deadline (the total without one), and any
error after it fires is reported as that timeout. Each body read then gets
whatever is left of the window.

## One interpreter, chosen by the controller

The image's `python3` on its default `PATH` is a pyenv shim in
`/.sprite/bin`, and pyenv picks the version from a `.python-version` file in
the working directory or any parent (the Sprites Python docs and pyenv's
README, as the owner cited them). Inside the unpacked checkout that file
belongs to the PR. So no tool runs a shim or a bare `python3`:

1. After the tool check and **before the upload** (no PR byte is in the
   Sprite yet), one exec in an empty directory (`/tmp/atlas-neutral`) runs
   each `/.sprite/languages/python/pyenv/versions/*/bin/python3`, then
   `/usr/bin/python3`, with `-I -c` to print its own version.
2. The controller accepts only answers whose path is exactly one of those
   two shapes (a version-directory name must start with a letter or digit,
   so `..` is refused) with a strict `x.y.z` version, and picks the newest
   pyenv version, else the system one (`interpreter.choose_python`). The
   choice is an `interpreter` telemetry event with its path and version.
3. Python tools substitute that path, shell-quoted, for `{python}`, and run
   it with `-I`: isolated mode ignores `PYTHON*` variables and the user site
   and keeps the working directory off `sys.path`, so a PR file such as
   `compileall.py` cannot shadow the stdlib module. If nothing was resolved,
   a Python tool is UNKNOWN (`no trusted Python interpreter was resolved`)
   and never run.

The PR's files cannot choose the interpreter or a tool binary. The
interpreter is chosen before they exist. Every other binary comes from
`PATH=/usr/bin:/bin`, which the unpacked tree in `/work` is not on.

## Read-only tool bridge (offline, D39)

`bridge.py` is the tool surface the agentic lens loop uses (D31, D34, D40).
It has only run against fakes. `run_bridge`
stages the sources on a fresh disposable runner (`runner.run_session`, the
same create, deny-all, verify and destroy lifecycle as a review) and hands
a `Bridge` to the caller.

- **Staging** (`bridge_staging.py`, D31 Option B). git is found at
  `/usr/bin/git` or `/bin/git` before anything is uploaded. The merge-base
  and head tarballs, plus an optional default-branch tarball, are each at
  most 9 MiB compressed and 256 MiB or 50,000 members unpacked
  (`source_archive.py`, counted from the tar headers in memory across every
  gzip member, refusing any header it cannot fully read), and any
  other is refused before a runner exists. The one-shot reviewer's source
  upload and `probe-runner` are checked the same way, so they now also
  refuse a non-gzip archive, a repository of over 50,000 members
  (files, directories and links), which can fit well under 9 MiB, and one
  with a member whose parent directory is not an earlier entry. Each is
  uploaded through the source-upload exec shape, then all are committed in
  one exec into a bare repository with a fixed identity and date. That
  exec has 120 seconds (`runner.UNPACK_BUDGET_S`), and each tree's
  `tar -xzf` inside it is also stopped by the guest's `timeout` at 60
  seconds (`EXTRACT_TIMEOUT_S`). The runner holds the unpack caps again
  by its own tar before writing, counting the directories member paths
  imply, and under `ulimit -f` while writing (`guest_unpack.py`). A tree
  past them is refused, and a failed extraction that the script survives
  has its partial tree removed (a killed script cannot clean up: the
  runner is destroyed). HEAD's
  parent is BASE; DEFAULT is its own root commit. Tools use only the
  synthetic ids staging reports. The merge base comes from GitHub's
  compare endpoint (`fetch_sources`). Staging also probes, in the same
  exec and still before any PR content is unpacked, for an interpreter
  whose pytest runs isolated: each pyenv version and the system python,
  each bounded on its own, accepted only on `interpreter.trusted_path`'s
  shapes or a literal candidate the caller named. The newest pyenv hit
  (else the system one) is `Staged.pytest`; none makes the execution
  tools (D80) answer `unavailable` — a gap, not a crash.
- **Tools** (`bridge_args.py`). There are seven, each with typed arguments:
  `diff_stat`, `diff_file` (path, byte offset), `list_files` (rev,
  prefix), `read_file` (rev, path, at most 400 lines), `grep` (pattern,
  rev, prefix, fixed-string unless `regex`), and the two execution tools
  (D80): `run_tests` (an optional `path` selector — a file, a directory
  or a `file.py::node_id`, empty for the whole suite; and, config slice
  S7, an optional `command` naming one of the run's pre-approved
  allow-list proposals, which takes no selector and runs the proposal's
  own bridge-built argv) and `mutate`
  (`path`, `line`, `operator` — `negate-condition` or `remove-guard` —
  and an optional `tests` selector its two runs share). `rev` is BASE,
  HEAD, a staged DEFAULT, or MUTANT once a `mutate` call has committed
  one. Anything else is rejected before an exec, with a fixed
  code and a controller-written reason that echoes neither the tool name
  nor any value sent. One attempt may spend at most 64 calls and 1 MiB of
  output of its session (#693): the coordinator starts that budget over
  for each attempt, so a retry begins whole, and a refusal names the
  attempt that spent it. When three refusals have accumulated, the
  turn's results go back and one finalize turn asks the model to
  finalize with what it has; the tools stay on the request, because
  tool history next to an empty tools array is a shape the pinned
  Bedrock route is documented to reject, and the spent bridge refuses
  whatever the model still calls; the stop rides on what the attempt
  then delivers, naming the lens, the attempt and the cap. The two
  execution tools (D80) have caps of their own, per attempt: 8
  `run_tests` calls and 8 `mutate` calls (provisional, below the call
  cap, so executions cannot be the whole of an attempt's budget), each
  refused like any other spent budget.
- **Exec.** Each read is a fixed git argv with every value shell-quoted,
  under `env -i`, `timeout` and `ulimit -f`. The `-c` options, environment
  and repository attributes disable config, hooks, pagers, transports,
  diff drivers, filters, pathspec magic and in-tree `.gitattributes`.
  Output returns base64-encoded and is capped at the tool's bound (16 or
  32 KiB; 2,000 entries, 400 lines or 200 matches), cut only between
  whole UTF-8 characters, and the cut and the next diff offset are
  reported; output lost after git succeeded is an error, not an empty
  result. A timeout is a coverage gap, never a finding. `grep` and
  `list_files` read git's NUL-separated output, so a newline in a file
  name cannot move a match to another file, and every name `list_files`
  shows plainly reads back through `read_file` (the rest are marked).
  `diff_file` shows a renamed file as a rename from either path.
- **Execution (D80, corrected 2026-11-18 rounds 1-2; amended for the
  between-call daemon; the regex `grep` mode kept runner-side in round
  3).** Executed PR code runs as the same user that owns
  the runner's state, and git does **not** re-verify a loose object on
  read -- so nothing the runner holds is trusted as content after PR code
  has run. Three layers hold the line:
  - **The file-content reads are controller-side.** `read_file`, the
    fixed-string `grep` and `list_files` answer from the controller's
    own copy of the staged trees (extracted in memory from the tarballs
    it already holds) and, for MUTANT, from the recorded mutation's
    splice applied to that copy -- the same span splice the runner's
    script applies, parity pinned. They never exec and never trust
    anything read back from the runner; a runner that refuses every exec
    still serves them. The `grep` regex mode is deliberately **not**
    controller-side: it stays on the runner, where `timeout` bounds the
    engine (an in-process `re` scan would run unbounded, and the PR
    controls both the haystack and, by injection, the pattern), a bad
    pattern is git's exit status (a gap, not an uncaught `re.error`),
    and the dialect is `git grep -E`'s POSIX extended regex, unchanged
    from before the local path existed. It rides the same re-stage and
    quote-gate protections as the diff trio.
  - **The re-stage from the controller-held tarballs** (below) closes
    every *timestamped* tamper: the repository, `trees`, the scratch and
    the staging indexes are removed and rebuilt from freshly re-uploaded,
    digest-checked tarballs, and the staged commits are deterministic, so
    the recorded BASE/HEAD ids must come back exactly; a recorded
    mutation re-applies deterministically and the re-created mutant id is
    checked against the record.
  Each execution call -- and every runner read that follows one --
  re-stages, and only then serves or runs. The re-stage rebuilds the
  repository and trees from the controller-held tarballs, so executed
  code's own writes and timestamped tamper are healed; what the retired
  per-call sweep used to add on top -- killing processes a PR's tests
  detached between the rebuild and the read -- is an accepted residual
  (recorded on D80): a process detached by executed code can keep
  running and re-forge the runner-side object store, which can mislead
  the diff trio's and the regex `grep`'s reads, but the finding gate's
  quotes verify against controller-held head content, so a forged diff
  cannot mint a verified finding. The argv is built by the bridge and
  never by the model: `<trusted
  interpreter> -I -B -m pytest -q --color=no -p no:cacheprovider
  <selector>` -- isolated (`-I`: no `PYTHON*` variables, no user site,
  cwd off `sys.path`, so a PR `pytest.py` cannot shadow the runner
  machinery; `-B` because isolated mode ignores
  `PYTHONDONTWRITEBYTECODE`), module mode, and the model's selector as
  one positional argument. One test process runs at a time. A run's wall
  clock is the tool's `timeout_s` (default 60s, provisional) under the
  guest's `timeout`; its captured output is capped at the tool's
  `max_bytes` (default 16 KiB, provisional) and shown from the end,
  where pytest's summary and failures sit. A `mutate` call runs the
  baseline, stages a **fresh** copy (the baseline's writes carry into
  neither the mutated run nor the mutant commit), applies the
  one-operator mutation with the fixed script as a **span splice** (the
  model named only a path, a line and an operator; the rest of the file
  stays byte-identical), commits the mutated copy into the bare
  repository and records its id -- the mutated tree is reachable at
  exactly one new revision, and MUTANT resolves at that **recorded
  commit id** -- then runs the mutated copy. The verdict is the
  controller's, from the runs' reported exits and its own parse of their
  final pytest summary lines: `survived` only when the baseline ran at
  least one test and passed and the mutated run also passed with a
  summary showing one -- an exit 0 whose output carries no summary line
  proves nothing and is inconclusive; an already-failing,
  nothing-collected or nothing-ran baseline, a timed-out run, a mutated
  run where no test ran, and a mutated run at a non-test exit are
  `inconclusive` with the reason, never `survived`; a mutation that did
  not apply or a tree that could not be committed ends after the
  baseline and is inconclusive. The exits are in-band evidence, not
  proof -- the standing caveat `runner.parse_exit` records -- and here
  PR code runs, so a PR can shape its own test results; a forged verdict
  changes only what a lens may claim, and the finding still needs a
  verified quote. The re-stage's cost -- an upload-and-rebuild per
  execution and per post-execution runner read, plus a sweep -- is
  bounded by the exec budget and the existing caps. The interpreter is
  resolved before any PR content is unpacked; none means the tools
  answer `unavailable`. The caps count what ran: a refused call --
  rejected arguments, an already-spent budget -- takes no execution
  slot; a run that timed out keeps its. The allow-list seam for
  pre-approved commands is the bridge-owned argv table -- the approval
  flow around it is config slice S7 (D88), built beside it.
- **Results** are repository content and are not redacted. Each is
  scanned for committed secrets, and every hit is reported by path, line
  and pattern, pre-existing outside HEAD or in a file the PR did not
  change. Values are kept only for scrubbing and never shown. git's
  stderr and a run's stderr are redacted. Every call is a ledger record,
  and telemetry names only the tool. A run's output is PR-controlled
  text, not tree content: a secret hit in it has no location and is
  recorded as not introduced, and the output itself travels to the lens
  nonce-fenced like every tool result — evidence a finding may cite,
  never something that asserts one.

Not built yet: `log`, `blame`, `run_check`, and fetching the default-branch
tarball.

## Agentic lens loop (offline, D40)

`coordinator.review_lens` reviews a PR head with one lens through the
bridge. It is not on the CLI. The offline tests run it against
`LocalSprites` with a scripted model (`fakes.ScriptedLensModel`). The
live tool-calling adapter (`tool_model.OpenRouterLensModel`) and the
Sprite keepalive (`keepalive.py`) are built and tested offline (D41):
recorded HTTP for the adapter, and `LocalSprites` plus a fake Tasks
socket for the hold. The tests make no live model, Sprite or Fly call.
D41 records the 2026-11-12 probe that did.

- **Execution (D80).** The bridge's `run_tests` and `mutate` are on every
  lens's tool list, and the instructions name what they are: a test run
  or a mutant on a disposable copy of the head tree, evidence at the
  head SHA the result line names, output that is untrusted data inside
  the fence and can support a finding but never replace the reading it
  cites. The attempt counts what executed: an outcome carries
  `test_runs` and `mutants_survived` next to `changed_files` (the
  status line sums them), and an inconclusive mutant is a `TOOL_GAP`
  cause -- a run that proved nothing either way is an execution gap,
  never evidence, so a review with one open cannot approve.
- **Limits.** `lens_loop.AgenticLimits` has a $5 per-review reservation,
  kept by D43 (2026-11-12). The one-token-per-byte input bound stays,
  and the headroom is this reservation. The other defaults are still
  Brandon's provisional headroom (2026-11-11), configurable and to be
  revisited after live runs: 50 model calls per review, 50 turns per
  lens, 20 minutes per lens and 60 minutes per review. An override must be
  positive and finite, and a per-lens limit no greater than its per-review
  limit -- on `agentic-review`, against the totals the review runs on,
  which D68 derives above the configured values and re-checks after the
  derivation. Clearing one back to unset makes `resolve` raise
  `LimitsUnsetError`, naming each unset field, before any model, runner or
  ledger work. `retries` is 1. `call_retries` is 0 to 3 and defaults
  to 1: a failed model call is sent again after a backoff of 2s times
  the number of failed calls so far (2s, then 4s, then 6s), and each
  call reserves its own worst case (D49). Composed with the one timeout
  retry (D58), one logical turn's request can be sent up to
  2 × (`call_retries` + 1) times per attempt — 4 at the default. `pool_size` is 1 to 16. It defaults to
  1, and `agentic-review` uses 4 when neither `--pool-size` nor
  `ATLAS_POOL_SIZE` is set. `create_retries` is how many times a 429'd
  Sprite create waits and retries before giving up (D62): 0 to 24,
  default 6, the waits doubling from 2s capped at 60s, so the default
  spends about two minutes where #636's three waits spent 7. A Retry-After
  header the 429 carries is honored up to a 120s per-wait cap, and the
  runner's deadline bounds the whole loop sooner. `create_concurrency` is
  how many Sprite creates one review may have in flight at once (1 to 64,
  default 4); a pooled review passes a gate of that size to every lens
  run, and a lens that waits for a slot has the wait in its telemetry.
  The per-call
  input cap is the pinned model's catalog context minus the output
  reserve, and the output cap is the model's completion limit. An
  override can tighten either and cannot exceed the model. The
  reasoning hint defaults to half the output cap, so the reply has the
  other half. The reservation prices the whole output cap at the higher
  of the completion and reasoning rates -- one rate per token, not their
  sum, which double-billed every reasoning token and about doubled the
  output term that dominates a large-context call's worst case (D82,
  amending D43's Update). `diff_prefix_share` (D65) is
  the share of the model's resolved input cap the shared diff prefix may
  take; 0 pages every review, as before the prefix existed. When the
  reservation cannot cover that whole cap, the call is sent with the
  largest cap it can cover, if that is at least `min_output_tokens`
  (16,000 by default), and otherwise stops on `reservation_usd` (D50). A
  fitted cap whose previous hint does not fit it uses half that cap for
  the hint.
  `coordinator.limits_for_lens` reads the twenty-one limits through
  `agentic_config.load_agentic_limits`, from `ATLAS_*` or a flag string
  a caller passes. `model_for_lens` builds the adapter with those same
  bounds, and `review_lens` refuses a model whose per-call bounds differ.
  The `review` command does not accept these flags and does not read the
  variables. The one-shot path keeps its 3 calls, $3.00 and 200,000 input cap.
  On `agentic-review`, the picker's provider takes the smaller of those
  ceilings and `max_calls` / `reservation_usd`, and the picker's calls and
  dollars count toward the review's totals. D68: a multi-lens
  `agentic-review` derives its review-wide limits from the planned lens
  count under the absolute per-review ceiling
  (`review_wide.derive_review_wide`): the call cap is the per-lens call
  budget times the planned lenses plus the picker's calls, the
  reservation is the per-lens dollar budget times the planned lenses
  plus the picker's committed dollars clamped to the ceiling, and the
  review wall is the configured wall raised to the lens wall times the
  planned waves. An explicitly set `--max-calls`, `--reservation-usd` or
  `--review-wall-seconds` still wins for that one limit, and the ceiling
  clamps the reservation even then; a limit stop names the derived
  values, the ceiling, the observed value and the knob. The reviewed
  repo's `REVIEW.md` may set the ceiling with a `review_ceiling_usd:`
  line, read from the merge-base tree the review already fetches — the
  tree the PR branched from, not the base-ref tip — so a PR cannot move
  its own ceiling, and a ceiling changed on the base tip takes effect
  for pull requests branched after it. The clamp has one edge the
  backpressure closes (round-1 review of #717, M-1): a pool of
  concurrent first turns projects several worst-case reservations at
  once, so a clamped reservation can be smaller than one wave's
  worst-case reservations; a reservation that would pass the cap only on
  other calls' in-flight worst cases waits, bounded by the review wall,
  for one of them to settle instead of stopping its lens — the wait's
  real-time backstop arms only when the review clock itself stops moving
  across wakeups, so on a healthy clock the wall is the bound, however
  long a turn takes (round-2 review of #717, M-1R) — and stops outright
  only when the settled spend plus its own worst case cannot fit even
  with nothing in flight. Spend never passes the ceiling.
- **The prompt.** The system prompt is the controller's instructions, then
  the nonce fence rule, then the whole lens `body.md` between markers that
  carry its SHA-256, then `synthesis.md`'s whole *Finding contract*
  section. Nothing is cut. The first user turn is the operator's
  subject, then prior atlas rounds (`rounds.RoundLog`) and any context
  the caller passes, then the risk-ordered list of every file in the
  current diff, each fenced with the review's nonce. The caller context
  on the shipped `agentic-review` path is the conversation block, the CI
  evidence block, a delta review's highlight, and the reviewed repo's
  default-branch `AGENTS.md` as one coding-guidelines block (config
  slice S6, D81 Q8): fenced, budgeted against the model's input room in
  that order, every cut or failed read a named omission. The
  `AGENTS.md` is read from the repo's default branch — never the PR head
  or the merge-base, which a same-repo or stacked PR controls — and it
  is delivered as data only, never instructions; a repo whose default
  branch carries none is the ordinary unconfigured repo, not a gap. Prior finding
  lines are quoted in full, up to the 8,192-character record cap,
  not the 200-character quote default. They do not remove a file. A
  continuation may later list a subset. This first turn does not, and
  it has no parameter for one. The log is append-only JSONL, mode 0600
  on every write, keyed by repository and pull request number. The
  repository key is case-insensitive. An older head is labelled
  superseded and is not this review's scope. A record over 8,192
  characters stores no finding text. A record also carries the review's
  first limit stop, as its own message naming the lens, the attempt and
  the cap (#693), and the next round's first turn shows it back; a line
  from before the field existed parses with an empty stop. Prior blocks
  stay whole, newest first, inside 16,384 characters. Leaving out a
  superseded round does not block approval. Leaving out a round at the
  head under review does. A line that names another pull request, or no
  pull request, does not block this one. A line that names this pull
  request but cannot be parsed charges this review only when it sits at
  the head under review; at an older head it is superseded data, and a
  line whose head cannot be read charges nobody. A file the read cannot
  decode is moved aside under a `.corrupt-` name, so the next review
  starts fresh, and the review that saw it reports the loss once. The
  `agentic-review` command is the shipped
  caller: it builds the log at `<state dir>/rounds.jsonl` unless
  `--round-log` names another path, reads it into the first turn, and
  appends the review's own record (D67; the service passes a
  per-pull-request path, D74). It carries
  no diff text: the lens
  reads that through the tools, and every tool result comes back
  fenced.

  When the diff fits the model, the request is laid out differently so
  the review's lenses can share one cached block (D65, issue #696): the
  request opens with a byte-identical prefix — the tools, a shared
  system text (the prefix instructions, the review's one fence nonce,
  the Finding contract) and the fenced whole diff of the files the lens
  was given — and the prefix's last content part carries the explicit
  `cache_control` breakpoint; the lens skill (the retry preamble, then
  the attested body) and the first turn follow inside the same user
  message. The nonce is minted once per review from the CSPRNG, so the
  prefixes are byte-identical across lenses and across a lens's retry.
  The size threshold is `diff_prefix_share` of the model's resolved
  input cap, decided per attempt and named in the lens's draft line
  either way; above it, or when the model cannot name an input room, the
  review pages through `diff_file` exactly as this bullet describes.
- **One attempt** (`lens_loop.run_attempt`). Delivery is checked before the
  first model call. The attempt ends at the final reply, or when one of
  these cuts it short: the turn cap, the call cap, the dollar reservation
  (each call is reserved at the model's worst case, then settled at its
  reported cost), either wall clock, the per-call input cap, a call that
  does not fit the model's context, a turn the model ends at the output
  cap (`finish_reason=length`), a failed model call, or the runner's
  deadline during a tool call. A limit stop names the limit, the
  configured value, the observed value, and the flag or variable that
  changes it. A token refusal is `INPUT_CAP`, `OUTPUT_CAP`,
  `REASONING_CAP`, or `CONTEXT`, not a model error.
- **Checking the reply.** The reply must meet the finding contract
  (`lens_contract.py`) and name the lens and its body digest. Each quote is
  checked against the head file at the cited lines. The cited span is the
  quote's own line count, so a wider range does not verify. A quote of
  whole lines (8 or more non-space characters) may also match a window of
  the quote's own line count starting within three lines of the citation
  (D64; configurable, `ATLAS_QUOTE_TOLERANCE`), and the finding's location
  then names the lines that hold it; whitespace inside a line is
  collapsed. A removed line of that file still verifies, and so does a
  quote from an unchanged file the lens read at HEAD (D47; `quotes.py`).
  A quote that verifies neither way earns the bounded quote-repair turn
  (D64): the rejected quotes, their cited locations and the checker's
  reasons go back once per attempt (`ATLAS_QUOTE_REPAIRS`, default 1), the
  model corrects the range or drops the finding, the next reply is
  re-checked by the same checker, and the held reply's verified findings
  merge into it through the retry merge; a still-bad quote leaves the
  attempt as it was, and the bound hit is named in the lens line.
- **Partial results.** No findings counts as clean only after every
  changed file's diff was read in full: a `diff_file` chain from offset
  0 through every truncated page (D42) — or, on the shared-prefix path,
  the prefix itself, which held the whole diff of the files the lens was
  given from turn 1 (D65). A HEAD `read_file` does not
  replace that. A changed file left unread makes the lens partial, names
  the file in the draft, and is not retried. On the shared-prefix path
  the unread list never occurs — coverage is attested from what the
  prefix held — so the unread-list nudge and the `diff_file` page
  bookkeeping are retired there; the paged path keeps both, and its
  coverage stays honest: a lens never attests coverage it did not get.
  A timed-out, unavailable or over-limit tool call makes the lens
  partial. Every `diff_file` page counts against the bridge's
  per-attempt output budget (`SessionLimits`, 1 MiB by default; #693
  starts it over for each attempt, so a retry does not inherit what its
  predecessor spent). A PR whose diff is larger than that budget cannot
  come clean on this path: the call past the budget is refused
  `OVER_SESSION_LIMIT`, its file stays unread, and the review fails
  closed. Raising the budget is the only remedy built; no path-exclusion
  option exists. When three refusals have accumulated in the attempt,
  the turn's results go back and one finalize turn asks the model to
  finalize with what it has (#693): the tools stay on the request,
  because tool history next to an empty tools array is a shape the
  pinned Bedrock route is documented to reject, and the spent bridge
  refuses whatever the model still calls; the finding the model then
  delivers is attested, with the stop attached, naming the lens, the
  attempt and the cap.
- **Ledger and retries** (`attestation.py`). Each attempt is fsynced to an
  append-only ledger when it starts and again when it ends, keyed by
  repository, PR, head SHA, lens and body digest. A failed attestation, an
  unparsed reply, a failed quote or an abandoned attempt is retried once
  with the body injected again; a second one escalates. A settled lens
  keeps what the earlier attempts verified (#691): the last attempt's
  outcome stands -- its attestation and causes, so a retry that still
  failed is still partial or failed -- with the earlier attested attempts'
  verified findings merged into it, deduplicated (a finding the retry
  restates stays the retry's copy, an earlier verified finding replaces
  the retry's unverified copy at the same citation, and one the retry does
  not restate is appended; the identity is the location, the severity,
  valence and attribution, and the normalized finding and evidence text).
  A crash leaves an
  abandoned attempt that counts as used. A lens already settled for this
  head and body is reused without a runner, and (D73) the reused result
  keeps its findings while a moved evidence-snapshot digest -- the
  gathered CI items and the PR's remarks, fetch times excluded,
  stored with the finished attempt -- earns it one bounded no-tools
  re-assessment call against the review's shared spend: its reply may add
  findings, revise or propose withdrawing prior ones, a withdrawal or
  revision always with its stated reason, and silence keeps a prior
  finding as it stands. A withdrawal removes nothing -- it annotates, and
  so does a revision that would lower a Blocker's or a Major's severity,
  so the higher severity still counts for the verdict (round-1 review of
  #731, M2). The re-assessment is recorded on the lens's `#reassess`
  ledger key, so a garbled reply cannot turn a clean lens partial, and
  the effective result is composed from the ledger alone on every review;
  the composed outcome carries the latest re-assessment's own limit stop
  and, beside the settled run's dropped notes, only its latest reply's. A
  settled outcome with no changed-file count, from before the per-file
  gate, shows no coverage, so the review cannot approve on it.
- **The adapter** (`tool_model.OpenRouterLensModel`). One Chat Completions
  request per turn, with the one-shot provider pin (`require_parameters`,
  zero data retention unless `ATLAS_REQUIRE_ZDR` is false, no fallbacks,
  no plugins and no server tools) and only the bridge's tool schemas.
  `reasoning` is included only when every selected endpoint lists it.
  `cache_control` is sent on Anthropic-family routes even when no
  endpoint lists it, and a shared-prefix request also carries the
  explicit part-level breakpoint on the fenced diff (D65); a route whose
  endpoints do not list `cache_control` gets the prefix layout with no
  marker on any part. The loop settles `_actual_cost`, which
  includes a BYOK upstream charge. A turn with no readable cost but
  usable token counts is priced from the selected endpoints. Prompt
  tokens use the highest of the prompt and cache-write rates, and when
  the response reports cache read or write counts those counts use the
  endpoints' cache rates: a missing
  read rate uses the prompt rate, and a missing write rate uses the
  reservation's input rate. A response that reports cache reads but no
  write count charges its uncached tokens at the input rate, since a
  write could be among them. Counts that sum past the prompt tokens leave
  the turn unpriced. The output count is priced as one token, one rate
  (D82): a reported reasoning count is the subset of the completion count
  it sits in (OpenRouter's reasoning-tokens guide, fetched 2026-11-18),
  so the split prices the rest at the completion rate and the reasoning
  tokens at the reasoning rate -- or at the completion rate when the
  catalog lists no reasoning rate, which is what a missing rate stands
  for -- and a response that reports no reasoning count prices the whole
  completion count at the higher of the two rates, so it settles instead
  of staying unpriced. A reasoning count that claims to sit outside the
  completion count still leaves
  the turn unpriced. That missing-cost
  case stays at the reserved worst case, as do
  an unreadable upstream charge, a BYOK call with no upstream charge, and
  a turn with neither a readable cost nor usable token counts. A settle
  whose reported cost came in above the worst case reserved for the call
  moves committed spend to that reported actual -- which can sit above
  the reservation -- and is recorded as an overrun on
  the draft's `Model calls:` cost line (D82's tripwire, round-1 review of
  #757) -- the observable signal that a provider billed past the priced
  worst case. A readable
  cost is used as reported, including when the reasoning-token count is
  missing and when the response also reports cache tokens. The catalog is
  fetched once per provider for the review and reused, to confirm the
  model id. Prices and limits come from the selected endpoint rows. The
  adapter does
  not retry and does not reserve on the one-shot budget. A tool call whose
  arguments are not one JSON object, or that hold a non-finite number or
  nest deep enough to recurse, is handed to the bridge, which rejects it,
  and the refusal comes back nonce-fenced. No call is executed in the
  adapter. A key that does not count BYOK spend refuses an unparseable
  reply the same way it refuses one that is not explicitly non-BYOK. The
  refusal leaves the loop, and the ledger records it as a model error that
  is not retried, keeping the turns and tool calls completed before it and
  the committed secrets those calls found. The runner fails, so its note
  is quoted, and the next review of the same head does not call again.
- **The keepalive** (`keepalive.py`). For the length of a lens,
  `review_lens` holds the Sprite with a Tasks API task on
  `/.sprite/api.sock`: a 5-minute expiry, refreshed every 60 seconds, and
  deleted on the way out, including when the lens raises or is cancelled.
  The refresh thread is joined before the delete, and the join waits at
  most 20 seconds. A refresh stores a failure under the lock before
  releasing it. The lock and the stop and held guards are what stop a
  refresh after the hold has stopped from recreating the task; the Tasks
  API's PUT would otherwise upsert it. Each hold exec has its own 15-second
  budget, and the guest socket call times out after 10 seconds and reads
  only the status line. Refresh and tool execs share the runner's exec lock so
  they do not write one stream; the 15-second budget is how long a
  refresh can block a tool. A keepalive failure fails the runner, and a
  failed runner is not complete coverage. Snapshot and restore is not
  built; there is no public fork API (Fly support, 2026-11-06).
- **The draft** (`coordinator.render_draft`).
  - **Status line.** The first line is a status line: `"mode": "agentic"`,
    `coverage_complete`, `changed_files`, `unreviewed_files`,
    `test_runs` and `mutants_survived` (D80: the summed counts over the
    lenses' outcomes -- the `run_tests` calls that came back with a run,
    and the mutants whose verdict was survived; zero on an attempt that
    executed nothing, and an inconclusive mutant never counts as a
    survivor. The sums are the head's recorded executions, not what this
    review paid for: a lens reused from the ledger contributes its
    settled counts, which are real executions at this same head),
    `context_omissions`, `other_pull_requests`, `withdrawn`,
    `round_log_note`, `trace_id` when a span was recorded, the lens
    counts by state, and `limit_stop`. The two file fields are counts.
    `context_omissions` is a count. `other_pull_requests` is how many
    records in the log belonged to another pull request. `withdrawn` is
    how many prior findings a re-assessment annotated -- a D73
    withdrawal or revision -- which removes nothing, so it is an
    annotation count (round-1 review of #731, M2). `round_log_note` is
    empty, or the error class and its strerror when the log could not be
    written. `limit_stop` is the first limit that stopped a lens -- a
    lens's own run, or its latest re-assessment's refused reservation or
    spent-out call cap (round-1 review of #731, N4) -- or null. Paths
    stay out of the line. A delta review adds four counts -- `carried`
    (re-anchored, verified carried findings), `carried_unverified`
    (carried without a verified quote, raw unparsed lines included, so
    an all-clear on `carried` cannot hide them), `resolved`, and
    `reused` (D83: how many planned lenses the coordinator reused
    instead of re-running) -- and `delta_note` when the carry named a
    gap (round-1 review of #748).
  - **Coverage.** Coverage is complete only if every selected lens settled
    clean, every changed file's diff was read, the outcome recorded a
    changed-file count, and, when this review ran a runner, that runner
    completed. Each lens is held to its own entries: one clean run of a
    lens covers it however its other entries ended (#692, D76) — an
    earlier NOT RUN a later clean run superseded, or a later NOT RUN
    after an earlier clean run — while a lens with no clean run still
    blocks, and the superseded failure stays in the coverage section
    marked `recovered by L<n>'s clean run`. A delta review's reused
    lenses (D83) make no entry: their reuse is their coverage for the
    files their settled results read -- except the files the delta
    touched, which only a lens that ran this round can have read, so an
    uncovered one is unreviewed and the review cannot approve (round-1
    review of #760, Major A).
    Otherwise a REVIEW INCOMPLETE
    warning follows, and the
    review never approves. A failed runner's note is quoted in the draft.
    A settled outcome with no changed-file count shows no coverage.
  - **Findings.** Verified findings carry minted `L<lens>-F<n>` IDs and are
    ranked by severity. Findings from different lenses that name the same
    defect — the same target and the same claim — are one finding whose
    line names every lens that reported it (issue #822), and the
    per-review merge/verify call reconciles what that exact key cannot
    (the plan's step 7). The verdict comes from verified, introduced
    defects only. Unverified findings are listed apart and never counted.
    Possible committed secrets that the tools read are controller
    findings.
  - **Synthesis merge.** A review with findings runs one bounded,
    tool-less merge/verify call after the lenses (the plan's step 7):
    the reply's clusters and downgrade/drop proposals are reconciled
    against the findings the controller holds — a cluster's strongest
    finding represents it with every lens attribution, and a proposal is
    an annotation on the finding's line (`Merge: …`), never a deletion
    and never verdict input. A `## Synthesis merge` section names what
    the call did; a call the review's limits refused, or a reply that
    does not reconcile, fails the review closed — REVIEW INCOMPLETE, the
    findings stand unmerged, and the section names the cause.
  - **Prompt cache.** When the live adapters reported prompt-cache
    sessions (#695, D63), a `## Prompt cache` section follows the model
    calls line: one line per session — a conversation, bounded by its
    system prompt — with its turn count, the turns whose reported cached
    tokens fell short of the previous turn's prompt (or reported none;
    a session's first turn is never a miss), the session's cache-write
    total and final context, the session's opening turn's reported cache
    read — the shared diff prefix's read for that session (issue #696,
    D65) — and then a run total of the cache writes against the sum of
    the sessions' final contexts. A dry run's
    scripted model reports none, so the section is absent there.
  - **Scrubbing.** Every model-written value is redacted, scrubbed of
    flagged values, and quoted as data.

## Module layout

| Module | Job | I/O? |
| --- | --- | --- |
| `domain.py` | closed types: `PrEvent`, `EvidenceItem`, `Matched`/`Stale`/`Missing`, `Outcome`, `Omission` | no |
| `classify.py` | evidence vs. the head SHA → matched / stale / missing; failures at other commits with no head result | no |
| `redact.py` | secret redaction (`RedactedText` can only come from `redact()`) and `detect_secrets`, which reports pattern and line without changing text | no |
| `prompt.py` | trusted system prompt + nonce-fenced untrusted blocks (`RedactedText`, or `RepoText` for the unredacted diff) | no |
| `committed_secrets.py` | scan each file of the diff for possible committed secrets, located by file line and side | no |
| `evidence.py` | GitHub JSON / runner results → `EvidenceItem`, PR commits and remarks, shape validation | no |
| `conversation.py` | the PR conversation block under its budget, every cut and dropped remark an omission; and the coding-guidelines block (config slice S6, D81 Q8): the reviewed repo's default-branch `AGENTS.md` as one more fenced, budgeted untrusted block (`guidelines_block`), its read failures, over-bound file and cuts named, its content never instructions | via `GitHubReader` |
| `archive.py` | bounded in-memory ZIP reading for untrusted artifacts | no |
| `pagination.py` | `Link` header parsing | no |
| `pricing.py`, `budget.py` | catalog/key parsing (fail closed); per-review call and cost budget | no |
| `draft.py` | Markdown draft rendering | no |
| `groups.py` | one CI gate seen as check run + job + log + workflow run → one independent check | no |
| `notes.py` | the code-generated Controller notes | no |
| `diffs.py` | split a diff into files, rank them by risk, pack them into per-call parts, fit the part size to the measured prompt; the reviewed repo's path ranking (`PathRanks`, `rank_files`, the generated-file heuristic and `rerank_note`, config slice S5) re-orders files -- ordering only, never exclusion | no |
| `picker.py` | run `choosing-review-lenses` as one model call, parse its reply strictly, fall back to the critical tier, skip the call when no picked lens could fit; applies a repo preference's include/exclude to the picks (D69) and records it | reads the bundle |
| `verdict.py` | the proposed review event, the file-coverage gate on approval, the machine-readable status line and the incomplete-coverage warning | no |
| `telemetry.py` | lifecycle events, the `EventSink` (JSONL), labelled timed spans, the summary rows | writes the JSONL file |
| `instrumented.py` | `GitHubReader` wrapper that records every read as an event | via `GitHubReader` |
| `lenses.py` | load the chosen lenses' bodies whole under the budget -- no lens-count cap (D69) except triage's critical tier -- or mark them NOT RUN with a reason | reads the bundle |
| `bridge.py` | the tool bridge: the read-only git tools' per-call scripts, capped base64 replies, result statuses, secret locations, the call ledger, `run_bridge`; and the two execution tools (D80): `run_tests` and `mutate`, whose staged-copy scripts, framing, verdicts and per-attempt caps the same ledger records | via `SpritesApi` |
| `bridge_args.py` | the closed tool set and its argument rules (`validate`, `arg_names`, `required_args`), the mutant operator set and the MUTANT revision | no |
| `source_archive.py` | the unpacked-size and member caps a source tarball must pass before upload (`measure`) | no |
| `guest_unpack.py` | the same caps held again in the runner: its tar measures bytes, members and implied directories before extracting, then `ulimit -f` while extracting, every tar run under `timeout` | no |
| `bridge_staging.py` | Option B staging: trusted git, the hardened git options, tarballs committed into a bare repository, `fetch_sources`; the pytest-capable interpreter probe and the execution tools' staged-copy and mutant-commit pieces (D80) | via `SpritesApi`, `GitHubReader` |
| `lens_contract.py` | a lens's final reply under the finding contract, parsed strictly into typed findings (`parse_reply`); a finding whose severity is unknown is dropped and named with its raw severity, cut to 80 characters (the draft quotes and scrubs it, and the review cannot approve); any other problem refuses the whole reply, and a refusal never echoes model text | no |
| `quotes.py` | check each finding's quoted evidence against the head file at the cited lines (the span is the quote's line count, with the ±`quote_tolerance`-line window D64 adds), or the diff's removed lines (`check_quote`) | no |
| `reassess.py` | the reused settled lens's D73 re-assessment: the evidence-snapshot digest (`snapshot_digest`), the one bounded no-tools call's prompts and reply shape (`reassess_system`, `reassess_turn`, `parse_reassess_reply`, `judge`), and the effective result composed from the settled outcome plus the recorded re-assessments (`effective_outcome`) | no |
| `synthesis.py` | the per-review merge/verify call (the plan's step 7, issues #822 and #823): one bounded, tool-less call over the deduped findings, the review's context and the prior rounds; the reply's clusters and downgrade/drop dispositions validated (`parse_merge_reply`) and reconciled against the findings the controller holds (`reconcile`) — a cluster's strongest finding represents it with every lens attribution, and a downgrade or drop stays an annotation the verdict is never lowered by; a reply that does not reconcile, and a call the review's limits refuse, fail the review closed (REVIEW INCOMPLETE) with the cause named | no |
| `attestation.py` | lens-body delivery and acknowledgement checks, attempt outcomes and lens states, the append-only attempt ledger (`AttemptLedger`), the retry-once policy (`next_step`) and the verified-findings merge a settle carries (#691, reused by D64's in-session quote repair) | writes the ledger file |
| `lens_loop.py` | the agentic limits (the $5 reservation is D43; the other four are Brandon's provisional defaults, 2026-11-11; per-call bounds from the model; the quote-repair bound and window are D64; the shared diff prefix's share of the input room is D65; D68 adds the per-lens derivation knobs and the ceiling, and the `Derivation` record a derived limit stop reads), the `LensModel` port and its messages, tool schemas built from `bridge_args.TOOLS`, the paged lens system prompt and the shared-prefix builders (`lens_skill`, `shared_system`, `diff_prefix_for`), the spend tracker, one lens attempt (`run_attempt`) with its follow-up turns (D44's contract repair, D58's unread and no-progress nudges, D64's quote repair) | via `Bridge`, `LensModel` |
| `repo_config.py` | the reviewed repo's merge-base `REVIEW.md` config parse (D81's S1): the D68 ceiling line, the D69 lens-preference lines and the S5 path-ranking lines (`review_path_include:`, `review_path_exclude:`, `review_generated_files:`), read bounded (`MAX_CHECKED_BYTES`, 64 KiB, not parsed cut over the bound) and fail-open with named notes; unknown `review_`-namespaced keys parse as unsupported with a named note that names the key, the condition and the default that stands and never echoes the rejected value; the file name is one constant (`REVIEW_MD`), not a design commitment; the whole-file parse is `read_repo_config`, the per-line reads its windows; the schema also carries the service's two post-window keys (`review_severity_floor:`, `review_post_verbosity:`, S3) parsed by `parse_post_config` from the default-branch text the service fetches at post time, never from the merge-base, and the S7 execution-tool allow-list proposals (`review_test_commands:`) parsed by `parse_run_proposals` from the same default-branch window | no |
| `approval.py` | the #734 execution-tool allow-list's operator-approval gate (config slice S7, D88): `CommandProposal` (a parsed, validated declared test command), the `ApprovalChannel` port — the seam the decided shape backs with pre-approval (installation admins pre-approve on the S10 settings page, part B; no live approval during a review) — with `NeverApproved` as the production default until it lands, and `RunApprovals` -- the run-scoped gate that turns a blocked command into one approval request, denies every outcome but an explicit approval (a denial, a no-answer, an error, the run's wall or dollar limit reached while waiting), keeps denials sticky, and dies with the lens run | no |
| `review_wide.py` | D68's review-wide derivation for a multi-lens review: the call cap, reservation and review wall derived from the per-lens budgets and the planned lens count, clamped to the absolute per-review dollar ceiling; the ceiling's resolution order (repo `REVIEW.md`, configured, default) is the seam a later per-run policy plugs into. The `REVIEW.md` reads behind it live in `repo_config.py` (S1) | no |
| `agentic_config.py` | the one reader for those limits: a flag, else `ATLAS_*`, else the default | no |
| `limit_stop.py` | the text and ledger fields for a limit that stopped a lens | no |
| `coordinator.py` | one lens under the ledger in one runner session (`review_lens`), minted IDs, ranking, the mechanical verdict, the status line and draft; holds the Sprite for the lens (`keepalive.lens_hold`) | via ports, the ledger |
| `dedupe.py` | the synthesis's controller-side dedupe (issue #822): findings from different lenses naming the same defect — the same target (path and overlapping or nearby span) and the same claim (statement, valence and attribution) — collapse into one representative that carries every lens attribution; a verified finding and an unverified one never merge | no |
| `findings.py` | `MintedFinding`, the synthesis's finding record: the minted id, the lens it stands under, and the cross-lens attribution list a dedupe cluster's representative carries | no |
| `rounds.py` | the prior-round log (`RoundLog`): append-only JSONL, mode 0600, one record per finished review, fenced back as untrusted data. The `agentic-review` command builds the path at `<state dir>/rounds.jsonl` unless `--round-log` names another one (D67, D74) | writes the log file |
| `tool_model.py` | the live tool-calling adapter (`OpenRouterLensModel`): one pinned Chat Completions request per `LensModel` turn, `reasoning` only when the selected endpoints list it, `cache_control` on every Anthropic-family route plus the explicit part-level breakpoint on a shared prefix's fenced diff, strict tool-call arguments, cost from `_actual_cost` (BYOK upstream included; endpoint rates when the cost is missing but the token counts are usable, with cache read and write counts at the endpoints' cache rates when the response reports them, and the output count priced as one token, one rate -- the reported reasoning count split out of the completion count, the whole completion count at the higher rate when the count is missing, so it settles rather than keeping the reservation -- D82), and per-session prompt-cache accounting fed to `cache_stats.CacheLedger` (#695). Not on the CLI. Tested with recorded HTTP only | via the OpenRouter client |
| `cache_stats.py` | per-session prompt-cache accounting from a model's reported usage (#695): sessions bounded by the system prompt, the miss rule (cached tokens below the previous turn's prompt, or unreported), each session's opening-turn cache read — the shared diff prefix's read (D65) — and the run summary's session and total lines. Pure; no I/O | no |
| `keepalive.py` | the Sprite Tasks API hold for one lens: create, refresh every 60 seconds with a 5-minute expiry, delete on exit. Not on the CLI. Tested with `LocalSprites` and a fake socket | via the runner exec |
| `ports.py` | the adapter interfaces (`GitHubReader`, `SpritesApi`, `ModelProvider`, `ReviewHarness`, `RunnerLedger`, `Clock`); the agentic `LensModel` port is in `lens_loop.py` | no |
| `runner.py` | disposable-runner lifecycle (create → deny-all → verify → tool check → resolve interpreter → upload → unpack → tools → destroy), `probe_runner`, `run_session` (a `Session` on the same lifecycle), the one exec wrapper (`exec_argv`, minimal `env -i` environment) | via `SpritesApi` |
| `interpreter.py` | the resolve script, `choose_python` (accepts only the pyenv-versions and `/usr/bin/python3` path shapes), `{python}` substitution, the probe-only diagnostic scripts and output summary | no |
| `gather.py` | CI evidence labelled by SHA: check runs at the head and other PR commits, workflow runs, job logs for every ingested run's jobs, artifact contents at the head, omissions | via `GitHubReader` |
| `snapshot.py` | the read-only PR snapshot builder behind the parity anchors' eval fixtures (`snapshot-build`): the anchor's lineage commits, the remarks posted before the anchor push, the CI at the retained commits with the jobs' logs, the trees, the diff and the self-contained `history.bundle`; the build step's GitHub reads go through `gh api`, the fixture is committed and offline afterward | via `gh api` subprocesses and the local git |
| `controller.py` | one event in, one draft and its review verdict out | via ports |
| `harness.py` | skill-bundle harness: loads `collapsed/skills/reviewing-a-change/SKILL.md` | reads the bundle |
| `providers.py` | `OfflineProvider` (the default) | no |
| `github_api.py`, `github_auth.py`, `sprites_api.py`, `openrouter.py`, `http.py` | live adapters | network |
| `github_fixture.py`, `fakes.py`, `ledger.py`, `clock.py` | offline adapters, local state | local files |
| `local_runner.py` | the dry-run runner: `LocalSprites` runs each exec's wrapper locally (the same class the bridge and lens-loop tests use) and `LocalTasks` answers the keepalive hold on a unix socket | subprocesses, a local socket |
| `lens_script.py` | the dry-run lens script: the scripted reviewer's fixed reading behavior and the JSON scenarios the fixture ships | reads the script file |
| `cli.py`, `__main__.py` | entry point, dispatch tables | env, files |
| `service_admit.py` | webhook signature, event and allowlist admission (including the base-change `edited` retarget, which re-runs admission against the new base); the repo-narrowed admission config (config slice S4): the default-branch `REVIEW.md` narrowing lines parsed bounded and fail-open with named notes, and the pure narrowing of an admitted delivery — skip events and base-branch include/exclude — that can only remove a review, never widen the operator's envelope | no |
| `head_change.py` | the keep-or-cancel decision for a push that lands mid-review (#702, D79): the range's classification, the progress read back from the run's events file, the pure decision, and the live classification reads | GitHub (classification reads) |
| `delta.py` | the delta review a kept head's follow-up runs (#702, D83): the delta scope — what is new and the resolution gate, not a lens scope — the coordinator's per-lens re-run/reuse decision, the incremental-diff highlight block, the prior findings parsed from the round record, the carry-forward turn's pieces and the composition | GitHub (the range comparison) |
| `service_queue.py` | dedupe by repo, PR and head SHA; supersede a moved head; hold a kept head back as the pull request's pending follow-up (#702) | the queue file |
| `service_run.py` | one queued commit through the service mode's command (`agentic-review` by default, `review` in oneshot mode; D70), with the per-pull-request `--round-log` the agentic child takes (D74); the finding-line classifier and the severity-floor partition the post applies (S3) | the review child |
| `service_post.py` | one COMMENT review, idempotent; no other event can be sent; the repo's post settings (S3) lower only — a severity floor that holds below-floor preference-tier findings out of the Findings section, named, and a brief body that keeps the findings, the coverage note and the stops | GitHub |
| `service.py` | webhook HTTP server and the review worker; after the operator's envelope passes, reads the repo's default-branch `REVIEW.md` (the branch that changes only through reviewed merges, never the PR head or the PR's own base branch) through a read-only App client built from the same credentials as the head-change classifier's, and applies the repo's own narrowing, logging every skip with its reason and every failed or unusable read as a recorded gap; the handler's GitHub reads share one overall budget | network |

## Trust boundaries

- **Trusted:** the operator's event file, this repo's skill bundle and lens
  picker skill, the controller's own code and `ToolSpec` commands.
- **Untrusted:** everything from the PR. That means the diff, title and body,
  check names and summaries, job logs, artifact metadata and contents,
  runner tool output, issue text, and the model's own output. Lens bodies and
  the controller notes' fixed sentences are trusted; every untrusted value in
  the notes is quoted as a marked `"..."` literal, and the whole block is
  still fenced as untrusted data when sent. Redaction (the controller's
  credential values plus the secret patterns) covers all of it except the
  diff: CI logs and summaries, artifact excerpts, PR and issue text, runner
  output and every other quoted evidence value, before it reaches a prompt
  or the draft. The draft's body, model narrative included, is scrubbed
  again as it is rendered. In the prompt it sits
  inside `<untrusted-data id="NONCE">` fences, and the system prompt says
  never to follow instructions found there.
- **The diff is not redacted (D33).** It is already in the repository, other
  reviewers read it raw, and regex redaction of code dropped or mangled
  review input. A secret committed in it is already exposed, so the
  controller scans each file with `detect_secrets` and lists every hit under
  "Possible committed secrets" as a HIGH finding: path, file line, pattern
  label, and "rotate if real", never the value. Detection removes nothing.
  The scanned values are scrubbed from the finished draft in case the model
  repeats them, and the system prompt tells it never to. The scrub covers
  every section built from untrusted text and each path the coverage
  warning names, but not the status comment or the warning's own words, so
  a committed value cannot rewrite the review event. PR, issue, CI log,
  artifact and runner text keep their redaction, since they can carry
  runtime secrets that are not in the repository.
- **Runner:** a fresh Sprite for every review, never reused. Deny-all egress
  (`{"action": "deny", "domain": "*"}`) is set from the outside API and read
  back before anything runs. Memory is capped at 1024 MB. The Sprite gets no
  connectors and no credentials. A probe (`command -v` for each tool
  binary) runs before the source is uploaded, so PR code cannot answer it.
  A binary it does not report present is never executed and its tool is
  UNKNOWN. Source goes in as the head-SHA tarball over exec stdin
  (fed through `head -c N` into `/tmp/atlas-source.tar.gz`, so nothing
  waits for a stdin EOF) with a 300-second budget, and the runner reports the bytes it wrote,
  which must equal the bytes sent. A second exec unpacks it into `/work`
  with a 120-second budget. Before writing anything, the runner's own tar
  checks the archive against the same unpacked-size and member caps
  (`guest_unpack.py`), and extraction runs under `ulimit -f` sized to the
  byte cap, and every tar run is under a 60-second `timeout`. An archive
  past a cap, or a tar that stalls, is refused with a named reason, and a
  failed unpack the script survives removes its partial tree (D39; the
  shell's block size is (verify)). The tool check has 60 seconds and each tool
  exec its timeout plus 15. Every budget is capped by the remaining review
  deadline. The controller fetches the tarball with its own token. An external
  deadline is enforced by a watchdog timer. Destroy runs in `finally` and
  from the watchdog. It is idempotent and is verified by a follow-up
  existence check. It deletes only after this process's create succeeded:
  a refused create stops the run with nothing to delete, and a create
  whose outcome is unknown leaves the name for `sweep --force-live`. The
  runner name is written to the ledger before create, so `sweep --force-live`
  can clean up after a crashed controller. A live runner's name
  comes from the event, so `sweep --event` can find it from another
  machine.

## What a live run still needs

Everything above is tested offline, against fakes and fixtures. The owner
has run three live pilots and two live probes from a trusted machine (the
sections below, oldest first). The fixes made after each run are tested
offline only. Before another live review:

1. **Sprites protocol check.** With only `ATLAS_SPRITES_TOKEN` set, run
   `python -m atlas_reviewer probe-runner` from a trusted machine. It
   creates one runner, sets and reads back deny-all, probes the default
   tools, runs `echo atlas-framing-check` and prints the raw response bytes,
   then sends 3 MiB over exec stdin through the same `head -c` the source
   upload uses and prints how many bytes the runner received, and destroys
   the runner. Then run `probe-runner --sequence review` (see Live mode),
   which repeats a review's exec sequence on a real checkout without a
   model. Its telemetry table names the step that fails, if one does.
2. **GitHub App.** Set `ATLAS_GITHUB_APP_ID`, `ATLAS_GITHUB_APP_PRIVATE_KEY`
   and `ATLAS_GITHUB_INSTALLATION_ID`. The installation ID is not recorded
   anywhere in this repo. Find it on the App's installation settings page
   (the number in the URL) for the account that owns the test PR. The App
   must already be granted at least the read permissions listed above.
3. **OpenRouter.** Create a key with a hard credit limit of at most $5 (or at
   most `--key-ceiling-usd` or `ATLAS_KEY_CEILING_USD`, when raised) and
   set `ATLAS_OPENROUTER_API_KEY`.
4. **A test PR.** Write an event file (`repo`, `pr_number`, `head_sha`)
   for a PR that has finished CI at that head SHA.

Still unverified against live responses:

- **The Sprites exec response body.** Observed for a small echo, a 3 MiB
  stdin round-trip, a review's upload and unpack (third probe), and the
  third pilot's whole review sequence at `a246625`, which used the D28
  request shape and the D29 wrapper. Not yet observed: whether output
  streams before the command exits, and the D30 cutoff timer.
- **The GitHub and OpenRouter response shapes.** The pilots' drafts held a
  check run, job, log and workflow run, so those list shapes parsed; this is
  inferred from the owner's reports, not a recorded response. Not yet seen
  live: a job's `check_run_url` (taken from GitHub's documentation; without
  it the controller simply does not group that job), artifacts, pagination
  past one page, and OpenRouter's error and retry responses. The OpenRouter
  key preflight, catalog read and single chat completions worked.
- **The input-token bound.** It assumes no token encodes less than one UTF-8
  byte, plus 64 tokens of message overhead. It has not been checked against
  this model's tokenizer, and no pilot's token usage was reported to this
  repo. Reported usage is recorded in the draft, so a violated assumption
  shows up there.

## First live pilot (owner-reported, 2026-11-07, head `9ff859b`)

The owner's observations; no live call has been made from this repo's
sessions or CI.

- The probe passed. One small exec returned
  `b'\x01atlas-framing-check\n__ATLAS_EXIT__=0\n\x03\x00'`, which
  `decode_exec_output` handles.
- The image has `python3` but no `ruff` or `shellcheck` (see Runner tools).
- The review made one model call that cost $0.17. The model reported that no
  lens ran and that it never opened `reference/lenses/*/body.md` (see Lenses).
- The source upload (about 3 MiB of stdin) failed with "The read operation
  timed out", so no in-Sprite tool ran. Both Sprites were destroyed.

What the code does and does not support about that timeout: the upload exec
was already given the remaining review deadline (about 590 seconds), not the
client's 30-second default, so a 30-second default is not the cause as the
code reads. The root cause is not known. The upload now has an explicit
300-second budget and does not depend on the exec channel delivering a stdin
EOF; the second is a hypothesis, not a confirmed cause. If it fails again, the
error names the byte count, and `probe-runner`'s stdin round-trip separates a
stdin problem from a PR-tarball problem. (The third probe's upload and unpack
later passed.)

## Second live pilot (owner-reported, 2026-11-07, head `d63f087`)

Owner-reported; nothing here was observed from this repo's sessions or CI.
The 3 MiB stdin probe passed in about 2 seconds at that head. The review
then failed with `POST …/exec failed: The read operation timed out`, without
the upload's own label, so no in-Sprite tool ran; the runner was destroyed
and verified absent. The model made one call ($0.195) and saw 13 of 77 files
(60,000 of 412,078 diff characters), missing the runner, auth, redaction and
HTTP modules.

Which exec timed out is not known. The code before this change wrapped only
upload errors, and the tool check (60-second budget) and both tool execs
(135 seconds) passed theirs through bare, so the owner's inference that it
was not the upload is consistent with the code but unproven. The changes
since then: every exec error now names its purpose, timeout, duration and
time into the run; upload and unpack are separate execs; telemetry records
every step; `probe-runner --sequence review` reproduces the exec sequence
without a model; and the diff is reviewed in risk-ordered parts.

## Third live probe (owner-reported, 2026-11-07, head `fd56ca0`)

Owner-reported; nothing here was observed from this repo's sessions or CI.
`probe-runner --sequence review --tools review` got through create, egress,
the tool check, the upload (3,062,571 bytes in 0.25 s) and the unpack
(0.33 s). Then `exec / python-compileall version` (`python3 --version`, no
stdin) timed out at its 135-second budget.

What the code shows: all three no-input execs (tool check, unpack, version)
were built the same way: the same `SpritesClient.exec` call, method, headers,
no body (urllib sends `Content-Length: 0`), the same query keys (three `cmd`,
no `stdin`), and the same blocking `read()` to end of stream. They differed
only in the third `cmd` value and the timeout. So no request-shape difference
explains the hang. The real differences:

- **The command.** It was the first exec to run a binary the tool check had
  only resolved with `command -v`. The docs list Python among many runtimes
  preinstalled in the image. How `python3` is provided there (a plain binary
  or a version-manager shim that does work before starting the interpreter,
  which deny-all egress could block) is not known. `python3 --version`
  prints before Python imports anything, so the unpacked PR files cannot
  have affected it. (The fourth probe showed this last point wrong for a
  shim: pyenv reads `.python-version` from the checkout before any Python
  starts. See below.)
- **The evidence.** The old transport read the whole body with one blocking
  `read`, so a timeout discarded any bytes that had arrived. "No frames" was
  not measured: the command may have printed and then the stream not closed.
- **Stdin.** No-input execs relied on whatever the server attaches to stdin
  when `stdin` is false, which the spec does not document. `python3 --version`
  does not read stdin, so this is not the likely cause, but it was the one
  stdin difference between the execs, and it is now gone.

The next probe tells these apart. The tool check now reports where `python3`
resolves and what that links to. Silence fails within 30 seconds, labelled.
A stall keeps the bytes that arrived, and the start marker shows whether the
shell started at all.

## Fourth live probe (owner-reported, 2026-11-07, head `9805cfc`)

Owner-reported; nothing here was observed from this repo's sessions or CI.
The start marker arrived after the unpack, then `python3 --version` sent
nothing more until its 135-second budget (17 bytes, frames `0x01:1`). So
the shell started and the command itself hung. The tool check before the
unpack reported `path_python3 = /.sprite/bin/python3`, resolving to
itself: a script, not a link. The Sprites docs say `/.sprite/bin` holds
pyenv shims over `/.sprite/languages/python/pyenv` (default 3.13.x), and
this repo's `.python-version` is `3.12`.

**Hypothesis, not yet confirmed:** run from inside the checkout, the shim
selects the PR's pinned 3.12, which is not installed, and hangs rather than
failing. The interpreter fix above does not depend on it being right: tools
no longer go through the shim at all.

`probe-runner --sequence review` now tests it, with diagnostics that never
fail the probe and each carry the outcome they expect:

| Diagnostic | When | Environment | Records |
| --- | --- | --- | --- |
| `shim` | before upload | minimal | `readlink -f` target, size, shebang and first `exec` line, read as text (the shim is never run) |
| `pyenv versions` | before upload | minimal | `ls -1` of the pyenv versions directory |
| `trusted python after unpack` | after the tools | minimal | the resolved interpreter's `-I --version`, run from `/work` |
| `shim with PYENV_VERSION` | after the tools | Sprite default | the shim from `/work` with `PYENV_VERSION` set to the resolved version, bounded to 15 s |
| `bare python3 in the checkout` | last | Sprite default | bare `python3 --version` from `/work`, bounded to 15 s by `/usr/bin/timeout`, labelled expected-may-hang |

The version before unpack is the `interpreter` event. Read together: exit
124 on the last row, a quick answer from the `PYENV_VERSION` row, and no
`3.12` in `pyenv versions` confirm the hypothesis. A quick answer on the
last row refutes it. Each bounded exec also has a 25-second stream budget,
so a hang the in-guest bound cannot end is recorded as an exec failure and
the Sprite is still destroyed. Guest output is cut to one printable line of
at most 200 characters before it reaches telemetry. Reviews never run these
diagnostics.

## Third live pilot (owner-reported, 2026-11-07, head `a246625`)

Owner-reported; nothing here was observed from this repo's sessions or CI.
The review ran end to end. Its draft is model output and was treated as
untrusted: each of its five findings was checked against the code at
`a246625` before anything changed (D30).

| Finding | Verdict | Evidence at `a246625` | Fix |
| --- | --- | --- | --- |
| The assignment redactor misses prefixed env-var names | Real | `\b(password\|...)` needs a word boundary, and `_` is a word character, so `OPENAI_API_KEY=`, `DB_PASSWORD=`, `client_secret:`, plural `tokens:` and JSON `"api_key":` all passed through | The keyword may carry up to six `_`/`.`/`-` separated name parts on either side, after a non-alphanumeric lookbehind; bounded repeats keep matching linear |
| Failed archive reads escape the decompression budget | Real | `budget.left -= len(data)` ran only after a successful read, so an entry failing its CRC check after decompressing up to 5 MiB was never charged. The cost is CPU time, not memory: each read stays capped | The declared size is charged before the read, so a failing entry spends the total budget like a good one |
| Transport deadlines are not cumulative before body reads | Partial | In the streaming exec path, connect, send and each header line got a fresh socket timeout, so a server trickling headers was unbounded until the first body read. The non-streaming `UrllibTransport` never claimed a cumulative deadline and is unchanged | A cutoff timer shuts the socket down at the first-byte deadline; see "One exec shape" |
| A failed diff fetch still triggers an empty-diff model call | Real | `selection.parts or (DiffPart(()),)` made one call with an empty diff when the fetch had failed | A failed fetch makes no call; its omission row, a NOT REVIEWED coverage note and a no-narrative sentence say why. A fetched but empty diff still gets its call |
| Risk ranking under-prioritizes CI and dependency files; PR paths reach the controller notes raw | Real | CI and build config ranked below all source, `conftest.py` ranked as a test, and part notes and the diff-fetch error interpolated PR-controlled text verbatim into the authoritative notes (a newline could forge a heading) | A supply-chain tier second only to security, matched before any directory; every untrusted value in the notes goes through `quote_untrusted` and is labelled as quoted data |

Regression tests for each were checked to fail on the old code, except a
`db.password=` case the old pattern already caught.
