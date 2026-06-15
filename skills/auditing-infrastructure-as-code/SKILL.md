---
name: auditing-infrastructure-as-code
description: 'Audits infrastructure-as-code manifests (Terraform/OpenTofu, Kubernetes
  and Helm, CloudFormation, Pulumi) as code that provisions production: the blast
  radius of a change (in-place update vs replace/destroy of stateful resources), public
  exposure (`0.0.0.0/0`, public buckets), over-broad or wildcard IAM, secrets in plaintext
  or Terraform state, unpinned modules and providers, drift between declared and live
  infra, missing container resource limits / non-root / read-only roots, and unmaintained
  or soft-failed scanners. Orchestrates and judges blast-radius; defers the security
  verdict to humans and to sweeping-for-security. A repo-wide / scheduled audit. Use
  when auditing Terraform, Kubernetes, Helm, or CloudFormation. Skip when the repo
  or change contains no infrastructure-as-code manifests.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 31
    source: docs/research/cluster-5-verification.md#31
    hash: b48a1f46fac8684976a952a36efe34b0c6806057d4f77463ed79d01dc04409f3
---

# auditing-infrastructure-as-code

*Does this infra change expose or destroy something? Blast radius, public access, wildcard IAM, secrets in state, drift.*

## When to use

Audits infrastructure-as-code manifests (Terraform/OpenTofu, Kubernetes and Helm, CloudFormation, Pulumi) as code that provisions production: the blast radius of a change (in-place update vs replace/destroy of stateful resources), public exposure (`0.0.0.0/0`, public buckets), over-broad or wildcard IAM, secrets in plaintext or Terraform state, unpinned modules and providers, drift between declared and live infra, missing container resource limits / non-root / read-only roots, and unmaintained or soft-failed scanners. Orchestrates and judges blast-radius; defers the security verdict to humans and to sweeping-for-security. A repo-wide / scheduled audit. Use when auditing Terraform, Kubernetes, Helm, or CloudFormation. Skip when the repo or change contains no infrastructure-as-code manifests.

**Shape: repo.** Run against the whole repository (scheduled or on demand), not a single diff.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Blast radius of the change:** what does `terraform plan` (or the CloudFormation change set) say this actually does — **create, in-place update, or replace/destroy**? A `-/+` replace of a stateful resource (database, volume, bucket) is potential **data loss / downtime**; a destroy of anything stateful needs explicit confirmation and a backup (cross #20, #28).
- **Public exposure:** does the change open something to the world — `0.0.0.0/0` ingress, a public S3 bucket / blob container, a database with a public IP, a K8s `Service` of type `LoadBalancer` with no restriction? Default to private; flag any new public surface for explicit justification (security verdict owned by #14).
- **Over-broad IAM / least privilege:** wildcard `Action: "*"` or `Resource: "*"`, `AdministratorAccess`, or a role far broader than the workload needs? Scope to the specific actions/resources required (cross #14).
- **Secrets in plaintext or state:** are credentials hardcoded in `.tf` / vars / manifests, or written to **Terraform state** (which is plaintext)? Source from a secrets manager / sealed-secrets; ensure state is encrypted and access-controlled.
- **Unpinned modules & providers:** are Terraform `required_providers` / module sources and provider versions **pinned** (not floating to `latest`), and is the **state backend remote and locked** (not local `terraform.tfstate`)? Floating versions make the next apply non-reproducible (cross #18, #19).
- **Drift between declared and live:** does a `terraform plan` on supposedly-applied config come back **non-empty** (someone changed infra by hand)? ClickOps drift means the IaC is no longer the source of truth — reconcile or import it.
- **Container/workload defaults (K8s):** do Pods/Deployments set **resource requests and limits** (no limits → noisy-neighbour / OOM, cross #28), run **non-root** with a **read-only root filesystem**, avoid **`privileged` / hostNetwork / hostPath / docker-socket** mounts, and pin image digests (no `:latest`)?
- **Encryption & data protection:** is encryption-at-rest enabled on new storage (bucket / volume / DB) and TLS required in transit, rather than relying on a permissive default?

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
