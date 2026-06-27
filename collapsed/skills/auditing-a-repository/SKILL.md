---
name: auditing-a-repository
description: Run a whole-repository health audit with the code-quality-atlas repo-shaped
  audits (architecture, dependencies, config/build, docs, compliance, enforcement,
  infrastructure-as-code, maintainability hotspots). Use for a scheduled or on-demand
  repo audit, not a single diff. Runs the applicable audits and synthesizes one report.
provenance:
  taxonomy_version: v0.8
  built_from: []
---

# auditing-a-repository

## When to use

Run a whole-repository health audit with the code-quality-atlas repo-shaped audits (architecture, dependencies, config/build, docs, compliance, enforcement, infrastructure-as-code, maintainability hotspots). Use for a scheduled or on-demand repo audit, not a single diff. Runs the applicable audits and synthesizes one report.

## How this works

Rank the relevant lenses below by relevance to what is being reviewed, pick the breadth from the depth mode (default **review**), then for each selected lens **load its bundle** and apply it:

- Read `reference/lenses/<lens>/body.md` — the lens's checklist and examples. Open `reference/lenses/<lens>/tool-rules.md` or `sources.md` only if deeper tooling/provenance is called for.
- After the lenses run, merge their findings with the procedure in `reference/synthesis.md` — one deduplicated, ranked report with a single verdict.

## Depth modes

Routing first ranks **every** lens whose scope the change touches by **relevance** — it is no longer a hard 2-4 cap. A depth mode then sets the **breadth** (how far down the ranked list to run) and the severity floor. Pick the mode from the request; default to **review**.

| Mode | Breadth | Triggers |
|---|---|---|
| **triage** | the critical tier only — correctness, security, data-safety, and concurrency | "triage", "quick review", "fast check", "pre-merge gate" |
| **review** | the top 2-4 lenses by relevance (the default; overridable) | "review", "review this", "code review", "review this PR", "review the diff" |
| **comprehensive** | every relevant lens, uncapped — the full audit set at repo scope | "thorough", "comprehensive", "deep review", "use all relevant lenses", "review everything" |

- **triage** — A pre-merge gate: run only the critical-tier lenses and report Major and above.
- **review** — Default per-PR depth: relevance-ranked top-N with the round-based escalating floor.
- **comprehensive** — On-demand or scheduled: run all relevant lenses and pin the floor at Nit so readability-class and other long-tail findings surface instead of being trimmed.

## Routes

| When reviewing… | Run |
|---|---|
| Dependency add or bump | `auditing-dependencies-and-supply-chain` |
| CI / build / config change | `auditing-config-and-build-hygiene` |
| Install / setup / packaging change, an upgrade or migration guide, a config or CLI surface, or anything a downstream project adopts (a tool, plugin, template, or library) | `auditing-documentation-health` |
| Infrastructure-as-code change (Terraform/OpenTofu, Kubernetes/Helm, CloudFormation manifests) | `auditing-infrastructure-as-code` |
| Whole-repo health audit (scheduled / cron) | `finding-maintainability-hotspots`, `auditing-architecture-conformance`, `auditing-dependencies-and-supply-chain`, `auditing-config-and-build-hygiene`, `auditing-documentation-health`, `auditing-compliance-and-provenance`, `auditing-enforcement-and-meta-artifacts`, `auditing-infrastructure-as-code` |
| Enforcement config — lint/type suppressions, alert rules or dashboards, or checked-in generated artifacts | `auditing-enforcement-and-meta-artifacts` |

## Lenses

◆ = design-capable.

- [`finding-maintainability-hotspots`](reference/lenses/finding-maintainability-hotspots/body.md) — Where does the repo hurt most? Churn × complexity, change-coupling, bus factor, untracked debt.
- [`auditing-architecture-conformance`](reference/lenses/auditing-architecture-conformance/body.md) — Does the import graph still match the intended architecture? Layers, cycles, reach-arounds.
- [`auditing-dependencies-and-supply-chain`](reference/lenses/auditing-dependencies-and-supply-chain/body.md) — Is the dependency tree safe? CVEs, pinning, typosquats, install scripts, licenses.
- [`auditing-config-and-build-hygiene`](reference/lenses/auditing-config-and-build-hygiene/body.md) — Are config and CI trustworthy? Secrets, env parity, reproducible pinned builds, cache correctness.
- [`auditing-documentation-health`](reference/lenses/auditing-documentation-health/body.md) — Do the docs still tell the truth? API parity, stale examples, ADR coverage, changelog discipline.
- [`auditing-compliance-and-provenance`](reference/lenses/auditing-compliance-and-provenance/body.md) — Any licensing, PII, or provenance exposure? Detect and escalate to humans — never decide legal questions.
- [`auditing-enforcement-and-meta-artifacts`](reference/lenses/auditing-enforcement-and-meta-artifacts/body.md) — Is the enforcement apparatus healthy? Suppression hygiene & baseline trend, actionable alerts/monitoring-as-code, codegen-source drift gate.
- [`auditing-infrastructure-as-code`](reference/lenses/auditing-infrastructure-as-code/body.md) — Does this infra change expose or destroy something? Blast radius, public access, wildcard IAM, secrets in state, drift.
