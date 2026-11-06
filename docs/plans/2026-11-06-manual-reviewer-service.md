# Manual reviewer service — first operator-triggered review path

**Status: implemented, offline only (2026-11-06).** The service is built and
runs end to end offline: fixture GitHub, the in-memory Sprites fake, and the
offline provider. It has not run live. The three missing pieces are listed
under [Live-run gaps](#live-run-gaps). Decision record: **D24** in
[`../open-questions.md`](../open-questions.md), a scoped step under the still-open
**Q24**.

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
  `atlas_reviewer`). Every adapter uses only the stdlib (`urllib`,
  `zipfile`, `tarfile`, `fcntl`), so `requirements.in` is unchanged. Nothing
  argued for a second stack: the work is HTTP plus pure data shaping.
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
`check_run:1001` or `workflow_log:5001`), `tool` (name + version, or
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

## Runner lifecycle

Based on the 2026-11-06 live Sprites validation. The order is:

1. Write the runner name to the ledger, before anything exists remotely.
2. Create a fresh Sprite. Never reuse one: guests can restore checkpoints
   and create Tasks.
3. Set deny-all egress from the outside API, then **read it back**. If the
   read-back is anything other than exactly `deny *`, nothing executes.
4. Cap memory at 1024 MB.
5. Upload the head-SHA tarball over exec stdin, capped at 9 MiB against the
   documented 10 MiB stdin limit.
6. Run each tool under `timeout`.
7. Destroy the Sprite.

Every step checks an external deadline. A watchdog timer destroys the
Sprite at the deadline even while an exec is hung. `finally` destroys it on
success, on a handled error, and on an unexpected exception (which still
propagates).

Destroy is idempotent and thread-safe. A 404 counts as already destroyed,
a failed delete is retried once, and a follow-up existence check verifies
the result. Only a verified destroy clears the ledger. An unverified one is
reported in the draft and left for `sweep`.

Exec-session kill was not tested live, so it is never used. The live
adapter refuses to manage any Sprite whose name does not start with
`cqa-rev-`. No port method can pass an environment, a file, a connector, or
a token into a Sprite.

## Adapters

| Port | Offline (tests, `--dry-run`) | Live |
| --- | --- | --- |
| `GitHubReader` | `FixtureGitHub` (fixture directory) | `GitHubClient`: GET-only; redirects followed manually **without** credentials (stdlib urllib would replay `Authorization`, confirmed against CPython 3.12's `redirect_request`); first page only |
| `SpritesApi` | `FakeSprites` (records calls; fault/hang injection) | `SpritesClient`: outside control-plane API |
| `ModelProvider` | `OfflineProvider` (calls no model) | none yet: first to wire is the Anthropic Messages API |
| `ReviewHarness` | `SkillBundleHarness` over the offline provider | same harness over a live provider |
| `RunnerLedger` | `MemoryLedger` | `FileLedger` (fsynced append) |

## Live-run gaps

1. **GitHub App token minting.** The service reads a pre-minted
   installation token for App 5648875 from `ATLAS_GITHUB_TOKEN`. Minting
   one in-process needs an RS256 JWT signed with the App private key, and
   that needs a crypto dependency.
2. **Sprites wiring.** An org-scoped token goes in `ATLAS_SPRITES_TOKEN`.
   The **exec request shape is unverified**: argv as repeated `cmd` query
   parameters, stdin as the body. Confirm it against the Sprites OpenAPI
   before the first live run. Also confirm which default tools the runner
   image has.
3. **Model provider and model choice.** No live provider ships. The first
   to add is an Anthropic Messages API adapter (stdlib HTTP, key from
   `ATLAS_PROVIDER_API_KEY`). Still to decide: the model, the per-review
   token/cost cap, and the retry/timeout policy.

## Explicitly out of scope

Each item below is left out on purpose rather than deferred:

- publishing anything to GitHub
- webhooks
- a queue or concurrency beyond one review at a time (enforced by a lock
  file)
- billing, BYOK onboarding, Vercel, Neon, and multi-tenancy
- artifact **content** download (artifacts are recorded as metadata
  evidence only)
- pagination beyond the first page of each GitHub list endpoint
