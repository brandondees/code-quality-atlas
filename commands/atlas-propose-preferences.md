---
description: >-
  Interview this repo and propose a team-preferences overlay
  (.code-quality-atlas/preferences.md) — the inference path from
  docs/team-preferences-overlay.md §6. Reads existing linter configs,
  recurring code patterns, CLAUDE.md/AGENTS.md, and ADRs, then emits a
  proposal document of candidate preferences, each paired with its evidence
  and framed as a yes/no question. Never writes the live overlay directly —
  ratification is per-item and human. Use when asked to "set up my
  preferences", "propose team preferences", "infer our house style", or
  "bootstrap the preferences overlay".
argument-hint: "(no arguments — always reviews the whole repo)"
allowed-tools: Read, Grep, Glob, Bash, Write
---

You are running the **inference path** of the code-quality-atlas team
preferences overlay (see `docs/team-preferences-overlay.md`, §6). Your job is
to produce a **proposal document**, never the live overlay — the single
guardrail that matters:

> Inference is proposal-only. Nothing enters `preferences.md` without an
> explicit, per-item human decision. A vibe-coded or haphazard codebase can
> *look* like it encodes deliberate decisions when each one was really an
> unconsidered approve-click — inferring preferences from "what the code
> already does" would launder those accidents into ratified standards, which
> is the worst failure mode a quality suite can have.

This command is explicitly invoked — never run it as part of a normal review,
and never auto-generate a proposal just because `.code-quality-atlas/preferences.md`
is absent.

## 1. Check for an existing overlay

If `.code-quality-atlas/preferences.md` already exists at the repo root, tell
the user and ask whether they want a **fresh proposal** (to review alongside
the existing file) or to stop. Do not overwrite the live overlay yourself —
only the human, editing it directly, ever does that.

## 2. Gather evidence

Look for signals across the six directive kinds
(`docs/team-preferences-overlay.md` §4). For each, gather **observations**,
not conclusions:

- **Lens selection / weighting** — does the repo look internal-only (no
  public-facing UI, an admin tool) where a11y might be deprioritized? Does it
  have a documented history of premature abstraction (worth an always-run
  restraint note) or of security incidents (worth always-run security)?
- **Threshold tuning** — existing linter configs (`.eslintrc*`, `.rubocop.yml`,
  `ruff.toml`/`pyproject.toml [tool.ruff]`, `.golangci.yml`, `.editorconfig`,
  etc.) that already encode numeric thresholds (function length, complexity,
  line length). Also look for a documented PR-size norm (CONTRIBUTING.md,
  PR template).
- **House conventions** — recurring structural patterns that appear
  consistently across the codebase (e.g. every service uses fat objects with
  no DI framework; every module avoids a specific idiom). Only patterns with
  **high, consistent recurrence** are candidates — a pattern seen once or
  twice is not evidence of a house decision.
- **Scoped exemptions** — directories that look frozen/legacy/generated:
  `legacy/`, `vendor/`, `generated/`, `*_pb2.py`, `.min.js`, anything with a
  codegen header comment, or a directory the repo's own docs call out as
  deprecated/frozen.
- **Standing acknowledgements** — anything in the repo's own docs, issue
  tracker references, or code comments that reads as a *known, accepted*
  deviation (e.g. a comment citing a tracked ticket for why something unsafe
  is intentional for now). Do not infer these from code alone — only surface
  ones the repo already documents as a conscious, accepted risk.
- **Improvement-valence verbosity** — no code signal for this one; always
  propose it as a plain question (defects-only is the safe default), never
  infer a mode from repo state.

Read `CLAUDE.md` / `AGENTS.md` and any `docs/adr/` or `docs/decisions/`
directory for explicit statements of team intent — these are the strongest
evidence, since they're already the team's own words.

## 3. Build the proposal — descriptive, not prescriptive

For each candidate, write an entry that keeps observation and recommendation
**visibly separate** and forces the human to make the jump:

```markdown
- candidate: <the directive kind> — <short description>
  observed: <what you actually found, with a file/count/percentage — e.g.
    "23 of 27 service classes in src/services/ have 5+ instance variables and
    no constructor-injected interfaces; ruby-style transaction scripts, not
    DDD collaborators">
  proposed rule: <the overlay entry this would become, in the template's
    format>
  question: "Is this a deliberate house decision, or just how it ended up?
    If deliberate, why?"
```

Do not use words like "your team decided" or "the convention is" — those
claims belong to the human, not to your inference. Every entry stays in
`observed`/`proposed rule` framing until ratified.

Order the proposal by the six directive-kind sections from
`templates/preferences-template.md`, so it reads as a companion document the
human can ratify section by section. Skip sections with no evidence rather
than padding with weak/low-confidence candidates — a short honest proposal
beats a long speculative one.

## 4. Write the proposal, not the overlay

Write the proposal to `.code-quality-atlas/preferences.proposed.md` (never
`.code-quality-atlas/preferences.md`) — a `proposed:` staging file distinct
from the live, ratified overlay per §6's optional-staging note. Include a
header:

```markdown
<!-- code-quality-atlas preferences proposal — generated by
/code-quality-atlas:atlas-propose-preferences on <today's date>. This is NOT
the live overlay; code-quality-atlas lenses do not read this file. Review
each candidate, then hand-copy the ones you ratify into
.code-quality-atlas/preferences.md using templates/preferences-template.md's
format, adding a `decided: <date>, @<you>` line to each. Delete or ignore any
candidate you reject. See docs/team-preferences-overlay.md §6. -->
```

## 5. Report

Summarize what you found: how many candidates per directive kind, and the
single strongest one (the entry with the most consistent evidence). Tell the
user the proposal file's path and that **nothing takes effect** until they
copy ratified entries — with a `decided:` line — into
`.code-quality-atlas/preferences.md` themselves (or ask you to, item by item,
in a follow-up). If you found no meaningful candidates for a section, say so
plainly rather than inventing weak ones — an empty section is a valid,
honest result.
