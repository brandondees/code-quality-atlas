---
name: sweeping-for-security
description: 'Sweeps changes for security risks: injection (SQL/command/XSS) from
  unparameterized or unencoded untrusted input, missing authorization on object references
  (IDOR), hardcoded secrets, weak or homegrown crypto, unsafe deserialization, SSRF,
  CSRF, permissive CORS/TLS settings, and sensitive data in logs or URLs. Use when
  reviewing auth, user input, queries, secrets, crypto, cookies, file paths, or any
  code handling untrusted data.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 14
    source: docs/research/cluster-4-runtime.md#14
    hash: e106f7b704d223bd84ff7b4a0745c805b87bdce8aaa8329ce7a6e786d502700c
---

# sweeping-for-security

## When to use

Sweeps changes for security risks: injection (SQL/command/XSS) from unparameterized or unencoded untrusted input, missing authorization on object references (IDOR), hardcoded secrets, weak or homegrown crypto, unsafe deserialization, SSRF, CSRF, permissive CORS/TLS settings, and sensitive data in logs or URLs. Use when reviewing auth, user input, queries, secrets, crypto, cookies, file paths, or any code handling untrusted data.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Does any query/command/HTML/path get built by string concatenation or interpolation of request-derived data? If so, demand parameterized queries / contextual output encoding / allow-listed path resolution.
- Every state-changing or data-returning endpoint: is there an explicit authorization check tied to the *resource owner*, not just authentication? (IDOR = authenticated but not authorized.) Object references taken from the request (IDs, filenames) must be authorized, never trusted.
- Are secrets (keys, tokens, passwords, connection strings) absent from source, config-in-repo, and log output? Real secrets belong in a secrets manager / env injected at runtime.
- Is crypto delegated to a vetted library with modern algorithms (AES-GCM/ChaCha20-Poly1305, argon2/bcrypt/scrypt for passwords, ECDSA/Ed25519)? Flag homegrown crypto, ECB mode, MD5/SHA1 for security, static IVs/nonces, and `Math.random()`/non-CSPRNG for tokens.
- Is untrusted input ever deserialized with a format that can instantiate arbitrary types (Java/Python `pickle`/PHP unserialize/unsafe YAML)? Prefer data-only formats (JSON) with schema validation.
- For any server-side fetch of a URL/host derived from user input: is the target allow-listed and are internal/metadata addresses (169.254.169.254, link-local, RFC1918, localhost) blocked? (SSRF / A10.)
- Are state-changing requests protected against CSRF (same-site cookies + token, or non-cookie auth)? Are cookies `HttpOnly`, `Secure`, `SameSite`?
- Is PII/sensitive data minimized, encrypted at rest/in transit, and kept out of logs, URLs, and error messages? (Cross-links #27 and #16.)

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
