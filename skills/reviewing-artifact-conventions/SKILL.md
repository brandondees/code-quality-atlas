---
name: reviewing-artifact-conventions
description: 'Reviews a standardized non-source artifact against its own published
  "well-formed X" standard rather than as application code — the artifact review shape
  (D15), presence-activated. On detecting a supported artifact it loads that artifact''s
  rubric and reviews against it. Supported artifact: a SKILL.md / agent-skill definition,
  reviewed against Anthropic''s skill-authoring best practices (trigger-rich frontmatter
  within limits, a lean progressive-disclosure body with detail bundled, a single
  default approach, no time-sensitive text, one-level-deep references, eval-first).
  Use when reviewing a SKILL.md or agent-skill definition (or another listed authored
  artifact) against the standard it should follow. Skip when none of the listed artifacts
  are present — ordinary source code is the other lenses'' job, and this is authoring
  quality, distinct from doc-drift (#22) and runtime agent-safety (#32).'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 101
    source: docs/research/artifact-rubrics.md#101
    hash: ecb1c4bd2787e47cb7ab520f57763b56a641f65170d669cf0ca6e8a6dcf01f21
---

# reviewing-artifact-conventions

*Is this authored artifact well-formed per its own standard? Detect the artifact (e.g. SKILL.md), load its rubric, review against it.*

## When to use

Reviews a standardized non-source artifact against its own published "well-formed X" standard rather than as application code — the artifact review shape (D15), presence-activated. On detecting a supported artifact it loads that artifact's rubric and reviews against it. Supported artifact: a SKILL.md / agent-skill definition, reviewed against Anthropic's skill-authoring best practices (trigger-rich frontmatter within limits, a lean progressive-disclosure body with detail bundled, a single default approach, no time-sensitive text, one-level-deep references, eval-first). Use when reviewing a SKILL.md or agent-skill definition (or another listed authored artifact) against the standard it should follow. Skip when none of the listed artifacts are present — ordinary source code is the other lenses' job, and this is authoring quality, distinct from doc-drift (#22) and runtime agent-safety (#32).

**Shape: artifact.** Presence-activated: run only when one of the artifacts in the table below is present in the change or repo. Detect the artifact, open its rubric, and review the artifact against that published standard — not the surrounding application code. Skip entirely when none of the listed artifacts are present.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Artifacts

Detect which artifact the change adds or touches, then open its rubric and review the artifact against that published standard:

| Artifact | Activate when | Rubric to apply |
|---|---|---|
| SKILL.md / agent skill | a SKILL.md or agent-skill definition file is added or changed | [reference/skill-md.md](reference/skill-md.md) |

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/skill-md.md](reference/skill-md.md) — the rubric for SKILL.md / agent skill; open it on a presence hit and review against it.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — the tools that mechanize part of each rubric; for wiring up checks, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the published standards behind each rubric; for provenance, not needed during a review.
