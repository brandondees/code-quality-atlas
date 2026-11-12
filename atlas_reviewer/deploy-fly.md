# Deploy the controller on Fly.io

One operator, one review at a time. The app has no public service and no
standing Machine. Each review is one Machine. It writes the draft and
telemetry to its own disk and waits. The operator copies both files off
and then destroys the Machine. There is no webhook receiver and no queue.
This is the D24 shape on a Fly host (D37 in
[`docs/open-questions.md`](../docs/open-questions.md)).

Nothing in this repository creates the app or sets a secret. The commands
below are what an operator runs. One operator run, of app `atlas-reviewer`
in the Fly org `personal`, is recorded under
[What the 2026-11-10 deploy showed](#what-the-2026-11-10-deploy-showed).
That run used the earlier shape, `fly machine run --rm` with the draft on
stdout, before the review wrote to disk and was held.

The commands pass `--app atlas-reviewer`. That is the `app` value in the
repo-root [`fly.toml`](../fly.toml). Fly app names are global. If
`fly apps create` says the name is taken, leave `fly.toml` unchanged and
pass `--app <name>` on every command in this runbook. The image reference
is then `registry.fly.io/<name>:<label>`. `fly apps create` and
`fly apps destroy` take that same `<name>`. Do not edit `app` in
`fly.toml` to work around a taken name.

## What is committed

| File | Role |
| --- | --- |
| [`Dockerfile`](../Dockerfile) | `python:3.12.16-slim-bookworm` pinned by manifest-list digest, `pip install --require-hashes --only-binary=:all: -r requirements.txt`, user `atlas` (uid 10001) |
| [`fly.toml`](../fly.toml) | App name, primary region, and Dockerfile. No HTTP service, no `services` table, no process group |
| [`docker-entrypoint.sh`](docker-entrypoint.sh) | Writes the event file, runs `python -m atlas_reviewer`, and with `ATLAS_HOLD_SECONDS` set keeps the Machine up after the CLI exits |
| [`.dockerignore`](../.dockerignore) | Keeps the build context to the files the image copies, and keeps `.env`, `*.env`, `secrets.env`, and `*.pem` out of it |

`requirements.txt` is the repo's hashed lock for the whole dev set
(`requirements.in`: PyYAML, mypy, pytest, pytest-cov, ruff, types-PyYAML,
and `PyJWT[crypto]`). There is no separate runtime lock, so the image
installs that file. The controller's own imports beyond the standard
library are PyJWT and cryptography. See [Accepted costs](#accepted-costs).

The image contains the controller package, `collapsed/skills/reviewing-a-change/SKILL.md`,
that bundle's `reference/lenses/*/body.md`, and
`skills/choosing-review-lenses/SKILL.md`. It does not contain the fixture
PR, so `--dry-run` is a local-checkout command, not a Fly command.

`ATLAS_REVIEWER_STATE_DIR` in the image is `/home/atlas/.atlas-reviewer-state`.
That directory is on the Machine's disk. It is not a secret.

## Fly credentials

Run every Fly command with a token scoped to the Fly org `personal`. A
saved `fly auth login` session, or a `FLY_API_TOKEN` already exported for
other work, acts on whatever orgs it can reach. Mint the org token once
from a session that administers `personal`, straight into a file outside
this checkout:

```sh
SECRETS_DIR="$HOME/atlas-secrets"
(umask 077 && mkdir -p "$SECRETS_DIR" &&
  fly tokens create org --org personal --name atlas-reviewer --expiry 168h \
    > "$SECRETS_DIR/fly-personal.token" &&
  date +%s > "$SECRETS_DIR/fly-personal.minted")
```

[fly tokens create org](https://fly.io/docs/flyctl/cmd/fly_tokens_create_org)
makes a token for one org. In every new shell, including a second
terminal, load it into a shell variable without `export`, and wrap `fly`
so the token reaches only a subshell. This block mints nothing:

```sh
SECRETS_DIR="$HOME/atlas-secrets"
FLY_PERSONAL_API_TOKEN="$(cat "$SECRETS_DIR/fly-personal.token")"
flyp() {
  (
    unset FLY_ACCESS_TOKEN
    export FLY_API_TOKEN="$FLY_PERSONAL_API_TOKEN"
    fly "$@"
  )
}
```

flyctl prefers `FLY_ACCESS_TOKEN` to `FLY_API_TOKEN` when both are set,
so the subshell unsets it. Every `flyp` command below also names the app
with `--app` or the org with `--org personal`. `fly apps destroy` takes
the app name as its argument instead. Keep the token file and every
secrets file under `$SECRETS_DIR`, never in the checkout. `.gitignore`
and `.dockerignore` also refuse `.env`, `*.env`, `secrets.env`, and
`*.pem`, in case one is saved here by mistake.

The token expires 168 hours (7 days) after it is minted, and the mint
recorded when that was. Check that more than a day is left before each
review:

```sh
minted=$(cat "$SECRETS_DIR/fly-personal.minted")
[ $(( $(date +%s) - minted )) -lt $(( 144 * 3600 )) ] ||
  echo "the Fly token expires within a day: renew it"
```

To renew, run the mint block again from a session that administers
`personal`. It overwrites the token file and the minted time. Then run
the load block again in each open shell. The old token keeps working
until its own expiry.

## Create the app

From the repo root, where `fly.toml` is:

```sh
flyp apps list --org personal --quiet | grep -qx atlas-reviewer ||
  flyp apps create atlas-reviewer --org personal
```

The list check skips creation when the app already exists. `fly apps
create` does not write a `fly.toml`
([fly apps create](https://fly.io/docs/flyctl/cmd/fly_apps_create)).
Secrets need the app, so this comes first.

## Secrets

Set these on the Fly app. They are the names `cli.py` already reads.
Values stay out of this repository, out of the image, and out of the
commands below.

| Name | Who reads it |
| --- | --- |
| `ATLAS_GITHUB_APP_ID` | controller, to mint a GitHub App JWT |
| `ATLAS_GITHUB_APP_PRIVATE_KEY` | controller, to sign that JWT |
| `ATLAS_GITHUB_INSTALLATION_ID` | controller, to exchange the JWT for one installation token |
| `ATLAS_SPRITES_TOKEN` | controller, as the Sprites control-plane bearer token |
| `ATLAS_OPENROUTER_API_KEY` | controller, only when the review passes `--provider openrouter --allow-live-inference` |

The installation still asks for `contents`, `checks`, `actions`, and
`pull_requests` read. The review does not gain a GitHub write from being
on Fly.

`fly secrets import` reads `NAME=VALUE` pairs from stdin, one pair per
line ([fly secrets import](https://fly.io/docs/flyctl/cmd/fly_secrets_import)).
A real newline would start a new line, so the private key has to be one
line. The controller already accepts a single-line value whose `\n`
sequences stand for newlines. Append that line to the secrets file
without printing it. The `grep` skips the append when the file already
has the key, so running this twice does not add a second
`ATLAS_GITHUB_APP_PRIVATE_KEY` line:

```sh
(umask 077 && grep -qs '^ATLAS_GITHUB_APP_PRIVATE_KEY=' "$SECRETS_DIR/secrets.env" ||
  python3 -c 'import pathlib, sys; sys.stdout.write("ATLAS_GITHUB_APP_PRIVATE_KEY=" + pathlib.Path(sys.argv[1]).read_text().replace("\n", "\\n") + "\n")' \
  "$SECRETS_DIR/github-app.pem" >> "$SECRETS_DIR/secrets.env")
```

Add the other four `NAME=VALUE` lines to `$SECRETS_DIR/secrets.env` with
an editor. `--stage` stores the secrets and skips a deployment
([fly secrets set](https://fly.io/docs/flyctl/cmd/fly_secrets_set)
documents `--stage` as "Set secrets but skip deployment"). The secrets
guide says a staged secret is available on Machines started after the
command, and that an app's secrets are environment variables on every
Machine of that app, whether or not Fly Launch manages the Machine
([Secrets and Fly Apps](https://fly.io/docs/apps/secrets)).

```sh
flyp secrets import --stage --app atlas-reviewer < "$SECRETS_DIR/secrets.env"
flyp secrets list --app atlas-reviewer
```

Do not run `fly secrets deploy`. After `--stage`, flyctl suggests that
command. The secrets guide says `fly secrets deploy` redeploys the current
release with the staged secrets
([Secrets and Fly Apps](https://fly.io/docs/apps/secrets)). That is a
release, and it updates the app's Machines. This runbook does not release
the app and does not keep a Machine. On the deploy recorded below, the
secrets stored by `--stage` were already applied to the next
`fly machine run`.

`fly secrets list` prints names and digests, not values. The env file
holds all five names. `ATLAS_OPENROUTER_API_KEY` can be omitted when every
run stays on the offline provider; a run that passes
`--provider openrouter --allow-live-inference` then fails in the
controller before a model call, because the variable is missing.

The key needs a hard credit limit of at most $5. OpenRouter's key-limit
guide says `include_byok_in_limit` defaults to false, so a key made in
the website, without that field set through the management API, does not
count BYOK spend against its limit. Brandon found no toggle for the flag
on key creation or on edit (2026-11-11); the same guide says the
dashboard toggle is shown once the account has BYOK provider keys
configured. The controller accepts the key and runs in no-BYOK mode: a
model response is used only when `usage.is_byok` is false. A response
that reports BYOK, that does not say, or whose HTTP 200 body cannot
be parsed, stops the review with exit 3 and makes no further model
call. A key with the flag set true is
unchanged: a BYOK response is accepted, and its upstream cost counts
toward the review cap.

The entrypoint does not print the environment. The Sprites adapter still
sends no `env`, `dir`, `path`, or `tty` into a Sprite; the Sprites token
is only the control-plane `Authorization` header. The redactor still
scrubs the private key, the Sprites token, the OpenRouter key, and every
installation token minted during the run from the draft and from
telemetry. The App ID and the installation ID are not in that scrub list.

## Publish the image

From a clean checkout of the commit to deploy:

```sh
test -z "$(git status --porcelain)"
LABEL="reviewer-$(git rev-parse --short=12 HEAD)"
flyp deploy --build-only --push --image-label "$LABEL" --app atlas-reviewer
IMAGE="registry.fly.io/atlas-reviewer:$LABEL"
```

If the default Depot builder fails, run the same publish with
`--depot=false`:

```sh
flyp deploy --build-only --push --image-label "$LABEL" --depot=false --app atlas-reviewer
```

`--depot=false` is the documented switch off Depot when a remote build
hangs waiting for the Depot builder
([Troubleshoot your deployment](https://fly.io/docs/getting-started/troubleshooting)).
On the 2026-11-10 deploy, Depot timed out after about 5 minutes with
`authentication handshake failed: EOF`. The same publish with
`--depot=false` then succeeded in about 2 minutes. Do not drop
`--build-only` from either command.

`fly deploy --build-only --push` builds and pushes and does not deploy
([Working with Docker on Fly.io](https://fly.io/docs/blueprints/working-with-docker)).
The label names the commit, so one tag is one build of one commit and a
later publish does not move it. Releasing without `--build-only` is a
Fly Launch release of this file, and this file is not a service
definition. The image digest is recorded with each review's output,
below.

This setup does not run `fly ips allocate-v4` or `fly ips allocate-v6` and
does not pass `--port`. `fly ips list --app atlas-reviewer` lists allocated
addresses ([fly ips list](https://fly.io/docs/flyctl/cmd/fly_ips_list)). A
public address there was allocated by something else.

## Run one review

A review is five steps: start the Machine, wait for the review to exit,
copy its output off, release the Machine, and destroy it. Do not skip
the wait or the copy. Fly gives a Machine "ephemeral storage, a blank
slate on every startup"
([An introduction to Fly Machines](https://fly.io/docs/machines/overview/)),
and the draft is on that storage, so it does not survive a stop and a
start. Starting a stopped Machine again runs the review again.

Name the event. `ATLAS_EVENT_JSON` is the event object only (`repo`,
`pr_number`, `head_sha`). It is not a Fly secret.

```sh
REPO=OWNER/REPO
PR=123
SHA=FULL_40_HEX_SHA
EVENT=$(printf '{"repo":"%s","pr_number":%s,"head_sha":"%s"}' "$REPO" "$PR" "$SHA")
NAME="review-pr$PR-$(printf '%.12s' "$SHA")"
```

Check that no review Machine is already started. The controller's
single-review lock is a file on that Machine's disk, so a second
`fly machine run` is a second review. There is no queue to stop you.

```sh
flyp machine list --app atlas-reviewer
```

In another terminal, start the logs before the review. Run the load
block from [Fly credentials](#fly-credentials) there first: a new shell
has neither the token variable nor `flyp`. The controller's progress and
the runner Sprite's name go to the logs:

```sh
flyp logs --app atlas-reviewer
```

`fly logs` streams the app's logs until you stop it
([fly logs](https://fly.io/docs/flyctl/cmd/fly_logs)). A fetch started
afterwards can miss the start of the run (see
[What the 2026-11-10 deploy showed](#what-the-2026-11-10-deploy-showed)).

### Start the review

```sh
flyp machine run "$IMAGE" \
  --app atlas-reviewer \
  --name "$NAME" \
  --region iad \
  --vm-cpu-kind shared \
  --vm-cpus 1 \
  --vm-memory 1024 \
  --restart no \
  --entrypoint /usr/local/bin/atlas-reviewer \
  --env ATLAS_EVENT_JSON="$EVENT" \
  --env ATLAS_HOLD_SECONDS=3600 \
  -- review --event /home/atlas/event.json \
       --out /home/atlas/out/draft.md \
       --events /home/atlas/out/events.jsonl \
       --provider openrouter --allow-live-inference
```

Set `MACHINE_ID` to the Machine ID that command prints. `fly machine
list` shows it too.

`fly machine run` takes the app from `--app` and disregards the rest of
`fly.toml`, so these flags are what make the Machine a one-off with no
published port
([Run a new Machine](https://fly.io/docs/machines/flyctl/fly-machine-run)).
`--restart no` keeps Fly from starting it again. There is no `--rm`: the
operator destroys the Machine after copying its output. Do not pass
`--port`. `--region iad` is the region this command selects;
`primary_region` in `fly.toml` is not consulted by `fly machine run`.
`--vm-memory` is megabytes, and 1024 MB is the size recorded for this
command, not a measurement from a live review.

The same page says the command waits until the Machine has started and
any configured health checks have passed. This image defines no health
check. flyctl's exit means the Machine started, not that the review
finished.

The `--` ends flyctl's own flags. Everything after it is the controller
command (`config.init.cmd` on that Machine). `--entrypoint` is the script
in the image. It writes `ATLAS_EVENT_JSON` to `/home/atlas/event.json`
as uid 10001, creates `/home/atlas/out`, and runs the CLI.
`fly machine run --file-local` is not used: that flag's doc does not say
which uid owns the file or what mode it gets, and this process is not
root.

The Machines API describes `name` as a "Unique name for the Machine"
([Machines](https://fly.io/docs/machines/api/machines-resource)), so
`--name` names the review after its PR and commit. The runner Sprite is
named after the event too: `cqa-rev-pr<PR>-<first 12 of SHA>-<8 hex>`.
The controller prints `atlas_reviewer: runner Sprite for this review:
<name>` before it creates that Sprite. If a Sprite already has the name,
the review exits 3 before creating anything.

Leave off `--provider openrouter --allow-live-inference` to use the
offline provider. GitHub and Sprites still run. Do not pass `--dry-run`.

### Wait for the review to exit

When the CLI exits, the entrypoint writes its exit code to
`/home/atlas/out/exit-code` and holds the Machine for
`ATLAS_HOLD_SECONDS`. Poll for that file.

On 2026-11-11, with flyctl, the first `fly ssh console` on the first
held Machine failed for about 6 minutes, and later Machines connected
in about 3 seconds. A likely cause is first-time SSH or WireGuard
setup; that was not confirmed. The earlier poll discarded stderr, so
the failure had no visible reason. This poll leaves stderr on the
terminal. The first connection can be slow. This is what that run
showed, not a documented Fly behavior.

```sh
code=
deadline=$(( $(date +%s) + 3600 ))
while [ -z "$code" ] && [ "$(date +%s)" -lt "$deadline" ]; do
  sleep 30
  code=$(flyp ssh console --app atlas-reviewer --machine "$MACHINE_ID" -q \
    -C 'cat /home/atlas/out/exit-code' | tr -dc '0-9')
done
echo "review exit code: ${code:-none after an hour}"
```

`review` exits 4 when file coverage is incomplete (D36). With complete
coverage it exits 5 when the review requests changes and 0 otherwise.
Usage is 2 and a boundary failure is 3. A stop is 130, the
shell's status for a process that died on SIGINT (`subprocess` sees
the signal as a negative code). flyctl's own exit status is not one
of those. With no code after an hour, the review is hung. Go to
[Hard stop](#hard-stop).

Two other places show the process exit code, but not during the hold.
The entrypoint is the Machine's main child and keeps running while it
holds, so they appear only when the hold ends or the Machine stops, and
by then the draft is gone:

- the `fly logs` line `Main child exited normally with code: N`
- `fly machine status <id>` events, which show `exit_code=N`

Use them to confirm the code after the release step below, never in
place of the poll.

### Copy the output off

Copy into a directory outside the checkout, then record which image ran:

```sh
RUN_DIR="$HOME/atlas-runs/$NAME"
mkdir -p "$RUN_DIR"
flyp ssh sftp get /home/atlas/out/draft.md "$RUN_DIR/draft.md" \
  --app atlas-reviewer --machine "$MACHINE_ID" || echo "no draft.md on the Machine"
flyp ssh sftp get /home/atlas/out/events.jsonl "$RUN_DIR/events.jsonl" \
  --app atlas-reviewer --machine "$MACHINE_ID" || echo "no events.jsonl on the Machine"
flyp image show --app atlas-reviewer > "$RUN_DIR/image.txt"
```

[fly ssh sftp](https://fly.io/docs/flyctl/cmd/fly_ssh_sftp) copies one
file. [fly image show](https://fly.io/docs/flyctl/cmd/fly_image_show)
lists each Machine's image with its digest. The draft carries the review
event and, when coverage is incomplete, the
"REVIEW INCOMPLETE -- not approvable" warning. A review that exits 2 or
3 may stop before writing a draft or `events.jsonl`; the copy then says
which file is missing, and the next command still runs. The reason is in
`fly logs`, and in `events.jsonl` when that file exists.

Then check the draft's cleanup line:

```sh
grep -F 'destroy was NOT verified' "$RUN_DIR/draft.md" &&
  echo "after the release, recover the runner Sprite by name"
```

A match means the runner Sprite may still exist. The ledger that recorded
its name is on this Machine's disk and goes with it, so a plain `sweep`
on another Machine finds nothing (`0 runner(s) in the ledger`). After the
release, recover it with `sweep --event ... --force-live`, as in
[Recover a runner Sprite by name](#recover-a-runner-sprite-by-name).
With no draft, `fly logs` says whether the review got as far as creating
the runner.

### Release and destroy the Machine

```sh
flyp machine stop "$MACHINE_ID" --app atlas-reviewer
flyp machine wait "$MACHINE_ID" --app atlas-reviewer --state stopped
flyp machine status "$MACHINE_ID" --app atlas-reviewer
flyp machine destroy "$MACHINE_ID" --app atlas-reviewer
flyp machine list --app atlas-reviewer
```

`fly machine stop` sends SIGINT. During the hold, the entrypoint exits
on that signal with the review's exit code, so the Machine's exit code
is the review's. A normal exit destroys the runner Sprite in the
controller's `finally` before the process exits.

### Hard stop

For a review that is still running and should not be:

```sh
flyp machine stop "$MACHINE_ID" --app atlas-reviewer --signal SIGINT --timeout 120
flyp machine wait "$MACHINE_ID" --app atlas-reviewer --state stopped
flyp machine destroy "$MACHINE_ID" --app atlas-reviewer --force
```

The entrypoint passes a stop it receives on to the CLI as SIGTERM,
because `sh` starts the CLI with SIGINT ignored. The CLI turns SIGTERM
into `KeyboardInterrupt`, so its `finally` blocks delete the runner
Sprite within its 60-second cleanup budget. The CLI ignores any further
stop signal, so stopping again does not skip that delete. `--timeout 120`
is how long Fly waits before SIGKILL.

`fly machine stop`, including `--signal SIGINT`, signals the entrypoint.
The entrypoint then exits without holding, so there is nothing to copy.
On 2026-11-11, with flyctl, that stop ended the Machine with exit 130
about 1 second later, and the runner Sprite was gone. That is the
supported hard stop.

A SIGTERM sent straight to the CLI process does not signal the
entrypoint. Observed the same day with flyctl, the entrypoint held, and
`/home/atlas/out/exit-code` was 130. That is an observation from that
run, not a supported stop path: this runbook does not say how to find
the CLI's PID or when to prefer that over `fly machine stop`.

`--force` destroys the Machine in any state. A SIGKILL skips `finally`,
so after a hard stop check for the runner Sprite as below.

### Recover a runner Sprite by name

`fly apps destroy` does not remove Sprites. A Sprite lives on the
Sprites service, not on Fly, and deleting a Machine or the app leaves it
running. The runner ledger was on the review Machine's disk, which is
gone, so recovery is by name. The single-review lock is per Machine, so
nothing stops this sweep from destroying the runner of a review still
running on another Machine. Check first that no review Machine is
running:

```sh
flyp machine list --app atlas-reviewer
```

Then sweep by name. `--force-live` records that you checked; without it
the sweep refuses (exit 2).

On 2026-11-11, with flyctl, `fly machine run --rm` hung at "Attempting
to start machine..." after the Machine had already exited and been
removed. It hung twice for more than 4 minutes, and a third time on a
very short command (`probe-runner`). `timeout 45` stopped the hang.
This is what that run showed, not a documented Fly behavior. `timeout`
is GNU coreutils (`gtimeout` from Homebrew coreutils on macOS). It
runs a program and cannot call the `flyp` function, so the sweep and
the protocol probe export the org token inside a subshell the way
`flyp` does, and run `timeout 45 fly ...` there. The review-sequence
run uses that same subshell and `--detach`, with no `timeout`. The
token stays in the subshell's environment, not on a command line.

Note the Machine ID that `fly machine run` prints before any hang.
If `MACHINE_ID` is empty, stop. Read the Machine list
(`fly machine list`) and take the ID from there. Do not run the logs
command until `MACHINE_ID` is set. With it empty, that command reads
the app-wide log.

```sh
flyp machine list --app atlas-reviewer
```

If the wrapper stops a hung flyctl, its status is timeout's, not the
controller's. Read that Machine's logs only
([fly logs](https://fly.io/docs/flyctl/cmd/fly_logs) filters with
`--machine`):

```sh
flyp logs --app atlas-reviewer --machine "$MACHINE_ID" --no-tail
```

App-wide `--no-tail` keeps only the last 100 lines and can return
another Machine's `Main child exited normally with code: N`. A
timeout can also stop a slow but healthy run before this Machine has
written that line; then the outcome is unknown. For the sweep, the
success signal is that Machine's own
`<name>: destroyed (verified absent)` or
`<name>: already absent, nothing deleted (verified absent)` line. If
neither line appears for that Machine, run the sweep again. Exit 3
means the same: the runner was not verified gone.

The protocol probe below uses the same `timeout 45` subshell and the
same per-Machine logs read. `timeout 45` is what stopped the hang on
the short commands that run showed. A review sequence also creates a
runner and fetches the head-SHA tarball, so the same 45 seconds can
stop a run that is still working. That command uses `--detach`
instead. The machine-run doc says `--detach` returns immediately
instead of monitoring deployment progress
([fly machine run](https://fly.io/docs/flyctl/cmd/fly_machine_run/)).
The 2026-11-11 run did not use `--detach`. Its exit code is still that
Machine's logs line, read with `--machine` as above.

```sh
(
  unset FLY_ACCESS_TOKEN
  export FLY_API_TOKEN="$FLY_PERSONAL_API_TOKEN"
  timeout 45 fly machine run "$IMAGE" \
    --app atlas-reviewer \
    --region iad \
    --vm-cpu-kind shared \
    --vm-cpus 1 \
    --vm-memory 1024 \
    --rm \
    --restart no \
    --entrypoint /usr/local/bin/atlas-reviewer \
    --env ATLAS_EVENT_JSON="$EVENT" \
    -- sweep --event /home/atlas/event.json --force-live
)
```

`sweep --event` derives the runner name from the event. `sweep --runner
<name>` takes the name from the logs line instead. Either one records the
name in that Machine's ledger and destroys it. The same command works
from a checkout with `ATLAS_SPRITES_TOKEN` set:
`python -m atlas_reviewer sweep --event event.json --force-live`.

The protocol probe and the sweep use the same image, the same
`--rm --restart no` flags, and the same `timeout 45` subshell. The
review-sequence run uses `--detach` instead. The protocol probe's output
is short. On the 2026-11-11 probe-runner run, telemetry from a `--rm` probe was gone
with the Machine's disk and survived only in `fly logs`. Start
streaming logs before the probe, with the `flyp logs` command in
[Run one review](#run-one-review). If flyctl hangs after the Machine
has already exited, read that Machine's exit with the
`--machine "$MACHINE_ID"` logs command above.

A probe does not call a model, and nothing in the controller checks
that. App secrets are on every Machine, so the probe Machine also
receives `ATLAS_OPENROUTER_API_KEY`. That is a current limitation. On
that probe-runner run the key was there. That run did not show that
`fly secrets unset --stage` keeps the key off the next Machine. The
steps below are the workaround, not something that probe confirmed.
Before the probe, unstage it. `--stage` skips a release, as
[Secrets](#secrets) already says for
`fly secrets set`. `fly secrets list` prints names, not values; the
OpenRouter name should be absent:

```sh
flyp secrets unset ATLAS_OPENROUTER_API_KEY --stage --app atlas-reviewer
flyp secrets list --app atlas-reviewer
```

The command with no `ATLAS_EVENT_JSON` is only the protocol probe:

```sh
(
  unset FLY_ACCESS_TOKEN
  export FLY_API_TOKEN="$FLY_PERSONAL_API_TOKEN"
  timeout 45 fly machine run "$IMAGE" \
    --app atlas-reviewer \
    --region iad \
    --vm-cpu-kind shared \
    --vm-cpus 1 \
    --vm-memory 1024 \
    --rm \
    --restart no \
    --entrypoint /usr/local/bin/atlas-reviewer \
    -- probe-runner
)
```

`probe-runner --sequence review` on Fly cannot use `--tarball`. This
image copies the controller, not a checkout tarball. The review
sequence needs `--event` and `ATLAS_EVENT_JSON`. The entrypoint writes
that variable to `/home/atlas/event.json`. On the 2026-11-11
probe-runner run the command was `--sequence review --event
/home/atlas/event.json --tools review`:

```sh
(
  unset FLY_ACCESS_TOKEN
  export FLY_API_TOKEN="$FLY_PERSONAL_API_TOKEN"
  fly machine run "$IMAGE" \
    --app atlas-reviewer \
    --region iad \
    --vm-cpu-kind shared \
    --vm-cpus 1 \
    --vm-memory 1024 \
    --detach \
    --rm \
    --restart no \
    --entrypoint /usr/local/bin/atlas-reviewer \
    --env ATLAS_EVENT_JSON="$EVENT" \
    -- probe-runner --sequence review --event /home/atlas/event.json --tools review
)
```

Note the Machine ID that command prints.
If `MACHINE_ID` is empty, stop and read the Machine list, as above.
Do not run the wait or the logs command until it is set.

`--rm` destroys the Machine when it stops
([Run a new Machine](https://fly.io/docs/machines/flyctl/fly-machine-run/)).
The Machines API can wait for `destroyed` as well as `stopped`
([Wait for State](https://fly.io/docs/machines/api/machines-resource/#wait-for-a-machine-to-reach-a-specified-state)).
Wait for `destroyed` here, not `stopped`: a `--rm` Machine is gone
once it exits, so `stopped` is not the state this probe ends in.
The 2026-11-11 run did not use `fly machine wait`.
[`fly machine wait`](https://fly.io/docs/flyctl/cmd/fly_machine_wait/)
defaults to 5 minutes. This wait uses 1 hour, the same bound as the
review poll, because a review sequence also creates a runner and
fetches a tarball.

```sh
flyp machine wait "$MACHINE_ID" --app atlas-reviewer --state destroyed --wait-timeout 1h
```

Then read that Machine's logs, before staging the key again. The probe
passed when that Machine's line is
`Main child exited normally with code: 0`. The controller writes
`status: completed` for that exit. It writes
`probe: FAILED -- the runner is not usable as probed` and the logs
line ends in `code: 3` when the runner did not complete.

```sh
flyp logs --app atlas-reviewer --machine "$MACHINE_ID" --no-tail
```

If that line is still absent after the wait, read the log stream
started before the probe
([Run one review](#run-one-review)). `--no-tail` keeps only the last
100 lines. Do not stage the key. Report that this probe did not show
`code: 0`.

After the probe, stage the pilot key again from stdin. The `grep`
writes that one line to the import, not to the terminal. `--stage`
still skips a release. Then list the names again. `fly secrets list`
prints names, not values; the OpenRouter name should be present:

```sh
grep -E '^ATLAS_OPENROUTER_API_KEY=' "$SECRETS_DIR/secrets.env" |
  flyp secrets import --stage --app atlas-reviewer
flyp secrets list --app atlas-reviewer
```

## Tear it down

`fly apps destroy` deletes the app
([fly apps destroy](https://fly.io/docs/flyctl/cmd/fly_apps_destroy)).
`--yes` accepts the confirmations. Secrets live in that app's vault, so
they go with the app. Sprites do not. Do this when `fly machine list`
shows no Machine and every review's runner Sprite was destroyed or
recovered by name.

```sh
flyp machine list --app atlas-reviewer
flyp apps destroy atlas-reviewer --yes
```

## What the 2026-11-10 deploy showed

An operator created app `atlas-reviewer` in the Fly org `personal` and
ran one offline-provider review of
[PR #605](https://github.com/brandondees/code-quality-atlas/pull/605),
with `fly machine run --rm` and the draft on stdout. This repository
still does not create the app or set a secret. That run showed:

- `fly deploy --build-only --push` accepted this no-service `fly.toml`.
  The default Depot builder timed out after about 5 minutes with
  `authentication handshake failed: EOF`. The same command with
  `--depot=false` succeeded in about 2 minutes.
- The builder pulled the pinned `python:3.12.16-slim-bookworm` base image.
- The process ran as uid 10001.
- The process exited 4. flyctl's own exit only meant the Machine started.
  The code was the logs line `Main child exited normally with code: 4`
  and `exit_code=4` on `fly machine status <id>` after `--rm` had
  destroyed the Machine.
- The controller destroyed the Sprite, and a check afterwards found it
  absent.
- No secret values appeared in `fly logs`.
- `fly secrets import --stage` was enough. flyctl suggested
  `fly secrets deploy`. That command was not run, and the next
  `fly machine run` already had the staged secrets.
- `fly logs` started before the run kept all 137 draft lines.
  `fly logs --no-tail` after `--rm` returned the last 100 lines only, so
  the draft header and the "REVIEW INCOMPLETE -- not approvable" warning
  were already gone. That is why a review now writes its draft to disk.

It did not show the held shape this runbook now uses, a complete review
exiting 0, a run that passes `--provider openrouter
--allow-live-inference`, or a taken app name handled only with
`--app <name>`.

## Accepted costs

- Every app secret is in the environment of every Machine of the app
  ([Secrets and Fly Apps](https://fly.io/docs/apps/secrets)). A
  `probe-runner` or `sweep` Machine needs only `ATLAS_SPRITES_TOKEN` and
  still gets the GitHub App key and the OpenRouter key. A probe does
  not call a model, and nothing refuses to run it while
  `ATLAS_OPENROUTER_API_KEY` is set. Unstage that key before a probe,
  as in [Recover a runner Sprite by name](#recover-a-runner-sprite-by-name).
  Each Machine runs
  one controller command from this image and publishes no port. A second
  app per credential set is not worth it for one operator.
- The image installs the whole dev lock, so mypy, pytest, and ruff are in
  the runtime image. The hashed lock is the one CI already checks. A
  separate runtime lock is a follow-up, not part of this deploy.
- A held Machine is billed until the operator destroys it, up to
  `ATLAS_HOLD_SECONDS` after the review. If nobody copies the output
  within that hold, the entrypoint exits and Fly resets the stopped
  Machine's root filesystem, with the draft on it.

## Checked without a live deploy

`atlas_reviewer/tests/test_fly_deploy.py` parses `fly.toml` and the
Dockerfile: the TOML keys, the pin, the non-root user, the hashed
install, the files copied in, and no published port. It runs the
entrypoint against a stub CLI to check the exit-code file and the hold.
Its checks on this runbook's text are string-presence guards: they
confirm a command or a warning is written here, not that Fly accepts it.
No Fly API was called.

The 2026-11-10 run covered the build, the base image, uid 10001, and
the secrets staying out of `fly logs`. A live run of the held shape is
what can show: that an org token for `personal` is enough for every step
here, `fly ssh` and `fly ssh sftp` included; that the exit-code file,
the draft, and the telemetry can be copied off a held Machine; that Fly
refuses a second Machine with the same `--name`; and that
`fly machine stop` reaches the entrypoint and the runner Sprite is
deleted.
