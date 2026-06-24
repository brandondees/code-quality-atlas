# Rubric — SKILL.md / agent skill

Review a **SKILL.md / agent skill** against its published standard. Activate when a SKILL.md or agent-skill definition file is added or changed. Report only real deviations from the standard; if the artifact is well-formed, reply "No findings".

## Reviewable heuristics (skill-checklist seeds)

- **Frontmatter is well-formed and within limits:** Does the skill have YAML frontmatter with a **gerund**, lowercase-hyphen `name` and a **specific, third-person `description` ≤1024 characters** that names the concrete situations and keywords that should trigger it? A missing, vague, first-person, or over-long description is the most common and most damaging defect — it is the always-on activation surface.
- **Progressive disclosure — a lean entry point, detail bundled:** Is the `SKILL.md` body a **lean entry point** (well under ~500 lines: when-to-use + a short checklist) with the heavy detail (full heuristics, tool rules, references, examples) in **one-level-deep bundled files loaded on demand**, rather than one long inlined wall? Bundled context is effectively free until read; an inlined mega-body taxes every session.
- **Trigger-rich description with a skip clause:** Beyond being present, does the description read like an activation trigger — concrete situations, file types, and keywords — and state **when *not* to use it** (a skip/"use when… skip when…" clause), so the model selects it precisely and doesn't fire it on every change?
- **A single default approach, not an option-menu:** Does the skill prescribe **one concrete recommended path** rather than a buffet of alternatives ("you could A, or B, or C")? Option-menus raise ambiguity and hurt portability to smaller models; pick a sensible default and name it.
- **Concrete good/bad examples and an output format:** Does a bundled `examples.md` (or equivalent) show **input → expected-finding pairs** and the **output format** to match, rather than only abstract prose? Concrete examples are what make the behavior reproducible across models.
- **No time-sensitive or environment-bound text:** Is the skill free of text that **rots** — "new", "currently", version numbers, dates, "as of" — and of harness/OS assumptions (use forward-slash paths, consistent terminology)? Time-sensitive wording silently goes stale.
- **One-level-deep references with a ToC for long files:** Are bundled files **one level deep** (not a nested tree the model must traverse), and does any bundled file **over ~100 lines open with a table of contents** so the model can navigate it without reading all of it?
- **Eval-first regression net:** Does the skill ship **≥3 evaluation scenarios** (query + expected behavior, ideally with a no-skill baseline) so its behavior is pinned and a later edit can be regression-checked rather than vibe-checked?
- **Model-portable, plain-markdown form:** Is the skill **plain Markdown + files with no Claude/harness-specific assumptions**, written as explicit, concrete, low-ambiguity checklists so it degrades gracefully on smaller or non-Claude models? Portability is a stated goal of the standard, not a nicety.

## Key references

- **Anthropic — Agent Skill authoring best practices** — https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices → mine: the canonical standard. Frontmatter `name` (gerund, lowercase-hyphen) + a specific third-person `description` ≤1024 chars carrying explicit trigger keywords; a lean `SKILL.md` body (<500 lines, aim far less); progressive disclosure (detail in bundled, one-level-deep files loaded on demand; a ToC for files >100 lines); a single default approach over option-menus; no time-sensitive text; forward-slash paths; consistent terminology; model-portability (don't assume the reader is Claude).
- **Anthropic — Equipping agents for the real world with Agent Skills** — https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills → mine: the three-tier progressive-disclosure cost model — metadata (always-on) → body (on relevance) → bundled files (on demand, "effectively unbounded"). Grounds why the body must stay lean and detail must be bundled, not inlined.
- **Anthropic — Writing effective tools for AI agents** — https://www.anthropic.com/engineering/writing-tools-for-agents → mine: the description is the activation surface — specific, situation-naming triggers beat vague ones; too many/overlapping descriptions degrade selection. Grounds the trigger-richness and skip-clause checks.

## Tooling rules worth lifting

*(No public `SKILL.md` linter exists yet; the atlas's own pipeline is the closest reference implementation. Named tools `(verify)` on your stack.)*

- **Frontmatter schema check** — validate `name` matches `^[a-z0-9-]+$` and is a gerund, and that `description` is non-empty and ≤1024 characters (the atlas's `tooling/manifest.py` does exactly this on our skills; lift it as a YAML-frontmatter schema gate).
- **Body-length / progressive-disclosure gate** — flag a `SKILL.md` body over ~500 lines, or one that inlines what belongs in a bundled file; a simple line-count + "are there bundled `reference/` files?" check.
- **Markdown hygiene** — `markdownlint` over the skill and its bundled files (heading increments, fenced-code languages, list spacing) so the artifact is clean Markdown.
- **Link / reference depth** — a relative-link checker (e.g. `lychee`) confirming bundled references resolve and sit one level deep, not a deep tree.
- **Eval presence** — a check that the skill ships an evals file with ≥3 scenarios (the atlas's `tooling/evals.py` / `cli eval` is the model).
