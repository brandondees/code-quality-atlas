# Tool rules to triage — reviewing-decision-lifecycle

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents
- From category #29

## From category #29

### Tooling rules worth lifting
- **`adr-tools` / Log4brains / MADR templates** — scaffold and index ADRs; make "is there a decision record for this non-obvious choice?" mechanically checkable. `(verify)`.
- **`endoflife.date` (API) / `deps.dev` / OSV `(verify)`** — machine-readable lifecycle & maturity signals for an adopted dependency/runtime (is it approaching EOL?).
- **Dependency-weight inspectors — `npm why` / `cargo tree` / `pipdeptree` / `dependency-review-action`** — surface the transitive weight a new dependency drags in (part of adoption cost; cross #18).
- **API-deprecation encodings — `Deprecation`/`Sunset` response headers (RFC 8594/8631), OpenAPI `deprecated: true`, GraphQL `@deprecated(reason:)`** — put planned retirement into the contract (cross #13).
- **License / portability scanners (FOSSA, Snyk)** — flag proprietary / copyleft surface that raises exit cost and lock-in (cross #27).
- **Renovate/Dependabot with EOL feeds** — flag an adopted technology entering end-of-life so the retire decision is triggered, not missed.
