# atlas_reviewer — manual Code Quality Atlas review service

An operator-triggered controller. You give it one PR event (repo, PR number,
head SHA). It collects CI evidence for that exact SHA, runs extra review tools
in a fresh Sprite with no credentials, runs the review through this repo's
collapsed `reviewing-a-change` skill bundle, and writes a **review draft** to
stdout or a file.

It never writes to GitHub. No reviews, comments, check runs, labels, or
issues. It has no webhook receiver and no queue, and runs one review at a
time. Design and decision record:
[`docs/plans/2026-11-06-manual-reviewer-service.md`](../docs/plans/2026-11-06-manual-reviewer-service.md)
(D24-D30, D32, D33, D35 and D36 in
[`docs/open-questions.md`](../docs/open-questions.md)).
D37 is the Fly one-off deploy. Other follow-ups are in that plan's
"Follow-ups" section.

## Deploy on Fly

The controller can run as one Fly Machine per review: no public service,
no standing Machine, no webhook, and no queue. The image is
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

## Run it offline (no credentials)

From the repo root:

```sh
pip install -r requirements.txt   # Python 3.12+, in a virtual environment
python -m atlas_reviewer review --event atlas_reviewer/fixtures/sample-pr/event.json --dry-run
```

`--dry-run` wires a fixture directory as GitHub, the in-memory fake as the
Sprites runner, and the offline provider, which calls no model, so the
draft reports the diff as NOT REVIEWED and its lenses as planned, not run.
No model reviewed any file, so a dry run always exits 4, review incomplete
(see Review event and the coverage gate). CI runs this same command. Useful flags:

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

## Live mode

