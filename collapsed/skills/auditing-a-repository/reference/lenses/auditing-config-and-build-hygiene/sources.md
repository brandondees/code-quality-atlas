# References to mine — auditing-config-and-build-hygiene

## Contents

- From category #19
- From category #26

## From category #19

### Key references

- **Jez Humble & David Farley — *Continuous Delivery*** → mine: the deployment pipeline; **build once, promote the same artifact**; keep the build green; automate everything.
- **Forsgren, Humble, Kim — *Accelerate* / DORA** → mine: the **four key metrics** (deployment frequency, lead time for changes, change-failure rate, time-to-restore) — the outcomes CI/CD quality should move; speed and stability are *not* a trade-off.
- **Trunk-Based Development** — https://trunkbaseddevelopment.com/ → mine: short-lived branches, integrate continuously, hide incomplete work behind feature flags (cross #26).
- **Bazel / hermetic & reproducible builds** → mine: declared inputs only, sandboxed actions, content-addressed caching → identical inputs produce identical outputs; kills "works on my machine."
- **Martin Fowler — "Continuous Integration"** → mine: a slow or flaky CI is itself a quality defect; keep it fast and green, quarantine flakies.

## From category #26

### Key references

- **The Twelve-Factor App — Config (factor III)** — https://12factor.net/config → mine: strict separation of config from code; store config in **env vars**; never commit config/secrets. Also factor X (dev/prod parity), XI (logs to stdout — cross #16).
- **Pete Hodgson — "Feature Toggles (aka Feature Flags)" (martinfowler.com)** — https://martinfowler.com/articles/feature-toggles.html → mine: toggle **categories** (release, ops, experiment, permission), decoupling deploy from release, and the crucial point that **flags have a lifecycle** — release flags are temporary and must be removed to avoid debt (cross #21).
- **HashiCorp Vault / secrets management** → mine: secrets out of config files; prefer dynamic, leased, rotated secrets.
- **Config validation at startup / "fail fast"** → mine: validate all config at boot (clear error on missing/invalid), don't discover misconfig at 3am on first use.
