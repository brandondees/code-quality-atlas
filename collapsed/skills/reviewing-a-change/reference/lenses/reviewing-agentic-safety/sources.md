# References to mine — reviewing-agentic-safety

## Contents

- From category #32

## From category #32

### Key references

- **OWASP — Top 10 for Agentic Applications (2026)** (released 2025-12-09) — https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/ → mine: agentic risk now has its **own** Top 10, distinct from the LLM-app list — external validation of map-gaps G2. Entries *(verified 2026-06-12 against the official OWASP announcement)*: **ASI01** Agent Goal Hijack, **ASI02** Tool Misuse, **ASI03** Identity & Privilege Abuse, **ASI04** Agentic Supply Chain Vulnerabilities, **ASI05** Unexpected Code Execution, **ASI06** Memory & Context Poisoning, **ASI07** Insecure Inter-Agent Communication, **ASI08** Cascading Failures, **ASI09** Human-Agent Trust Exploitation, **ASI10** Rogue Agents. Mitigation spine worth lifting directly: approval gates for state-changing actions, recursion bounds and step budgets, runtime monitors that pause the agent on policy-boundary crossings.
- **OWASP — Agentic AI: Threats and Mitigations v1.0 (2025-02-17)** — https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/ → mine: the companion threat-model reference behind the agentic Top 10 (memory poisoning, tool misuse, privilege compromise, cascading failures across multi-agent workflows) — use for threat-by-threat depth when a finding needs grounding.
- **Model Context Protocol — security best practices (spec docs)** — https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices → mine: the named MCP anti-patterns reviews must catch: **token passthrough** (explicitly prohibited — a server must validate a token's *audience* and never forward tokens not issued for it), **confused deputy** (a proxy/server tricked into spending its higher authority for a lower-trust caller; require explicit consent for dynamically registered clients, OAuth 2.1 + PKCE, strict redirect-URI validation), and **tool poisoning** (malicious instructions embedded in tool descriptions/metadata — invisible to the user, read by the model).
- **Lethal trifecta + OWASP LLM06 (Excessive Agency) — see #25.** #25 carries the full references for Simon Willison's lethal-trifecta pattern and the OWASP LLM Top 10. #32 owns the *action-leg mitigations* of the trifecta (egress allow-list, capability scoping, human-in-the-loop on data-carrying actions); #25 owns the *framing* and the model-call legs.
