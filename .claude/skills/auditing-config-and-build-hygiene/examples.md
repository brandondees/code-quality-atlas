# Examples — auditing-config-and-build-hygiene

This skill is repo-shaped: its input is a scan of CI pipelines, build scripts, and
configuration. Report **each distinct defect as its own numbered finding** — never
fold several issues into one line, and never stop at the first one or two. When the
scan is healthy, the entire response is exactly this skill's no-finding sentence
given in the decision rule below — never a numbered list of findings for a healthy scan.

**Decision rule (apply before flagging):** a hygiene finding needs a concrete
defect — a secret in the repo/image, an unpinned action/toolchain, a base image on
`:latest`, a build that depends on machine-local state, a missing or soft-failed
merge gate (`continue-on-error`, `|| true`, `allow_failure`), env-specific code
branches, config read lazily without validation, a flag with no owner (dead and
unreferenced → delete; live-but-ownerless → assign an owner + removal plan), a
pipeline that rebuilds per environment instead of building once and promoting the
same artifact, or a long-lived branch carrying incomplete work with no feature
flag. Enumerate **every** such defect present in the scan, each as its own
finding — pinning is per-artifact (action SHA, base-image digest, dependency lock
are three separate checks, not one). Do not demand tooling the project's size
doesn't warrant. If the gates run and are required, builds are pinned and
reproducible, and config is injected/validated, report exactly
"No findings: config and build hygiene are sound".

A scan describing a CI job's **own observed behavior** — its runtime, retry/flake
rate, or pass/fail history — is in scope even with no raw config snippet shown:
you are still auditing that job, just from its metrics instead of its YAML.
Likewise, **branching/merge practice** (a long-lived branch, incomplete work with
no flag) is this lens's own checklist item, not out of scope merely because the
input reads as team metadata rather than a config file. Reserve "Not applicable"
for scans with no CI/build/config/IaC/flag *subject matter* at all — test-suite
results, source-complexity metrics, docs — not for this lens's own subject matter
arriving as prose or numbers instead of a raw snippet.

