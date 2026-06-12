# References to mine — reviewing-llm-integration

## Contents
- From category #25
- From category #27

## From category #25

### Key references
- **OWASP — Top 10 for LLM Applications (2025)** — https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/ → mine: the security spine for LLM features. **Verified 2025 list:** LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Supply Chain, LLM04 Data and Model Poisoning, LLM05 Improper Output Handling, LLM06 Excessive Agency, LLM07 System Prompt Leakage, LLM08 Vector and Embedding Weaknesses, LLM09 Misinformation, LLM10 Unbounded Consumption. (LLM06 Excessive Agency was notably expanded into excessive *functionality*, *permissions*, and *autonomy*.)
- **NIST — AI Risk Management Framework (AI RMF 1.0, SP 100-1) + Generative AI Profile (NIST-AI-600-1)** — https://www.nist.gov/itl/ai-risk-management-framework → mine: the Govern / Map / Measure / Manage functions and the GenAI-specific risk profile — a governance/eval vocabulary for "did we test the nondeterministic behavior and bound the risk."
- **Anthropic / OpenAI — prompt-engineering & safety best-practices docs** — e.g. https://docs.anthropic.com/ → mine: delimit and label untrusted input, separate system vs user instructions, structured/tool-use outputs over free-text parsing, and refusal/guardrail design. (Provider-specific model IDs and pricing should be checked against current docs, not memory.)
- **Simon Willison — "The lethal trifecta for AI agents" (2025-06-16)** — https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ → mine: prompt injection is unsolved by prompting alone; the *lethal trifecta* = (access to private data) + (exposure to untrusted content) + (ability to communicate/exfiltrate externally). If a design has all three, treat it as exploitable by default. (Aug 2025 disclosures in Cursor, GitHub Copilot, Claude Code, Devin, Google Jules followed this exact pattern.)
- **Microsoft — Responsible AI / Azure AI Content Safety + "LLM-as-judge" eval guidance** → mine: layered guardrails (input + output classifiers) around the model, not just inside the prompt; using a separate model/rubric to grade outputs at scale.
- **Eugene Yan — "Patterns for Building LLM-based Systems & Products" / "evals" writing** — https://eugeneyan.com/ → mine: concrete engineering patterns — evals first, guardrails, caching, defensive UX for wrong answers, and keeping a golden-set regression suite for prompts.
- **Chip Huyen — "Building LLM applications for production" / *AI Engineering*** — https://huyenchip.com/ → mine: production concerns — prompt versioning, eval pipelines, cost/latency tradeoffs, and treating prompts + models as versioned, testable artifacts.
- **OWASP — Top 10 for Agentic Applications (2026)** (released 2025-12-09) — https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications/ → mine: agentic risk now has its **own** Top 10, distinct from the LLM-app list — external validation of map-gaps G2. Entries (per early secondary coverage; `(verify exact wording against the published PDF)`): ASI01 Agent Goal Hijack, ASI02 Tool Misuse and Exploitation, ASI03 Identity and Privilege Abuse, ASI04 Agentic Supply Chain Vulnerabilities, ASI05 Unexpected Code Execution (RCE), ASI06 Memory and Context Poisoning, ASI07 Insecure Inter-Agent Communication, ASI08 Cascading Failures, ASI09 Human-Agent Trust Exploitation, ASI10 Rogue Agents. Mitigation spine worth lifting directly: approval gates for state-changing actions, recursion bounds and step budgets, runtime monitors that pause the agent on policy-boundary crossings.
- **OWASP — Agentic AI: Threats and Mitigations v1.0 (2025-02-17)** — https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/ → mine: the companion threat-model reference behind the agentic Top 10 (memory poisoning, tool misuse, privilege compromise, cascading failures across multi-agent workflows) — use for threat-by-threat depth when a finding needs grounding.
- **Model Context Protocol — security best practices (spec docs)** — https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices → mine: the named MCP anti-patterns reviews must catch: **token passthrough** (explicitly prohibited — a server must validate a token's *audience* and never forward tokens not issued for it), **confused deputy** (a proxy/server tricked into spending its higher authority for a lower-trust caller; require explicit consent for dynamically registered clients, OAuth 2.1 + PKCE, strict redirect-URI validation), and **tool poisoning** (malicious instructions embedded in tool descriptions/metadata — invisible to the user, read by the model).

## From category #27

### Key references
- **SPDX — license identifiers + SBOM** — https://spdx.org/licenses/ (standard short IDs + permanent URLs).
  → mine: standard license IDs (`MIT`, `Apache-2.0`, `GPL-3.0-only`, `LGPL-3.0`, `AGPL-3.0-only`, `BSD-3-Clause`, `MPL-2.0`) and `SPDX-License-Identifier:` headers; SBOM (SPDX / CycloneDX) as the provenance artifact a review can check against.
- **FSF "copyleft" guidance + Blue Oak / choosealicense.com**
  → mine: copyleft strength ladder — permissive (MIT/BSD/Apache-2.0) → weak/file-level (MPL-2.0, LGPL) → strong (GPL) → network/strong (AGPL). **AGPL triggers on *network interaction*, not just distribution** — the classic SaaS surprise: modifying AGPL software and offering it as a service obliges you to provide its source to users who interact with it. Apache-2.0 carries an explicit patent grant; GPLv2-only ↔ Apache-2.0 is a known incompatibility.
- **OpenChain / OWASP Dependency-Track + CycloneDX** `(verify)`.
  → mine: continuous SBOM-based license + vulnerability + policy monitoring; treat license policy as a gate, not a one-time audit. (Vuln side cross-links #18.)
- **GDPR (EU 2016/679) & CCPA/CPRA**
  → mine: lawful basis + consent, **data minimization**, purpose limitation, storage-limitation/**retention**, data-subject rights (access/erasure/portability), **data residency**/cross-border transfer, breach-notification timelines. Code that collects/stores/transfers PII must map to these (cross-links #14 PII handling, #16 telemetry).
- **REUSE Specification (FSFE)** — https://reuse.software/spec/ (`reuse lint` makes per-file SPDX+copyright machine-checkable).
  → mine: every file should declare copyright + SPDX license (header or `.license` sidecar); `reuse lint` makes provenance machine-checkable. A new source file with no license header is a provenance gap.
- **DCO (Developer Certificate of Origin) / `Signed-off-by` + AI-codegen provenance debates** `(verify)`.
  → mine: contributor attestation of right-to-contribute; the open question of attribution/licensing for AI-generated code and training-data provenance — at minimum, label AI-assisted contributions and run license/secret/IP checks on them as untrusted input.
- **Accessibility-as-law: ADA / Section 508 / EN 301 549 / EAA (EU 2019/882, in force 2025-06-28)**
  → mine: WCAG 2.x AA conformance is the de facto legal yardstick (cross-links #23) — a11y findings can carry legal, not just UX, weight.
