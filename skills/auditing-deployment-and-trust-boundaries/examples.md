# Examples — auditing-deployment-and-trust-boundaries

This skill is repo-shaped: its input is the deployment/execution wiring already
committed in the repo — CI/CD workflow files, cron/systemd/launchd unit files,
deploy scripts, and any config that states which services trust which. Report
**each distinct threat as its own numbered finding** — never fold several into
one line, and never stop at the first one or two. **Cite only what the input
actually shows** — do not invent a CVE, a credential value, or a component the
input doesn't name. When the wiring holds up, the entire response is exactly
"No findings: deployment/execution wiring is sound".

**Decision rule (apply before flagging):** a finding needs a concrete threat
visible in the input — an unattended job that **executes content from the same
branch/tree it just fetched** with no intervening gate (Poisoned Pipeline
Execution), a deploy **credential whose scope exceeds what it deploys**, a
**secret read from a file in the repo** rather than a secrets manager, a CI job
pinned to a **long-lived self-hosted runner**, or a component that **trusts
another purely by network reachability** with no auth. A concrete code-level
vuln routes to `sweeping-for-security` (#14); a declared-IaC resource's blast
radius or public exposure routes to `auditing-infrastructure-as-code` (#31);
whether a gate is required/flaky at all routes to `auditing-config-and-build-
hygiene` (#19). Do not demand a control the wiring's actual risk doesn't
warrant — a properly scoped credential behind a required, reviewed trigger is
not a finding just because deployment automation exists.

## Contents

- [Bad → finding (unattended git-sync + deploy)](#bad--finding-unattended-git-sync--deploy)
- [Bad → finding (systemd unit + credential-in-tree)](#bad--finding-systemd-unit--credential-in-tree)
- [Good → no finding](#good--no-finding)
- [Good → no finding (self-hosted runner, properly isolated)](#good--no-finding-self-hosted-runner-properly-isolated)
- [Delegating → routed to a sibling lens](#delegating--routed-to-a-sibling-lens)
- [Not applicable](#not-applicable)

## Bad → finding (unattended git-sync + deploy)

**Input (deployment wiring):**

```text
launchd: com.acme.git-sync.plist
  ProgramArguments: ["/usr/bin/git", "-C", "/srv/app", "pull", "origin", "main"]
  StartInterval: 300          # every 5 minutes, unattended
  # on pull completion, launchd also loads com.acme.deploy.plist:
launchd: com.acme.deploy.plist
  ProgramArguments: ["/srv/app/deploy-binaries.sh"]
  # deploy-binaries.sh (from the just-pulled tree):
  #   ./install-launchd.sh && ./windmill.sh sync && systemctl restart app-services
  RunAtLoad: true
branch protection on main: required PR review, 1 approval
```

**Expected finding:**

1. **Poisoned Pipeline Execution — unattended execute-on-pull with no execution gate.**
   `git-sync` fast-forwards `main` every 5 minutes and `deploy.plist` then runs
   `deploy-binaries.sh` from that same freshly-pulled tree, which itself runs
   `install-launchd.sh` and restarts services — a chain of scripts pulled straight
   from `main` executing with no check beyond whatever already gated the merge.
   Branch protection requires review to *merge*, but nothing re-verifies what's
   about to *execute*; anyone who can land a commit on `main` (a merged PR, a
   compromised dependency's build step, a bot with write access) gets host code
   execution with persistence. Insert a gate between pull and execute — pin
   deploy to a specific reviewed/tagged commit rather than the moving branch
   tip, or require a separate signed release artifact the deploy step verifies
   before running anything from it.
2. **No provenance check on what's about to run.** `deploy-binaries.sh` executes
   whatever is on disk with no verification that it matches an approved build
   (no signature, no attestation, no diff against the last-known-good commit).
   A build-provenance check (SLSA-style: verify what you're running against
   where it came from) would catch a poisoned tree before execution rather than
   after.

## Bad → finding (systemd unit + credential-in-tree)

**Input (deployment wiring):**

```text
systemd unit: /etc/systemd/system/billing-sync.service
  [Service]
  User=root
  EnvironmentFile=/srv/billing/prod.env    # committed to the repo, tracked in git
  ExecStart=/srv/billing/sync.py
  # no PrivateTmp=, no NoNewPrivileges=, no ProtectSystem=
prod.env (in repo): STRIPE_SECRET_KEY=sk_live_51H..., DB_ADMIN_PASSWORD=Correct-Horse-1
```

**Expected finding:**

1. **Credential-in-tree at rest.** `prod.env` is committed to the repository and
   carries a live Stripe secret key and an admin DB password — reachable by
   anyone who can read the repo, not just anyone who can reach the server.
   Move both to a secrets manager referenced at runtime; rotate both values,
   since they must be treated as already exposed.
2. **Unsandboxed root service.** `billing-sync.service` runs as `User=root`
   with none of `PrivateTmp=`/`NoNewPrivileges=`/`ProtectSystem=` set — a bug or
   compromise in `sync.py` runs with full host privilege and no containment.
   Run as a dedicated non-root user and add the standard systemd sandboxing
   directives; `systemd-analyze security billing-sync.service` will score the
   exposure directly.

## Good → no finding

**Input (deployment wiring):**

```text
GitHub Actions: .github/workflows/deploy.yml
  on: release: { types: [published] }        # triggered only by a signed, reviewed release
  permissions: { contents: read, id-token: write }
  jobs:
    deploy:
      runs-on: ubuntu-latest                 # ephemeral, provider-managed
      steps:
        - uses: aws-actions/configure-aws-credentials@<pinned-sha>
          with: { role-to-assume: arn:aws:iam::123:role/deploy-billing-service,
                  aws-region: us-east-1 }     # role scoped to one service, OIDC short-lived
        - run: ./deploy.sh                    # deploys only the tagged release artifact
branch protection on main: required PR review, required status checks, no direct pushes
no cron/systemd/launchd unit executes repo content unattended
```

**Expected finding:** None — the deploy trigger is a reviewed, signed release
rather than an unattended pull; the runner is ephemeral; the deploy credential
is OIDC short-lived and scoped to the one service it deploys, not the whole
account; and nothing else in the repo auto-executes fetched content. Report
exactly "No findings: deployment/execution wiring is sound". Do NOT flag the
mere *existence* of a deploy pipeline — the question is whether its wiring lets
an adversary reach execution, not whether automation exists at all.

## Good → no finding (self-hosted runner, properly isolated)

**Input (deployment wiring):**

```text
GitHub Actions: self-hosted runner, ephemeral (spun up per job, torn down after)
  runner is provisioned in an isolated VM image per job, no persistent state
  between jobs; secrets scoped per-environment with required-reviewer gates
  on the "production" environment
```

**Expected finding:** None — the self-hosted runner is per-job ephemeral (torn
down after each run), which removes the host-persistence risk a long-lived
self-hosted runner carries; production secrets sit behind an environment gate
requiring a reviewer. Report exactly "No findings: deployment/execution wiring
is sound". Do NOT flag "self-hosted" alone as the defect — the persistence
risk this lens checks for is specifically a runner that *survives* across jobs.

## Delegating → routed to a sibling lens

**Input (deployment wiring):**

```text
main.tf: resource "aws_s3_bucket_public_access_block" "assets" { block_public_acls = false }
deploy.yml: on: push: { branches: [main] }, then: terraform apply -auto-approve
```

**Expected finding:** The `terraform apply` on push is triggered from a reviewed
branch with no unattended-execute-on-pull pattern outside CI's own sandboxing —
not this lens's finding. The public S3 bucket is a **declared-IaC exposure
finding**, owned by `auditing-infrastructure-as-code` (#31); route it there
rather than re-adjudicating the Terraform resource itself here. (If the CI
trigger itself lacked review gating on `main`, that half would still be this
lens's finding — the two are independent checks on the same input.)

## Not applicable

**Input:**

```python
# math_utils.py — a pure library with no packaging, CI deploy step, or service
def clamp(value, low, high):
    return max(low, min(value, high))
```

**Expected finding:** "Not applicable: no CI/CD deploy step, cron/systemd/launchd
unit, deploy script, or service-trust config present to audit." Do NOT report
"No findings" here — that sentence means a check ran and found nothing, not
that nothing in this input was checkable.
