# Tool rules to triage — reviewing-artifact-conventions

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents

- From category #101

## From category #101

### Tooling rules worth lifting

*(No public `SKILL.md` linter exists yet; the atlas's own pipeline is the closest reference implementation. Named tools `(verify)` on your stack.)*

- **Frontmatter schema check** — validate `name` matches `^[a-z0-9-]+$` and is a gerund, and that `description` is non-empty and ≤1024 characters (the atlas's `tooling/manifest.py` does exactly this on our skills; lift it as a YAML-frontmatter schema gate).
- **Body-length / progressive-disclosure gate** — flag a `SKILL.md` body over ~500 lines, or one that inlines what belongs in a bundled file; a simple line-count + "are there bundled `reference/` files?" check.
- **Markdown hygiene** — `markdownlint` over the skill and its bundled files (heading increments, fenced-code languages, list spacing) so the artifact is clean Markdown.
- **Link / reference depth** — a relative-link checker (e.g. `lychee`) confirming bundled references resolve and sit one level deep, not a deep tree.
- **Eval presence** — a check that the skill ships an evals file with ≥3 scenarios (the atlas's `tooling/evals.py` / `cli eval` is the model).
