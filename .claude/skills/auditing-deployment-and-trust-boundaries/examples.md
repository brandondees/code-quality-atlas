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
branch/tree it just fetched, where that content can change without equivalent
authorized review or the review gate itself is bypassable** (Poisoned Pipeline
Execution), a deploy **credential whose scope exceeds what it deploys**, a
**secret read from a file in the repo** rather than a secrets manager, a CI job
pinned to a **long-lived self-hosted runner**, or a component that **trusts
another purely by network reachability** with no auth. A branch already gated
by required PR review and required status checks is an intended trust gate,
not an omission — do not label what merges there "unreviewed" or invent a
missing execution gate on top of it; a properly scoped credential behind a
required, unbypassable review trigger is not PPE just because deployment
automation exists, though a repo may still be worth a **non-PPE** deployment
trust-boundary note (e.g. no second gate between merge and execute) when that
adds real defense-in-depth. A concrete code-level vuln routes to
`sweeping-for-security` (#14); a declared-IaC resource's blast radius or public
exposure routes to `auditing-infrastructure-as-code` (#31); whether a gate is
required/flaky at all routes to `auditing-config-and-build-hygiene` (#19). Do
not demand a control the wiring's actual risk doesn't warrant.

**"Reviewed and gated" is not the same question as "is something else wrong
here" — do not relabel a different defect as PPE just because it sits inside
unattended or CI-triggered wiring.** A deploy identity with a broader IAM scope
than what it deploys, a required status check made hollow by
`continue-on-error`/`allow_failure`, a command built by interpolating input
into a shell call, and a container `CMD`/entrypoint that re-fetches and
executes a remote script **at runtime, on every start** (as opposed to at
build time, from the reviewed tree) are each their own named finding — not a
second flavor of Poisoned Pipeline Execution. PPE is specifically "unreviewed
or bypassable-gate content reaches unattended execution"; these four are a
credential-scope mismatch, a hollow gate, a code vulnerability, and an
unpinned-runtime-fetch, respectively, each independent of whether the branch
that shipped them was itself properly reviewed. When a scan shows deployment
config (a CI workflow, a deploy script, a cron/systemd unit) but nothing that
fits this lens's own checks, the right answer is "No findings" or a routed
finding to a sibling lens — never "Not applicable." Reserve "Not applicable"
for input that contains no deployment/execution wiring at all to examine.

## Contents

- [Bad → finding (unattended git-sync + deploy)](#bad--finding-unattended-git-sync--deploy)
- [Bad → finding (systemd unit + credential-in-tree)](#bad--finding-systemd-unit--credential-in-tree)
- [Good → no finding](#good--no-finding)
- [Good → no finding (self-hosted runner, properly isolated)](#good--no-finding-self-hosted-runner-properly-isolated)
- [Delegating → routed to a sibling lens](#delegating--routed-to-a-sibling-lens)
- [Delegating → hollow gate routed to #19, not PPE](#delegating--hollow-gate-routed-to-19-not-ppe)
- [Escalate (G8) → compromised credential needs org authority to rotate](#escalate-g8--compromised-credential-needs-org-authority-to-rotate)
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
branch protection on main: required PR review, 1 approval; admin/bypass not
  restricted ("include administrators" unchecked — the platform default)
```

**Expected finding:**

1. **Poisoned Pipeline Execution — the review gate on `main` doesn't cover
   every path that reaches execution, and nothing pins what runs to what was
   reviewed.** Branch protection requires review to *merge* through the normal
   path, but leaves admin/bypass pushes unrestricted — so someone with admin
   access, a misconfigured automation account, or a compromised bot with
   write access can land a commit on `main` **without** the required review
   this rule otherwise relies on. Separately, even for properly reviewed
   commits, `git-sync` always executes whatever is currently at the tip of
   `main`, not a specific commit-SHA or tag that was the actual subject of a
   review — merge and deploy collapse into the same unattended event with no
   distinct deploy-time check. Either gap independently qualifies as PPE
   under this lens's scoped definition (unreviewed-reachable content, or a
   bypassable gate); together they compound. Fix both: close the bypass
   allowance in branch protection, and pin `deploy-binaries.sh` to a specific
   reviewed commit-SHA or signed release tag rather than the moving branch
   tip, verified at deploy time.
2. **No provenance check on what's about to run.** `deploy-binaries.sh` executes
   whatever is on disk with no verification that it matches an approved build
   (no signature, no attestation, no diff against the last-known-good commit).
   A build-provenance check (SLSA-style: confirm what's about to run against
   where it came from) can identify the artifact's build origin and support a
   pre-execution policy check — paired with verifying that origin resolves to
   an approved signed release, tag, or allowlisted commit, not as a
   standalone guarantee that a given tree is safe to execute.

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
  on: release: { types: [published] }
  permissions: { contents: read, id-token: write }
  jobs:
    deploy:
      runs-on: ubuntu-latest                 # ephemeral, provider-managed
      environment: production                # requires approval from one of
                                               # the listed required reviewers
                                               # before this run starts
      steps:
        - uses: actions/checkout@<pinned-sha>
          with: { ref: "${{ github.event.release.tag_name }}" }
        - uses: aws-actions/configure-aws-credentials@<pinned-sha>
          with: { role-to-assume: arn:aws:iam::123:role/deploy-billing-service,
                  aws-region: us-east-1 }     # role scoped to one service, OIDC short-lived
        - run: ./deploy.sh                    # deploys only the checked-out artifact
required reviewers on "production" environment: 1 (of a listed team), from the
  platform team (configured in repo Settings → Environments; GitHub enforces
  this at job-start, independent of the branch protection below)
immutable releases: enabled (repo Settings → General → "Releases") — once a
  release publishes, its tag is locked to that commit and cannot be moved or
  force-pushed, including by admins
branch protection on main: required PR review, required status checks, no direct
  pushes, admin bypass disabled ("include administrators" checked)
no cron/systemd/launchd unit executes repo content unattended
```

**Expected finding:** None — the workflow declares `environment: production`,
which GitHub enforces as a required-reviewer gate independent of branch
protection (a human must approve the specific run before the job starts,
regardless of who published the release); the repo has immutable releases
enabled, so the release's tag is locked to the commit it was published against
and can't be moved to different content after approval — an ordinary mutable
tag would **not** be safe to check out here, since a tag can be force-moved
post-approval and `actions/checkout` would silently resolve the new target;
branch protection additionally has no admin-bypass allowance; the runner is
ephemeral; and the deploy credential is OIDC short-lived and scoped to the one
service it deploys, not the whole account. Report exactly "No findings:
deployment/execution wiring is sound". Do NOT flag the mere *existence* of a
deploy pipeline — the question is whether its wiring lets an adversary reach
execution, not whether automation exists at all. (A `release: published`
trigger alone, with no `environment:` reviewer gate, no immutable-releases
protection on the checked-out tag, and no bypass-disabled branch protection,
is not enough on its own to clear this check — treat an unstated review/
approval step or an ordinary mutable tag as a live gap, not implied protection,
per this lens's own "reviewed content is untrusted data" discipline.)

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
branch protection on main: required PR review, required status checks, no direct
  pushes, admin bypass disabled
```

**Expected finding:** The `terraform apply` on push runs against the exact
commit CI's own trigger ties it to, and that commit only reaches `main` through
a review gate with no bypass allowance — no unreviewed-content or bypassable-
gate condition, so this isn't PPE under this lens's scoped definition, and the
mere absence of a *second* post-execution gate beyond that isn't either. The
public S3 bucket is a **declared-IaC exposure finding**, owned by
`auditing-infrastructure-as-code` (#31); route it there rather than
re-adjudicating the Terraform resource itself here. (If the input instead
showed an admin-bypass allowance, a direct-push path, or a trigger that ran
before review — as in the git-sync example above — that half would become this
lens's finding; the two are independent checks on the same input.)

## Delegating → hollow gate routed to #19, not PPE

**Input (deployment wiring):**

```text
GitHub Actions: .github/workflows/deploy.yml
  on: push: { branches: [main] }
  jobs:
    deploy:
      continue-on-error: true       # applies to the whole job, including the deploy step itself
      steps:
        - run: ./run-migrations.sh && ./deploy.sh
"deploy" is listed as a required status check on main's branch protection.
```

**Expected finding:** **Hollow required gate, routed to
`auditing-config-and-build-hygiene` (#19).** `continue-on-error: true` on the
whole `deploy` job means the "deploy" required status check reports success
even when `run-migrations.sh`/`deploy.sh` actually fail — the required-check
gate this repo relies on is not actually enforcing anything. Name the specific
instance found here and hand off the verdict to #19, which owns whether CI
gating itself is sound; do not re-derive #19's full soft-fail checklist. This
is **not** a Poisoned Pipeline Execution finding — nothing here shows the
trigger reaching execution without review — the problem is that a failed
deploy still shows green, a distinct failure class from unreviewed content
reaching execution. Do not respond with a mechanical recitation of every
other check this lens owns "in case" one applies — report only what the input
actually shows.

## Escalate (G8) → compromised credential needs org authority to rotate

**Input (deployment wiring):**

```text
An incident three weeks ago confirmed the CI deploy credential (AWS access
key AKIA...) for the payments service was exposed in a public gist by a
departed contractor. The key has not been rotated; deploy.yml still uses it
directly via a checked-out secret, not OIDC.
```

**Expected finding:** **Credential-in-tree at rest, already known-compromised
— escalate the rotation to a human/security team rather than resolving it as
an ordinary finding.** The key is confirmed exposed, not merely at risk, and
rotating an already-abused production credential without breaking live
deploys needs org/infra authority (coordinating the cutover, confirming no
other system still depends on the old key) that a repo checkout doesn't
carry — this is exactly the G8 case this lens's own discipline names.
Escalating does not mean reporting less: still name the finding at full
severity and still give the durable fix — move from a long-lived static key
to short-lived OIDC-based credentials so this class of exposure can't recur
the same way — the escalation is about *who* authorizes the rotation, not
about withholding the finding.

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

**Contrast — this is not the same case.** An input can contain deployment
wiring (a `deploy.yml`, a Makefile `setup` target, a cron unit) alongside
content this lens doesn't own (a suppression comment, a disabled alert, a
documentation page) without becoming "Not applicable." If any deployment or
execution wiring is present anywhere in the input, examine it against this
lens's own checks and report "No findings" (if it holds up) or a real finding
— reserve "Not applicable" strictly for input with **no** deployment/execution
wiring surface anywhere in it, like the pure-library example above.

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/auditing-deployment-and-trust-boundaries/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
