---
name: sweeping-for-security
description: 'Sweeps changes for security risks: injection (SQL/command/XSS) from
  unparameterized or unencoded untrusted input, missing authorization on object references
  (IDOR), missing segregation of duties / maker-checker on high-consequence workflows,
  hardcoded secrets, weak or homegrown crypto, unsafe deserialization, SSRF, CSRF,
  permissive CORS/TLS settings, and sensitive data in logs or URLs. Use when reviewing
  auth, authorization workflows, user input, queries, secrets, crypto, cookies, file
  paths, or any code handling untrusted data.'
provenance:
  taxonomy_version: v0.8
  built_from:
  - category: 14
    source: docs/research/cluster-4-runtime.md#14
    hash: 32bbeac23db2c3de68eafbf812b9f9b097f72becc3e59e35e10e20e8e9387b0b
---

# sweeping-for-security

*Can an attacker abuse this? Injection, authorization, secrets, crypto, untrusted data.*

## When to use

Sweeps changes for security risks: injection (SQL/command/XSS) from unparameterized or unencoded untrusted input, missing authorization on object references (IDOR), missing segregation of duties / maker-checker on high-consequence workflows, hardcoded secrets, weak or homegrown crypto, unsafe deserialization, SSRF, CSRF, permissive CORS/TLS settings, and sensitive data in logs or URLs. Use when reviewing auth, authorization workflows, user input, queries, secrets, crypto, cookies, file paths, or any code handling untrusted data.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Does any query/command/HTML/path get built by string concatenation or interpolation of request-derived data? If so, demand parameterized queries / contextual output encoding / allow-listed path resolution.
- Every state-changing or data-returning endpoint: is there an explicit authorization check tied to the *resource owner*, not just authentication? (IDOR = authenticated but not authorized.) Object references taken from the request (IDs, filenames) must be authorized, never trusted.
- Can the *same actor* both initiate and approve a high-consequence action (a payment/refund, a role or permission grant, a deploy, a bulk delete)? Sensitive workflows need *segregation of duties / maker-checker* — two distinct actors, so no single actor completes the workflow alone. A role/permission gate authorizes *who* may act and is **not** itself dual-control: if the action records an initiator (e.g. `requested_by`) and an approver but never compares their identities, the maker-checker control is missing even when a role check is present. This is orthogonal to least-privilege (*how much* one actor may do) and IDOR (*whose* resource): flag the missing dual-control and surface it to security/compliance — *which* operations require it is a business-policy call, not a code default. (SOX §404; maps A01 Broken Access Control / A04 Insecure Design.)
- Are secrets (keys, tokens, passwords, connection strings) absent from source, config-in-repo, and log output? Real secrets belong in a secrets manager / env injected at runtime.
- **Credential & certificate expiry / rotation (correct at merge, detonates when the clock runs out):** does anything time-limited this change introduces or depends on — TLS/mTLS certs, OAuth tokens and refresh flows, API keys, signing/JWT keys, service-account creds — have a defined **renewal or rotation path**, and an alert before it lapses? A credential that works today and silently expires in N days is the single most preventable major-outage class; flag a hardcoded-and-unrotated secret or a cert/token with no owner, no expiry monitoring, and no rotation runbook (cross #26, #28).
- Is crypto delegated to a vetted library with modern algorithms (AES-GCM/ChaCha20-Poly1305, argon2/bcrypt/scrypt for passwords, ECDSA/Ed25519)? Flag homegrown crypto, ECB mode, MD5/SHA1 for security, static IVs/nonces, and `Math.random()`/non-CSPRNG for tokens.
- Is untrusted input ever deserialized with a format that can instantiate arbitrary types (Java/Python `pickle`/PHP unserialize/unsafe YAML)? Prefer data-only formats (JSON) with schema validation.
- For any server-side fetch of a URL/host derived from user input: is the target allow-listed and are internal/metadata addresses (169.254.169.254, link-local, RFC1918, localhost) blocked? (SSRF / A10.)

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
