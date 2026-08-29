# Self-Hosted CI Runner Setup

How to register a self-hosted GitHub Actions runner, size the host it runs on,
diagnose a job that never started, and migrate a runner to a new machine —
plus the gotchas that would otherwise resurface on every new host.

See [calendar-proxy's `docs/runtime.md`](https://github.com/brandondees/calendar-proxy/blob/main/docs/runtime.md#self-hosted-ci-runners)
for what actually runs where and the operational trade-offs; this page is the
"how to set one up" companion.

> **This file is copied verbatim into every repo on the runner fleet.**
> `calendar-proxy/docs/self-hosted-runners.md` is the canonical copy — fix it
> there and re-copy, rather than patching a copy in place. Copies are used
> instead of a cross-repo link because most work in these repos happens in
> isolated containers where a link to another repo is not reachable. The
> accepted cost is drift: a copy may lag the canonical, so check the canonical
> before trusting anything here that looks surprising.
>
> **Links to `calendar-proxy` in this file require access to that repo**,
> which is private. They resolve for the fleet's operators and `404` for
> anyone else — relevant because some repos carrying this copy are public.
> Nothing here depends on following them; they are provenance, not
> instructions.
>
> Concrete file references in the gotchas below (`fly-deploy.yml`,
> `nightly.yml`, `markdown.yml`, …) are **examples from calendar-proxy**,
> where each gotcha was first hit. They illustrate the shape of the problem;
> they are not claims about the repo you are reading this in.
>
> Fleet as of 2026-08-29: one Linux host (`runner-2604`, an OrbStack Ubuntu
> 26.04 LTS VM, 6 CPU / 12 GB) serving six repos, plus `macos-local` (the Mac
> itself) and an X64 fleet on other machines (`orbstack-linux`,
> `bazzite-runner-*`). Every repo's Linux runner is named `orbstack-linux-mbp`
> — the name is per-repo, so the same name on six repos is six registrations
> of one host, not a conflict.

This guide answers the three questions that come up every time CI looks
broken:

1. **Which runners exist, where do they live, and what do they do?** —
   [Fleet registry](#fleet-registry)
2. **How do I bring a dead runner back online?** —
   [Operating the runners](#operating-the-runners)
3. **Why is my job stalled?** —
   [Diagnosing a job that never ran](#diagnosing-a-job-that-never-ran)

(Listed in the order the sections appear below, not in order of how often you
will want them — in practice question 3 is the common entry point.)

## Fleet registry

Runner **names** are per-repo, so the same name appearing in several repos is
several registrations of one machine, not one shared runner. Labels are what
`runs-on:` actually matches, and they are matched **case-insensitively**
(`linux` matches the `Linux` label).

| Name                            | OS    | Arch   | Host                                   | Labels                                      |
| ------------------------------- | ----- | ------ | -------------------------------------- | ------------------------------------------- |
| `macos-local`                   | macOS | ARM64  | The Mac itself (native, launchd)       | `self-hosted`, `macOS`, `ARM64`             |
| `orbstack-linux-mbp`            | Linux | ARM64  | The Mac, OrbStack VM **`runner-2604`** | `self-hosted`, `Linux`, `ARM64`, `orbstack` |
| `orbstack-linux`                | Linux | x86_64 | Other laptop (OrbStack VM)             | `self-hosted`, `Linux`, `X64`, `orbstack`   |
| `bazzite-runner-9cbf0d01cf92-2` | Linux | x86_64 | Bazzite host (other machine)           | `self-hosted`, `Linux`, `X64`, `bazzite`    |
| `bazzite-runner-9cbf0d01cf92-3` | Linux | x86_64 | Bazzite host (other machine)           | `self-hosted`, `Linux`, `X64`, `bazzite`    |

Not every repo has every runner registered. **Check the live list rather than
trusting this table** — it has gone stale before, and a table that names a
deleted host is worse than no table:

```sh
gh api repos/<owner>/<repo>/actions/runners \
  --jq '.runners[] | "\(.name) \(.status) busy=\(.busy) [\([.labels[].name]|join(","))]"'
```

> **`orbstack-linux-mbp` moved hosts on 2026-08-29.** It previously lived in
> an OrbStack VM named `actions-runner-mbp` running Ubuntu 25.10 — an interim
> release that went EOL 2026-07-01 and was still serving CI for six repos two
> months later. The runner was re-registered under the same name and labels
> into `runner-2604` (Ubuntu 26.04 LTS) and the old VM deleted. Anything still
> naming `actions-runner-mbp` is stale.

## Registering a runner

GitHub Actions runners are **repo-scoped**, not shared across repos on a
personal (non-org) account — each repo needs its own registration, even on a
machine that already runs a runner for a different repo. A given directory
holds exactly one repo's runner config, so use a separate directory per repo
(`~/actions-runner-<repo>` is the convention used so far).

For a single runner, the web UI walkthrough below is fine. For several repos
at once, skip it — mint tokens from the API instead, which is scriptable and
avoids the browser entirely:

```sh
tok=$(gh api -X POST repos/<owner>/<repo>/actions/runners/registration-token --jq '.token')
```

Then reuse one already-downloaded (and checksum-verified) runner tarball
across every repo rather than re-downloading per repo, and loop:
`mkdir -p ~/actions-runner-<repo> && cd $_ && tar xzf <tarball> && ./config.sh
--url https://github.com/<owner>/<repo> --token "$tok" --unattended --name
<runner-name> --work _work`.

That only **registers** the runner. Continue with steps 3-4 below to install
it as a persistent service — a registered-but-not-installed runner works
until the terminal closes or the host reboots, and then silently stops
picking up jobs (which presents as checks stuck `queued`, not as an error).

The web-UI flow, for reference:

1. In the target repo: **Settings → Actions → Runners → New self-hosted
   runner**, pick the OS and architecture. GitHub shows a download/configure
   script with an embedded registration token — the token is single-use and
   expires quickly (well under an hour), so run the steps promptly after
   generating it.
2. Follow GitHub's shown steps, with two changes from the default:
   - Use a per-repo directory:
     `mkdir ~/actions-runner-<repo> && cd ~/actions-runner-<repo>` instead of
     the generic `actions-runner`.
   - Add `--unattended --name <runner-name> --work _work` to the `config.sh`
     invocation so it doesn't prompt interactively. Runner names used so far:
     `macos-local` (the Mac itself), `orbstack-linux-mbp` (an OrbStack Ubuntu
     VM on that Mac).
3. Install as a persistent service so it survives reboots and doesn't depend
   on a terminal staying open:
   - macOS: `./svc.sh install && ./svc.sh start` (installs a launchd
     `LaunchAgent` under the invoking user — no `sudo` needed).
   - Linux: `sudo ./svc.sh install <user> && sudo ./svc.sh start` (installs a
     systemd service; `sudo` is required here).
4. Verify: the repo's **Settings → Actions → Runners** page should show the
   new runner as `Idle`, and it flips to `Active` while running a job.

The resulting service name follows GitHub's own convention —
`actions.runner.<owner>-<repo>.<runner-name>` — so multiple repos' runners on
the same machine are easy to tell apart in `launchctl list` /
`systemctl list-units`.

## Operating the runners

### `macos-local` (native, no virtualisation)

Runs as a launchd user agent on the Mac itself:

- Install path: `~/actions-runner/` — the **generic** path, unlike the Linux
  VM's per-repo directories
- Config: `~/actions-runner/.runner`
- Plist: `~/Library/LaunchAgents/actions.runner.<owner>-<repo>.macos-local.plist`
- Logs: `~/Library/Logs/actions.runner.<owner>-<repo>.macos-local/`

```sh
P=~/Library/LaunchAgents/actions.runner.<owner>-<repo>.macos-local.plist
launchctl bootout   "gui/$(id -u)" "$P"   # stop
launchctl bootstrap "gui/$(id -u)" "$P"   # start
```

### `orbstack-linux-mbp` (inside an OrbStack VM)

The runner is a systemd unit **inside** the VM. The Mac never talks to GitHub
directly — the VM does.

| Layer               | Where                                                         |
| ------------------- | ------------------------------------------------------------- |
| Host OrbStack app   | `/Applications/OrbStack.app` (start-at-login on)              |
| VM name             | `runner-2604`                                                 |
| Runner install path | `/home/dees/actions-runner-<repo>/` (per repo, inside the VM) |
| Runner systemd unit | `actions.runner.<owner>-<repo>.orbstack-linux-mbp.service`    |

#### Boot chain, and its weak link

```text
macOS login  →  OrbStack launches (start_at_login=true)
                 │
                 └─ VM `runner-2604` starts ON DEMAND
                                    │
                                    └─ systemd brings up
                                       actions.runner.*.service
                                       which connects to GitHub.
```

The **on-demand** step is the weak link: OrbStack does not boot every VM when
the app launches — a VM starts only when something touches it (`orb -m <name>
...`). Until something does, the VM stays cold and every runner on it appears
offline, which presents as jobs stuck `queued`.

Runner services are installed `enabled`, so once the VM is up they start on
their own. The gap is purely "who starts the VM".

#### The watchdog pattern

A host-side agent that (1) starts the VM if it isn't running, (2) restarts the
runner service inside it if that is `inactive`/`failed`, and (3) logs a
heartbeat, run hourly, closes that gap without operator intervention.
`second-brain-config` implements exactly this in
`scripts/runner-healthcheck.sh`, driven by a launchd agent.

Two lessons from operating it:

- **A watchdog that hardcodes a VM name is a liability during a host
  migration.** When `actions-runner-mbp` was deleted, that script's default
  `VM_NAME` still named it, so every hourly run failed at step 1 and exited
  _before_ checking the runner — silently disabling the self-healing while CI
  itself kept working, which is what hid it. Deleting a host means grepping
  the whole fleet for its name, not just checking what runs _inside_ it.
- **`sudo -n` inside the VM needs a NOPASSWD entry** for the restart step, or
  step 2 fails every time with a bare log line. A watchdog whose repair action
  cannot actually run is only a monitor.

A native Linux host needs _less_ of this, not none: there is no VM to be
stopped from outside, which is the specific gap the watchdog's step 1 exists
for. It still gets no crash recovery.

**The runner unit does not restart itself.** `svc.sh install` renders
upstream's `actions.runner.service.template`, which contains no `Restart=`
directive at all — so systemd's default `Restart=no` applies and a crashed or
OOM-killed runner simply stays dead. Verified on this fleet:

```sh
$ systemctl show 'actions.runner.<owner>-<repo>.<name>.service' -p Restart --value
no
$ grep -l 'Restart=' /etc/systemd/system/actions.runner.*.service | wc -l
0
```

This is not hypothetical. When the OOM cascade described under
[Sizing the host](#sizing-the-host) killed four of five runner services, none
of them came back on their own — they stayed `failed` until the VM was
rebooted, and they returned then only because the units are `enabled` (start
at boot), which is a different mechanism from a restart policy. A dead runner
service means that repo's jobs sit `queued` with no error, which is row 2 of
the triage table above.

If you want crash recovery, add it explicitly — a drop-in is the least
invasive way, since `svc.sh` will overwrite the unit itself on reinstall:

```sh
sudo systemctl edit 'actions.runner.<owner>-<repo>.<name>.service'
# [Service]
# Restart=always
# RestartSec=10
```

#### Manual checks

```sh
orb list                                        # is the VM up?
orb -m runner-2604 systemctl status 'actions.runner.*'
orb -m runner-2604 journalctl -u 'actions.runner.*' -n 50 --no-pager
gh api repos/<owner>/<repo>/actions/runners \
  --jq '.runners[] | "\(.name) \(.status) busy=\(.busy)"'
gh api repos/<owner>/<repo>/actions/runs \
  --jq '.workflow_runs[] | select(.status != "completed") | "\(.name) \(.status) \(.head_branch)"'
```

## Diagnosing a job that never ran

Four unrelated failures present almost identically — a job with **no runner
name, zero steps, and no log** — and they want completely different fixes.
Distinguishing them by eye is not possible; you have to read the check-run
annotation. Getting this wrong cost most of a day on 2026-08-29, when a
billing stop was diagnosed as an OOM because the two look the same in the
Actions UI.

| Symptom                                                | Cause                                         | Confirm with                                        |
| ------------------------------------------------------ | --------------------------------------------- | --------------------------------------------------- |
| Fails in ~2s, `runner=` empty, `steps=0`, log 404s     | **Account billing / spending limit**          | check-run annotation (see command below)            |
| Sits `queued`, never starts, no error                  | **No runner online with the required labels** | `gh api repos/O/R/actions/runners`                  |
| Started, then `cancelled` mid-run with steps part-done | **Runner process OOM-killed**                 | `journalctl -u 'actions.runner.*' \| grep -i oom`   |
| Queued behind a long job on a single-runner repo       | **Ordinary serialization**                    | `gh api .../actions/runners --jq '.runners[].busy'` |

The annotation is the only place the billing cause is stated in words, and
neither `gh run view` nor the job log surfaces it:

```sh
gh api "repos/<owner>/<repo>/check-runs/<job-id>/annotations" \
  --jq '.[] | "\(.annotation_level): \(.message)"'
# -> failure: The job was not started because recent account payments have
#    failed or your spending limit needs to be increased.
```

Two traps when reading this:

- **A hosted job that succeeds does not prove hosted runners work.**
  Dependabot's graph-update jobs bill to GitHub rather than to the account, so
  they keep passing right through a billing stop. Seeing one green is not
  evidence; check a job you actually own.
- **Only private repos are affected by a spending limit.** Public repos get
  free hosted minutes, so the same workflow can be broken in one repo and fine
  in another on the same account, which reads as a repo-specific bug.

The structural fix is not to restore billing — it is to stop depending on
hosted runners for anything gating self-hosted work. A cheap `changes` /
path-filter job on `ubuntu-latest` in front of self-hosted jobs means every
other job `needs:` it, so one hosted failure takes the whole workflow red.
Put the gate on the same runner class as the work it gates.

Be precise about what happens to the gated jobs, because it depends on how
they are written. By default a job whose `needs:` dependency failed is
**skipped**, not run. The workflows on this fleet deliberately gate on
`if: ${{ !cancelled() && needs.changes.outputs.<x> != 'false' && ... }}`,
and `!cancelled()` overrides the implicit `success()` GitHub adds — so they
_do_ still run, and were observed passing on `orbstack-linux-mbp` while the
hosted gate failed. Either way the run is red; the difference is whether you
also lose the test signal.

### Other symptoms worth recognizing

**Jobs stalled `queued`, walked in order:**

1. Is at least one runner with the required labels `online`? A `linux` job
   needs any Linux runner; a `macOS` job needs `macos-local` specifically.
2. If the local Linux runner is offline, is the VM even up? `orb list`, then
   `orb start runner-2604`. This is the on-demand weak link described above.
3. Is the runner service active inside the VM?
   `orb -m runner-2604 systemctl status 'actions.runner.*'`
4. Is this repo's runner simply busy with one of **its own** jobs? One
   registration runs one job at a time. Note the runner API's `busy` flag is
   per-repo — another repo's job does **not** show up there and does not
   queue behind yours (see the capacity note below), so if `busy=false` and
   the job still isn't starting, look at host load rather than for a queue.

**`docker: command not found` or a missing `/var/run/docker.sock`** — the job
landed on a Linux runner whose VM has no Docker. Nothing installs it
automatically:

```sh
orb -m runner-2604 bash -c '
  sudo apt-get update -qq &&
  sudo apt-get install -y docker.io docker-compose-v2 &&
  sudo usermod -aG docker dees &&   # see the caveat below
  sudo systemctl enable --now docker &&
  sudo systemctl restart "actions.runner.*"
'
```

> **`usermod -aG docker` grants root-equivalent access to the host.** Anyone
> who can talk to the Docker socket can start a privileged container that
> mounts `/`, so docker-group membership is effectively unrestricted root
> ([Docker's own post-install
> docs](https://docs.docker.com/engine/install/linux-postinstall/) say so
> explicitly). That is a deliberate trade here — the runner has to build
> images — but it is worth making consciously rather than copy-pasting it
> mid-incident, and it compounds the cross-repo blast radius described under
> [Accepted Risks](#accepted-risks): every repo's CI on this host inherits
> that access. Rootless Docker is the mitigation if that ever stops being an
> acceptable trade.

**GitHub says the runner is online but jobs still do not start** — the agent
hits a TLS hiccup on its broker connection and normally reconnects itself, but
a wedged agent looks identical from outside the VM. Read its own diagnostic
log, which is per-repo:

```sh
orb -m runner-2604 tail -50 ~/actions-runner-<repo>/_diag/Runner_*.log
```

If the newest entry is hours old, or shows endless `BrokerServer` errors with
no recovery, restart that repo's runner service.

**`No space left on device`** — see
[Automated Disk Cleanup](#automated-disk-cleanup). Because the host is shared
by six repos, reach for the bounded `docker-gc.sh` rather than
`docker system prune -af`: a blanket prune throws away every repo's cached
layers and _still_ misses the per-job buildx builders where the space actually
accumulates.

> **"Stuck queued" has an upper bound, and it is not forever.** GitHub
> terminates a job that has not started within **24 hours**
> ([queue limits](https://docs.github.com/en/actions/reference/limits)), so a
> job blocked on a dead or missing runner eventually surfaces as _cancelled_
> rather than staying pending indefinitely. That matters twice: a cancelled
> job with no logs is easy to misread as a flake rather than a runner
> outage, and `timeout-minutes` still does not help, because it only starts
> counting once a job has begun.

## Sizing the host

An undersized host does not fail cleanly; it thrashes, and the symptoms point
away from memory. On 2026-08-29 a 4 CPU / 8 GB VM serving six repos produced
**45 OOM kills in 30 minutes**, which killed four of five runner _services_
outright — and a dead runner service means its repo's jobs sit `queued`
(row 2 of the table above), so the presenting symptom was "CI is stuck", not
"we are out of memory".

Recognizing the thrash state, which is easy to misread as "busy":

- Load average very high (57 was observed) while the actual build processes
  hold **small** RSS — 30–130 MB each. Low RSS under high load means working
  sets have been swapped out and the box is page-faulting, not computing.
- `SwapFree` near zero. Once swap is exhausted the OOM killer is the only
  remaining relief valve, and it picks victims host-wide — one repo's heavy
  build can kill another repo's runner.
- Waiting does not recover it. Load climbed for an hour while "letting it
  settle"; it only recovered when the runner processes were killed.

```sh
# On the runner host
uptime; free -h
journalctl -b --no-pager | grep -ci 'oom-kill\|Out of memory'
systemctl list-units 'actions.runner.*' --all --no-legend --plain
```

Working configuration for six repos on one OrbStack VM: **6 CPU / 12 GB**.
After the bump: 0 OOM kills, ~6 GB available under load, swap essentially
untouched. For OrbStack specifically, `memory_mib` is a _ceiling_, not a
reservation — raising it lets the VM grow under pressure rather than taking
the memory immediately — and applying a CPU/memory change requires a full
`orbctl stop && orbctl start`, not a machine restart.

Two measurement traps on macOS hosts:

- **`df -h /` reads the read-only system volume** and can show a comfortable
  number while the real volume is nearly full. Use
  `df -h /System/Volumes/Data`.
- **OrbStack VMs share a host kernel**, so `uptime` inside any machine reports
  the same host-wide load. Per-VM load readings are not per-VM.

## Migrating a runner to another host

Runner registrations are per-repo and name-scoped, so a migration is
"register the new one under the same name, then retire the old install" — no
workflow change is needed if the labels match.

```sh
# 1. On the OLD host: stop and unregister the service (leaves files intact)
cd ~/actions-runner-<repo> && sudo ./svc.sh stop && sudo ./svc.sh uninstall

# 2. On the NEW host: clone an existing runner install, then STRIP ITS STATE
cp -a ~/actions-runner-<other-repo> ~/actions-runner-<repo>
cd ~/actions-runner-<repo>
rm -rf .runner .runner_migrated .credentials .credentials_rsaparams \
       .service .env .path _work _diag

# 3. Register under the SAME name, with --replace to take over the old entry
gh api -X POST repos/<owner>/<repo>/actions/runners/registration-token --jq .token \
  | { read TOK; ./config.sh --url https://github.com/<owner>/<repo> \
        --token "$TOK" --unattended --replace \
        --name <same-runner-name> --labels <custom-labels> --work _work; }

# 4. Install and start
sudo ./svc.sh install <user> && sudo ./svc.sh start
```

Notes that cost time doing this:

- **`cp -a` carries a `.runner_migrated` file** that `config.sh` treats as
  "already configured", failing with _"Cannot configure the runner because it
  is already configured"_ even after `.runner` and `.credentials` are removed.
  It is not in any of the obvious cleanup lists — remove it explicitly.
- **`--replace` is what lets you keep the name.** Without it, registering a
  second runner under an existing name is rejected.
- **Custom labels must be re-supplied.** `self-hosted`, `Linux`, and the arch
  are added automatically; anything else (e.g. `orbstack`) is lost unless
  passed to `--labels`, and losing it silently strands every job whose
  `runs-on:` names it.
- **The registration token still reaches `config.sh` as an argv element.**
  Reading it from stdin, as above, keeps it out of _shell history_ — which is
  worth doing — but `--token "$TOK"` is a process argument, so it is visible
  in `ps` to any local user for the lifetime of the call, and to anything
  scraping `/proc`. There is no argv-free flag; the mitigations are to treat
  the host as trusted, and to rely on the token being single-use and
  short-lived (well under an hour). Do not describe this as "not on the
  command line".

Before deleting the old host, verify what actually depends on it rather than
assuming. Check for runner services (`systemctl list-units 'actions.runner.*'`),
scheduled units the fleet relies on (`docker-gc.timer`, `disk-guardrail.timer`
— confirm the new host has them, not just the old one), credential
directories (`~/.fly`, `~/.gnupg`, `~/.docker`), and whether `~/.ssh` holds
real keys or symlinks to the host Mac. Reclaimed disk is also **asynchronous**
— free space can briefly go _down_ right after a delete, so re-measure a few
minutes later before concluding nothing was freed.

## Known gotchas

Everything below was discovered the hard way wiring up `calendar-proxy`'s two
runners (PR [#760](https://github.com/brandondees/calendar-proxy/pull/760))
and will very likely resurface on the next repo/machine:

- **The runner user is unprivileged.** Unlike GitHub-hosted `ubuntu-latest`,
  a self-hosted runner typically has no write access to `/usr/local/bin` or
  other system directories. Any workflow step that downloads a tool binary
  and installs it needs to target `$HOME/.local/bin` (or similar) and add
  that to `$GITHUB_PATH`, not `mv` into a system path — a plain
  `mv ... /usr/local/bin/foo` fails with `Permission denied`.
- **Architecture-specific binary pins need re-checking.** Any workflow step
  that downloads a pinned tool release (calendar-proxy's `mise`, `hadolint`)
  by a
  hardcoded asset name (`*-linux-x64`, `*-Linux-x86_64`) will silently fail
  to execute on an ARM64 runner — re-pin to the matching arch's asset name
  and re-verify its checksum from the tool's actual release page; don't
  guess or reuse the x64 checksum.
- **Docker must be installed and running** on a Linux runner that needs it
  (image builds, any Docker-based release gate). Nothing installs this
  automatically — it's a one-time manual setup on that machine.
- **Check the dependency tree ships arm64 artifacts before committing to a
  migration — some repos simply can't move.** A locked dependency with no
  `manylinux_aarch64` wheel doesn't error cleanly; the resolver silently
  falls back to building from sdist, which can mean a 20+ minute
  cargo/cmake compile on every job, or an outright failure. `software-factory`
  is blocked on exactly this (`libsql` publishes `macosx_11_0_arm64`,
  `manylinux_x86_64`, and `win_amd64` — no Linux arm64), which takes all of
  its workflows off the table for an ARM64 host regardless of anything else.
  Check before planning, not after:

  ```sh
  curl -s https://pypi.org/pypi/<package>/<version>/json | jq -r '.urls[].filename'
  ```

  The same applies to Rust crates needing a C toolchain (`aws-lc-sys`,
  `ring` → install `cmake` + `clang` on the host) and to any tool fetched as
  a prebuilt binary. A repo blocked this way is a good candidate for an x64
  runner rather than a forced port.

- **Puppeteer's `linux_arm` Chrome-for-Testing channel is not a working arm64
  build.** The first symptom looks like a missing-file problem — the
  bundled-download step reports "the browser folder exists but the
  executable is missing" — but that specific message is actually caused by
  `unzip` not being installed on the host (Puppeteer's extractor silently
  no-ops without it, an easy trap: installing `unzip` and clearing the stale
  half-extracted `~/.cache/puppeteer/**/linux_arm-*` folder makes the
  download "succeed"). Verified directly (checksummed, extracted, launched):
  even with `unzip` present, the binary that download actually contains is
  x86_64 (`readelf -h` reports `Machine: Advanced Micro Devices X86-64`), not
  arm64 — it fails to launch at all on an arm64 host ("Dynamic loader not
  found: /lib64/ld-linux-x86-64.so.2"). `unzip` alone does not fix this. The
  working fix: fetch **Playwright's** genuine Linux ARM64 Chromium build
  instead (`npx playwright@<pinned-version> install chromium --with-deps` —
  a one-off invocation, never added as a project dependency) and point
  Puppeteer at it via `PUPPETEER_EXECUTABLE_PATH` plus
  `PUPPETEER_SKIP_DOWNLOAD=true`; Puppeteer only speaks the DevTools Protocol
  to whatever binary it's given, so it doesn't care who downloaded it. See
  `.github/workflows/markdown.yml`'s `lint-format` job for the working
  implementation. If a job only needs `npm ci` to succeed and never actually
  launches a browser (e.g. `npm-audit-nightly.yml`, which only runs `npm
audit`), `PUPPETEER_SKIP_DOWNLOAD=true` alone is enough — no need to fetch
  any browser at all.
- **Gate `pull_request`-triggered jobs against forks before routing them to
  self-hosted hardware.** A self-hosted runner executes checked-out code
  directly on that machine, not an ephemeral disposable VM — a `pull_request`
  workflow with no such gate would run untrusted fork contributors' code (Go
  tests, `npm ci` postinstall scripts, `docker build`, etc.) directly on
  personal hardware. Add this to the gating job (mirrors the check already
  used in `fly-deploy.yml`'s preview job):

  ```yaml
  if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository
  ```

  A fork PR then reports its checks as skipped instead of executing. Worth
  doing even on a currently-private repo with no outside collaborators, since
  it's cheap insurance against the repo going public or gaining
  collaborators later without anyone revisiting this.

- **GitHub-hosted runners are not a given fallback.** If the GitHub account
  has a billing/payment problem, `ubuntu-latest`/`macos-latest` jobs fail
  outright with "recent account payments have failed" — confirmed while
  setting this up. Don't assume you can temporarily fall back to
  GitHub-hosted without first checking **Settings → Billing & plans**.
- **Keep elevated-credential jobs off self-hosted hardware — check the
  credential is actually scoped, not just intended to be.** A self-hosted
  runner also executes untrusted third-party dependency code with no human
  review gate (Dependabot-authored PRs that auto-merge on green CI, e.g.
  `dependabot-auto-merge.yml`'s `docker`/`gomod` ecosystems) — co-locating
  that with release-signing or persistent-deployment credentials on the same
  physical host is a real lateral-movement risk, not a theoretical one.
  `release.yml` (cosign OIDC signing, GHCR push) and all of `fly-deploy.yml`
  stay on GitHub-hosted for this reason. A first pass at this repo moved
  `fly-deploy.yml`'s `preview`/`cleanup` jobs to self-hosted on the reasoning
  that their `FLY_API_TOKEN` is scoped to preview-app create/destroy only —
  but that scoped token was only _planned_ (tracked in a still-open issue), so
  those jobs were actually still using the same broad, unscoped token
  `staging` was deliberately kept off self-hosted to protect. Caught in
  review before merging (round-1 atlas review, PR #763) — worth double
  checking a "this token is narrowly scoped" justification actually holds
  today, not just once a tracked follow-up lands.
- **`actions/setup-<lang>` may have no build for your host's OS version, and
  fails outright rather than falling back.** `actions/setup-python` publishes
  linux-arm64 builds only for Ubuntu LTS-ish versions (22.04 / 24.04 /
  26.04). On a host running a non-LTS release — e.g. Ubuntu 25.10 — there is
  no matching build, no tool cache to fall back to, and often no matching
  `pythonX.Y` in apt either, so `setup-python` fails to resolve a version at
  all. GitHub-hosted images hide this completely because they ship a
  prepopulated `/opt/hostedtoolcache`.

  **The best fix is to run an LTS host, which sidesteps this entirely** — on
  26.04 `setup-python` resolves natively and none of the workaround below is
  needed (verified). Reach for the manual tool cache only when you're stuck
  on an OS version upstream doesn't publish for; seed it once per host and
  point every runner at it:

  ```sh
  # Extract into a scratch directory of its own. This matters: setup.sh
  # populates the tool cache with `cp -R ./*` from the CURRENT directory, so
  # running it anywhere containing unrelated files copies those into the tool
  # cache too. It does not extract to $AGENT_TOOLSDIRECTORY itself -- it
  # creates that tree and copies into it.
  mkdir -p /tmp/pyseed && cd /tmp/pyseed

  # Pick a build for the nearest supported OS version; verify it RUNS first
  # (they are portable across nearby glibc versions, but check, don't assume).
  curl -fsSL -o py.tar.gz "$(curl -s https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json \
    | jq -r '[.[] | select(.version|startswith("3.12.")) | .files[]
      | select(.platform=="linux" and .arch=="arm64" and .platform_version=="24.04")][0].download_url')"
  tar xzf py.tar.gz

  # setup.sh creates $AGENT_TOOLSDIRECTORY/Python/<version>/<arch> and writes
  # the <arch>.complete marker setup-python looks for. Needs write access to
  # that path -- prefix with sudo, or chown it to the runner user first.
  AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache ./setup.sh
  ```

  Then add `AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache` to each runner's
  `.env` and restart it. One shared cache serves every repo's runner on that
  host. The same class of problem applies to other `setup-*` actions.

  **A shared tool cache is a cross-repo integrity boundary.** Every repo's
  jobs can write to it, and a later job in a _different_ repo executes what
  it finds there — so a compromised or malicious workflow can plant or
  replace an interpreter another repo then runs. That is the same
  non-ephemeral-host exposure described under
  [Accepted Risks](#accepted-risks), but sharper, because the artifact is an
  executable on a path other jobs deliberately trust. Accepted here for a
  single-owner fleet; if that stops holding, the mitigations are a per-repo
  cache directory, or a root-owned cache the runner user can read but not
  write (seeded once by an operator).

- **A workflow can silently depend on a toolchain component the runner image
  happened to preinstall.** `dtolnay/rust-toolchain` installs with
  `--profile minimal`, which excludes `clippy` and `rustfmt` — but a
  `cargo clippy` step still passes on `ubuntu-latest`, because that image
  preinstalls a Rust toolchain that already carries clippy. On a
  self-hosted host the same step fails with `'cargo-clippy' is not installed
for the toolchain`. Fix it in the workflow (`components: clippy`), not by
  running `rustup component add` on the host — the workflow should declare
  what it needs so it stays correct on every runner. Check with
  `rustup component list --toolchain stable --installed`. Treat this as a
  general pattern, not a Rust quirk: any "it worked on hosted" step may be
  leaning on an undeclared part of that image.
- **Cache keys that hold compiled binaries must include `runner.arch`, not
  just `runner.os`.** `runner.os` is `Linux` on both `x86_64` and ARM64, so a
  cache populated by a hosted x64 runner will restore `x86_64` binaries onto
  an ARM64 host. This fails **silently and late**: a guard step like
  `which cargo-component` still passes (the file exists), and the failure
  surfaces later as an exec-format error. Audit every `actions/cache` whose
  path holds executables (`~/.cargo/bin`, tool caches) before migrating.
  Note `Swatinem/rust-cache` already keys on the rustc host triple, so it is
  arch-safe without changes.
- **GitHub-hosted preinstalls CLI tools a self-hosted runner won't have.**
  `gh`, `openssl`, `jq`, and similar are baked into `ubuntu-latest`'s image;
  a self-hosted host only has them if the operator installed them, and a
  missing tool fails whatever step needs it with a generic "command not
  found" rather than anything actionable. Add a cheap preflight step
  (`command -v gh >/dev/null || { echo "::error::gh not installed on this
self-hosted runner"; exit 1; }`) to any job depending on a tool that isn't
  part of the base OS — see `fly-deploy.yml`'s `preview` job — so a
  rebuilt/reset runner host fails loudly and immediately instead of mid-job.

  **Distinguish two cases, because they want different fixes.** A _toolchain
  component the workflow uses_ (clippy, a Rust toolchain, a Python version)
  belongs in the workflow, declared explicitly — see the two gotchas above.
  A _base OS utility_ (`zip`, `wget`, `rsync`, `file`, `cmake`, `clang`)
  belongs on the host: adding an install step to every workflow that happens
  to need `zip` is noise. Provision those once. Running baseline for this
  host, accumulated by hitting each one in CI:

  ```sh
  sudo apt-get install -y cmake clang python3-pip zip unzip wget rsync file
  # plus: docker (+ add the runner user to the docker group), gh, jq, node/npm
  ```

  Rather than discovering these one red CI run at a time, grep the repo for
  what its own scripts declare before migrating — many document it:
  `grep -rn -A4 "External tools:" tooling/ hooks/` and
  `find . -name '*.sh' -exec grep -rhoE "command -v +[a-z0-9_-]+" {} +`
  (`**/*.sh` does **not** recurse in bash unless `shopt -s globstar` is set,
  so the glob form silently checks only the current directory).

- **Self-hosted capacity is fixed and shared, unlike GitHub-hosted's
  effectively unlimited parallel pool — but be precise about _how_ it is
  shared, because the two mechanisms need different diagnoses.**

  **Within one repo**, a registration runs one job at a time, so that repo's
  jobs genuinely queue behind each other. A workflow that used to fan out
  across independent hosted VMs now serializes.

  **Across repos, there is no queue.** Each repo has its own runner install
  and its own systemd unit (`~/actions-runner-<repo>/`,
  `actions.runner.<owner>-<repo>.<name>.service`), so six repos are six
  independent `Runner.Listener` processes, each polling only for its own
  repo. They can and do run jobs simultaneously — four were observed `busy`
  at once on this host. What they share is finite CPU and RAM, so
  cross-repo interference shows up as **resource contention**, not as a
  queue.

  The practical consequence: when a job is slow or stuck, `busy` on the
  runner API only tells you about that repo. If it reads `false` and the job
  still isn't moving, the answer is host load or memory
  ([Sizing the host](#sizing-the-host)), not another repo's job "ahead in
  line". Contention also makes timing-sensitive gates noisier than on a
  dedicated hosted VM — see `nightly.yml`'s `aggregate-nfr1` job.

- **Every workflow needs a `concurrency` group once it's self-hosted, and a
  `push` trigger scoped to the default branch.** Both are near-free on hosted
  runners and expensive here.

  Without a `concurrency` group, superseded pushes to a branch don't cancel —
  they queue. Observed: three obsolete runs of the same workflow stacked on
  one branch, each holding the single runner in turn ahead of everything else.

  Separately, a `push: branches: ["**"]` trigger alongside `pull_request`
  means a branch with an open PR matches **both**, and because the two events
  produce different `github.ref` values they land in different concurrency
  groups and therefore do not dedupe — every push runs the entire matrix
  twice. On hosted runners the duplicate merely burned its own VM; here the
  two runs compete for the same cores. This drove a host to load 36 and failed
  a timing-sensitive test that was not actually broken.

  ```yaml
  on:
    push:
      branches: [main] # not ["**"]
    pull_request:

  concurrency:
    group: ${{ github.workflow }}-${{ github.ref }}
    # Cancel superseded PR runs; let a push to main always finish.
    cancel-in-progress: ${{ github.event_name == 'pull_request' }}
  ```

- **A job requiring a label no runner carries sits `queued`, silently.**
  GitHub does not error on an unsatisfiable `runs-on:` — it waits. A
  Dependabot-generated dependency-graph job requesting a `dependabot` label
  sat queued for over nine hours this way, indistinguishable in the UI from a
  job waiting on a busy runner. Audit with:

  ```sh
  gh api repos/<owner>/<repo>/actions/runners \
    --jq '.runners[] | "\(.name): \([.labels[].name] | join(","))"'
  ```

- **`docker/setup-buildx-action` builders accumulate on a persistent host.**
  Each is a `docker-container` instance with its own build-cache silo.
  Recent versions of the action do clean up the builder they create, so in
  principle this should not pile up — but verified on this fleet that it does
  anyway: `docker buildx ls` showed five builders, three of them orphaned
  `calproxy-verify-builder-*` instances from jobs long finished. Treat the
  cleanup as best-effort, because a cancelled or OOM-killed job never reaches
  its cleanup step — precisely the failure mode a contended self-hosted host
  produces most often. `docker builder prune` / `docker buildx prune` with no
  `--builder` flag acts only on the currently-selected builder, silently
  missing every other one; you have to
  enumerate every builder (`docker buildx ls`) and prune each one
  explicitly. See [Automated Disk Cleanup](#automated-disk-cleanup) below —
  this is exactly what took the Linux runner's disk from fine to 100% full
  over a few days of normal CI activity, with `docker system prune` alone
  barely denting it.

## Accepted Risks

These are real downgrades from GitHub-hosted runners. They are accepted
deliberately for a personal-use fleet rather than solved, and are recorded
here so the trade is explicit and revisitable instead of discovered during an
incident. Raised in review across
[calendar-proxy#763](https://github.com/brandondees/calendar-proxy/pull/763),
`git_archive_sync#546`, and `code-quality-atlas#338`.

- **Single point of failure, with no fallback and no monitoring.** Every
  migrated workflow now depends on one machine being awake, online, and
  registered. There is no automatic failover to a hosted runner and no
  alerting on runner availability. The sharp edge is that this does **not**
  fail fast: `timeout-minutes` only bounds a job once it has _started_, so a
  job with no available runner sits **`queued`** rather than
  erroring. Symptom to recognize: checks that never start, on every branch at
  once. First things to check are `systemctl status
'actions.runner.*'` on the host and the repo's **Settings → Actions →
  Runners** page. Manual recovery is to bring the runner back up, or edit the
  affected `runs-on:` back to `ubuntu-latest` and push — remembering that
  hosted runners are only a fallback if the account's billing is healthy.
- **Cross-repo blast radius on a shared, non-ephemeral host.** Several repos'
  CI now runs on the same persistent machine, and nothing resets it between
  jobs — no fresh VM, no snapshot restore. That is a different and broader
  exposure than the fork-PR case the `if:` gates address: a compromised
  dependency pulled by _any one_ repo's CI (a poisoned package resolved at
  install time, a tampered apt package) can leave state behind — a planted
  binary on `PATH`, a modified shell profile, a lingering process — that the
  _next_ job inherits, regardless of which repo it belongs to. The fork gates
  do not help here, because this vector arrives through dependencies rather
  than through contributor code. Mitigations not currently in place:
  per-job ephemeral runners (container/VM-per-job), or splitting repos across
  separate hosts by trust level.
- **Reduced parallelism.** One runner registration processes one job at a
  time, so a workflow that previously fanned out across independent hosted
  VMs (a 4-way test matrix plus lint plus a separate test job — 6 concurrent
  VMs) now serializes within this repo. It does **not** additionally queue
  behind other repos' jobs — those run on their own registrations
  concurrently — but it does compete with them for CPU and RAM, so expect
  materially longer wall-clock CI per push either way. Registering additional
  runner instances for this repo on the host is the straightforward fix if
  turnaround starts to matter, bounded by what the host can actually feed
  (see [Sizing the host](#sizing-the-host)).
- **Runner OS support lifecycle is now yours to track.** GitHub retires and
  refreshes its hosted images; a self-hosted host does not update itself. This
  bit us concretely: the first Linux runner was built on Ubuntu 25.10, a
  9-month interim release, and was found still serving CI for five repos
  roughly two months after that release went EOL (2026-07-01) — i.e. with no
  security patches. Prefer an **LTS** release when provisioning (the
  replacement runs 26.04 LTS, supported to 2031), and treat the host's EOL
  date as a real calendar item. An interim release also has a thinner archive,
  which is what made the `shellcheck` apt pin unsatisfiable and forced the
  switch to an upstream-release install.

## Automated Disk Cleanup

A persistent runner's Docker state (buildx build caches, dangling images,
orphaned volumes) only ever grows — nothing tears it down the way an
ephemeral GitHub-hosted VM would. Left unmanaged, this fills the disk
silently until a job fails with `ENOSPC` (confirmed in practice — see PR
[#763](https://github.com/brandondees/calendar-proxy/pull/763)'s review
thread). Two systemd timers on `orbstack-linux-mbp` handle this automatically
now; see [`scripts/runner-maintenance/`](https://github.com/brandondees/calendar-proxy/tree/main/scripts/runner-maintenance)
for
the actual unit files and install steps.

- **`docker-gc.timer`** — daily, runs `docker buildx prune
--max-used-space=10GB` against **every** buildx builder (not just
  `default` — see the gotcha above), plus `docker system prune --filter
until=72h` and `docker volume prune`. Bounded by size/age, not a full
  wipe, so recently built layers stay cached for the next job — this is
  the difference between this and a blind `docker system prune -a`, which
  would force every subsequent build to start cold.
- **`disk-guardrail.timer`** — every 15 minutes, checks `df` on `/`; at
  ≥80% usage it runs the same cleanup with a tighter 5GB cap and logs a
  warning if that still doesn't bring usage back under the threshold. This
  is the gap that actually mattered in practice: the daily timer alone
  would have caught this eventually, but not before a same-day CI run hit
  `ENOSPC` first.

Use `--max-used-space`, not the older `--keep-storage` flag (deprecated,
still accepted with a warning) — they sound similar but aren't quite the
same knob; `--reserved-space` is a different flag still (a floor that's
never pruned below, not a ceiling).

## Uninstalling a runner

From the runner's directory — `sudo` on Linux, none needed on macOS,
matching the install step above: `sudo ./svc.sh stop && sudo ./svc.sh
uninstall`, then
`./config.sh remove --token <a-removal-token-from-the-repo's-Runners-page>`.
Removing the directory without running `config.sh remove` first leaves a
stale, offline entry on the repo's Runners page.

Before decommissioning the **host** rather than one runner, see the checklist
at the end of
[Migrating a runner to another host](#migrating-a-runner-to-another-host) —
in particular, grep the whole fleet for the host's name. Automation living
_outside_ the host can reference it, and that is not visible from inside.

## Why self-hosted at all?

GitHub-hosted runners bill per minute, with macOS roughly an order of
magnitude more than Linux, which adds up on repos that run CI on every push.
(Deliberately not quoting rates here — they change, and a stale number in a
copied file is worse than a link: see
[Actions runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing).) Self-hosting also
keeps caches warm across runs — a persistent `~/.cargo`, a stable per-runner
cache root, a populated Docker layer cache — making incremental rebuilds far
faster than the cold cache a fresh hosted VM gets.

The trade is that infrastructure failures become yours: disk exhaustion,
memory exhaustion, a stopped VM, a wedged runner agent, an EOL host OS. Those
are the failures this guide exists to make diagnosable, and the ones catalogued
under [Accepted Risks](#accepted-risks) are the ones deliberately _not_ solved.

## Per-repo notes

<!-- Everything above is fleet-wide and identical across repos. Keep
     repo-specific detail below this line so re-copying the canonical guide
     doesn't clobber it. -->

**Workflow → runner mapping.** Which of this repo's workflows target which
labels — worth listing when the repo has more than one target class, since a
job whose labels no runner carries sits `queued` with no error:

```sh
grep -rn 'runs-on:' .github/workflows/ | sed 's/:  */: /'
```
