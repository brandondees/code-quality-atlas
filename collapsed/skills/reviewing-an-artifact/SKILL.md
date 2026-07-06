---
name: reviewing-an-artifact
description: Review a standardized authored artifact against its own published standard
  rather than as application code — e.g. a SKILL.md / agent-skill definition. Detects
  the artifact and applies its rubric. The collapsed entrypoint for artifact-shaped
  review.
provenance:
  taxonomy_version: v0.9
  built_from: []
---

# reviewing-an-artifact

## When to use

Review a standardized authored artifact against its own published standard rather than as application code — e.g. a SKILL.md / agent-skill definition. Detects the artifact and applies its rubric. The collapsed entrypoint for artifact-shaped review.

## How this works

Rank the relevant lenses below by relevance to what is being reviewed, pick the breadth from the depth mode (default **review**), then for each selected lens **load its bundle** and apply it:

- Read `reference/lenses/<lens>/body.md` — the lens's checklist and examples. Open `reference/lenses/<lens>/tool-rules.md` or `sources.md` only if deeper tooling/provenance is called for.
- After the lenses run, merge their findings with the procedure in `reference/synthesis.md` — one deduplicated, ranked report with a single verdict.

## Depth modes

Routing first ranks **every** lens whose scope the change touches by **relevance** — it is no longer a hard cap. A depth mode then sets the **breadth** (how far down the ranked list to run, plus room for judgment calls above that floor) and the severity floor. Pick the mode from the request; default to **review**.

| Mode | Breadth | Triggers |
|---|---|---|
| **triage** | the critical tier only — correctness, security, data-safety, and concurrency | "triage", "quick review", "fast check", "pre-merge gate" |
| **review** | the top 3-8 lenses by relevance, plus any additional relevant lenses the reviewer judges worthwhile (the default; not a strict cap) | "review", "review this", "code review", "review this PR", "review the diff" |
| **comprehensive** | every relevant lens, uncapped — the full audit set at repo scope | "thorough", "comprehensive", "deep review", "use all relevant lenses", "review everything" |

- **triage** — A pre-merge gate: run only the critical-tier lenses and report Major and above.
- **review** — Default per-PR depth: relevance-ranked top-N (3-8) with the round-based escalating floor; extend past N when the change's scope genuinely calls for another lens.
- **comprehensive** — On-demand or scheduled: run all relevant lenses and pin the floor at Nit so readability-class and other long-tail findings surface instead of being trimmed.

## Routes

| When reviewing… | Run |
|---|---|
| A standardized authored artifact rather than source code — a SKILL.md or agent-skill definition (more artifact rubrics to come) | `reviewing-artifact-conventions` — artifact-shaped — detect the artifact, then review it against its own published standard, not as application code |

## Lenses

◆ = design-capable.

- [`reviewing-artifact-conventions`](reference/lenses/reviewing-artifact-conventions/body.md) — Is this authored artifact well-formed per its own standard? Detect the artifact (e.g. SKILL.md), load its rubric, review against it.
