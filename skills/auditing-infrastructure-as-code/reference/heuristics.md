# Reviewable heuristics — auditing-infrastructure-as-code

## Contents
- From category #31

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
