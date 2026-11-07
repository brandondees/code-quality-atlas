# Manual reviewer service — first operator-triggered review path

**Status: implemented; one owner-run live pilot on 2026-11-07, fixes since
offline only (first slice 2026-11-06; live-readiness slice and pilot fixes
2026-11-07).** The service runs end to end offline: fixture GitHub,
the in-memory Sprites fake, and the offline provider. The second slice adds
everything a live run needs in code: pagination, head-SHA job-log and
artifact ingestion, in-process GitHub App tokens, the documented Sprites
exec protocol with a tool probe, and a capped OpenRouter provider. None of
it has run live yet. What a live run still needs is under
[Live-run gaps](#live-run-gaps). Decision records: **D24** and **D25** in
[`../open-questions.md`](../open-questions.md) (**D26** records the pilot
fixes), scoped steps under the still-open **Q24**.

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
  still only counts evidence for the event SHA.
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
6. Upload the head-SHA tarball over exec stdin, capped at 9 MiB against the
   documented 10 MiB stdin limit. The exec has its own 300-second budget,
   capped by the remaining deadline, and extracts with `head -c N | tar`
   so it does not wait for a stdin EOF. The first pilot's upload of about
   3 MiB timed out ("The read operation timed out") although the exec was
   already given the remaining deadline, not the 30-second client default;
   the cause is unknown and the no-EOF extraction is an untested
   hypothesis. `probe-runner` now also sends 3 MiB through that same
   `head -c` and reports the bytes received.
7. Run each available tool under `timeout`.
8. Destroy the Sprite.

Every step checks an external deadline. A watchdog timer destroys the
Sprite at the deadline even while an exec is hung. `finally` destroys it on
success, on a handled error, and on an unexpected exception (which still
propagates).

Destroy is idempotent and thread-safe. A 404 counts as already destroyed,
a failed delete is retried once, and a follow-up existence check verifies
the result. Only a verified destroy clears the ledger. An unverified one is
reported in the draft and left for `sweep`.

Exec follows the Sprites OpenAPI 0.1.12 (`POST /v1/sprites/{name}/exec`:
argv as repeated `cmd` query parameters, `stdin=true` only when a body is
sent, raw octet-stream body of at most 10 MiB). The document does not
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
| `GitHubReader` | `FixtureGitHub` (fixture directory) | `GitHubClient`: GET-only; redirects followed manually **without** credentials (stdlib urllib would replay `Authorization`, confirmed against CPython 3.12's `redirect_request`); `Link: rel="next"` followed to a 10-page cap, and a link off the API origin is refused |
| `TokenSource` | `StaticToken` (tests only) | `AppInstallationTokens`: RS256 JWT → read-only, single-repo installation token, cached until 5 minutes before expiry |
| `SpritesApi` | `FakeSprites` (records calls; fault/hang injection; configurable installed binaries) | `SpritesClient`: outside control-plane API, per OpenAPI 0.1.12 |
| `ModelProvider` | `OfflineProvider` (calls no model; the default) | `OpenRouterProvider`: `anthropic/claude-sonnet-5.5`, pinned routing, key preflight, per-review budget (D25) |
| `ReviewHarness` | `SkillBundleHarness` over the offline provider | same harness over a live provider |
| `RunnerLedger` | `MemoryLedger` | `FileLedger` (fsynced append) |

## Live-run gaps

Setup still required, all of it tested only against fakes:

1. **Sprites probe.** Re-run `probe-runner` from a trusted machine and
   check the stdin round-trip line. The pilot found `python3` but no `ruff`
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

### Still unverified against live responses

- **The Sprites exec response body.** Observed once, for a small echo. A
  large stdin upload has failed and not yet succeeded.
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
  shows its choices.
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
