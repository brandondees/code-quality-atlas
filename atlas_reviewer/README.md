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
  `workflow_run`, `workflow_log`, `artifact`, `runner_tool`.
- `--include-issues` opts in to fetching the issues the PR body closes.
  Off by default.
- `--deadline-seconds N` sets the external runner deadline (default 600).

Tests: `python -m pytest atlas_reviewer/tests -q --cov=atlas_reviewer`.

## Live mode

```sh
python -m atlas_reviewer review --event event.json      # GitHub + Sprites, offline provider
python -m atlas_reviewer sweep                          # destroy runners a crashed review left behind
```

Environment variables (names only; never commit values):

| Variable | Held by | Purpose |
| --- | --- | --- |
| `ATLAS_GITHUB_TOKEN` | controller → GitHub adapter | GitHub App installation token (App 5648875), read-only |
| `ATLAS_SPRITES_TOKEN` | controller → Sprites adapter | Sprites org token for the outside control-plane API |
| `ATLAS_PROVIDER_API_KEY` | controller (reserved) | Model provider key. No live provider reads it yet. If set, its value is scrubbed from untrusted text |
| `ATLAS_REVIEWER_STATE_DIR` | controller | Runner ledger and single-review lock (default `.atlas-reviewer-state/`, gitignored) |

None of these values reaches a Sprite, a prompt, or the draft. Each token goes
only to the adapter that uses it. The controller also scrubs every token's
exact value from untrusted text, on top of the pattern-based redaction.

## Module layout

| Module | Job | I/O? |
| --- | --- | --- |
| `domain.py` | closed types: `PrEvent`, `EvidenceItem`, `Matched`/`Stale`/`Missing`, `Outcome` | no |
| `classify.py` | evidence vs. the head SHA → matched / stale / missing | no |
| `redact.py` | secret redaction; `RedactedText` can only come from `redact()` | no |
| `prompt.py` | trusted system prompt + nonce-fenced untrusted blocks | no |
| `evidence.py` | GitHub JSON / runner results → `EvidenceItem`, shape validation | no |
| `draft.py` | Markdown draft rendering | no |
| `ports.py` | the adapter interfaces (`GitHubReader`, `SpritesApi`, `ModelProvider`, `ReviewHarness`, `RunnerLedger`, `Clock`) | no |
| `runner.py` | disposable-runner lifecycle (create → deny-all → verify → run → destroy) | via `SpritesApi` |
| `controller.py` | one event in, one draft out | via ports |
| `harness.py` | skill-bundle harness: loads `collapsed/skills/reviewing-a-change/SKILL.md` | reads the bundle |
| `providers.py` | `OfflineProvider` (the only provider shipped) | no |
| `github_api.py`, `sprites_api.py`, `http.py` | live adapters, stdlib HTTP | network |
| `github_fixture.py`, `fakes.py`, `ledger.py`, `clock.py` | offline adapters, local state | local files |
| `cli.py`, `__main__.py` | entry point, dispatch tables | env, files |

## Trust boundaries

- **Trusted:** the operator's event file, this repo's skill bundle, the
  controller's own code and `ToolSpec` commands.
- **Untrusted:** everything from the PR. That means the diff, title and body,
  check names and summaries, workflow logs, artifact metadata, runner tool
  output, issue text, and the model's own output. All of it is redacted before
  it reaches a prompt or the draft. In the prompt it sits inside
  `<untrusted-data id="NONCE">` fences, and the system prompt says never to
  follow instructions found there.
- **Runner:** a fresh Sprite for every review, never reused. Deny-all egress
  (`{"action": "deny", "domain": "*"}`) is set from the outside API and read
  back before anything runs. Memory is capped at 1024 MB. The Sprite gets no
  connectors and no credentials. Source goes in as the head-SHA tarball over
  exec stdin; the controller fetches it with its own token. An external
  deadline is enforced by a watchdog timer. Destroy runs in `finally` and
  from the watchdog. It is idempotent and is verified by a follow-up
  existence check. The runner name is written to the ledger before create,
  so `sweep` can clean up after a crashed controller.

## What a live run still needs

1. **A GitHub App installation token.** The service reads a pre-minted token
   from `ATLAS_GITHUB_TOKEN`. It does not mint one: minting needs an RS256
   JWT signed with the App private key, and that needs a crypto dependency
   this repo does not carry. Mint it out of band with contents, checks,
   actions, and pull_requests set to read, plus issues read only if you use
   `--include-issues`.
2. **Sprites wiring.** Put an org token (not a personal one) in
   `ATLAS_SPRITES_TOKEN`. Then confirm the exec request shape against the
   Sprites OpenAPI before the first live run. `sprites_api.py` sends argv as
   repeated `cmd` query parameters and stdin as the body, and that shape is
   unverified. Also confirm the runner image actually has the default tools
   (`python3`, `ruff`, `shellcheck`). Absent tools are reported as UNKNOWN,
   not as failures.
3. **A live model provider.** None is wired; `--provider` accepts only
   `offline`. The first adapter to add is the **Anthropic Messages API**
   (`POST https://api.anthropic.com/v1/messages`, stdlib HTTP, `x-api-key`
   from `ATLAS_PROVIDER_API_KEY`). The harness already sends
   `Prompt.system` / `Prompt.user`, which map directly onto that API's
   `system` and user message. Still open: which model to use, the
   max-tokens and cost cap per review, and how retry or timeout behaviour
   maps onto `BoundaryError`.
