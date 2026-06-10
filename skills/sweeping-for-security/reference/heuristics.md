# Reviewable heuristics — sweeping-for-security

## Contents
- From category #14

## From category #14

### Reviewable heuristics (skill-checklist seeds)
- Does any query/command/HTML/path get built by string concatenation or interpolation of request-derived data? If so, demand parameterized queries / contextual output encoding / allow-listed path resolution.
- Every state-changing or data-returning endpoint: is there an explicit authorization check tied to the *resource owner*, not just authentication? (IDOR = authenticated but not authorized.) Object references taken from the request (IDs, filenames) must be authorized, never trusted.
- Are secrets (keys, tokens, passwords, connection strings) absent from source, config-in-repo, and log output? Real secrets belong in a secrets manager / env injected at runtime.
- Is crypto delegated to a vetted library with modern algorithms (AES-GCM/ChaCha20-Poly1305, argon2/bcrypt/scrypt for passwords, ECDSA/Ed25519)? Flag homegrown crypto, ECB mode, MD5/SHA1 for security, static IVs/nonces, and `Math.random()`/non-CSPRNG for tokens.
- Is untrusted input ever deserialized with a format that can instantiate arbitrary types (Java/Python `pickle`/PHP unserialize/unsafe YAML)? Prefer data-only formats (JSON) with schema validation.
- For any server-side fetch of a URL/host derived from user input: is the target allow-listed and are internal/metadata addresses (169.254.169.254, link-local, RFC1918, localhost) blocked? (SSRF / A10.)
- Are state-changing requests protected against CSRF (same-site cookies + token, or non-cookie auth)? Are cookies `HttpOnly`, `Secure`, `SameSite`?
- Is PII/sensitive data minimized, encrypted at rest/in transit, and kept out of logs, URLs, and error messages? (Cross-links #27 and #16.)
- Safe defaults: deny-by-default access, TLS verification on, debug/stack traces off in prod, CORS not `*` with credentials, no default/sample credentials shipped.
- Least privilege: does the code/service request the narrowest scopes, file perms, DB grants, and cloud IAM roles it needs? Flag wildcard IAM policies and over-broad DB users.
- New/updated dependency: is it from a reputable source, recently maintained, free of known CVEs, and pinned via lockfile? (Cross-links #18.)
- Is security-relevant activity (auth success/failure, access-control denials, high-value mutations) logged in a way that's actually monitorable (A09) — without logging the sensitive payload itself?

---
