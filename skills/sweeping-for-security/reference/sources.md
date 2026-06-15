# References to mine — sweeping-for-security

## Contents

- From category #14

## From category #14

### Key references

- **OWASP — OWASP Top 10:2021** — https://owasp.org/Top10/ → mine: the canonical risk buckets a review must screen for, in priority order: A01 Broken Access Control, A02 Cryptographic Failures, A03 Injection (XSS folded in here), A04 Insecure Design, A05 Security Misconfiguration, A06 Vulnerable & Outdated Components, A07 Identification & Authentication Failures, A08 Software & Data Integrity Failures (deserialization, supply chain), A09 Security Logging & Monitoring Failures, A10 Server-Side Request Forgery (SSRF). Use as the top-level checklist spine.
- **OWASP — Application Security Verification Standard (ASVS) 5.0** (released **May 2025**) — https://owasp.org/www-project-application-security-verification-standard/ → mine: ~350 testable, per-control requirements across **17 chapters** with a three-tier model. v5.0 **renumbered** vs. v4 and added modern coverage (V3 Web Frontend Security, V9 Self-Contained Tokens, V10 OAuth/OIDC, V17 WebRTC). Each requirement is already phrased as a checkable assertion — ideal seed text for skill checklist items. *(Note: the old V1 Architecture / V2 Auth / V4 Access Control numbering is v4; use 5.0 chapter numbers going forward.)*
- **MITRE — CWE Top 25 Most Dangerous Software Weaknesses (2024)** — https://cwe.mitre.org/top25/archive/2024/2024_cwe_top25.html → mine: weakness-level (not risk-level) granularity for grep/AST rules. **2024 top three: #1 CWE-79 (XSS) — up from #2; #2 CWE-787 (Out-of-bounds Write) — down from #1; #3 CWE-89 (SQL Injection).** Other high entries: CWE-352 (CSRF), CWE-22 (Path Traversal), CWE-78 (OS Command Injection), CWE-862 (Missing Authorization), CWE-918 (SSRF), CWE-502 (Deserialization), CWE-798 (Hardcoded Credentials), CWE-269 (Improper Privilege Management). (Scored frequency × severity over 31,770 CVEs from Jun 2023–Jun 2024.)
- **OWASP — Cheat Sheet Series** — https://cheatsheetseries.owasp.org/ → mine: concrete "do this / not that" remediation patterns (parameterized queries, output encoding contexts, password storage with bcrypt/argon2/scrypt, CSP construction) — the fix half of each finding.
- **OWASP — Proactive Controls** → mine: framing that reviewers should reward positive controls (parameterize, encode, validate, use vetted crypto) rather than only flag negatives.
- **NIST — SP 800-63B Digital Identity Guidelines** → mine: authoritative source for authn rules (password length over composition, no forced periodic rotation, breached-password checks, MFA guidance) — counters folklore review comments.
- **Maker-checker / four-eyes & segregation of duties (SOX)** — https://en.wikipedia.org/wiki/Maker-checker ; https://www.securends.com/blog/segregation-of-duties-for-sox-compliance/ → mine: the canonical anti-fraud / anti-collusion control that no single actor both initiates and approves a sensitive operation. A business-logic authorization *pattern* (distinct from authn, IDOR, and least-privilege), SOX §404-mandated; review high-consequence workflows for a dual-control / two-actor gate. Detect-and-route: *which* operations require dual-control is a business-policy call, not a code default.
