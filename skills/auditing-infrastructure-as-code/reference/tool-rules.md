# Tool rules to triage — auditing-infrastructure-as-code

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents
- From category #31

## From category #31

### Tooling rules worth lifting
- **Checkov** — `checkov -d .`; built-in policy IDs `CKV_AWS_*` / `CKV_K8S_*` / `CKV2_*` (the `CKV2_` graph checks are the cross-resource ones); custom policies in Python/YAML; `--compact --quiet` for CI.
- **Trivy** — `trivy config <dir>` (IaC misconfig, includes the former tfsec rules `AVD-*`); `trivy k8s`; pairs with `trivy image` / `trivy fs` for CVEs so one tool spans IaC + supply chain.
- **kube-linter** — `kube-linter lint .` over K8s manifests/Helm; default checks: `latest-tag`, `no-read-only-root-fs`, `run-as-non-root`, `unset-cpu-requirements` / `unset-memory-requirements`, `privileged-container`, `dangling-service`.
- **hadolint** — `DL3008` (pin apt versions), `DL3007` (no `:latest` base), `DL3002` (no root `USER`), `DL3025` (JSON CMD) — image hygiene (Dockerfile *mechanics* owned by #19).
- **Conftest / OPA** — `conftest test plan.json` to enforce Rego policy on a `terraform show -json` plan; **Sentinel** for Terraform Cloud/Enterprise org policy.
- **`terraform plan` / `terraform validate` / `tflint`** — `validate` for syntax, `tflint` for provider-specific correctness + deprecations, `plan` (reviewed in the PR) as the blast-radius and drift signal; run `plan` in CI before any `apply`.
