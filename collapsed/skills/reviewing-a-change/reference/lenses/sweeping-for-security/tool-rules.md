# Tool rules to triage — sweeping-for-security

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents

- From category #14

## From category #14

### Tooling rules worth lifting

- **Semgrep** `tainted-sql-string` / registry `python.lang.security.audit.formatted-sql-query` — taint-flow from request input into a SQL string (SQLi). `(verify)` exact rule IDs.
- **Bandit** (Python) — `B608` `hardcoded_sql_expressions` (string-built SQL → SQLi); `B602` `subprocess_popen_with_shell_equals_true` (command injection); `B301` `pickle` on untrusted data (unsafe deserialization); `B307` `eval` on untrusted data (code injection); `B105`–`B107` hardcoded password string/funcarg/default; `B501` `request_with_no_cert_validation` (`verify=False`, TLS disabled); `B303`/`B324` `hashlib` weak hash (MD5/SHA1). *(plugin names verified against bandit.readthedocs.io)*
- **ESLint `eslint-plugin-security`** `detect-non-literal-fs-filename` (path traversal), `detect-child-process` (command injection), `detect-eval-with-expression`, `detect-non-literal-regexp` (ReDoS surface), `detect-object-injection`.
- **ESLint (React)** `react/no-danger` / `react/no-danger-with-children` — flags `dangerouslySetInnerHTML` (XSS sink).
- **SonarQube / SonarSource** hotspot & vuln rules, e.g. `javascript:S5122` (permissive CORS), `javascript:S2076`/`S2078` (OS command / LDAP injection), `java:S2068` (hardcoded credentials), `java:S5547` (weak/insecure cipher). `(verify)` exact squids.
- **CodeQL** query packs: `js/sql-injection`, `js/path-injection`, `js/reflected-xss`, `js/request-forgery` (SSRF), `py/command-line-injection`, `java/unsafe-deserialization`. `(verify)` exact query IDs.
- **Gitleaks / TruffleHog / `detect-secrets`** — entropy + regex detection of committed API keys, tokens, private keys, connection strings.
- **gosec** (Go) — `G201`/`G202` SQL string format/concat (CWE-89), `G204` subprocess from variable (CWE-78), `G401` weak crypto + `G501` import-blocklist `crypto/md5` (MD5/DES), `G101` hardcoded credentials, `G402`/`G403` insecure TLS / weak RSA (<2048), `G107` HTTP request with variable URL (SSRF surface, CWE-88). *(IDs/CWE mappings verified against securego/gosec)*
- **npm audit / `pip-audit` / OWASP Dependency-Check / Trivy / Grype** — known-CVE detection in declared & transitive deps (maps A06). Trivy also flags IaC misconfig and secrets.
- **brakeman** (Rails) — `SQL`, `CrossSiteScripting`, `MassAssignment`, `Redirect` (open redirect), `RemoteCodeExecution` warning categories.
