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
(D24 in [`docs/open-questions.md`](../docs/open-questions.md)).

## Run it offline (no credentials)

From the repo root:

```sh
python -m atlas_reviewer review --event atlas_reviewer/fixtures/sample-pr/event.json --dry-run
```

`--dry-run` wires a fixture directory as GitHub, the in-memory fake as the
Sprites runner, and the offline provider, which calls no model. CI runs this
same command. Useful flags:

- `--out draft.md` writes the draft to a file.
- `--expect check_run:NAME` (repeatable) names evidence that must exist. If
  it is absent, the draft reports it as UNKNOWN. Valid kinds: `check_run`,
  `workflow_run`, `job`, `workflow_log`, `artifact`, `runner_tool`.
- `--include-issues` opts in to fetching the issues the PR body closes.
  Off by default.
- `--deadline-seconds N` sets the external runner deadline (default 600).
- `--max-model-calls N` (1 to 3, default 3) caps model calls per review,
  retries included, and so also caps how many diff parts are reviewed (see
  Diff coverage).
- `--diff-chars-per-call N` (default 60000, at least 1000) is how many diff
  characters each model call may carry.
- `--events FILE` writes lifecycle telemetry as JSONL (see Lifecycle
  telemetry). A dry run writes none without it.

Tests: `python -m pytest atlas_reviewer/tests -q --cov=atlas_reviewer`.

## Live mode

```sh
python -m atlas_reviewer review --event event.json   # GitHub App + Sprites, offline provider
python -m atlas_reviewer review --event event.json \
  --provider openrouter --allow-live-inference       # plus one capped OpenRouter review
python -m atlas_reviewer probe-runner                # Sprites protocol, tool and stdin check, nothing from a PR
python -m atlas_reviewer probe-runner --sequence review --tarball checkout.tar.gz
                                                     # the review's exact exec sequence on a real checkout, no model
python -m atlas_reviewer sweep                       # destroy runners a crashed review left behind
```

`probe-runner --sequence review` runs the same `run_disposable` exec order a
review uses: tool check, tarball upload, unpack, then a trivial tool
(`--tools trivial`, the default, counts the unpacked files) or the review's
default tools (`--tools review`). It calls no model and gathers no CI
evidence. The source is a local `.tar.gz` (`--tarball`, for example from
`git archive --format=tar.gz --prefix=src/ HEAD`) or the head-SHA tarball
fetched with the GitHub App (`--event`, needing the three `ATLAS_GITHUB_*`
variables). Both are held to the review's 9 MiB tarball cap.

`sweep` takes the same single-review lock as `review` and `probe-runner`.
The ledger lists a live review's runner too, so sweeping during a review
would destroy that runner mid-run. While a review holds the lock, `sweep`
exits with the usage error (2) and destroys nothing.

`--state-dir DIR` is a top-level option, so it goes before the subcommand.
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
redaction.

**GitHub App tokens.** `github_auth.py` signs an RS256 JWT with the App key
(PyJWT with `cryptography`, the only non-stdlib runtime dependency, used by
the controller alone). It exchanges the JWT for an installation token that
asks for `contents`, `checks`, `actions`, and `pull_requests` read, plus
`issues` read only with `--include-issues`, scoped to the event's single
repository. A response that grants any non-read permission is refused.
The token is cached until five minutes before its `expires_at`.

**CI evidence ingestion** (`gather.py`, `archive.py`). Every GitHub list
(check runs, workflow runs, jobs, artifacts) follows `Link: rel="next"`
up to 10 pages. A list cut off there, a per-review count cap (5 runs, 10
job logs, 5 artifacts), an oversized download (5 MiB per log, 10 MiB per
artifact ZIP), or a rejected or partly skipped archive each appear in the
draft's **Omissions and limits hit** table. Whatever they left unread is
UNKNOWN. Logs and artifacts are fetched only for jobs and runs at the head
SHA. Artifact ZIPs are read in memory with stdlib `zipfile` and never
extracted to disk. An entry is skipped if it has an unsafe path
(absolute, drive, `..`), is a symlink or special file, is encrypted, is
not on the text-type allowlist, is binary, or exceeds the size or ratio
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
$5 with credit left. Each call re-reads the model's public catalog entry
and fails closed if a price or limit is missing or unparseable. It then
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
and is not a mismatch. Cost is taken from each response's `usage.cost`, never
from that counter.

