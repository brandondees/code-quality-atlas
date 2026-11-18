# Deploy the webhook service on Fly.io

One always-on Machine receives GitHub App webhooks and posts one COMMENT
review per commit. This is a second app from the one-off controller in
[`deploy-fly.md`](deploy-fly.md). That app stays without a public service
and without a standing Machine. Decision: D53 in
[`docs/open-questions.md`](../docs/open-questions.md).

Nothing in this repository creates the app, sets a secret, or turns on the
GitHub App webhook. The commands below are what an operator runs, from a
trusted machine, with a token scoped to the Fly org `personal`.

## What is committed

| File | Role |
| --- | --- |
| [`fly.service.toml`](../fly.service.toml) | App `atlas-reviewer-service`, HTTP on 8080, `auto_stop_machines = "off"`, `auto_start_machines = false`, one `shared-cpu-1x` Machine with 1024 MB, and a 1 GB volume at `/data` for the queue and the post ledger |
| [`docker-entrypoint.sh`](docker-entrypoint.sh) | `serve` runs `python -m atlas_reviewer.service`. Any other argument stays the one-off CLI |
| [`Dockerfile`](../Dockerfile) | The same image as the one-off controller. It does not publish a port by itself |

`fly.toml` is not this app. Do not `fly deploy` it for the webhook. A plain
`fly deploy` in the repo root reads `fly.toml` and would release the
one-off app.

## Cost

Fly's pricing page (https://fly.io/docs/about/pricing, read 2026-11-12)
prices Machines in `iad` and `ewr` as its lowest regions, for 30 days of
continuous runtime. `shared-cpu-1x` with 1 GB of RAM is $6.70 per 30 days.
This Machine is `shared-cpu-1x` with 1024 MB, the same memory as the
one-off review Machine, so that row is the compute cost while it stays up.
A stopped Machine is billed $0.15 per GB of its root filesystem per month.
This image's root filesystem size is not measured here. The queue volume
is 1 GB, which that page prices at $0.15 per GB per month, so $0.15 per
month on top of the compute.

