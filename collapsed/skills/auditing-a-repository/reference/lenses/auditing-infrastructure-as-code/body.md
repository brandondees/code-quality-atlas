# auditing-infrastructure-as-code

Does this infra change expose or destroy something? Blast radius, public access, wildcard IAM, secrets in state, drift.

## When to use

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Checklist

The full review checklist, grouped by the research category each check draws from:

## From category #31

### Reviewable heuristics (skill-checklist seeds)

- **Blast radius of the change:** what does `terraform plan` (or the CloudFormation change set) say this actually does — **create, in-place update, or replace/destroy**? A `-/+` replace of a stateful resource (database, volume, bucket) is potential **data loss / downtime**; a destroy of anything stateful needs explicit confirmation and a backup (cross #20, #28).
- **Public exposure:** does the change open something to the world — `0.0.0.0/0` ingress, a public S3 bucket / blob container, a database with a public IP, a K8s `Service` of type `LoadBalancer` with no restriction? Default to private; flag any new public surface for explicit justification (security verdict owned by #14).
- **Over-broad IAM / least privilege:** wildcard `Action: "*"` or `Resource: "*"`, `AdministratorAccess`, or a role far broader than the workload needs? Scope to the specific actions/resources required (cross #14).
- **Secrets in plaintext or state:** are credentials hardcoded in `.tf` / vars / manifests, or written to **Terraform state** (which is plaintext)? Source from a secrets manager / sealed-secrets; ensure state is encrypted and access-controlled.
- **Unpinned modules & providers:** are Terraform `required_providers` / module sources and provider versions **pinned** (not floating to `latest`), and is the **state backend remote and locked** (not local `terraform.tfstate`)? Floating versions make the next apply non-reproducible (cross #18, #19).
- **Drift between declared and live:** does a `terraform plan` on supposedly-applied config come back **non-empty** (someone changed infra by hand)? ClickOps drift means the IaC is no longer the source of truth — reconcile or import it.
- **Container/workload defaults (K8s):** do Pods/Deployments set **resource requests and limits** (no limits → noisy-neighbour / OOM, cross #28), run **non-root** with a **read-only root filesystem**, avoid **`privileged` / hostNetwork / hostPath / docker-socket** mounts, and pin image digests (no `:latest`)?
- **Encryption & data protection:** is encryption-at-rest enabled on new storage (bucket / volume / DB) and TLS required in transit, rather than relying on a permissive default?
- **Tool currency & gate health:** is the IaC scanner in CI **maintained and actually running** (Checkov/Trivy current — not archived Terrascan or unmaintained tfsec), required to pass (not `continue-on-error`), and are its suppressions rule-scoped with a reason (cross #30)?
- **Policy-as-code for repeated objections:** is an org guardrail that keeps coming up in review (mandatory tags, no public exposure, approved regions) **codified as OPA/Conftest/Sentinel policy** evaluated on the plan, rather than re-litigated by hand each PR?

---

## Examples

This skill is repo-shaped: its input is a scan of IaC manifests (Terraform /
OpenTofu, Kubernetes / Helm, CloudFormation) plus, where present, a `terraform
plan` summary and the IaC scanner config. Report **each distinct defect as its own
numbered finding** — never fold several into one line, and never stop at the first
one or two. **Cite only signals present in the scan** — do not invent a CVE, a
plan action, or a resource the scan does not show. When the manifests are sound,
the entire response is exactly "No findings: infrastructure-as-code is sound".

**Decision rule (apply before flagging):** an IaC finding needs a concrete defect
visible in the scan — a `plan` that **replaces/destroys** a stateful resource,
**public exposure** (`0.0.0.0/0`, public bucket/blob, public DB), **wildcard or
over-broad IAM** (`Action: "*"`, `Resource: "*"`, `AdministratorAccess`), a
**secret** hardcoded in a manifest or written to Terraform state, **unpinned**
modules/providers or **local/unencrypted** state, **declared-vs-live drift** (a
non-empty plan on supposedly-applied config), unsafe **container defaults** (no
resource limits, privileged, root, `:latest`), missing **encryption at rest**, or
a **stale/soft-failed scanner** (archived Terrascan, unmaintained tfsec,
`continue-on-error`). The security *verdict* on exposure/IAM is owned by
`sweeping-for-security` (#14) — flag it here, attribute the verdict there. Do not
demand controls a repo's stated risk level doesn't warrant. If providers are
pinned, state is remote/locked/encrypted, access is least-privilege and private,
and the scanner is maintained and required, report exactly
"No findings: infrastructure-as-code is sound".

## Bad → finding (Terraform scan)

**Input (IaC scan):**

```text
terraform plan: aws_db_instance.orders  -/+ destroy and recreate (engine_version change)
main.tf:    resource aws_security_group ingress { cidr_blocks = ["0.0.0.0/0"], from_port = 5432 }
            resource aws_iam_policy { Action = "*", Resource = "*" }
            provider "aws" {}                       # no version constraint
            variable "db_password" { default = "Pa$$w0rd-prod" }
backend:    local (terraform.tfstate committed to the repo)
CI:         tfsec (last check added 2024); continue-on-error: true
```

**Expected finding:**

1. **Destructive plan on a stateful resource:** the plan shows `aws_db_instance.orders`
   `-/+` (destroy + recreate) — that is data loss and downtime. Find a non-replacing
   path for the engine_version change, or snapshot + plan a migration; never apply a
   replace of a database unreviewed.
2. **Public database exposure:** the security group opens port 5432 to `0.0.0.0/0`
   — the orders DB is reachable from the internet. Restrict ingress to the app
   subnet/SG (security verdict owned by `sweeping-for-security`).
3. **Wildcard IAM:** `Action = "*"` on `Resource = "*"` grants full admin — scope to
   the specific actions and resources the workload needs (least privilege, cross #14).
4. **Secret in a manifest and in state:** `db_password` is hardcoded as a default
   and will be written to Terraform state (plaintext). Source it from a secrets
   manager; rotate the exposed value.
5. **Unpinned provider + local committed state:** the `aws` provider has no version
   constraint (next apply is non-reproducible) and state is `local` and committed
   (no locking, secrets in the repo). Pin the provider and move state to a remote,
   locked, encrypted backend.
6. **Decaying scanner, not enforced:** `tfsec` is unmaintained (folded into Trivy;
   no new checks since 2024) and runs `continue-on-error: true`, so it gates
   nothing. Migrate to Trivy/Checkov and make it required (cross #30).

## Bad → finding (Kubernetes scan)

**Input (IaC scan):**

```text
deploy.yaml: containers: [{ image: api:latest, securityContext: { privileged: true } }]
             # no resources.requests / resources.limits
service.yaml: kind: Service, type: LoadBalancer, no loadBalancerSourceRanges
kube-linter: not run in CI
```

**Expected finding:**

1. **Privileged container running latest:** the API container is `privileged: true`
   (full host access — a container escape is a host compromise) and pinned to
   `:latest` (unreproducible, silent upgrades). Drop privileged, run as non-root
   with a read-only root FS, and pin an image digest.
2. **No resource requests/limits:** the container sets neither — it can consume a
   node's CPU/memory and OOM-kill or starve neighbors (noisy-neighbour, cross #28).
   Set requests and limits.
3. **Unrestricted public LoadBalancer:** the `Service` is `type: LoadBalancer` with
   no `loadBalancerSourceRanges` — it exposes the workload to the whole internet.
   Restrict the source ranges or front it with an ingress + WAF (verdict owned by
   `sweeping-for-security`).
4. **No manifest linting in CI:** `kube-linter` is not run, so these defaults regress
   silently. Add it as a required check.

## Good → no finding

**Input (IaC scan):**

```text
terraform plan: 2 to add, 1 to change, 0 to destroy (all stateless: a tag + an SG rule)
main.tf:    providers pinned (aws ~> 5.40); modules pinned by version; state in S3
            backend with DynamoDB lock + SSE; no secrets in vars (sourced from SSM)
            SG ingress restricted to the app SG; IAM scoped to specific actions/ARNs
            RDS storage_encrypted = true; S3 bucket private + SSE
k8s:        resources requests+limits set; runAsNonRoot; readOnlyRootFilesystem;
            images pinned by digest
CI:         checkov required to merge, passing; conftest policy (no public, mandatory tags)
plan-drift: terraform plan on the applied config is empty (no drift)
```

**Expected finding:** None — providers/modules pinned, state remote+locked+encrypted,
secrets externalized, access least-privilege and private, storage encrypted, K8s
defaults safe, scanner maintained and required, and no drift. Report exactly
"No findings: infrastructure-as-code is sound". Do NOT manufacture a finding from a
healthy plan (adds/changes to stateless resources are not destructive) or invent a
CVE the scan does not show.

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
