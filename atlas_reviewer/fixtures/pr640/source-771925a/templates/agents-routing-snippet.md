<!-- code-quality-atlas routing snippet. Copy the marked block below into your
repo's CLAUDE.md AND AGENTS.md (both — different agents read different files), or
run the /code-quality-atlas:atlas-init command to add and keep it current
automatically. The HTML-comment markers let the init command update the block
in place without disturbing the rest of the file. -->

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