The alternative, Fly Proxy auto-stop and auto-start, was not chosen.
GitHub closes a webhook delivery that has no 2xx within 10 seconds and
does not redeliver it on its own
(https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks
and
https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries,
read 2026-11-12). Fly's configuration reference says `auto_stop_machines =
"off"` means Fly Proxy does not stop the Machine, and that auto-stop and
auto-start should both be enabled or both disabled
(https://fly.io/docs/reference/configuration/, the `http_service` section,
read 2026-11-12). That reference does not bound a cold start under 10
seconds. The standing Machine is what can answer inside GitHub's window.

## Secrets

Names only. Values stay out of the checkout, the command line, and this
file. Put them in a file outside the repo, mode 0600:

```text
ATLAS_GITHUB_APP_ID=
ATLAS_GITHUB_APP_PRIVATE_KEY=
ATLAS_GITHUB_INSTALLATION_ID=
ATLAS_GITHUB_APP_SLUG=
ATLAS_GITHUB_WEBHOOK_SECRET=
ATLAS_SPRITES_TOKEN=
ATLAS_OPENROUTER_API_KEY=
ATLAS_ALLOW_LIVE_INFERENCE=1
ATLAS_SERVICE_PROVIDER=openrouter
ATLAS_HEAD_CHANGE_POLICY=keep
ATLAS_HEAD_CHANGE_CANCEL_FRACTION=0.5
```

`ATLAS_GITHUB_WEBHOOK_SECRET` is new. It is the App webhook secret, at
least 16 characters, and the same value is set on the GitHub App. The
private key may be one line with literal `\n` sequences. The service
refuses to listen without the webhook secret, the three `ATLAS_GITHUB_APP_*`
values and `ATLAS_GITHUB_INSTALLATION_ID`, and, for the default `openrouter`
provider, `ATLAS_ALLOW_LIVE_INFERENCE=1`.

The child also receives the model settings when they are set on the
Machine. They are not secrets, and they do not belong in `service.env`.
`ATLAS_MODEL` selects the model. `ATLAS_PROVIDERS` is the provider list.
`ATLAS_ALLOW_SAFETY_RETENTION` opts into provider retention.
`ATLAS_REQUIRE_ZDR` set to `false` turns off the zero-data-retention
requirement; unset keeps it on. `ATLAS_KEY_CEILING_USD` is the most the
OpenRouter key's own credit limit may be, and the review reads it.
`ATLAS_SERVICE_MODE` selects the child command: `agentic` (the default,
D70) runs `agentic-review`, whose review-wide limits derive from the
planned lens count under the per-review dollar ceiling (D68), and
`oneshot` runs the one-shot `review` command — D25's ceilings apply: 3
calls, $3, and 200,000 input tokens; an unknown value refuses to start the
service. `ATLAS_SERVICE_DEADLINE_S` sets the parent's wall clock around one
review child, 60 to 14,400 seconds. The default follows the mode:
oneshot keeps 1,200 seconds; agentic defaults to the 14,400-second
upper bound, because there the parent deadline is a backstop, not the
real limit — the child's own derived wall and D68's dollar ceiling are
what stop a review. A plan's derived wall can reach
`ATLAS_LENS_WALL_S × ⌈planned lenses ÷ pool⌉`; an explicit deadline
must cover the plans you expect (a value below the child's *configured*
wall refuses to start), and at pool 1, plans of 13 or more lenses
exceed even 14,400 seconds — raise `ATLAS_POOL_SIZE` or lower
`ATLAS_LENS_WALL_S` for those, and a configured `ATLAS_REVIEW_WALL_S`
above that ceiling refuses to start, since no in-bounds deadline can
cover it. A
review the parent kills at the deadline posts nothing: the job fails,
the failure is a telemetry event, and the child's own stop has already
destroyed its Sprite. Flipping either
setting on the running app is a separate, approved deploy step and is
not part of the change that introduces them; this runbook only names
them. The
agentic limit variables (`ATLAS_PER_LENS_CALLS`, `ATLAS_PER_LENS_USD`,
`ATLAS_REVIEW_CEILING_USD`, and the rest of `README.md`'s `ATLAS_*`
limit table) reach the
child when set on the Machine. The only GitHub credential the child
receives is still the read-only installation token the parent minted,
which includes issues read alongside the contents, checks, actions and
pull-request reads, so a child run with `--include-issues` holds a token
that can read issues; an optional read the token cannot serve is refused
by GitHub and recorded as a gap, never a crash.
The App private key, the webhook secret, and `FLY_API_TOKEN` stay in the
parent.

The App needs Pull requests set to read and write. The service's posting
token asks for `pull_requests: write` and no other write. The operator CLI
still asks for read only. After the permission change, accept it on the
installation that covers `brandondees/code-quality-atlas`.

Define `flyp` as in [`deploy-fly.md`](deploy-fly.md): the org token is
loaded into a shell variable, and each `flyp` command exports
`FLY_API_TOKEN` inside a subshell that unsets `FLY_ACCESS_TOKEN`. Do not
run `fly secrets deploy`. Stage the secrets, then `fly deploy`, which
updates the Machine. A staged secret is available on Machines started or
updated after the stage command
(https://fly.io/docs/apps/secrets/, read 2026-11-12).

```sh
set -eu
cd /path/to/code-quality-atlas
APP=atlas-reviewer-service
ORG=personal
SECRETS_DIR="$HOME/atlas-secrets"

flyp apps list --org "$ORG" --quiet | grep -qx "$APP" ||
  flyp apps create "$APP" --org "$ORG"

flyp secrets import --stage --app "$APP" < "$SECRETS_DIR/service.env"

