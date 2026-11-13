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
```

`ATLAS_GITHUB_WEBHOOK_SECRET` is new. It is the App webhook secret, at
least 16 characters, and the same value is set on the GitHub App. The
private key may be one line with literal `\n` sequences. The service
refuses to listen without the webhook secret, the three `ATLAS_GITHUB_APP_*`
values, and, for the default `openrouter` provider, `ATLAS_ALLOW_LIVE_INFERENCE=1`.

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
and `kill_timeout` is `30s`, which covers the worker drain.

After that, restarts keep the queue and the post
ledger. The queue refuses a new job when 2,000 active jobs (`queued`, `running`, `post_pending`, `posting`) belong to other pull requests. A newer head of a pull request that already has an active job takes that slot. Replacing a job that is still `running` or `posting` can leave the count at 2,000 plus those superseded jobs, and that extra is at most the worker concurrency. The dedupe list keeps every pull request's current head, so it
can grow past 20,000 by one key per pull request. A run directory is
removed when its job ends. A key is about 80 bytes. The 1 GB volume
holds the queue file, `posted.json`, and `service.jsonl`.

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
`brandondees/code-quality-atlas`.

`ATLAS_REVIEW_REPOS` defaults to that repository. Leave it unset until a
second repository is an explicit decision. One installation id cannot
cover a repository on another account.

## What a delivery does

`opened`, `synchronize`, and `ready_for_review` on a non-draft PR are
queued. A draft is ignored. A bad signature is refused with HTTP 401. A
second delivery of the same head SHA does nothing. A newer head cancels
the review in progress, and that cancelled review is not posted. A review
that exits 0, 4, or 5 is posted as one COMMENT review. Any other exit
posts nothing and writes a telemetry event under the Machine's state
directory.

The comment says it is advisory and not a substitute for the full Claude
Code protocol review, then lists lenses run, lenses not run, the
file-coverage note, limit stops, and cost.

## Tear down

Destroy the runner Sprites first (`python -m atlas_reviewer sweep` is the
one-off tool; a Sprite left by a crashed review is still destroyed by
name). Then:

```sh
flyp apps destroy "$APP" --yes
```

That does not destroy the one-off app `atlas-reviewer`.
