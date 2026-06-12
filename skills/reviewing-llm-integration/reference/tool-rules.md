# Tool rules to triage — reviewing-llm-integration

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents
- From category #25
- From category #27

## From category #25

### Tooling rules worth lifting
*(This space is young; many "rules" are validators/frameworks/scanners rather than classic lint IDs. IDs `(verify)`.)*
- **Pydantic / `instructor` / Zod / OpenAI structured outputs / JSON-Schema response_format** — enforce a schema on model output and reject/repair non-conforming responses. The reviewable rule: *no model output is consumed without schema validation.*
- **Guardrails AI** (`guardrails-ai`) — declarative output validators/"validators" (regex, JSON schema, PII, toxicity, competitor-mention, on-topic) with re-ask on failure. Lift the catalog of validator types as checklist items.
- **NeMo Guardrails** (NVIDIA) — programmable input/output "rails" (topical, safety, jailbreak-detection rails) wrapping the LLM call.
- **Rebuff / LLM Guard (Protect AI) / Lakera Guard / `promptmap`** — prompt-injection & jailbreak detection, plus PII/secret scrubbing on inputs and outputs. LLM Guard is a modular input/output scanner layer (sanitization, prompt-injection resistance, secret filtering, data-leak prevention); input scanners include `PromptInjection`, `Anonymize`, `BanSubstrings` and output scanners include `Sensitive`, `NoRefusal`, `Relevance` `(verify exact scanner names)`.
- **garak** (NVIDIA) — LLM vulnerability scanner: probes for prompt injection, jailbreak, data leakage, toxicity — an automated red-team in CI.
- **Eval harnesses** — `promptfoo` (declarative test cases + assertions + red-team, CI-friendly), OpenAI **Evals**, **DeepEval** (`deepeval`, pytest-style metrics: faithfulness, answer-relevancy, hallucination, G-Eval), **Ragas** (RAG metrics: faithfulness, context precision/recall), **TruLens**. Lift: prompts ship with a regression eval suite and assertion thresholds.
- **LangSmith / Langfuse / Phoenix (Arize) / Helicone** — tracing, prompt/version tracking, token-cost accounting, and dataset-backed evals for LLM calls (observability for #25, overlapping #16).
- **Semgrep / CodeQL emerging LLM rules** — e.g. flagging untrusted/user data concatenated directly into a prompt template, or model output passed to `eval`/shell/SQL without validation (LLM05 Improper Output Handling). `(verify)` — coverage is partial and rule IDs unstable.
- **`detect-secrets` / DLP scanners on the request path** — ensure PII/secrets aren't shipped to a third-party model API (overlaps #14/#27).

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
