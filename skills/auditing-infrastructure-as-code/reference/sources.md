# References to mine — auditing-infrastructure-as-code

## Contents
- From category #31

## From category #31

### Key references
- **Checkov (Palo Alto Networks / Prisma Cloud, formerly Bridgecrew)** — https://github.com/bridgecrewio/checkov . The most widely-adopted open-source IaC scanner; 1,000+ built-in policies across Terraform/CloudFormation/K8s/Helm/ARM, **graph-based cross-resource checks** (e.g. a security group wired to a public subnet), and custom policies in Python or YAML. Standalone CLI is free.
  → mine: the default first scanner for Terraform/CloudFormation/K8s; its graph checks catch relationships a single-resource linter misses. Soft-failed or `--skip-check`'d en masse, it is theater (cross #30 suppression hygiene).
- **Trivy (Aqua Security) — IaC/misconfiguration scanning; tfsec is folded in** — https://github.com/aquasecurity/trivy . Aqua merged **tfsec into Trivy** (announced 2023, completed 2024); tfsec still runs but gets **no new checks**, and its `AVD-AWS-xxxx` IDs map unchanged into Trivy. For new work, use Trivy `config`/`misconfig`, not tfsec.
  → mine: if a repo still calls `tfsec`, that is a **stale-tool finding** — migrate to Trivy so post-2024 Terraform features are covered. One scanner (Trivy) covers IaC misconfig **and** image/dependency CVEs (cross #18).
- **kube-linter (StackRox / Red Hat) + hadolint** — https://github.com/stackrox/kube-linter . kube-linter checks Kubernetes YAML and Helm charts against best practices (no `latest` tag, resource requests/limits set, non-root, read-only root FS, no privileged); hadolint (DL3xxx) covers Dockerfiles (the Dockerfile mechanics themselves are #19's, but image-security defaults are shared).
  → mine: a K8s workload with **no resource limits** (noisy-neighbour / OOM-kill risk, cross #28), running **privileged / as root**, or pulling **`:latest`** is the recurring set — these are the kube-linter defaults worth asserting by hand.
- **Policy-as-code: OPA / Conftest (Rego) and HashiCorp Sentinel** — https://www.openpolicyagent.org/ , https://www.conftest.dev/ .
  → mine: org-specific guardrails (no public S3, mandatory tags, approved regions/instance types) belong in **versioned policy** evaluated in CI on the `plan`, not in a reviewer's memory — recommend codifying a repeated manual objection as a policy.
- **Drift detection: `terraform plan` (canonical), driftctl (maintenance mode), Snyk IaC** — https://developer.hashicorp.com/terraform/cli/commands/plan .
  → mine: a non-empty `terraform plan` against a supposedly-applied config **is** drift — someone changed live infra by hand (ClickOps), and the next apply will revert or fight it. `driftctl` is now maintenance-mode (Snyk moved drift detection into its platform); the always-available signal is `plan` in CI.
- **Cautionary — verify the tool still lives.** **Terrascan (Tenable) was archived 2025-11-20, read-only** — no new checks, no new provider/CVE coverage. A pipeline still gating on Terrascan has a **silently-decaying** gate.
  → mine: a concrete instance of this suite's standing rule — a canonical-but-dead scanner is a gap to close (migrate to Checkov/Trivy), not a gate to trust because it still exits zero (cross #19, #30).
