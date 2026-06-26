# References to mine — reviewing-ai-authored-code

## Contents

- From category #34
- From category #18

## From category #34

### Key references

- **Spracklen et al. — "We Have a Package for You! A Comprehensive Analysis of Package Hallucinations by Code-Generating LLMs" (arXiv 2406.10279, 2024)** — https://arxiv.org/abs/2406.10279 → mine: the empirical spine for the package-hallucination leg. ~**20%** of packages recommended by code LLMs do not exist; ~**43%** of hallucinated names **recur** across re-prompts (so they are *predictable* registration targets — "slopsquatting"); commercial-model rate ~5.2% vs open-model ~21.7%. The reviewable consequence: every newly added import/dependency must be confirmed to *exist and be the intended project*, not assumed real because it reads plausibly.
- **Liang et al. — "Beyond Functional Correctness: Investigating Coding Style / Hallucinations in LLM-generated Code" (arXiv 2404.00971, 2024)** — https://arxiv.org/abs/2404.00971 → mine: a taxonomy of LLM-code defects *beyond* "does it run" — invented or misused APIs and parameters, plausible-but-wrong logic that reads fluently, and inconsistent internal state (a name defined one way, used another). The vocabulary for the "confident and wrong" checks below.
- **Veracode — 2025 GenAI Code Security Report** (summarized by ActiveState, "Is AI-Generated Code Poisoning Your Software Supply Chain?") — https://www.activestate.com/blog/is-ai-generated-code-poisoning-your-software-supply-chain/ → mine: across a 100+-model analysis, ~**45%** of LLM-produced code carried a known security weakness (especially injection and weak-default classes). Justifies the security-signature check — and the hand-off: this lens *flags the AI signature*, #14 *renders the security verdict*.
- **Simon Willison — "Slopsquatting" / on hallucinated dependencies (2025)** — https://simonwillison.net/tags/slopsquatting/ → mine: the attacker's loop — harvest recurring hallucinated names, register them on the public index, wait for the next agent to `pip install` / `npm install` one. Reinforces that an unrecognized new dependency from a generated diff is a *security* event, not just a correctness nit.
- **GitClear — "AI Copilot Code Quality" research (annual; 2024 and 2025 editions)** — https://www.gitclear.com → mine: a measured rise in **copy-pasted / duplicated** blocks and **churned** (quickly-reverted) lines in AI-assisted repos — the "superficially clean but intrinsically complex" signature. Grounds the duplication-instead-of-reuse and over-helpful-addition checks.

## From category #18

### Key references

- **SLSA — Supply-chain Levels for Software Artifacts (OpenSSF)** — https://slsa.dev/ → mine: a build-integrity ladder (v1.0 Build L1–L3: provenance → signed/hosted → isolated/non-forgeable). Can you *prove* the artifact came from this source via this build?
- **OpenSSF Scorecard** — https://securityscorecards.dev/ `(verify URL)` → mine: 18+ automated checks of a dependency's security hygiene (branch protection, code review, maintained, pinned deps, fuzzing) — a vetting rubric for "should we depend on this?"
- **SBOM — SPDX & CycloneDX (OWASP)** — https://cyclonedx.org/ → mine: the component inventory (packages, versions, licenses, relationships); the basis for both vuln scanning and license review (cross #27).
- **OSV.dev / OSV-Scanner (Google), pip-audit, npm audit, govulncheck, OWASP Dependency-Check, Trivy, Grype, Snyk** → mine: known-CVE detection across declared *and transitive* deps.
- **Russ Cox — "Our Software Dependency Problem" (2019)** — https://research.swtch.com/deps `(verify URL)` → mine: a discipline for *evaluating* a dependency before adding it (cost, maintenance, transitive weight, security surface).
- **left-pad / event-stream / xz-utils (CVE-2024-3094)** → mine: the canonical cautionary tales — trivial dep removal breakage, account-takeover injection, a backdoor planted by a "maintainer."
