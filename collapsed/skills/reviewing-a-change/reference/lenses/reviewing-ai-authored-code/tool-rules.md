# Tool rules to triage — reviewing-ai-authored-code

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents

- From category #34
- From category #18

## From category #34

### Tooling rules worth lifting

*(Most of this signature is judgment, not lint. The mechanical subset overlaps #18 tooling; named tools `(verify)` on your stack.)*

- **Dependency existence / install-time guards** — resolve every newly added dependency against the real index *before* trusting it: `pip install --dry-run` / `npm view <pkg>` / lockfile resolution in CI; a name that does not resolve, or that was first published days ago with no history, is a slopsquat candidate. Pair with `pip-audit` / `osv-scanner` / `npm audit` / Socket / Snyk for reputation and known-malware signals (shared with #18).
- **Typosquat / confusable-name detectors** — tooling that flags a new dependency one edit away from a popular package (Socket, `pip-audit` plugins, confusable-name linters); a hallucinated name is often a near-miss of a real one.
- **Duplication / churn detectors** — `jscpd`, `pmd-cpd`, SonarQube duplication, or a churn report (GitClear-style) to catch regenerated blocks that re-implement an existing helper instead of importing it.
- **API/symbol existence** — type-checkers and resolvers (`mypy` / `pyright`, `tsc`, the compiler) catch invented methods/params *if* the symbol is typed; treat a green type-check as necessary-not-sufficient (a real-but-misused API still type-checks).
- **Dead-link / citation checkers** — `lychee` / `markdown-link-check` over comments and docs in the diff: a fabricated issue link, RFC number, or doc URL is a tell that the surrounding prose was generated, not verified.

## From category #18

### Tooling rules worth lifting

- **Dependabot** (GitHub, ~14 ecosystems) / **Renovate** (Mend, 30+ managers, groups PRs) — automated update PRs.
- **OSV-Scanner, pip-audit, npm audit, cargo-audit, govulncheck, bundler-audit, Trivy, Grype, Snyk** — CVE scanning.
- **Socket.dev** — *behavioral* supply-chain analysis (new install scripts, network/filesystem access) to catch malicious packages, not just known CVEs.
- **Lockfiles** (`package-lock.json`, `poetry.lock`, `Gemfile.lock`, `go.sum`) + `npm ci`/equivalent — reproducible, hash-pinned installs.
- **depcheck / knip / deptry** — unused & missing dependency detection.
- **license scanners** (license-checker, FOSSA, Trivy) — feed #27.