flyp deploy -c fly.service.toml --app "$APP" --ha=false
```

`--ha=false` keeps a single Machine. The config's `auto_stop_machines` is
`off`, so that Machine keeps running after the deploy. If it is later
stopped, a webhook does not start it (`auto_start_machines` is false).
Start it with `flyp machine start <id> --app "$APP"`.

`initial_size` makes `fly deploy` create the volume `atlas_reviewer_state`
in `iad` when one does not exist yet (Fly's configuration reference,
`mounts.initial_size`, read 2026-11-12). It is mounted at `/data`, which
is `ATLAS_REVIEWER_STATE_DIR`. The image starts as root. The entrypoint
chowns that directory to uid 10001 and continues as that user, so a fresh
root-owned volume does not need a manual chown. `kill_signal` is `SIGINT`
and `kill_timeout` is `120s`. A review child is signalled SIGTERM and the
parent waits 90 seconds, the 60 second Sprite cleanup budget plus one 30
second Sprites call, before SIGKILL. The extra 30 seconds is the parent
exiting after that wait. A shorter `kill_timeout` kills the process while
the Sprite is still being destroyed.

After that, restarts keep the queue and the post
ledger. The queue refuses a new job when 2,000 active jobs (`queued`, `running`, `post_pending`, `posting`) belong to other pull requests. A newer head of a pull request that already has an active job takes that slot. Replacing a job that is still `running` or `posting` can leave the count at 2,000 plus those superseded jobs, and that extra is at most the worker concurrency. The dedupe list keeps every pull request's current head, so it
can grow past 20,000 by one key per pull request. A run directory is
removed when its job ends. A key is about 80 bytes. The 1 GB volume
holds the queue file, `posted.json`, `service.jsonl`, and the per-PR
round logs (D74): one append-only `/data/rounds/<repo>-<pr>.jsonl` per
pull request, keyed by repository and PR number, not by head SHA, so the
next push's review reads the earlier rounds. A review appends one record
of at most about 8 KB per finished run. The queue's one-active-job-per-PR
rule makes each log single-writer; the teardown window of a superseded
review can still overlap the next head's first write. What a bad line
then costs depends on what it hides: a line that lands torn names no
pull request and charges nobody; a garbled or version-skewed line that
names this pull request is charged to it only when it sits at the head
under review -- at an older head it is superseded data -- and that
charge holds the review at COMMENT until the log is repaired, which is
why the reader also acts on what it can repair: a file whose bytes it
cannot decode is moved aside automatically under a
`.corrupt-<UTC timestamp>-<nanoseconds>` name beside the log, the
review that saw it reports the omission once, and the next head starts
a fresh log. A read that fails any other way -- a permission refusal,
an unreachable parent, a directory at the log's path -- renames
nothing: the operator's recovery for that, and for a garbled line at
the current head the reader cannot clear, is to repair or remove
`/data/rounds/<repo>-<pr>.jsonl` by hand; salvage the quarantined copy
first, because deleting the log loses only prior-round context. No
cleanup path removes a round log: the run
directory that is removed when a job ends does not contain it, and the
log stays on the volume until a later cleanup slice trims it. At one
record per finished review, growth is slow enough that the 1 GB volume
is not the binding constraint; if a repository's log ever grows past
useful size, trimming it loses only prior-round context, the way
deleting it does.

`fly apps destroy` deletes the app's volumes and volume snapshots
(Fly's delete-an-app page, read 2026-11-12). Copy what you need off
`/data` before destroying the app. The one-off app is a different app
and is not destroyed by this command.

Confirm the process without printing the environment:

```sh
flyp status --app "$APP"
flyp checks list --app "$APP"
flyp logs --app "$APP"
flyp ssh console --app "$APP" -C "tail -n 200 /data/service.jsonl"
```

If `flyp checks list` shows `/health` critical while the Machine is
started, restart it and read the log. A 503 there means a worker died or
the queue could not be saved, and GitHub will not redeliver the webhook:

```sh
flyp machine restart <id> --app "$APP"
flyp logs --app "$APP"
```

The health check is `GET /health` and expects a 200. A ready log line
names the port, the concurrency, and the allowlist. It does not name
secret values.

## GitHub App webhook

In the App's webhook settings, set the payload URL to
`https://atlas-reviewer-service.fly.dev/webhook`. Fly app names are
global. If `fly apps create` says `atlas-reviewer-service` is taken, leave
`app` in `fly.service.toml` unchanged, set `APP` to the name you choose,
and pass `--app "$APP"` on every command in this runbook, which the fences
already do. The payload URL is then `https://<that-name>.fly.dev/webhook`.
Set the webhook secret to the same value as
`ATLAS_GITHUB_WEBHOOK_SECRET`. Content type JSON. Subscribe to
**Pull requests** and nothing else. The installation must include
`brandondees/code-quality-atlas`, and the App itself must grant read on
contents, checks, actions, pull requests and issues: the parent's
read-token mint requests all five, so an installation whose App is
missing any of them fails every mint at review start and no review
posts.

`ATLAS_REVIEW_REPOS` defaults to that repository. Leave it unset until a
second repository is an explicit decision. One installation id cannot
cover a repository on another account.

## What a delivery does

