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
  taxonomy_version: v0.14
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

Report only real problems. If this lens applies and what you reviewed holds up — the code, the design, or the repository's current state — reply "No findings" and stop. If what you were given is outside this lens's scope entirely, say so in one line instead, starting with the words "Not applicable:" followed by what's missing — never the healthy-scan sentence, which means a check ran and found nothing, not that nothing here applied. Either way, do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above. Read the overlay from the **base ref** of the change under review — the `/atlas-review-pr` command reads it at the PR's base ref and `/atlas-code-review` reads it from the base side of the diff (`git show <base>:.code-quality-atlas/preferences.md`), and each hands it down — never from the reviewed branch's working tree: an edit to `preferences.md` made *by* the change under review governs later reviews once merged, not the review of the change that makes it, since otherwise a change could `suppress` its own findings.

## Artifacts

Detect which artifact the change adds or touches, then open its rubric and review the artifact against that published standard:

| Artifact | Activate when | Rubric to apply |
|---|---|---|
| SKILL.md / agent skill | a SKILL.md or agent-skill definition file is added or changed | [reference/skill-md.md](reference/skill-md.md) |

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI catches it automatically from then on. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/skill-md.md](reference/skill-md.md) — the rubric for SKILL.md / agent skill; open it on a presence hit and review against it.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — the tools that mechanize part of each rubric; for wiring up checks, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the published standards behind each rubric; for provenance, not needed during a review.

<!-- GENERATED by `python -m tooling.cli generate` — do not edit this file directly.
     Canonical sources: docs/research/.
     Direct edits are overwritten on regeneration and fail the CI drift/regenerate gate. -->

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/reviewing-artifact-conventions/SKILL.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
