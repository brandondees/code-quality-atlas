# References to mine — reviewing-observability-and-operability

## Contents

- From category #16

## From category #16

### Key references

- **Google — Site Reliability Engineering (SRE Book) & SRE Workbook** — https://sre.google/books/ → mine: SLI/SLO/error-budget framing; the "four golden signals" (latency, traffic, errors, saturation) as the default metric set; alert on symptoms (SLO burn) not causes.
- **Charity Majors, Liz Fong-Jones, George Miranda — Observability Engineering (Honeycomb/O'Reilly)** — https://www.honeycomb.io/ → mine: structured, high-cardinality, wide events over unstructured log lines; the ability to ask new questions of production without shipping new code ("unknown-unknowns").
- **OpenTelemetry — specification & semantic conventions** — https://opentelemetry.io/docs/ → mine: vendor-neutral traces/metrics/logs; standardized span/attribute naming and trace-context propagation so observability is portable and correlated.
- **Twelve-Factor App — Logs (factor XI)** — https://12factor.net/logs → mine: treat logs as an event stream written to stdout; the app should not manage log routing/rotation. (Cross-links #26.)
- **Google SRE — "Implementing SLOs" chapter** → mine: error budgets convert reliability into a quantitative, reviewable contract; instrument what the SLO needs (good-vs-total events).
- **RFC 5424 (syslog severities)** → mine: the canonical log-level ladder (DEBUG/INFO/NOTICE/WARNING/ERROR/CRITICAL...) so "what level should this be" has an objective answer.