`opened`, `synchronize`, and `ready_for_review` on a non-draft PR are
queued. A draft is ignored. A bad signature is refused with HTTP 401. A
second delivery of the same head SHA does nothing. A newer head cancels
the review in progress, and that cancelled review is not posted — unless
the head-change policy decides to keep it: under the default
`ATLAS_HEAD_CHANGE_POLICY=keep`, a push that lands while a review is
still running is decided per push (a merge of the base branch, a
docs-or-tests-only change, or a push touching no file the review is
still reading keeps the review; a code push cancels a review that is
still early, under `ATLAS_HEAD_CHANGE_CANCEL_FRACTION`), and a kept head
is recorded as the pull request's pending follow-up, queued when the
running review settles. The follow-up of a settled success is a delta
review: it reviews only what the range between the settled head and the
new head changed, carries the earlier review's findings forward through
one bounded carry-forward call (re-anchored through the quote checker,
the new commits' fixes marked resolved), and its post cites the review
it builds on. Setting the policy to `cancel` restores the
blanket supersede. The decision and the review costs are telemetry
events in `/data/service.jsonl` (`head change`, `review cost`,
`follow-up queued`). A review
that exits 0, 4, or 5 is posted as one COMMENT review. Any other exit
posts nothing and writes a telemetry event under the Machine's state
directory.

The comment says it is advisory and not a substitute for the full Claude
Code protocol review, then lists the draft's verified findings, lenses
run, lenses not run, the file-coverage note, limit stops, and cost. A lens
an earlier entry left NOT RUN but one of the lens's own runs recovered
is listed as run, with the failure carried as a recovered note
among the limit stops (#692, D76); a lens with no clean run is still not
run.

## Downgrading

The queue file carries a `pending` key (a kept head waiting for its
review to settle) and a per-job `delta_from` (the delta review's base),
which a release from before #702 ignores: a downgrade strands a kept
head — its record is unread by the older release, and a redelivery of
that head is answered duplicate, so it is never reviewed. Before
downgrading, stop the service and let it drain (the queue file's
`pending` key is the exact observable, and `service.jsonl`'s
`follow-up queued` events the live signal; the boot log's
`pending follow-ups N` count is taken once at boot, after the recovery
pass has already installed the heads it could, and does not track the
drain). A pending head recovered by the running
release is an ordinary queued job the older release understands.

## Tear down

Disable the GitHub App webhook before stopping the Machine. A delivery
that arrives after the sweep can queue a review, and that review can
create a Sprite the sweep already missed. In the App's webhook settings,
turn the webhook off, or unsubscribe **Pull requests**.

Stop the Machine only after that, and let it drain. The stop below sends
SIGINT. `--timeout 120` is the number of seconds Fly waits before
SIGKILL, the same number as `kill_timeout`. It does not make flyctl
wait. Without `--wait-timeout`, flyctl returns when the stop API
accepts the request, and the Machine can still be running. A sweep
then can meet a review that is still creating a Sprite.
`--wait-timeout 120s` is what blocks until the Machine's state is
`stopped`. If that wait expires, flyctl exits with an error that the
machine did not stop within the wait timeout, and the script below
does not sweep. Check `flyp machine status <id> --app "$APP"` and run
the same stop again. Sweep only after a stop that includes
`--wait-timeout` exits 0.

A plain `python -m atlas_reviewer sweep` reads `runners.ledger` in its
state directory. The service does not write `/data/runners.ledger`. Each
review writes its ledger under `/data/runs/<repo>-<pr>-<sha>/state/`, and
that directory is removed when the job ends, so the plain sweep finds
nothing. The per-PR round log (D74) lives at
`/data/rounds/<repo>-<pr>.jsonl`, outside the run directory, and stays
when the job ends.

A leftover Sprite is named the way the README states it:
`cqa-rev-pr<PR>-<first 12 of the head SHA>-<8 hex of a SHA-256 over repo,
PR, and SHA>`. The same name is the `runner` field on the `runner named`
line in `/data/service.jsonl`, which the ssh tail earlier in this runbook
shows while the Machine is up. A name that is still running can also be
read in the Sprites console by the `cqa-rev-` prefix. Sweep each leftover
with `--runner` and that name, from a machine that holds
`ATLAS_SPRITES_TOKEN`. The run directory is removed when the job ends, so
this teardown does not copy an event file and does not use `--event`. The
sweep prints `verified absent` for each name. `NOT verified` means that
Sprite is still billable. Run that name again. Destroy the app only after
those lines say verified absent.

```sh
if ! flyp machine stop <id> --app "$APP" --signal SIGINT --timeout 120 --wait-timeout 120s
then
  echo "atlas-reviewer: the Machine did not reach stopped; do not sweep" >&2
  exit 1
fi

python -m atlas_reviewer sweep --runner "$RUNNER" --force-live

flyp apps destroy "$APP" --yes
```

`$RUNNER` is the `cqa-rev-` name. The destroy deletes the app's volumes.
It does not destroy the one-off app `atlas-reviewer`.
