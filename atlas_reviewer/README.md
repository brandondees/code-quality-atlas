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
(D24-D30 and D32 in [`docs/open-questions.md`](../docs/open-questions.md)).
Planned follow-ups, none built here, are listed in that plan's
"Follow-ups" section.

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
  retries included. One goes to the lens picker (except at triage depth, or
  with only one call), the rest to diff parts (see Lenses and Diff coverage).
- `--diff-chars-per-call N` (default 176000, at least 1000) is the most diff
  characters a model call may carry. Each review shrinks it further until
  every planned prompt fits the token bound (see Diff coverage).
- `--depth {triage,review,comprehensive}` (default `review`) is the atlas
  depth mode. Triage runs the critical tier with no picker call.
- `--events FILE` writes lifecycle telemetry as JSONL (see Lifecycle
  telemetry). A dry run writes none without it.
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
parsed strictly, and a name with no body in the bundle is listed as omitted.
With no diff there is no model call at all (see Diff coverage). At
**triage** depth or with `--max-model-calls 1`, no picker call is made and
the critical tier runs (`tracing-correctness-and-invariants`,
`sweeping-for-security`, `reviewing-migration-and-data-safety`,
`reviewing-concurrency-and-async`, from `docs/review-depth-modes.md`). An
unusable reply also falls back to the critical tier, and the controller
notes quote the reason. The picker call counts toward the 3-call cap.

`lenses.py` then reads each chosen lens's `reference/lenses/<lens>/body.md`
and inlines the bodies into the trusted system prompt, in pick order, under a
**60,000-character budget** and a cap of **8 lenses**. A lens that does not
fit is cut at a line boundary and marked truncated, or omitted when under
4,000 characters of budget remain. The draft's **Review lenses** table and the
controller notes say which lenses were included, truncated or omitted, with
character counts and the picker rank, and the prompt tells the model that
only inlined lenses ran. PR text can steer the pick, but only within the
closed set of lens names in the bundle. `reference/synthesis.md` and
`reference/tool-evidence.md` are not inlined.

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
`fixtures/`) demotes them; then tests, config and docs, so
`tests/test_redact.py` is a test and `docs/security.md` a doc. Parts are
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
kept, files sent in full, files cut, and every file never sent, grouped by
risk tier, highest first. A part whose call fails or is refused (call cap,
cost cap, token bound) gets its own row listing the files sent but not
reviewed. After the calls, a controller note states whether coverage is
complete or PARTIAL and how many files each outcome covers. Nothing short of
every file sent in full with every call returning a review is called
complete.

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

With the picker call, review depth sends at most 2 parts; triage sends up to
3. A diff over that capacity is PARTIAL: the omissions row says "too large
for one review pass", and the coverage note says the cut and unsent files
are listed there, highest risk first. The second pilot's 412,078-character
diff would still be PARTIAL, with the unseen files being the lowest-risk
tiers.

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
| `diffs.py` | split a diff into files, rank them by risk, pack them into per-call parts, fit the part size to the measured prompt | no |
| `picker.py` | run `choosing-review-lenses` as one model call, parse its reply strictly, fall back to the critical tier | reads the bundle |
| `telemetry.py` | lifecycle events, the `EventSink` (JSONL), labelled timed spans, the summary rows | writes the JSONL file |
| `instrumented.py` | `GitHubReader` wrapper that records every read as an event | via `GitHubReader` |
| `lenses.py` | load and budget the chosen lenses' bodies | reads the bundle |
| `ports.py` | the adapter interfaces (`GitHubReader`, `SpritesApi`, `ModelProvider`, `ReviewHarness`, `RunnerLedger`, `Clock`) | no |
| `runner.py` | disposable-runner lifecycle (create → deny-all → verify → tool check → resolve interpreter → upload → unpack → tools → destroy), `probe_runner`, the one exec wrapper (`exec_argv`, minimal `env -i` environment) | via `SpritesApi` |
| `interpreter.py` | the resolve script, `choose_python` (accepts only the pyenv-versions and `/usr/bin/python3` path shapes), `{python}` substitution, the probe-only diagnostic scripts and output summary | no |
| `gather.py` | head-SHA CI evidence: lists, job logs, artifact contents, omissions | via `GitHubReader` |
| `controller.py` | one event in, one draft out | via ports |
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
  still fenced as untrusted data when sent. All of it is redacted before
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
  (fed through `head -c N` into `/tmp/atlas-source.tar.gz`, so nothing
  waits for a stdin EOF) with a 300-second budget, and the runner reports the bytes it wrote,
  which must equal the bytes sent. A second exec unpacks it into `/work`
  with a 120-second budget. The tool check has 60 seconds and each tool
  exec its timeout plus 15. Every budget is capped by the remaining review
  deadline. The controller fetches the tarball with its own token. An external
  deadline is enforced by a watchdog timer. Destroy runs in `finally` and
  from the watchdog. It is idempotent and is verified by a follow-up
  existence check. The runner name is written to the ledger before create,
  so `sweep` can clean up after a crashed controller.

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
