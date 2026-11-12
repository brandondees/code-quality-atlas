# Deploy the webhook service on Fly.io

One always-on Machine receives GitHub App webhooks and posts one COMMENT
review per commit. This is a second app from the one-off controller in
[`deploy-fly.md`](deploy-fly.md). That app stays without a public service
and without a standing Machine. Decision: D44 in
[`docs/open-questions.md`](../docs/open-questions.md).

Nothing in this repository creates the app, sets a secret, or turns on the
GitHub App webhook. The commands below are what an operator runs, from a
trusted machine, with a token scoped to the Fly org `personal`.

## What is committed

| File | Role |
| --- | --- |
| [`fly.service.toml`](../fly.service.toml) | App `atlas-reviewer-service`, HTTP on 8080, `auto_stop_machines = "off"`, `auto_start_machines = false`, one `shared-cpu-1x` Machine with 1024 MB |
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
This image's root filesystem size is not measured here.

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

Confirm the process without printing the environment:

```sh
flyp status --app "$APP"
flyp checks list --app "$APP"
flyp logs --app "$APP"
```

The health check is `GET /health` and expects a 200. A ready log line
names the port, the concurrency, and the allowlist. It does not name
secret values.

## GitHub App webhook

In the App's webhook settings, set the payload URL to
`https://atlas-reviewer-service.fly.dev/webhook` when the app name is
`atlas-reviewer-service`. If the name was taken and the app was created
under another name, the host is `https://<that-name>.fly.dev` and the path
is still `/webhook`. Set the webhook secret to the same value as
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
