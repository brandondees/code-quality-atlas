# Tool rules to triage — reviewing-observability-and-operability

## Contents
- From category #16

## From category #16

### Tooling rules worth lifting
- **ESLint** `no-console` — raw `console.log` instead of the project's structured logger (and noise/PII leakage risk). Often paired with a custom rule banning the logger's `debug` in prod paths.
- **`eslint-plugin-no-secrets`** / log-content linters — heuristic detection of secrets or high-entropy strings being logged.
- **golangci-lint** `bodyclose` & `contextcheck` — unclosed resources and missing `context.Context` propagation (the latter breaks trace propagation, deadlines, and cancellation → poor operability).
- **`err113` / `wrapcheck` / `errorlint`** (Go) — errors created/returned without wrapping context (`fmt.Errorf("...: %w", err)`) → unactionable, context-poor errors.
- **SonarQube** rules for logger usage, e.g. `java:S2629` (don't build log message strings when the level is disabled) and rules against logging-and-rethrowing (double logging) / swallowing exceptions silently. `(verify)` squids.
- **`pylint` / `flake8-logging-format` (`G` codes)** — use lazy `%`-style logging args, don't pre-format; don't use f-strings in logging calls (`logging-fstring-interpolation`).
- **`structlog` / Zap / Serilog / SLF4J + Logback** conventions — not linters but the de-facto "structured logging" baseline; a review can require the project's structured logger over `print`/`console`/`puts`.
- **Health-check conventions** — Kubernetes `livenessProbe` vs `readinessProbe` vs `startupProbe`; Spring Boot Actuator `/actuator/health` (liveness & readiness groups). Lift: distinct liveness (am I alive) vs readiness (can I serve traffic) endpoints.
- **OpenTelemetry / Prometheus client linters & `promtool check rules`** — validate metric/recording/alerting rule definitions; enforce metric naming conventions (unit suffixes like `_seconds`, `_bytes`, `_total`).
