# Manual reviewer service — first operator-triggered review path

**Status: implemented and frozen as the single-prompt manual reviewer
(first slice 2026-11-06; live-readiness slice, pilot fixes, diff fitting
and the lens picker 2026-11-07).** The service runs end to end offline:
fixture GitHub, the in-memory Sprites fake, and the offline provider. The
second slice adds everything a live run needs in code: pagination, head-SHA
job-log and artifact ingestion, in-process GitHub App tokens, the
documented Sprites exec protocol with a tool probe, and a capped OpenRouter
provider. The owner ran three live pilots and two live probes from a
trusted machine (below). The third pilot, at `a246625`, ran end to end.
The fixes made after each run (D26-D30, D32) are tested offline only. What
a live run still needs is under [Live-run gaps](#live-run-gaps), and what
is left for later is under [Follow-ups](#follow-ups-not-in-this-slice).
Decision records in [`../open-questions.md`](../open-questions.md): **D24**
(this service) and **D25** (the live-readiness slice); **D26-D30** (the
fixes driven by each live run); **D32** (diff fitting and the lens
picker). All are scoped steps under the still-open **Q24**. **D31** is a
separate, undecided proposal for a lens-based agentic reviewer, and none of
it is built here.

**Goal.** Produce one Code Quality Atlas review **draft** for one PR commit.
The run is triggered by an operator and funded by the operator. It never
publishes to GitHub. It reuses CI evidence only when that evidence is for
the exact head SHA. Any extra tools run in a disposable runner that holds
no credentials.

**Approved flow.** The operator triggers the controller with a PR event
(repo, PR number, head SHA). The controller gathers CI evidence for that
SHA: check runs, workflow runs and their logs, and artifact metadata. It
then runs extra tools in a fresh Sprite with no credentials. Finally it
runs the skill bundle through a harness/provider adapter and writes the
review draft to stdout or a file.

## Where it lives, and why here

`atlas_reviewer/` is a new top-level Python package. It has its own entry
point (`python -m atlas_reviewer`), its own tests (`atlas_reviewer/tests/`),
its own CI steps (a separate pytest + coverage run and an offline dry run),
and its own README. Nothing under `skills/`, `collapsed/`, `tooling/`, or
`commands/` imports it. It reads exactly one thing from the rest of the
repo: the generated `collapsed/skills/reviewing-a-change/SKILL.md`, which
is the skill bundle it runs, read as data.

- **Not a conflict with the decision log.** No `D`-entry rules out code
  beyond the skill pipeline in this repo. D1 frames the project as a skill
  suite, and this service *consumes* that suite rather than changing it.
  Q24 asks whether the reviewer should move to a substrate with "direct
  control over the container, its filesystem, and its process lifecycle".
  It is open with no disposition. The owner's approval of this flow is a
  partial, reversible answer, recorded as D24, and Q24 stays open.
- **Not `tooling/`.** `tooling/` is the generation/drift/eval pipeline for
  the skills. Mixing a credential-holding controller into it would blur
  both boundaries and pull its coverage and mypy scope along.
- **Not the separate private webhook router.** Webhooks are off for this
  path, and that router is a different codebase and stack. Nothing here
  depends on it.
- **Stack: the repo's own.** Python 3.12+, pytest with the 94% coverage
  floor (`[tool.coverage.report]`, applied to this package's own run),
  ruff with the repo's rule set, and mypy (`[tool.mypy] files` now lists
  `atlas_reviewer`). The adapters use the stdlib (`urllib`, `zipfile`,
  `tarfile`, `fcntl`) plus one vetted dependency, `PyJWT[crypto]`, added in
  the second slice for RS256 App-token signing (D25). Only
  `github_auth.py` imports it. Nothing argued for a second stack: the work
  is HTTP plus pure data shaping.
- **License.** MIT, like `tooling/` (D11). `LICENSE` and
  `tests/test_license_paths_exhaustive.py` classify the new directory.

## Types and module layout (sketched first)

The domain is closed. `Evidence = Matched | Stale | Missing`. `Matched` and
`Stale` check their SHA relationship when constructed, so a `Matched` item
for another SHA cannot be built. `outcome()` returns PASS or FAIL only for
`Matched` evidence whose conclusion is success / failure / timed_out /
action_required. Every other case is UNKNOWN; artifacts, which carry no
verdict, get a separate "present, no verdict" outcome. Every `EvidenceItem`
carries `head_sha`, `provenance` (kind, name, and a source id such as
`check_run:1001`, `job_log:7001` or `artifact:9001:zip`), `tool` (name + version, or
`unreported` where GitHub does not report one), a timezone-aware
`fetched_at`, and a `conclusion`.

Untrusted text is typed. `RedactedText` can only be minted by `redact()`,
and `UntrustedBlock`, the only way PR data enters a `Prompt`, accepts only
`RedactedText`.

The per-module table is in [`atlas_reviewer/README.md`](../../atlas_reviewer/README.md#module-layout).
The pure core (`domain`, `classify`, `redact`, `prompt`, `evidence`, `draft`)
does no I/O. All I/O sits behind the ports in `ports.py`.

## Evidence rules

- An item whose `head_sha` differs from the event's is **Stale** (UNKNOWN).
  This holds even when the API was asked to filter by SHA. The classifier
  never trusts the filter.
- A source is **expected** at the head SHA when the operator named it
  (`--expect`), or when it was observed on another commit of the same PR.
  An expected source with no head-SHA item is **Missing** (UNKNOWN).
- A failed fetch is Missing with the error as its reason. So is a tool
  absent from the runner image, or one the runner never reached. None of
  these is ever a pass.
- When the PR head has moved past the event SHA, the draft says so. It
  still only counts evidence for the event SHA. The diff endpoint serves
  the current head, so the diff goes to no model call unless the head
  equals the event SHA both before and after it is fetched.
- Issue text is off by default (`--include-issues` turns it on). It needs
  the extra `issues: read` permission.
- Every limit that stops a read is an **omission**: a page cap on a GitHub
  list, a per-review count cap, an oversized log or artifact, a rejected
  archive, or a skipped archive entry. The draft lists each omission, and
  whatever it left unread is Missing (UNKNOWN). Job logs and artifact
  contents are fetched only for jobs and runs whose `head_sha` matches.

## Untrusted bytes (second slice)

Job logs and artifact ZIPs are PR-controlled bytes. The controller caps
every download in the transport (5 MiB per log, 10 MiB per artifact, and
an artifact whose listed size is already over the cap is never
downloaded). It reads ZIPs in memory with stdlib `zipfile` and never
extracts them. The archive as a whole is rejected if it is not a ZIP or
has more than 200 entries. An entry is skipped, and the skip listed, if:

- its path is absolute, has a drive letter or `..`, or contains NUL
- it is a symlink or special file (from the Unix mode in `external_attr`)
- it is encrypted
- its suffix is not on a short text allowlist
- it contains NUL bytes
- its declared size is over 5 MiB, or its declared ratio is over 100:1
- the 20 MiB total budget is already spent

CPython's `zipfile` never yields more than an entry's declared size and
checks its CRC-32 at the end, so a header that under-declares its size
fails as unreadable (tested). Every text is redacted before use, and an
artifact's excerpt is capped at 4,000 characters. Nothing is executed.

## Runner lifecycle

Based on the 2026-11-06 live Sprites validation. The order is:

1. Write the runner name to the ledger, before anything exists remotely.
2. Create a fresh Sprite. Never reuse one: guests can restore checkpoints
   and create Tasks.
3. Set deny-all egress from the outside API, then **read it back**. If the
   read-back is anything other than exactly `deny *`, nothing executes.
4. Cap memory at 1024 MB.
5. Probe tool availability (`command -v` for each tool's binary) before any
   PR bytes are uploaded. A binary that is not reported present is never
   run, and its tool is UNKNOWN. If the probe itself fails, every tool is
   UNKNOWN.
6. Resolve the trusted Python interpreter from an empty directory, before
   any PR byte is in the Sprite (D29).
7. Upload the head-SHA tarball over exec stdin, capped at 9 MiB against the
   documented 10 MiB stdin limit, to a file
   (`head -c N > /tmp/atlas-source.tar.gz`, so nothing waits for a stdin
   EOF). The runner reports the bytes it wrote, which must equal N. The
   exec has a 300-second budget.
8. Unpack the file into `/work` in a second exec (120-second budget), so a
   transport stall and a slow extraction fail under different labels.
9. Run each available tool under `timeout`.
10. Destroy the Sprite.

Every exec budget (tool check 60 seconds, upload 300, unpack 120, each tool
exec its timeout plus 15) is capped by the remaining deadline. Every step
is a telemetry event (D27), and every failure is re-raised with its phase,
step, duration and time into the run.

Every step checks an external deadline. A watchdog timer destroys the
Sprite at the deadline even while an exec is hung. `finally` destroys it on
success, on a handled error, and on an unexpected exception (which still
propagates).

Destroy is idempotent and thread-safe. A 404 counts as already destroyed,
a failed delete is retried once, and a follow-up existence check verifies
the result. Only a verified destroy clears the ledger. An unverified one is
reported in the draft and left for `sweep`.

Exec follows the Sprites OpenAPI 0.1.12 (`POST /v1/sprites/{name}/exec`:
argv as repeated `cmd` query parameters, `stdin=true` on every exec since
D28, raw octet-stream body of at most 10 MiB). The document does not
specify the 200 response body, and the 2026-11-06 live validation saw
stdout prefixed with the WebSocket framing byte 0x01. So the decoder strips
bytes 0x00–0x04 and takes the exit code from an in-band marker that each
script prints last. `probe-runner` exists to check this live. It
provisions a runner, probes, prints one raw exec response, and destroys
the runner.

Exec-session kill was not tested live, so it is never used. The live
adapter refuses to manage any Sprite whose name does not start with
`cqa-rev-`. No port method can pass an environment, a file, a connector, or
a token into a Sprite.

## Adapters

| Port | Offline (tests, `--dry-run`) | Live |
| --- | --- | --- |
| `GitHubReader` | `FixtureGitHub` (fixture directory) | `GitHubClient`: GET-only; redirects followed manually, up to 3, keeping credentials only while the chain stays on the API origin and **without** them once it leaves (stdlib urllib would replay `Authorization`, confirmed against CPython 3.12's `redirect_request`); `Link: rel="next"` followed to a 10-page cap, and a link off the API origin is refused |
| `TokenSource` | `StaticToken` (tests only) | `AppInstallationTokens`: RS256 JWT → read-only, single-repo installation token, cached until 5 minutes before expiry |
| `SpritesApi` | `FakeSprites` (records calls; fault/hang injection; configurable installed binaries) | `SpritesClient`: outside control-plane API, per OpenAPI 0.1.12 |
| `ModelProvider` | `OfflineProvider` (calls no model; the default) | `OpenRouterProvider`: `anthropic/claude-sonnet-5.5`, pinned routing, key preflight, per-review budget (D25) |
| `ReviewHarness` | `SkillBundleHarness` over the offline provider | same harness over a live provider |
| `RunnerLedger` | `MemoryLedger` | `FileLedger` (fsynced append) |

## Live-run gaps

Setup still required, all of it tested only against fakes:

1. **Sprites probe.** Re-run `probe-runner` from a trusted machine and
   check the stdin round-trip line, then `probe-runner --sequence review`,
   which runs a review's exact exec sequence on a real checkout without a
   model and prints the telemetry table. The pilot found `python3` but no `ruff`
   or `shellcheck` in the image, so the default tools are now
   `python-compileall` only; a tool is added once the image has its binary.
2. **GitHub App installation.** Set `ATLAS_GITHUB_APP_ID` (App 5648875),
   `ATLAS_GITHUB_APP_PRIVATE_KEY` and `ATLAS_GITHUB_INSTALLATION_ID`. The
   installation ID is not recorded in this repo.
3. **OpenRouter key.** Set `ATLAS_OPENROUTER_API_KEY` to a key whose hard
   credit limit is at most $5.
4. **A test PR** with finished CI at the event's head SHA.

### First live pilot (owner-reported, 2026-11-07, head `9ff859b`)

The probe passed, with exec framing
`b'\x01atlas-framing-check\n__ATLAS_EXIT__=0\n\x03\x00'`, which the decoder
handles. The image has `python3` and neither `ruff` nor `shellcheck`. The
review made one model call costing $0.17. The source upload (about 3 MiB)
timed out, so no in-Sprite tool ran, and both Sprites were destroyed. The
model reported that no lens ran. D26 records the fixes: the upload budget, the
default tools, lens bodies in the prompt, grouped checks, controller notes,
recorded truncation, the sweep lock, and the OpenRouter counter-lag note.

### Second live pilot (owner-reported, 2026-11-07, head `d63f087`)

The 3 MiB stdin probe passed in about 2 seconds. The review then failed
with `POST …/exec failed: The read operation timed out`, without the
upload's label, so no in-Sprite tool ran; cleanup was verified. One model
call ($0.195) saw 13 of 77 files (60,000 of 412,078 diff characters), and
missed the runner, auth, redaction and HTTP modules. Which exec timed out
is not known: only upload errors were labelled, and the tool check and the
tool execs passed theirs through bare. D27 records the fixes.

### Pilot-fix decisions (D27)

- **Telemetry.** One `EventSink` (JSONL file, plus the summary table in the
  draft and `probe-runner` output) receives an event for every step:
  evidence and tarball fetches, model preflight, ledger record, create,
  deny-all set and read-back, memory limit, every exec (purpose, timeout,
  bytes sent and received, stream-id bytes seen, exit status, duration),
  tool check, upload (bytes the runner wrote), unpack, each tool, each
  model call, each delete attempt, the existence check, and the cleanup
  outcome. Free text is redacted first. `Telemetry.span` re-raises any
  boundary error with its phase, step, duration and time into the run, so
  none is left as a bare timeout.
- **Upload and unpack are separate execs**, and the upload's byte count is
  confirmed, so a transport stall and a slow extraction are told apart.
- **`probe-runner --sequence review`** runs `run_disposable` itself (tool
  check, upload, unpack, then a trivial file count or the review's tools)
  on a local tarball or the App-fetched head tarball, with no model.
- **Risk-ordered diff parts.** The diff is split into files, ranked
  (security, auth, secrets and redaction; runner, sandbox, HTTP and model
  boundary; other code; config and CI; tests and fixtures; docs; D30 later
  moved CI, dependency and build files up to second) and packed
  first-fit into at most `--max-model-calls` parts of
  `--diff-chars-per-call` characters, one model call each. The three-call
  cap (retries included), the $3 reservation and the preflight are
  unchanged and shared by all parts, so a retry can leave a later part
  refused. Incomplete coverage is an omission listing every unsent file by
  tier; a part whose call fails lists its files as unreviewed; a controller
  note says complete or PARTIAL after the calls.

### Third live probe and the exec-shape decisions (D28)

The owner's `probe-runner --sequence review --tools review` at `fd56ca0`
got through create, egress, the tool check, the upload (3,062,571 bytes,
0.25 s) and the unpack (0.33 s). Then `python3 --version` (no stdin) timed
out at 135 seconds. In code, the three no-input execs were identical
requests apart from the third `cmd` value and the timeout. So the cause is
in the command or the server, not in how the request was built. The old
transport's single blocking `read` also threw away any bytes that had
arrived, so "no frames" was never measured. Details and the remaining
hypotheses are in the reviewer README's "Third live probe" section.

- **One exec shape.** `sprites_api.exec_request` builds every exec: `cmd`
  repeated, always `stdin=true`, and an octet-stream body that is exactly
  the stdin bytes (possibly empty) with an explicit `Content-Length`. No
  `env`, `dir`, `path` or `tty`. `runner.exec_argv` wraps every script:
  start marker, then the script with exactly N bytes of stdin then EOF
  (`head -c N |` or `</dev/null`), then the exit marker.
- **Fail fast on silence.** Exec responses are read as they stream. A
  command that sends no input fails, labelled with its stage and purpose,
  if no byte arrives within `--first-frame-seconds` (default 30). A stall
  keeps the bytes that did arrive and reports their count, the frames seen
  and the last output.
- **Resolution, not execution, in the tool check.** It now also reports
  each binary's `command -v` path and `readlink -f` target.

### Fourth live probe and the trusted-interpreter decisions (D29)

The owner's probe at `9805cfc` got the start marker after the unpack, then
`python3 --version` hung to 135 seconds. The tool check had resolved
`python3` to `/.sprite/bin/python3`, a pyenv shim that picks its version
from `.python-version` in the working directory, and this repo pins `3.12`
while the image's default is 3.13.x. The hypothesis is that the PR's pin
makes the shim pick an uninstalled version and hang. It is not confirmed;
the probe's new diagnostics test it. Details are in the reviewer README's
"Fourth live probe" section.

- **Minimal environment on every exec.** `exec_argv` prefixes
  `/usr/bin/env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 /bin/sh -c`.
  This uses the wrapper rather than the API's `env`/`dir` parameters, so the
  request shape stays the one D28 tested, and the spec does not say whether
  `env` merges or replaces.
- **The controller chooses the interpreter, before the PR exists in the
  Sprite.** One exec between the tool check and the upload, from an empty
  directory, reports each pyenv `versions/*/bin/python3` and
  `/usr/bin/python3` that runs. Only those two path shapes are accepted;
  the newest pyenv version wins, else the system one.
- **Python tools name it only as `{python}`** and run it with `-I`.
  `ToolSpec` refuses a `python3` tool without the placeholder. No resolved
  interpreter makes a Python tool UNKNOWN.
- **Probe-only diagnostics.** These read the shim as text and list the
  installed versions. They then run the trusted interpreter from the
  checkout, the shim with `PYENV_VERSION`, and finally a bare `python3`
  bounded to 15 s and labelled expected-may-hang. None of them is fatal,
  and a review never runs them.

### Third live pilot and the hardening decisions (D30)

The owner's third pilot at `a246625` ran end to end. Its draft is model
output, so each of its five findings was checked against the code first:
four were real and one partial. Details are in the reviewer README's
"Third live pilot" section.

- **Assignment redaction** matches a keyword inside a longer name
  (`OPENAI_API_KEY`, `client_secret`, `"api_key"`), not only after a word
  boundary. The name parts are bounded so matching stays linear.
- **Archive budget** charges an entry's declared size before decompressing
  it, so entries that fail their CRC check still spend the total budget.
- **One cumulative deadline before the body** on streaming execs: a cutoff
  timer shuts the socket down at the first-byte deadline, so trickled
  headers cannot outlast it. The non-streaming transport is unchanged.
- **No model call without a diff.** A failed diff fetch is an omission and
  a NOT REVIEWED coverage note, not an empty-diff call.
- **Supply-chain tier.** CI workflows, dependency manifests, lockfiles and
  build hooks rank right after security code and are matched before any
  directory pattern.
- **Quoted untrusted values in the controller notes.** Paths, runner and
  tool output and upstream error text appear only as one-line JSON string
  literals in code spans, and the notes intro and system prompt say such
  values are data, not controller statements.

### Diff fitting and the repo's own lens picker (D32)

Operator-requested in Run #9. Offline only, no live call made here.

- **Part size.** `--diff-chars-per-call` defaults to the whole prompt room
  under the token check: `min(200k input, 200k assumed context − 24k
  output)` = 176,000 characters (`budget.prompt_token_room`). The suggested
  ~450k characters would need a characters-per-token ratio. The input
  bound deliberately assumes none (one token per UTF-8 byte), so a 450k
  part could never pass `check_tokens`. `diffs.fit_diff` measures every
  planned prompt and shrinks the part size from the byte-largest actual
  part, for up to 8 rounds, until the largest prompt fits.
- **Reservation math.** One full-room call reserves at most 176k × $6/M +
  24k × $22.5/M ≈ $1.60 at the top fixture tier, under $3.00. Two
  unsettled worst cases ($3.19) don't fit, so a later call is reserved only
  after earlier ones settle to their actual cost. The 3-call cap and the
  $3.00 reservation are unchanged.
- **Too large.** A diff over capacity is PARTIAL. The omissions row says
  "too large for one review pass", and the cut and unsent files are listed
  by risk tier.
- **Lens picker.** `lenses.py`'s path-and-keyword route digest is retired.
  `picker.py` runs `skills/choosing-review-lenses/SKILL.md` as one model
  call at the operator's `--depth`. Triage, a 1-call budget or an unusable
  reply runs the critical tier (`docs/review-depth-modes.md`). The picker
  call is one of the 3 calls, so review depth reviews at most 2 diff parts.
- **Next step, proposed only:** a lens-based agentic reviewer (D31,
  [`2026-11-07-lens-based-agentic-reviewer.md`](2026-11-07-lens-based-agentic-reviewer.md)).

### Still unverified against live responses

- **The Sprites exec response body.** Observed for a small echo, a 3 MiB
  stdin round-trip, a review's upload and unpack (third probe), and the
  third pilot's whole review sequence at `a246625`, which used the D28
  request shape and the D29 wrapper. Not yet observed: whether output
  streams before the command exits, and the D30 cutoff timer.
- **The GitHub and OpenRouter response shapes.** The pilot's draft held a
  check run, job, log and workflow run, so those list shapes parsed (inferred
  from the owner's report, not a recorded response). Not yet seen live: a
  job's `check_run_url` (from GitHub's documentation; grouping needs it),
  artifacts, pagination past one page, and OpenRouter's error and retry
  responses. The key preflight, catalog read and one chat completion worked.
- **The input-token bound.** It assumes no token encodes less than one
  UTF-8 byte, plus 64 tokens of message overhead. It has not been checked
  against this model's tokenizer, the pilot's token usage was not reported
  here, and the prompt is now larger because lens bodies are inlined.
  Reported usage is recorded, so a violated assumption shows up in the draft.

### Pilot-fix decisions (D26)

- **Lenses.** The controller selects lenses from the diff's paths and the PR
  text (`lenses.py`, a code-side digest of the bundle's route table), reads
  each `body.md`, and inlines them in the trusted system prompt under a
  60,000-character budget and a 6-lens cap. The draft lists each lens as
  included, truncated or omitted. The model has no file tools, so naming
  lenses never ran them. The selector is a coarse heuristic and the table
  shows its choices. (D32 replaced this selector with the repo's own lens
  picker and raised the cap to 8.)
- **Grouped checks.** A check run, its job (via the documented
  `check_run_url`), the job's log and the workflow run are one independent
  check. A run is context for its jobs only when a job carries its verdict;
  an unexplained run failure stays independent, and any failing or UNKNOWN
  view makes the whole check so. No name matching.
- **Controller notes.** Runner cleanup proof, exec failures, tool results,
  omissions and lens coverage are generated by code into one section and
  given to the model as established facts. They can quote runner output, so
  they are fenced as untrusted data.
- **Default tools.** `python-compileall` only: egress is deny-all and a
  Sprite is never reused, so a binary missing from the image cannot be
  installed, and CI evidence already covers lint.
- **Recorded truncation.** A diff, PR body or issue body cut at its cap is an
  omission, with the files the model never saw. Omissions are built before
  the evidence block, so the model is told.
- **Sweep.** It takes the single-review lock, because the ledger lists a live
  review's runner and sweeping would destroy it mid-run.
- **OpenRouter counter lag.** The key's usage counter can lag a call by about
  90 seconds (pilot observation, not checked against the docs). It is read
  only by the preflight, so a $0 readback after inference is not a mismatch.

### Second-slice decisions (D25)

- **Cost reservation.** Each attempt reserves input bound × the highest
  input price (cache writes included) + max output × the highest completion
  price + reasoning budget × any separate reasoning price + any request
  fee. Each price is the highest across the base entry and every override.
  A failed attempt stays counted at its full reservation, since it may
  have been billed. The cap is the lower of $3.00 and the key's remaining
  credit at preflight.
- **Retries.** Retries are allowed on 408, 429, 500, 502, 503 and 504 responses and on
  transport errors, with 2 s and then 4 s backoff. Every attempt counts
  toward the three-call cap. A served-model mismatch, an empty review, or
  any other 4xx is not retried.
- **Provider slugs.** `provider.only` is `amazon-bedrock`,
  `google-vertex/global`, `google-vertex/us`, and `google-vertex/europe`,
  with `allow_fallbacks: false`. The provider-selection doc
  (https://openrouter.ai/docs/guides/routing/provider-selection, "Base
  Slug Matching", fetched 2026-11-07) says a bare slug matches every
  eligible endpoint of that provider, regions included. A same-day
  read-only check of the public provider list found Vertex only as those
  three region slugs, not as bare `google-vertex`, and found Bedrock as
  the base slug plus region slugs that check did not name. Those unnamed
  region slugs are not pinned. The in-region routing doc
  (https://openrouter.ai/docs/guides/features/in-region-routing, "Regional
  Endpoints on the Global Domain") says a bare `amazon-bedrock` does not
  pin that provider's regional-surcharge endpoints. A slug
  outside this set, including the docs' own examples
  `google-vertex/us-east5` and `amazon-bedrock/eu-west-1`, is refused
  before any request.

## Explicitly out of scope

Each item below is left out on purpose rather than deferred:

- publishing anything to GitHub
- webhooks
- a queue or concurrency beyond one review at a time (enforced by a lock
  file)
- billing, BYOK onboarding, Vercel, Neon, and multi-tenancy
- executing or extracting artifact or log content (it is parsed in memory
  as text only)
- model fallbacks, plugins, web search, or a fourth model call per review

## Follow-ups (not in this slice)

This slice stays the single-prompt manual reviewer. Left for later PRs,
each needing its own decision:

- **The lens-based agentic loop.** D31, proposal only:
  [`2026-11-07-lens-based-agentic-reviewer.md`](2026-11-07-lens-based-agentic-reviewer.md).
- **Deploying the controller** (for example on Fly) instead of running it
  from an operator's trusted machine.
- **Omission rows for check summaries, log tails and artifact excerpts.**
  These are capped today, but the caps are not listed as omissions the way
  diff, PR-body and issue-body cuts are.
