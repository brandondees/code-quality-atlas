# code-quality-atlas

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
