# References to mine — auditing-documentation-health

## Contents

- From category #22

## From category #22

### Key references

- **Diátaxis (Daniele Procida) — https://diataxis.fr/**
  → mine: four distinct doc modes — **tutorials** (learning-oriented), **how-to guides** (task/goal-oriented), **reference** (information-oriented), **explanation** (understanding-oriented) — on two axes (action↔cognition, acquisition↔application). A doc that mixes modes (tutorial that drifts into reference) is a smell; missing a *whole quadrant* (e.g. no how-tos) is a gap.
- **Michael Nygard — "Documenting Architecture Decisions" (ADR, 2011)** — https://adr.github.io/ (overview: https://martinfowler.com/bliki/ArchitectureDecisionRecord.html)
  → mine: lightweight, immutable, append-only decision records with the fields **title, status, context, decision, consequences** (status: proposed/accepted/superseded). The *why* lives here, not in code comments. Superseding rather than editing preserves history.
- **Keep a Changelog — https://keepachangelog.com/ + Semantic Versioning — https://semver.org/**
  → mine: human-readable `CHANGELOG.md` grouped by Added/Changed/Deprecated/Removed/Fixed/Security, newest-first, `Unreleased` section; tie entries to SemVer bumps. "Don't let your friends dump git logs into changelogs" `(verify)` phrasing.
- **Google Developer Documentation Style Guide / "Docs as Code"** `(verify)`.
  → mine: docs live in the repo, reviewed in PRs, linted and built in CI; same change should update the doc that describes it. Treat doc drift like a failing test.
- **Write the Docs community / "documentation system" essays** `(verify)`.
  → mine: README-as-front-door checklist (what it is, why, install, minimal usage, where to go next); the "minimal runnable example" as the highest-leverage doc artifact.
- **The C4 model (Simon Brown) and Mermaid / PlantUML diagrams-as-code** `(verify)`.
  → mine: diagrams should be versioned text (Mermaid/PlantUML), not binary screenshots, so they're diffable and stay in sync; C4's Context→Container→Component levels give a "what level is this diagram" check.
- **AGENTS.md — open agent-instructions convention** — https://agents.md/ (introduced by OpenAI 2025-08; stewarded by the **Agentic AI Foundation** under the Linux Foundation since 2025-12, founded by Anthropic, OpenAI, and Block; adopted by tens of thousands of repos and the major coding agents).
  → mine: "a README for agents" — a repo-level Markdown file carrying build/test/lint commands, conventions, and layout for *automated* contributors, with **nearest-file-wins** precedence so monorepo subprojects ship tailored instructions. Establishes agent-facing docs as a first-class doc artifact — which means it inherits every doc obligation in this category, drift above all (a stale AGENTS.md actively misleads agents that, unlike humans, won't shrug it off).
