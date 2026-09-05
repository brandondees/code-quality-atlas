# code-quality-atlas

<!-- BEGIN shared orientation -->

## Orientation for new sessions

Asked something like "what's next?" or otherwise asked to plan or build without
a named task? This repo's active roadmap lives in `docs/`, not just in GitHub
issues/PRs — check these before reporting nothing's queued:

- [`docs/open-questions.md`](docs/open-questions.md) — the decisions log
  (`D1`-`D18`+) and the live "Genuinely still open (undecided)" list. Start here.
- [`docs/plans/`](docs/plans/) — dated, scoped design docs, each carrying its
  own `**Status:**` header; check that header per file rather than assuming
  the whole directory is a live work queue or a historical record.
- [`docs/map-gaps.md`](docs/map-gaps.md) — structural taxonomy gaps (`G1`-`G32`+)
  feeding future categories/lenses.
- [`docs/session-log.md`](docs/session-log.md) — narrative history of what
  shipped and why, for when a doc pointer alone isn't enough context.
- [`docs/map/CLAUDE.md`](docs/map/CLAUDE.md) — the repo's own ICM system map:
  what the nouns are (a lens, a category, an eval scenario, a decision...)
  and what a change hits, cited against source rather than re-derived from
  scratch each session.

Before authoring anything here, read the **standing authoring rules** in
[`docs/research/README.md`](docs/research/README.md) — behavioral claims,
summaries agreeing with what they summarize, and convention sweeps. They apply to
every artifact in this repo, not only the research files, and each one is there
because a reviewer caught it after it shipped.

**Resumed or restarted session?** This repo is worked on from cloud sessions whose
container can be reset mid-task, leaving the working tree at an *older* commit than
the branch already pushed. Run `git fetch origin <branch> && git status -sb` before
the first edit: a blind push from a stale tree reverts your own earlier work and
reports success. The mirror image is a tracking ref left stale when a merged branch
is deleted server-side, which makes tooling report phantom unpushed commits —
`git merge-base --is-ancestor HEAD origin/main` distinguishes the two.

## Development setup

Python **3.12+** (`pyproject.toml`'s `requires-python`, matching ruff's
`target-version` and `requirements.txt`'s pip-compile header — the only
version CI tests against). From the repo root:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q --cov=tooling   # test suite + coverage gate (94% floor)
ruff check . && ruff format --check .   # lint + format
python -m tooling.cli drift     # skills in sync with their research sources?
```

Everything here assumes the repo root as the working directory — `tooling.cli`
imports break run from elsewhere (e.g. `ModuleNotFoundError` from `/tmp`).

<!-- END shared orientation -->

This is separate from the code-review routing block below: that block answers
"review this change" requests; this section answers "what should I work on"
requests. (This orientation section is scoped to this repo's own contributor-
facing `AGENTS.md`/`CLAUDE.md` — it does not apply to consumers of the plugin,
who don't have this repo's planning docs, so it is not part of
`templates/agents-routing-snippet.md`.)

This file carries the code-review routing block that also appears in
[`CLAUDE.md`](CLAUDE.md), for agents that read `AGENTS.md` instead. (`CLAUDE.md`
additionally carries the "Plugin consumers" guidance.) The block below is the
canonical routing snippet
([`templates/agents-routing-snippet.md`](templates/agents-routing-snippet.md));
the `/code-quality-atlas:atlas-init` command writes and refreshes it in consumer
repos. Keep this copy in sync when the template changes.

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
| Review a pull request (number, URL, or named branch) | standalone form: the `/code-quality-atlas:atlas-review-pr` command. Collapsed form: no command ships — describe the request in natural language ("review this PR") and let `reviewing-a-change` trigger directly |
| Code review of local changes with no PR (working tree, or a pushed branch without a PR) | standalone form: the `/code-quality-atlas:atlas-code-review` command. Collapsed form: no command ships — describe the request in natural language and let `reviewing-a-change` trigger directly |
| Unsure which lenses a change needs | standalone form: the `choosing-review-lenses` skill, then the lenses it names. Collapsed form: invoke the matching entrypoint (e.g. `reviewing-a-change`) directly — it ranks and selects the relevant lenses internally |
| Ground a review in the repo's own linters, type checkers, and scanners before judging | standalone form: the `grounding-review-in-tool-output` skill, run before the lenses. Collapsed form: the same procedure ships bundled as each entrypoint's `reference/tool-evidence.md` and runs ahead of its lenses |
| Merge several reviewers' findings into one verdict | standalone form: the `synthesizing-review-findings` skill. Collapsed form: the same procedure ships bundled as each entrypoint's `reference/synthesis.md` (e.g. `reviewing-a-change/reference/synthesis.md`) and runs automatically after its lenses |

`/code-quality-atlas:atlas-review-pr` and `/code-quality-atlas:atlas-code-review`
are **Claude Code slash commands** — invoke them with the leading `/`, not as
Skill-tool skill names. In routine / web sessions where slash commands don't
resolve, fetch and follow the command file directly: call
`mcp__github__get_file_contents` with `owner: brandondees`, `repo:
code-quality-atlas`, `path: commands/atlas-review-pr.md` (or `path:
commands/atlas-code-review.md` for local changes), and **`ref`** — pass the
commit noted in this repo's `.claude/skills/.atlas-vendored`
(`source=...@<sha>`) if that file exists **and names an actual commit, not
the `<self>` self-vendoring sentinel** `tooling/vendor-skills.sh` writes when
a repo vendors the suite into itself, otherwise `refs/heads/main` (an
explicit `ref` here, even branch-level, beats the implicit default-branch
fetch this omitted before, issue #388) — to retrieve the current
instructions, then follow them exactly.
<!-- END code-quality-atlas routing -->

**A lens fix goes into its sources, never a generated or mirrored copy.**
Per lens under `skills/<name>/`: `skills/manifest.yaml` + the relevant
`docs/research/*.md` sections are the **sources**; `SKILL.md` +
`reference/*.md` are **generated** from them by `tooling.cli generate`
(every generated file carries a `<!-- GENERATED ... -->` marker — leading
for `reference/*.md`, trailing on `SKILL.md` since its YAML frontmatter
must lead the file); `examples.md` + `evals/eval.json` are
**hand-authored** and never overwritten by regeneration. `.claude/skills/`
and `collapsed/` are both **mirrors** one level further out — a
self-vendored copy of `skills/<name>/` (via `tooling/vendor-skills.sh .`,
see [`docs/distribution.md`](docs/distribution.md) Channel B, so reviewing
this repo itself resolves lens content through the same `Skill` tool path
any repo that vendored the suite gets) and the generated 4-entrypoint
bundled form, respectively — never edit either directly, even though
`.claude/skills/` is what the `Skill` tool actually resolves and loads. If
you're asked to fix a lens: edit the *sources* (manifest and/or research)
for generated content, or `skills/<name>/examples.md`/`evals/eval.json`
directly for hand-authored content; then run `python -m tooling.cli
generate` and re-run `tooling/vendor-skills.sh .`, committing the refresh
(see
[`docs/runbooks/regenerating-skills.md`](docs/runbooks/regenerating-skills.md)).