## What the draft contains

In order: the evidence summary, **Controller notes**, **Review lenses**, the
independent-checks table, every evidence item, UNKNOWN items, omissions,
model usage, **Lifecycle telemetry**, and the model's narrative, one
subsection per diff part when the diff was split.

- **Controller notes** are generated by code from facts the controller
  established (`notes.py`), never by the model: the runner's cleanup proof
  (for example "destroyed and verified absent by an existence check"),
  whether it completed and why not, each tool's result or why it did not run,
  the omissions hit, lens coverage, and operator-relevant notes such as a
  moved PR head. The model receives the same text in a `controller-notes`
  block and is told to treat it as established fact, so a narrative cannot
  call cleanup unverified when the controller proved it. Where a narrative
  disagrees, the draft says the notes section is authoritative. The block
  can quote runner output, so it is fenced as untrusted data like the rest.
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
them (the first pilot's model said so). `lenses.py` picks lenses from the
changed paths in the diff and the PR title and body, using a code-side digest
of the route table in `collapsed/skills/reviewing-a-change/SKILL.md` (a test
checks that every lens it names exists in the bundle). It ranks them, reads
each lens's `reference/lenses/<lens>/body.md`, and inlines the bodies into the
trusted system prompt, in rank order, under a **60,000-character budget** and a
cap of **6 lenses**. A lens that does not fit is cut at a line boundary and
marked truncated, or omitted when under 4,000 characters of budget remain.
The draft's **Review lenses** table and the controller notes say which lenses
were included, truncated or omitted, with character counts, and the prompt
tells the model that only inlined lenses ran. The selection is a coarse
path-and-keyword heuristic, not a classifier: it can pick a lens that does not
fit and miss one that does, and the table shows what it chose and why. The
summed prompt is still bound by the 200k-token input check, and a prompt over
it is refused, not trimmed. `reference/synthesis.md` and
`reference/tool-evidence.md` are not inlined.

## Runner tools

The default tools are `python-compileall` only (`python3 -m compileall`). The
pilot found `python3` but neither `ruff` nor `shellcheck` in the Sprite image.
They are dropped from the defaults because egress is deny-all and a Sprite
is never reused, so nothing can be installed into a runner, and a binary the
image lacks can only ever produce UNKNOWN rows. The repo's own CI already
reports lint, so the CI evidence covers it. To add a tool once the image
ships its binary, append a `ToolSpec(name, binary, version_cmd, run_cmd)` to
`DEFAULT_TOOLS` in `controller.py`; `probe-runner` shows which binaries the
image has, and a configured tool whose binary is missing is still reported
UNKNOWN and never executed.

## Diff coverage

The diff is split into files and reviewed in up to `--max-model-calls` parts
of at most `--diff-chars-per-call` characters each, one model call per part
(`diffs.py`). Files are ordered by risk, not by their order in the diff:
security, auth, secrets and redaction first; then the runner, sandbox, HTTP
and model boundary; other code; config, CI and build; tests and fixtures;
docs last. Tier is decided by path patterns, with tests, config and docs
matched first, so `tests/test_redact.py` is a test and `docs/security.md` a
doc. Parts are filled first-fit in that order. A file larger than one part
is cut at a line boundary into a part of its own and marked cut. A file
that fits nowhere once every part is used is never sent.

Each call gets the same PR, evidence and controller-notes blocks plus its
own part, and a controller note naming the files in that part and saying
that other parts go to separate calls. When coverage is incomplete, the
**Omissions and limits hit** table has a `pull request diff` row: characters
kept, files sent in full, files cut, and every file never sent, grouped by
risk tier, highest first. A part whose call fails or is refused (call cap,
cost cap, token bound) gets its own row listing the files sent but not
reviewed. After the calls, a controller note states whether coverage is
complete or PARTIAL and how many files each outcome covers. Nothing short of
every file sent in full with every call returning a review is called
complete.

The defaults (3 calls of 60,000 characters) review about 180,000 characters
of diff. The second pilot's diff was 412,078 characters, so a diff that size
is still PARTIAL, with the unseen files being the lowest-risk tiers.

The PR body and each issue body are cut at 2,000 characters, and each cut is
an omissions row too. Omissions are computed before the evidence block is
built, so the model is told what it did not see. Check summaries, log tails
(the end of the log is kept by design) and artifact excerpts are capped too,
but those caps are not listed as omissions.

## Lifecycle telemetry

Every step of a review or probe is one structured event (`telemetry.py`):
GitHub evidence and tarball fetches, model preflight, runner ledger record,
create, deny-all set and read-back, memory limit, every exec, the tool
check, upload, unpack, each tool, each model call, each delete attempt,
the existence check, and the cleanup outcome. An exec event carries its
purpose, timeout, bytes sent and received, the stream-id bytes seen
(`frames_seen`, for example `0x01:1`), the exit status, and its duration.
The upload event carries the byte count the runner reports writing.

Events go to one `EventSink`. Live commands write JSONL to `--events FILE`,
or by default to `<state dir>/telemetry/<command>-<UTC time>.jsonl`. Each line
is written and closed as it happens, so a killed run keeps its events. The
draft and `probe-runner` print the same events as a summary table. Field
values are numbers, booleans or controller-chosen labels (step labels never
include branch names or other PR text). Error text goes through a redactor
holding every credential value from the environment, plus the pattern rules,
before any sink sees it.

`Telemetry.span` re-raises a failure with its phase and step, how long the
step ran, and how far into the run it failed, for example
`exec / tool check failed after 60.0s (61.2s into the run): POST
https://api.sprites.dev/v1/sprites/NAME/exec failed: The read operation timed
out`. The innermost step labels the error, so nothing surfaces as a bare
timeout.

## Module layout

| Module | Job | I/O? |
| --- | --- | --- |
| `domain.py` | closed types: `PrEvent`, `EvidenceItem`, `Matched`/`Stale`/`Missing`, `Outcome`, `Omission` | no |
| `classify.py` | evidence vs. the head SHA → matched / stale / missing | no |
| `redact.py` | secret redaction; `RedactedText` can only come from `redact()` | no |
| `prompt.py` | trusted system prompt + nonce-fenced untrusted blocks | no |
| `evidence.py` | GitHub JSON / runner results → `EvidenceItem`, shape validation | no |
| `archive.py` | bounded in-memory ZIP reading for untrusted artifacts | no |
| `pagination.py` | `Link` header parsing | no |
| `pricing.py`, `budget.py` | catalog/key parsing (fail closed); per-review call and cost budget | no |
| `draft.py` | Markdown draft rendering | no |
| `groups.py` | one CI gate seen as check run + job + log + workflow run → one independent check | no |
| `notes.py` | the code-generated Controller notes | no |
| `diffs.py` | split a diff into files, rank them by risk, pack them into per-call parts | no |
| `telemetry.py` | lifecycle events, the `EventSink` (JSONL), labelled timed spans, the summary rows | writes the JSONL file |
| `instrumented.py` | `GitHubReader` wrapper that records every read as an event | via `GitHubReader` |
| `lenses.py` | choose lenses from changed paths and PR text, load and budget their bodies | reads the bundle |
| `ports.py` | the adapter interfaces (`GitHubReader`, `SpritesApi`, `ModelProvider`, `ReviewHarness`, `RunnerLedger`, `Clock`) | no |
| `runner.py` | disposable-runner lifecycle (create → deny-all → verify → tool check → upload → unpack → tools → destroy), `probe_runner` | via `SpritesApi` |
| `gather.py` | head-SHA CI evidence: lists, job logs, artifact contents, omissions | via `GitHubReader` |
| `controller.py` | one event in, one draft out | via ports |
| `harness.py` | skill-bundle harness: loads `collapsed/skills/reviewing-a-change/SKILL.md` | reads the bundle |
| `providers.py` | `OfflineProvider` (the default) | no |
| `github_api.py`, `github_auth.py`, `sprites_api.py`, `openrouter.py`, `http.py` | live adapters | network |
| `github_fixture.py`, `fakes.py`, `ledger.py`, `clock.py` | offline adapters, local state | local files |
| `cli.py`, `__main__.py` | entry point, dispatch tables | env, files |

## Trust boundaries

- **Trusted:** the operator's event file, this repo's skill bundle, the
  controller's own code and `ToolSpec` commands.
- **Untrusted:** everything from the PR. That means the diff, title and body,
  check names and summaries, job logs, artifact metadata and contents,
  runner tool output, issue text, and the model's own output. Lens bodies and
  the controller notes' fixed sentences are trusted, but the notes can quote
  runner output, so they are fenced as untrusted data when sent. All of it is redacted before
  it reaches a prompt or the draft. In the prompt it sits inside
  `<untrusted-data id="NONCE">` fences, and the system prompt says never to
  follow instructions found there.
- **Runner:** a fresh Sprite for every review, never reused. Deny-all egress
  (`{"action": "deny", "domain": "*"}`) is set from the outside API and read
  back before anything runs. Memory is capped at 1024 MB. The Sprite gets no
  connectors and no credentials. A probe (`command -v` for each tool
  binary) runs before the source is uploaded, so PR code cannot answer it.
  A binary it does not report present is never executed and its tool is
  UNKNOWN. Source goes in as the head-SHA tarball over exec stdin
  (`head -c N > /tmp/atlas-source.tar.gz`, so nothing waits for a stdin
  EOF) with a 300-second budget, and the runner reports the bytes it wrote,
  which must equal the bytes sent. A second exec unpacks it into `/work`
  with a 120-second budget. The tool check has 60 seconds and each tool
  exec its timeout plus 15. Every budget is capped by the remaining review
  deadline. The controller fetches the tarball with its own token. An external
  deadline is enforced by a watchdog timer. Destroy runs in `finally` and
  from the watchdog. It is idempotent and is verified by a follow-up
  existence check. The runner name is written to the ledger before create,
  so `sweep` can clean up after a crashed controller.

## What a live run still needs

Everything above is tested offline only, against fakes and fixtures, except
for the one pilot below. Before another live review:

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

## First live pilot (owner-reported, 2026-11-07, head `9ff859b`)

One pilot ran from a trusted machine. These are the owner's observations; no
live call has been made from this repo's sessions or CI.

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
stdin problem from a PR-tarball problem.

Still unverified against live responses:

- **The Sprites exec response body.** The framing is observed for a small
  echo, and a 3 MiB stdin round-trip passed in the second pilot's probe. A
  review's tarball upload and unpack have not yet been seen to succeed.
- **The GitHub and OpenRouter response shapes.** From the pilot's draft
  (which held a check run, job, log and workflow run) the list shapes parsed;
  this is inferred from the owner's report and is not a recorded response. Not
  yet seen live: a job's `check_run_url` (taken from GitHub's documentation;
  without it the controller simply does not group that job), artifacts,
  pagination past one page, and OpenRouter's error and retry responses. The
  OpenRouter key preflight, catalog read and one chat completion worked.
- **The input-token bound.** It assumes no token encodes less than one UTF-8
  byte. The pilot's token usage was not reported to this repo, and the
  prompt is now larger because lens bodies are inlined.

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
