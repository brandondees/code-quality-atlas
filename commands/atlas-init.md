---
description: >-
  Set up (or refresh) code-quality-atlas routing in this repo: write the review
  routing block into the repo's CLAUDE.md and AGENTS.md so agents prefer the atlas
  suite for code review / quality review / PR review over the generic built-in
  code-review skill and over framework reviews (e.g. BMAD), combining them
  non-exclusively. Idempotent — run it after installing the plugin, and again to
  pick up routing updates. Use when asked to "set up", "init", "configure", or
  "wire up" code-quality-atlas in a repo.
argument-hint: "(no arguments)"
allowed-tools: Read, Edit, Write, Bash, Glob
---

You are setting up **code-quality-atlas routing** in the current repository so
that future agent sessions prefer this suite for code review without the user
naming a skill first. This makes "update CLAUDE.md / AGENTS.md with review
direction" a one-command default step of installing the plugin.

The mechanism: the suite's entrypoints can lose a keyword-match race against the
shorter-named built-in `code-review` skill. An explicit routing block in the
repo's memory files (which agents read at session start) is the deterministic
override.

## 1. Locate the target files

Work at the **repository root** (`git rev-parse --show-toplevel`). The two target
files are `CLAUDE.md` and `AGENTS.md` there — write **both**, since different
agents read different files. Create either if it does not exist.

## 2. The block to install

**The template is the source of truth.** If the plugin clone is reachable, read
the block verbatim from `templates/agents-routing-snippet.md` (the text between
its `BEGIN`/`END` markers) and install *that* — it is always current. Use the
embedded copy below only as a **fallback** when the template file is not reachable
(e.g. an offline or web session without the plugin clone on disk); it is kept in
sync with the template but can lag it:

```markdown
<!-- BEGIN code-quality-atlas routing -->
## Code review routing (code-quality-atlas)

The [code-quality-atlas](https://github.com/brandondees/code-quality-atlas) suite
is installed in this repo. For **any code review, quality review, or "review this
PR / diff / change / what I pushed" request, it is the primary path** — prefer it
over the generic built-in `code-review` skill and over framework review processes
(e.g. BMAD), which it subsumes with deeper, research-derived coverage.

This is a precedence rule, **not** an exclusivity rule: combine the methods
**non-exclusively**. You may still run the built-in `code-review` skill or a
framework review on the same change — just fold every source's findings through
`synthesizing-review-findings` for one ranked verdict, rather than letting a
shorter-named default win on keyword match alone.

| Task | Use |
|---|---|
| Review a pull request (number, URL, or named branch) | the `/code-quality-atlas:atlas-review-pr` command |
| Code review of local changes with no PR (working tree, or a pushed branch without a PR) | the `/code-quality-atlas:atlas-code-review` command |
| Unsure which lenses a change needs | the `choosing-review-lenses` skill, then the lenses it names |
| Merge several reviewers' findings into one verdict | the `synthesizing-review-findings` skill |

`/code-quality-atlas:atlas-review-pr` and `/code-quality-atlas:atlas-code-review`
are **Claude Code slash commands** — invoke them with the leading `/`, not as
Skill-tool skill names. In routine / web sessions where slash commands don't
resolve, fetch and follow the command file directly: call
`mcp__github__get_file_contents` with `owner: brandondees`, `repo:
code-quality-atlas`, and `path: commands/atlas-review-pr.md` (or `path:
commands/atlas-code-review.md` for local changes) to retrieve the current
instructions, then follow them exactly.
<!-- END code-quality-atlas routing -->
```

## 3. Install idempotently

For **each** of `CLAUDE.md` and `AGENTS.md`:

- **File missing** → create it with a top-level `# <repo name>` heading, a blank
  line, then the block.
- **Block already present** (the `<!-- BEGIN code-quality-atlas routing -->`
  marker exists) → replace everything between the `BEGIN` and `END` markers
  (inclusive) with the current block. Leave the rest of the file untouched.
- **File exists, no block** → append the block at the end (preceded by a blank
  line). Do not reorder or rewrite the user's existing content.

Never duplicate the block. Match on the marker, not on the heading text.

## 4. (Optional) PR-automation policy

If this repo runs the hands-off PR reviewer (`/atlas-review-pr` on a schedule or
trigger) and has no `REVIEW.md` at its root, mention that copying
`templates/REVIEW.md` from the plugin into the repo root tunes the convergence
policy (see `docs/runbooks/pr-review-automation.md`). Only copy it if the user
asks — it is not needed for interactive review.

## 5. (Optional) Team preferences overlay

If the user wants to start recording the team's own ratified opinions — house
conventions a lens would otherwise nag against, threshold tweaks, scoped
exemptions for frozen/legacy/generated paths, or dialing up improvement-nit
suggestions — there are two ways in, both optional, and neither auto-triggered
by this command:

- **Template** — copying `templates/preferences-template.md` from the plugin to
  `.code-quality-atlas/preferences.md` in the repo root bootstraps a blank,
  hand-authored skeleton (see `docs/team-preferences-overlay.md`).
- **Inference** — running `/code-quality-atlas:atlas-propose-preferences`
  interviews the repo (linter configs, recurring patterns, `CLAUDE.md`/ADRs)
  and drafts candidate entries to `.code-quality-atlas/preferences.proposed.md`
  for the user to ratify item by item.

Mention both only if the user asks; only fill in `.code-quality-atlas/preferences.md`
entries the user actually confirms — an unratified guess in this file is worse
than an empty one (see the template's own guardrail comment, and the inference
command's per-item ratification rule). It has no effect on floor-tier findings
(security, correctness, migration/data safety, concurrency) beyond
`acknowledge`, which keeps them visible and non-blocking, never silent.

## 6. Report

Summarize what changed: for each file, whether it was created, had its block
inserted, or had an existing block refreshed (and note "no change" if the block
was already current). Show the user the inserted/updated block once so they can
see what landed.