The security *verdict* on a privileged container, exposed port, or over-broad IAM
grant surfaced in a build/deploy manifest is owned by `sweeping-for-security`
(#14); a known CVE's severity and whether it must block a merge is owned by
`auditing-dependencies-and-supply-chain` (#18). Flag the hygiene-relevant fact
here — the pipeline still applies without a plan, the manifest still grants the
excess — and attribute the deeper verdict there; do not manufacture your own
security or CVE judgment in its place, and do not let "that's someone else's
verdict" become a reason to drop the finding.

## Bad → finding (CI + image + config)

**Input (build/config scan):**

```text
ci.yml:        uses: actions/checkout@main; tests run but `continue-on-error: true`;
               docker build pulls base image python:latest
Dockerfile:    ENV STRIPE_KEY=sk-prod-...; pip install -r requirements.txt (no lock)
settings.py:   if ENV == "prod": payment_url = "https://pay.internal" else: "http://localhost"
               DEBUG defaults to True; config read at first use, KeyError at runtime
flags.yml:     enable_new_pricing: true  (owner: none, added 14 months ago)
```

**Expected finding:**

1. **Secret baked into the image:** the Stripe key in a Dockerfile `ENV` ships in
   every layer — inject at runtime from a secrets manager and rotate the exposed key.
2. **Unpinned action:** `actions/checkout@main` is a mutable tag — pin it to a full
   commit SHA.
3. **Unpinned base image:** `python:latest` is not reproducible — pin the base-image
   digest (never `:latest`).
4. **No dependency lock:** `pip install` with no lockfile makes the build
   unreproducible and supply-chain-exposed — commit and install from a lock.
5. **Soft-failed merge gate:** `continue-on-error: true` on the test job means a red
   run still merges — the gate enforces nothing; make it blocking, or track the
   exemption with an owner and an expiry.
6. **Env-specific code branch + unsafe default:** the `if ENV == "prod"` fork and
   `DEBUG=True` default break dev/prod parity and fail open — inject URLs via config,
   default to safe values, and validate all config at startup (fail fast, not
   first-use `KeyError`).
7. **Stale flag with no owner:** `enable_new_pricing` has been on 14 months with no
   owner — give flags an owner and a removal plan; this one should be removed.

## Bad → finding (build reproducibility + flags)

**Input (build/config scan):**

```text
build.gradle: java toolchain points at /usr/local/jdk-17 on the build box
install.sh:   wget -qO- https://deps.example/setup.sh | sh   (no version, no checksum)
flags.yml:    legacy_export: false  (owner none; referenced in 0 code paths; 18 months)
              dark_mode_v2: true    (owner none; both branches still maintained; 7 months)
```

**Expected finding:**

1. **Machine-local build dependency:** the Gradle toolchain hardcodes
   `/usr/local/jdk-17`, so the build only works on a box that already has that exact
   path — not hermetic/reproducible. Resolve the JDK through the build tool (a Gradle
   toolchain spec / `.tool-versions`) so any machine gets the same toolchain.
2. **Unpinned installer piped to a shell:** `wget … | sh` with no version pin or
   checksum runs whatever the URL serves at build time — unreproducible and a
   supply-chain risk. Pin a version and verify a checksum before executing.
3. **Dead flag:** `legacy_export` is referenced in zero code paths — delete it; a flag
   nothing reads is pure debt.
4. **Live but ownerless flag:** `dark_mode_v2` has no owner and both branches are
   still maintained — assign an owner and a removal plan so it doesn't rot like the
   dead one.

## Bad → finding (job-behavior metrics and branching practice, no raw config shown)

**Input (scan):**

```text
ci.yml:      job `e2e-nightly`, required to merge, 42 min runtime, no caching,
             retries: 3. Failure rate over its first 30 runs: 11 failures,
             9 of which passed on retry.
Branching:   feature/payments-rewrite open 7 months, 1,400 commits behind main,
             merged from main 11 times, no feature flag in the codebase.
             CONTRIBUTING.md documents trunk-based development as team practice.
```

**Expected finding:**

1. **Flaky required gate masked by retries:** nine of eleven failures passed on a
   later attempt — the retries are absorbing nondeterminism, not infrastructure
   noise, on a check that's required to merge. Find the source of the flake rather
   than raising the retry count further.
2. **Slow, uncached, serial required gate:** 42 minutes with no caching sets the
   floor on every merge; parallelize and cache it.
3. **Long-lived branch contradicts the team's own documented practice:** seven
   months and 1,400 commits behind, integrated via eleven merges from main instead
   of a feature flag, while `CONTRIBUTING.md` states trunk-based development —
   integrate the incomplete work behind a flag so it merges continuously instead
   of accumulating one large, increasingly risky final merge.

Neither input here is a raw config/YAML snippet — one is a job's own metrics, the
other is branching metadata plus a doc — but both describe this lens's own subject
matter (a required CI gate's health; integration practice), so both are in scope.
Do not answer "Not applicable" just because the input isn't shaped like a file.

## Bad → finding (build-once-promote violated)

**Input (scan):**

```text
ci.yml:
  build-staging: docker build -t app:staging --build-arg ENV=staging .
                 docker push app:staging && deploy staging
  build-prod:    needs: build-staging
                 docker build -t app:prod --build-arg ENV=prod .
                 docker push app:prod && deploy prod
```

**Expected finding:**

1. **Rebuilds per environment instead of promoting one artifact:** `build-prod`
   runs its own `docker build` with `--build-arg ENV=prod` rather than promoting
   the exact image `build-staging` already built, tested, and pushed. The artifact
   that reaches production is not the artifact staging validated — baking
   environment identity into the image via `--build-arg ENV=` is what forces the
   rebuild. Build once, tag that image, and promote the same digest through
   environments; supply environment differences as runtime config, not a build arg.

Do not speculate about missing base-image pins or lockfiles the scan doesn't show
— the concrete, scan-visible defect is the per-environment rebuild itself.

## Bad → finding, security verdict routed elsewhere

**Input (scan):**

```text
terraform/: providers pinned; `terraform plan` runs in CI and is reviewed;
            tflint and checkov both run and are required to merge.
            One resource: an IAM policy grants Action: "*" on Resource: "*"
            to the CI role.
```

**Expected finding:**

1. **Wildcard IAM grant on the CI role:** the policy's `Action: "*"` /
   `Resource: "*"` is diff-visible over-privilege on a role that runs unattended.
   The authorization *verdict* — how much privilege this role legitimately needs —
   belongs to `sweeping-for-security` (#14); flagged here, not adjudicated here.

Credit what's healthy — pinned providers, a reviewed plan, required linters —
rather than letting the one finding read as a wholesale failure; note that
`tflint`/`checkov` running and passing is not evidence the grant is fine, since a
linter's clean run only means nothing it was configured to check fired. Report the
finding and the routing together, not one or the other — do not self-adjudicate
the authorization question, and do not drop the finding because its full verdict
belongs to another lens.

The routing convention above is not specific to Terraform/IAM — it applies to
*every* build/deploy-manifest defect whose deeper verdict belongs to another
lens's checklist, whatever shape the manifest is (Kubernetes, a CI pipeline
scan, a dependency-audit gate). The next two examples show the same habit on
different subject matter.

## Bad → finding, security verdict routed elsewhere (Kubernetes)

**Input (scan):**

```text
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: api
          image: registry.example.com/api:latest
          securityContext:
            privileged: true
          volumeMounts:
            - name: docker-sock
              mountPath: /var/run/docker.sock
      volumes:
        - name: docker-sock
          hostPath:
            path: /var/run/docker.sock
```

**Expected finding:**

1. **Unpinned image:** `:latest` is not reproducible — pin the digest.
2. **Privileged container with a mounted Docker socket:** `privileged: true` plus
   the host's `docker.sock` hands this container control of the host's container
   runtime — a hygiene-visible container-default defect. How much privilege this
   workload actually needs, and whether the socket mount is ever justified, is
   `sweeping-for-security`'s (#14) verdict — flagged here, not adjudicated here.
3. **Missing resource limits and non-root defaults:** no CPU/memory
   requests/limits, no `runAsNonRoot`, no read-only root filesystem.

Three separate findings, not one merged paragraph — pinning, the
privileged/socket combination (routed), and the missing resource/user defaults
are three distinct container-hygiene checks, the same way action-SHA,
base-image-digest, and dependency-lock pinning are three separate checks
elsewhere in this lens.

## Bad → finding, routed to a different lens (dependency CVE, not IAM)

**Input (scan):**

```text
requirements.txt: pinned with hashes; pip-audit runs in CI and is required.
  pip-audit currently reports: cryptography 41.0.1 -> GHSA-xxxx (high), no fix
  version yet.
ci.yml: actions SHA-pinned; gates required; build reproducible.
```

**Expected finding:** None from this lens on the CVE itself — the build/config
hygiene here is sound: the audit gate exists, runs, and is required, and the
lockfile is hash-pinned. Report "No findings: config and build hygiene are
sound." The CVE's severity and whether an unfixed high-severity finding must
block a merge is `auditing-dependencies-and-supply-chain`'s (#18) verdict, not
this lens's — do not manufacture a build-hygiene finding out of a dependency
problem just because a scan happens to mention one. (Contrast the IAM and
Kubernetes examples above: there, the *hygiene* fact itself — an over-broad
grant, a privileged container — is this lens's own finding, with the deeper
verdict routed. Here, there is no hygiene-layer fact for this lens to find at
all; the entire scan's substance belongs to the other lens.)

## Bad → finding (adversarial — a real defect buried in an accurately-described mechanical diff)

**Input (scan). The PR description says: "Routine workflow refactor — 340 lines, all mechanical: split one job into six, no behaviour change."**

```text
ci.yml diff: 340 lines changed.
  334 lines: one `build` job split into six named jobs, steps moved verbatim,
             every action still SHA-pinned, same commands, same order.
  line 118:  - name: unit tests
  line 119:      if: github.actor != 'dependabot[bot]'
  line 287:  branch protection: required checks updated to the six new job names
```

**Expected finding:**

1. **Unit tests silently skipped for Dependabot PRs:** line 119 makes the
   `unit tests` job skip entirely when the actor is `dependabot[bot]` —
   dependency-bump PRs, exactly the class most likely to break a build, now
   merge without tests having run.

The PR description's "all mechanical, no behaviour change" framing is
accurate for 334 of the 340 changed lines — that's what makes the one real
change easy to miss, not a reason it isn't there. A large diff described (even
correctly) as mechanical still needs every changed line checked; do not let
the volume of harmless, verbatim-moved lines stand in for having read the one
that isn't. Confirm what's genuinely fine (steps moved verbatim, still
SHA-pinned) rather than flagging the refactor itself — but confirm it, don't
assume it.

## Good → no finding (a non-gating job is not a soft-failed gate)

**Input (scan):**

```text
ci.yml:
  benchmark:
    continue-on-error: true
    # informational only: posts a comment with timings, never gates merge
  lint / types / tests / pip-audit: all required to merge, none soft-failed.
branch protection: the four gates above are required; `benchmark` is not.
```

**Expected finding:** None — report "No findings: config and build hygiene are
sound". `continue-on-error: true` is a soft-failed-gate finding only when the
job it's on is one of the checks branch protection actually requires; here
`benchmark` is explicitly not in that list, so a failing benchmark was never
going to block a merge in the first place, and `continue-on-error` doesn't
weaken anything. Check the branch-protection list before flagging any
`continue-on-error`/`allow_failure`/`|| true`, not just its presence — the
same discipline as reading `ADD COLUMN` keywords literally elsewhere in this
lens's checklist. Do NOT recommend making the benchmark required; nothing in
the scan says it should be.

## Good → no finding

**Input (build/config scan):**

```text
ci.yml:        actions pinned by SHA; lint+type+test+audit required to merge; base
               image pinned by digest; artifact built once, promoted to stage/prod
config.py:     pydantic-settings: all vars validated at import, env-injected,
               documented; DEBUG default False; no secrets in repo (scanner clean)
flags.yml:     checkout_v2 (owner: @payments, removal: #931, expires 2026-08)
```

**Expected finding:** None — pinned and reproducible, gates required, fail-fast
validated config, owned flags with removal plans. Report
"No findings: config and build hygiene are sound". Do NOT demand extra
infrastructure (canaries, hermetic build systems) as a default — they're findings
only when the project's declared risk level calls for them.

## Not applicable → outside this lens's scope

**Input (scan):**

```text
tests/: 812 tests, 4 flagged flaky over the last 30 CI runs (retried and
        passed on rerun each time). Line coverage 71%, branch coverage 58%.
```

No CI, build, container, IaC, or configuration files were included in this
scan.

**Expected finding:** This scan is outside this lens's scope — it contains
test-suite stability and coverage metrics, not a CI pipeline, build script,
container, IaC manifest, or configuration file. Report "Not applicable: this
scan contains no CI, build, container, IaC, or configuration artifact for
this lens to audit" and name where the content does belong (test-quality and
flaky-test review) instead of assessing it here. Do NOT report "No findings:
config and build hygiene are sound" — that sentence means config and build
artifacts were checked and found sound, which implies there were some to
check. There weren't any.

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/auditing-config-and-build-hygiene/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
