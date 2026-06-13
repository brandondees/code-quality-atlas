# References to mine — reviewing-pr-and-process-hygiene

## Contents

- From category #24
- From category #22

## From category #24

### Key references

- **Conventional Commits 1.0.0** — https://www.conventionalcommits.org/en/v1.0.0/ (feat→MINOR, fix→PATCH, `!`/`BREAKING CHANGE:`→MAJOR).
  → mine: `type(scope)!: subject` + body + footer; types `feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`perf`/`build`/`ci`; `!` or `BREAKING CHANGE:` footer signals SemVer-major. Machine-readable risk/intent → auto-changelog and release decisions (links #22).
- **Google Engineering Practices — "Code Review Developer Guide" (Small CLs; What to look for)** `(verify)`.
  → mine: prefer small, single-purpose changelists; review for design, functionality, complexity, tests, naming, comments; "approve when it definitely improves overall code health, even if not perfect."
- **SmartBear / Cisco code-review study** (10 months, 2,500 reviews, 3.2M LOC at Cisco) — smartbear.com "Best Practices for Peer Code Review".
  → mine: defect-detection density is highest **below 200 LOC** and falls off **above ~400 LOC**; best inspection rate **<300–500 LOC/hour** and within **60–90 min** before detection plummets (≈70–90% defect yield at that pace). Big PRs get rubber-stamped — size is itself a quality risk.
- **Tim Pope — "A Note About Git Commit Messages"** `(verify)`.
  → mine: imperative-mood subject ≤~50 chars, blank line, wrapped body explaining *why* not *what*; one logical change per commit. Atomic commits enable clean revert/bisect.
- **Chris Beams — "How to Write a Git Commit Message" (seven rules)** — https://cbea.ms/git-commit/ (50-char imperative subject, blank line, 72-wrapped body, why-not-how).
  → mine: the concrete subject/body rules; "If applied, this commit will <subject>." as the imperative test.
- **GitHub Docs — CODEOWNERS** `(verify)`.
  → mine: path-based required reviewers; ownership makes "who must approve this area" explicit and routes risk to the right people. Stale/missing CODEOWNERS = unowned blast radius.
- **Agent-native architecture (compound-engineering `agent-native-reviewer` prior art; "any action a user can take, an agent can too")** `(verify)`.
  → mine: parity check — new user-facing capabilities should also be reachable programmatically (API/CLI/tool), not UI-only, so agents and automation aren't second-class. (Project-specific principle; map to a reviewable check.)
- **AGENTS.md / Agentic AI Foundation (Linux Foundation, 2025-12)** — https://agents.md/ (see #22 for the doc-artifact side).
  → mine: industry grounding for treating agents as first-class contributors to the development process — the ecosystem now standardizes how repos onboard automated collaborators. Strengthens the agent-native-parity principle from "house rule" toward industry practice; the *docs* obligation lives in #22, the *process* stance (agents can do what contributors can do) lives here.

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
