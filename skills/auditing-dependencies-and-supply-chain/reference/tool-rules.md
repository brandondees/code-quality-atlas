# Tool rules to triage — auditing-dependencies-and-supply-chain

## Contents
- From category #18
- From category #27

## From category #18

### Tooling rules worth lifting
- **Dependabot** (GitHub, ~14 ecosystems) / **Renovate** (Mend, 30+ managers, groups PRs) — automated update PRs.
- **OSV-Scanner, pip-audit, npm audit, cargo-audit, govulncheck, bundler-audit, Trivy, Grype, Snyk** — CVE scanning.
- **Socket.dev** — *behavioral* supply-chain analysis (new install scripts, network/filesystem access) to catch malicious packages, not just known CVEs.
- **Lockfiles** (`package-lock.json`, `poetry.lock`, `Gemfile.lock`, `go.sum`) + `npm ci`/equivalent — reproducible, hash-pinned installs.
- **depcheck / knip / deptry** — unused & missing dependency detection.
- **license scanners** (license-checker, FOSSA, Trivy) — feed #27.

## From category #27

### Tooling rules worth lifting
- **`license-checker` / `license-checker-rseidelsohn` (npm)** — enumerate dependency licenses; `--failOn` / `--onlyAllow` to block disallowed licenses (e.g. GPL/AGPL) in a permissive project. `(verify)`.
- **FOSSA / Snyk / WhiteSource(Mend) / Black Duck** — license-policy gates, copyleft/contamination alerts, attribution-report generation, IP-snippet matching. `(verify)`.
- **ScanCode Toolkit + ScanCode.io** — detect licenses/copyrights/origin in source (provenance), emit SPDX. `(verify)`.
- **`reuse lint` (REUSE)** — fail when files lack SPDX license + copyright headers. `(verify)`.
- **`pip-licenses` (Python) / `cargo-deny` (Rust) / `go-licenses` (Go) / `licensee` (GitHub's repo license detector)** — per-ecosystem license inventory + allow/deny lists; `cargo-deny` also bans yanked/duplicate/vuln crates. `(verify)`.
- **Syft + Grype / Trivy / OWASP Dependency-Track** — generate SBOM (SPDX/CycloneDX) and run license **and** vuln policy; Trivy `--license-full` license scanning. `(verify)`.
- **DCO bot / `Signed-off-by` enforcement (`commit-msg` hook, GitHub DCO app)** — gate contributions on origin attestation. `(verify)`.
- **Secret scanners as provenance/compliance gate** — Gitleaks, TruffleHog, `detect-secrets` — block committed credentials/PII (overlaps #14) that create regulatory exposure.
- **Privacy/PII linters** — e.g. `semgrep` registry rules for PII logging / hardcoded keys; `eslint-plugin-no-secrets`; data-flow rules flagging PII to logs/3rd-party (overlaps #16/#25). `(verify)` exact rule ids.
