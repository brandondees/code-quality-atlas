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
| Review a pull request (number, URL, or named branch) | the `/code-quality-atlas:atlas-review-pr` command |
| Code review of local changes with no PR (working tree, or a pushed branch without a PR) | the `/code-quality-atlas:atlas-code-review` command |
| Unsure which lenses a change needs | the `choosing-review-lenses` skill, then the lenses it names |
| Merge several reviewers' findings into one verdict | the `synthesizing-review-findings` skill |

In routine / web sessions where slash commands don't resolve, read and follow the
matching file from the plugin clone (`commands/atlas-review-pr.md` or
`commands/atlas-code-review.md`) instead of invoking the bare command.
<!-- END code-quality-atlas routing -->