```sh
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
| `ATLAS_OPENROUTER_API_KEY` | controller → OpenRouter adapter | Read only with `--provider openrouter --allow-live-inference`. The key must carry a hard credit limit of at most $5 |
| `ATLAS_REVIEWER_STATE_DIR` | controller | Runner ledger and single-review lock (default `.atlas-reviewer-state/`, gitignored) |

None of these values reaches a Sprite, a prompt, or the draft. Each one
goes only to the adapter that uses it. The redactor also scrubs the exact
value of the App key, the Sprites token, the OpenRouter key, and every
installation token minted during the review, on top of pattern-based
redaction. That covers the draft, the telemetry, the probe report and the
error message on stderr.

**GitHub App tokens.** `github_auth.py` signs an RS256 JWT with the App key
(PyJWT with `cryptography`, the only non-stdlib runtime dependency, used by
the controller alone). It exchanges the JWT for an installation token that
asks for `contents`, `checks`, `actions`, and `pull_requests` read, plus
`issues` read only with `--include-issues`, scoped to the event's single
repository. A response that grants any non-read permission is refused.
The token is cached until five minutes before its `expires_at`.

**CI evidence ingestion** (`gather.py`, `archive.py`). Every GitHub list
(check runs, workflow runs, the PR's commits, jobs, artifacts) follows
`Link: rel="next"` up to 10 pages. Workflow runs listed by branch name are
kept only at the PR's own commits (GitHub lists at most 250), so a
same-named branch elsewhere adds nothing; head-SHA runs are listed by SHA
too. Check runs are listed at the head SHA and at up to 20 other commits
of the PR, newest first (D38), each item keeping the SHA GitHub reported, so
a failure at an earlier commit that was never re-run stays visible as
stale. A list cut off there, a per-review count cap (5 runs, 20 other
commits, 10 job logs, 5 artifacts), an oversized download (5 MiB per log, 10 MiB per
artifact ZIP), or a rejected or partly skipped archive each appear in the
draft's **Omissions and limits hit** table. Whatever they left unread is
UNKNOWN. Logs and artifacts are fetched only for jobs and runs at the head
SHA. Artifact ZIPs are read in memory with stdlib `zipfile` and never
extracted to disk. An entry is skipped if it has an unsafe path
(absolute, drive, `..`), is a symlink or special file, is encrypted, is
compressed with anything but STORED or DEFLATED, is not on the text-type
allowlist, is binary, or exceeds the size or ratio
caps. The archive as a whole is rejected if it has more than 200 entries.

**OpenRouter limits** (`openrouter.py`, `budget.py`, `pricing.py`). Model
`anthropic/claude-sonnet-5.5` only, with no fallback models, no plugins
and no web search. Provider routing is pinned (`only`, `allow_fallbacks:
false`, `zdr`, `max_price`) to the slugs a 2026-11-07 read of the public
provider list actually exposes: `amazon-bedrock`, `google-vertex/global`,
`google-vertex/us`, and `google-vertex/europe`. The bare `google-vertex`
slug is not one of them, and the routing docs say a bare slug matches
every region of that provider, so any slug outside this list is refused
before a request. Before any inference, `preflight()` reads
`GET /api/v1/key` and refuses unless the key has a hard limit of at most
$5 with credit left. A key whose `include_byok_in_limit` is not true is
accepted, and that run is in no-BYOK mode: a model response is used only
when `usage.is_byok` is false. Any other value, including a missing
field, or an HTTP 200 whose body cannot be parsed, stops the review
as a boundary error (exit 3) before another model call, and no draft
is written. When the flag is true, a BYOK
response is accepted, as before. Each call re-reads the model's public
catalog entry and fails closed if a price or limit is missing or
unparseable. It then
checks the input bound (200k tokens), max output (24k) and reasoning
budget (12k), and reserves the call's worst case at the highest listed
price tier. A reservation is refused if it would be the fourth call in the
review (retries included), or if it could push the review past $3.00 or
past the key's remaining credit. The draft's **Model usage** section
records each call's reservation and its actual cost and tokens. The call cap
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
priced from the highest catalog rates and upstream is still not added.
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
It must reply with only `{"lenses": [...]}`, at most 8 names at review depth
(the top of review mode's 3-8 breadth) or 40 at comprehensive. The reply is
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
in rank order up to the depth's breadth, so a thin or steered pick can add
lenses but not drop a critical one. The picker call counts toward the
3-call cap.

`lenses.py` then reads each chosen lens's `reference/lenses/<lens>/body.md`
and inlines it into the trusted system prompt, in priority order, under a
**60,000-character budget** and a cap of **8 lenses**. A lens is never cut:
a lens runs only if its whole body fits what is left of the budget, and
otherwise it is **NOT RUN** and the next one is tried, so a smaller later
lens can still fit. A lens past the cap is NOT RUN too, with its size. The
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

The model gets the PR conversation as one `pull-request` block of at most
65,536 characters (`conversation.py`, D38): title, author, branches, draft
flag, labels, requested reviewers and teams, the body (up to 16,384
characters), every commit subject (200 each, 8,192 in all), and every
review, review comment and conversation comment (4,000 each), each labelled
with its id, author, time and the commit it was made at. Commit subjects
and remarks keep the newest that fit; every older one dropped, every cut,
and every list that failed, hit the page cap or held an entry that did not
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
  compare endpoint (`fetch_sources`).
- **Tools** (`bridge_args.py`). There are five, each with typed arguments:
  `diff_stat`, `diff_file` (path, byte offset), `list_files` (rev,
  prefix), `read_file` (rev, path, at most 400 lines) and `grep` (pattern,
  rev, prefix, fixed-string unless `regex`). `rev` is BASE, HEAD or a
  staged DEFAULT. Anything else is rejected before an exec, with a fixed
  code and a controller-written reason that echoes neither the tool name
  nor any value sent. A session serves at most 64 calls and 1 MiB of
  output in all, then refuses calls without running them.
- **Exec.** Each call is a fixed git argv with every value shell-quoted,
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
- **Results** are repository content and are not redacted. Each is
  scanned for committed secrets, and every hit is reported by path, line
  and pattern, pre-existing outside HEAD or in a file the PR did not
  change. Values are kept only for scrubbing and never shown. git's stderr
  is redacted. Every call is a ledger record, and telemetry names only the
  tool.

Not built yet: `log`, `blame`, `run_check` and fetching the default-branch
tarball.

## Agentic lens loop (offline, D40)

`coordinator.review_lens` reviews a PR head with one lens through the
bridge. It is not on the CLI. The offline tests run it against
`LocalSprites` with a scripted model (`fakes.ScriptedLensModel`). The
live tool-calling adapter (`tool_model.OpenRouterLensModel`) and the
Sprite keepalive (`keepalive.py`) are built and tested offline (D41):
recorded HTTP for the adapter, and `LocalSprites` plus a fake Tasks
socket for the hold. No live model, Sprite or Fly call has been made.

- **Limits.** `lens_loop.AgenticLimits` has Brandon's provisional defaults
  (2026-11-11), set for headroom and configurable, to be revisited after
  live runs: a $5 reservation, 50 model calls per review, 50 turns per
  lens, 20 minutes per lens and 60 minutes per review. An override must be
  positive and finite, and a per-lens limit no greater than its per-review
  limit. Clearing one back to unset makes `resolve` raise
  `LimitsUnsetError`, naming each unset field, before any model, runner or
  ledger work. `retries` is 1 and `pool_size` must be 1.
- **The prompt.** The system prompt is the controller's instructions, then
  the nonce fence rule, then the whole lens `body.md` between markers that
  carry its SHA-256, then `synthesis.md`'s whole *Finding contract*
  section. Nothing is cut. The
  first user turn is the operator's subject, then any context the caller
  passes and the risk-ordered changed-file list, each fenced with the
  review's nonce. It carries no diff text: the lens reads that through the
  tools, and every tool result comes back fenced.
- **One attempt** (`lens_loop.run_attempt`). Delivery is checked before the
  first model call. The attempt ends at the final reply, or when one of
  these cuts it short: the turn cap, the call cap, the dollar reservation
  (each call is reserved at the model's worst case, then settled at its
  reported cost), either wall clock, a failed model call, or the runner's
  deadline during a tool call.
- **Checking the reply.** The reply must meet the finding contract
  (`lens_contract.py`) and name the lens and its body digest. Each quote is
  checked against the head file at the cited lines. The cited span is the
  quote's own line count, so a wider range does not verify. A removed line
  of that file still verifies (`quotes.py`).
- **Partial results.** No findings counts as clean only after a
  `diff_file` page or a HEAD `read_file` of a changed file. A timed-out,
  unavailable or over-limit tool call makes the lens partial.
- **Ledger and retries** (`attestation.py`). Each attempt is fsynced to an
  append-only ledger when it starts and again when it ends, keyed by
  repository, PR, head SHA, lens and body digest. A failed attestation, an
  unparsed reply, a failed quote or an abandoned attempt is retried once
  with the body injected again; a second one escalates. A crash leaves an
  abandoned attempt that counts as used. A lens already settled for this
  head and body is reused without a runner.
- **The adapter** (`tool_model.OpenRouterLensModel`). One Chat Completions
  request per turn, with the one-shot provider pin (`require_parameters`,
  zero data retention, no fallbacks, no plugins and no server tools) and
  only the bridge's tool schemas. The loop settles `_actual_cost`, which
  includes a BYOK upstream charge. A turn with no readable cost but usable
  token counts is priced at the highest catalog rates, except when the
  model has a reasoning rate and the response reports no reasoning-token
  count. That missing-cost case stays at the reserved worst case, as do
  an unreadable upstream charge, a BYOK call with no upstream charge, and
  a turn with neither a readable cost nor usable token counts. A readable
  cost is used as reported, including when the reasoning-token count is
  missing. The catalog is fetched once per turn.
  The adapter does not
  retry and does not reserve on the one-shot budget. A tool call whose
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
  API's PUT would otherwise upsert it. Each hold exec has its own 15 second
  budget, and the guest socket call times out after 10 seconds and reads
  only the status line. Refresh and tool execs share the runner's exec lock so
  they do not write one stream; the 15 second budget is how long a
  refresh can block a tool. A keepalive failure fails the runner, and a
  failed runner is not complete coverage. Snapshot and restore is not
  built; there is no public fork API (Fly support, 2026-11-06).
- **The draft** (`coordinator.render_draft`).
  - **Status line.** The first line is a status line: `"mode": "agentic"`,
    `coverage_complete`, and the lens counts by state.
  - **Coverage.** Coverage is complete only if every selected lens settled
    clean and, when this review ran a runner, that runner completed.
    Otherwise a REVIEW INCOMPLETE warning follows, and the review never
    approves. A failed runner's note is quoted in the draft.
  - **Findings.** Verified findings carry minted `L<lens>-F<n>` IDs and are
    ranked by severity. The verdict comes from verified, introduced defects
    only. Unverified findings are listed apart and never counted. Possible
    committed secrets that the tools read are controller findings.
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
| `conversation.py` | the PR conversation block under its budget, every cut and dropped remark an omission | via `GitHubReader` |
| `archive.py` | bounded in-memory ZIP reading for untrusted artifacts | no |
| `pagination.py` | `Link` header parsing | no |
| `pricing.py`, `budget.py` | catalog/key parsing (fail closed); per-review call and cost budget | no |
| `draft.py` | Markdown draft rendering | no |
| `groups.py` | one CI gate seen as check run + job + log + workflow run → one independent check | no |
| `notes.py` | the code-generated Controller notes | no |
| `diffs.py` | split a diff into files, rank them by risk, pack them into per-call parts, fit the part size to the measured prompt | no |
| `picker.py` | run `choosing-review-lenses` as one model call, parse its reply strictly, fall back to the critical tier, skip the call when no picked lens could fit | reads the bundle |
| `verdict.py` | the proposed review event, the file-coverage gate on approval, the machine-readable status line and the incomplete-coverage warning | no |
| `telemetry.py` | lifecycle events, the `EventSink` (JSONL), labelled timed spans, the summary rows | writes the JSONL file |
| `instrumented.py` | `GitHubReader` wrapper that records every read as an event | via `GitHubReader` |
| `lenses.py` | load the chosen lenses' bodies whole under the budget and cap, or mark them NOT RUN with a reason | reads the bundle |
| `bridge.py` | the read-only git tool bridge: per-call scripts, capped base64 replies, result statuses, secret locations, the call ledger, `run_bridge` | via `SpritesApi` |
| `bridge_args.py` | the closed tool set and its argument rules (`validate`, `arg_names`, `required_args`) | no |
| `source_archive.py` | the unpacked-size and member caps a source tarball must pass before upload (`measure`) | no |
| `guest_unpack.py` | the same caps held again in the runner: its tar measures bytes, members and implied directories before extracting, then `ulimit -f` while extracting, every tar run under `timeout` | no |
| `bridge_staging.py` | Option B staging: trusted git, the hardened git options, tarballs committed into a bare repository, `fetch_sources` | via `SpritesApi`, `GitHubReader` |
| `lens_contract.py` | a lens's final reply under the finding contract, parsed strictly into typed findings (`parse_reply`); refusals never echo model text | no |
| `quotes.py` | check each finding's quoted evidence against the head file at the cited lines (the span is the quote's line count), or the diff's removed lines (`check_quote`) | no |
| `attestation.py` | lens-body delivery and acknowledgement checks, attempt outcomes and lens states, the append-only attempt ledger (`AttemptLedger`), the retry-once policy (`next_step`) | writes the ledger file |
| `lens_loop.py` | the agentic limits (Brandon's provisional defaults, 2026-11-11), the `LensModel` port and its messages, tool schemas built from `bridge_args.TOOLS`, the lens system prompt, the spend tracker, one lens attempt (`run_attempt`) | via `Bridge`, `LensModel` |
| `coordinator.py` | one lens under the ledger in one runner session (`review_lens`), minted IDs, ranking, the mechanical verdict, the status line and draft; holds the Sprite for the lens (`keepalive.lens_hold`) | via ports, the ledger |
| `tool_model.py` | the live tool-calling adapter (`OpenRouterLensModel`): one pinned Chat Completions request per `LensModel` turn, strict tool-call arguments, cost from `_actual_cost` (BYOK upstream included; catalog rates when the cost is missing but the token counts are usable; a reasoning rate with no reasoning-token count is unpriced only when the cost is also missing). Not on the CLI. Tested with recorded HTTP only | via the OpenRouter client |
| `keepalive.py` | the Sprite Tasks API hold for one lens: create, refresh every 60 seconds with a 5-minute expiry, delete on exit. Not on the CLI. Tested with `LocalSprites` and a fake socket | via the runner exec |
| `ports.py` | the adapter interfaces (`GitHubReader`, `SpritesApi`, `ModelProvider`, `ReviewHarness`, `RunnerLedger`, `Clock`); the agentic `LensModel` port is in `lens_loop.py` | no |
| `runner.py` | disposable-runner lifecycle (create → deny-all → verify → tool check → resolve interpreter → upload → unpack → tools → destroy), `probe_runner`, `run_session` (a `Session` on the same lifecycle), the one exec wrapper (`exec_argv`, minimal `env -i` environment) | via `SpritesApi` |
| `interpreter.py` | the resolve script, `choose_python` (accepts only the pyenv-versions and `/usr/bin/python3` path shapes), `{python}` substitution, the probe-only diagnostic scripts and output summary | no |
| `gather.py` | CI evidence labelled by SHA: check runs at the head and other PR commits, workflow runs, head-SHA job logs and artifact contents, omissions | via `GitHubReader` |
| `controller.py` | one event in, one draft and its review verdict out | via ports |
| `harness.py` | skill-bundle harness: loads `collapsed/skills/reviewing-a-change/SKILL.md` | reads the bundle |
| `providers.py` | `OfflineProvider` (the default) | no |
| `github_api.py`, `github_auth.py`, `sprites_api.py`, `openrouter.py`, `http.py` | live adapters | network |
| `github_fixture.py`, `fakes.py`, `ledger.py`, `clock.py` | offline adapters, local state | local files |
| `cli.py`, `__main__.py` | entry point, dispatch tables | env, files |

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
3. **OpenRouter.** Create a key with a hard credit limit of at most $5 and
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
