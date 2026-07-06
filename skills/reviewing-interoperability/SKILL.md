---
name: reviewing-interoperability
description: 'Reviews a change for interoperability — whether the code correctly speaks
  the external standards and protocols it claims to (ISO/IEC 25010:2023). Consolidates
  conformance checks scattered across other lenses: HTTP semantics (safe/idempotent
  methods, status codes, conditional requests, caching); OAuth 2.0 / OIDC flow correctness
  (exact redirect_uri, state/nonce, PKCE); Semantic Versioning and wire/format back-compat;
  RFC formats (date, URI, email, JSON, CSV); Unicode normalization and encoding (NFC,
  UTF-8, the YAML "Norway" class); cron dialects (POSIX vs. Quartz); OpenTelemetry
  semantic conventions; and co-existence (ports, global state, shared paths). Use
  when a change parses or emits a standard format, calls or implements an external
  protocol or auth flow, versions a published surface, or serializes data another
  system reads. Owns conformance to an external standard; defers the contract we author
  to #13, internal correctness to #4, idiom to #8, config to #26. Skip changes with
  no boundary-crossing standard.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 37
    source: docs/research/cluster-4-runtime.md#37
    hash: 36865c82ae45b52ef3c3541a198542f09f18196cf9215e0dc0f1063846182b04
---

# reviewing-interoperability

*Does the code correctly speak external standards? HTTP/OAuth semantics, SemVer, RFC date/URI/email formats, Unicode, cron dialects, OTel semconv.*

## When to use

Reviews a change for interoperability — whether the code correctly speaks the external standards and protocols it claims to (ISO/IEC 25010:2023). Consolidates conformance checks scattered across other lenses: HTTP semantics (safe/idempotent methods, status codes, conditional requests, caching); OAuth 2.0 / OIDC flow correctness (exact redirect_uri, state/nonce, PKCE); Semantic Versioning and wire/format back-compat; RFC formats (date, URI, email, JSON, CSV); Unicode normalization and encoding (NFC, UTF-8, the YAML "Norway" class); cron dialects (POSIX vs. Quartz); OpenTelemetry semantic conventions; and co-existence (ports, global state, shared paths). Use when a change parses or emits a standard format, calls or implements an external protocol or auth flow, versions a published surface, or serializes data another system reads. Owns conformance to an external standard; defers the contract we author to #13, internal correctness to #4, idiom to #8, config to #26. Skip changes with no boundary-crossing standard.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Standard protocol semantics (HTTP / OAuth / OIDC):** Does the code obey the **protocol it speaks**, not just a happy-path mock? For HTTP: are methods **safe/idempotent as the spec requires** (a retried `POST` not double-charging; `PUT`/`DELETE` idempotent), are status codes used per their meaning (201/204/409/422, not 200-for-everything), and are conditional requests / caching (`ETag`, `If-None-Match`, `Cache-Control`, `Vary`) correct? For OAuth/OIDC: is `redirect_uri` **exact-matched**, is **`state`** validated (CSRF), is **`nonce`** checked (replay), is **PKCE** present on public clients, and are tokens kept out of the front channel? A flow that authenticates in the demo but skips `state` is interoperable-looking and unsafe.
- **RFC / format conformance at the boundary (dates, URIs, email, Unicode, JSON/CSV):** Does every value crossing an external boundary **parse and emit per its spec** — dates as **RFC 3339** (offset/`Z`, not a locale string), URIs per **RFC 3986** (proper percent-encoding, no naive string-concat), email per RFC 5321/5322 (and IDN/punycode where relevant), JSON per RFC 8259 (no duplicate keys, number-precision aware), CSV per RFC 4180 (quoting/embedded-newline)? Is text **Unicode-normalized (NFC) before compare/store/index**, UTF-8 validated, and the **YAML "Norway"/sexagesimal** class quoted? A value that *looks* right but a strict third-party parser rejects is the core interoperability defect.
- **Versioning & wire/format back-compat (semver discipline):** Is a **breaking** change to a published API, event schema, serialized format, or CLI surface reflected in the version (a major bump per **SemVer 2.0.0**), and does the change preserve compatibility for existing consumers (additive/optional fields, tolerant readers, no field-meaning reuse)? A breaking change shipped under a patch bump is a compatibility defect even when the code is correct in isolation.
- **Encoding, charset & content negotiation:** Are `Content-Type` / `charset`, `Accept` negotiation, and MIME types correct and consistent with what the body actually is — no `application/json` over a text blob, no charset assumed rather than declared, BOM and surrogate-pair edges handled? Mismatched declared-vs-actual encoding breaks the consumer, not the producer's tests.
- **Time, calendar & locale tags on the wire:** Are timestamps serialized with an explicit offset/zone (**RFC 3339**), zone identifiers from the **IANA tz database** (not fixed offsets that break across DST), and locale/language tags **BCP 47**-valid? (Internal clock/timezone correctness stays #4; this check is about the *format crossing the boundary* a third party must read.)
- **Schedule-expression & cron dialect:** Does a cron / schedule expression match the **dialect of the engine that runs it** — 5-field POSIX vs. Quartz's 6/7-field (seconds + year), differing day-of-week indexing and `?`/`L`/`#` extensions, and the runner's timezone assumption? A valid-looking expression in the wrong dialect silently misfires.
- **Convention conformance for observability & interchange (OTel semconv, well-known files):** Where the change emits telemetry or standard artifacts, does it follow the **OpenTelemetry semantic conventions** (stable attribute names, not bespoke keys), standard MIME types, and well-known formats/locations (`robots.txt`, `.well-known/`, sitemap, `llms.txt`) so external tooling consumes them? Off-convention names are technically valid and practically un-interoperable.
- **Co-existence (share the environment without detriment):** Does the change assume a resource it does not own — a **hardcoded port**, a global singleton or shared mutable file/lock path, an env-var name likely to collide, a fixed temp path — that breaks when co-located with another instance or service? The ISO co-existence facet: correct alone, broken sharing a host.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
