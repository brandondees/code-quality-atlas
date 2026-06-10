---
name: sweeping-for-security
description: 'Sweeps changes for security risks: injection (SQL/command/XSS) from
  unparameterized or unencoded untrusted input, missing authorization on object references
  (IDOR), hardcoded secrets, weak or homegrown crypto, unsafe deserialization, SSRF,
  CSRF, permissive CORS/TLS settings, and sensitive data in logs or URLs. Use when
  reviewing auth, user input, queries, secrets, crypto, cookies, file paths, or any
  code handling untrusted data.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 14
    source: docs/research/cluster-4-runtime.md#14
    hash: 7cd5c480a2632213453d2c0841bc42d22924124b10adb0b57832807967951853
---

# sweeping-for-security

## When to use

Sweeps changes for security risks: injection (SQL/command/XSS) from unparameterized or unencoded untrusted input, missing authorization on object references (IDOR), hardcoded secrets, weak or homegrown crypto, unsafe deserialization, SSRF, CSRF, permissive CORS/TLS settings, and sensitive data in logs or URLs. Use when reviewing auth, user input, queries, secrets, crypto, cookies, file paths, or any code handling untrusted data.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
