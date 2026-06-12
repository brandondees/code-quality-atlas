# Tool rules to triage — reviewing-resilience-and-scalability

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents
- From category #28

## From category #28

### Tooling rules worth lifting
- **This category is judgment-led, not linter-led.** Unlike #14/#15, there is little static analysis that proves resilience; the leverage is in design review and chaos/load testing, so the heuristics carry the weight. Treat the tools below as evidence-gatherers, not gates.
- **Resilience libraries (presence + correct use, not mere import):** Resilience4j / Polly / Hystrix-legacy (circuit breakers, bulkheads, rate limiters), Envoy/Istio outlier-detection & circuit-breaking, AWS SDK adaptive retry. A retry config with **no budget/jitter** is a finding, not a fix.
- **Load & soak testing:** k6, Gatling, Locust, `wrk` — a scalability or capacity claim is unbacked without a load profile; watch **p99/p999**, not mean.
- **Chaos / fault injection:** Chaos Mesh, Gremlin, AWS FIS, Toxiproxy (inject latency/faults into dependency calls) — the way to turn a resilience assertion into evidence.
- **Recovery drills:** scripted restore-from-backup in CI/staging, AWS Resilience Hub / Route 53 ARC for RTO/RPO assessment — backups are only credible once a restore is exercised.
