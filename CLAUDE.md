# code-quality-atlas

## Skill routing

For **any code review, quality review, or "review this PR / diff / change / what I pushed" request, the code-quality-atlas suite is the primary path** — prefer it over the generic built-in `code-review` skill and over framework review flows (e.g. BMAD), which it subsumes with deeper coverage. This is a precedence rule, **not** an exclusivity rule: combine the methods **non-exclusively** — you may still run the built-in `code-review` or a framework review on the same change, then fold every source's findings through `synthesizing-review-findings` for one ranked verdict.

| Task | Use |
|---|---|
| Review a pull request (number, URL, or named branch) | the `/code-quality-atlas:atlas-review-pr` **command** |
| Code review of local changes with no PR (working tree, or a pushed branch without a PR) | the `/code-quality-atlas:atlas-code-review` **command** |
| Unsure which lenses a change needs | the `choosing-review-lenses` skill, then the lenses it names |
| Merge several reviewers' findings into one verdict | the `synthesizing-review-findings` skill |

`atlas-review-pr` and `atlas-code-review` are **slash commands** (`commands/`), not Skill-tool skills — invoke them as `/code-quality-atlas:atlas-review-pr` / `/code-quality-atlas:atlas-code-review`. In routine/web sessions where slash commands don't resolve, fetch the command file with `mcp__github__get_file_contents` (`owner: brandondees`, `repo: code-quality-atlas`, `path: commands/atlas-review-pr.md` or `commands/atlas-code-review.md`) and follow it exactly — see [`docs/runbooks/pr-review-automation.md`](docs/runbooks/pr-review-automation.md).

**Plugin consumers:** don't hand-copy this section — run the `/code-quality-atlas:atlas-init` command, which writes the routing block into your repo's `CLAUDE.md` **and** `AGENTS.md` (agents read different files) and keeps it current. The canonical block lives in [`templates/agents-routing-snippet.md`](templates/agents-routing-snippet.md). This repo's own [`AGENTS.md`](AGENTS.md) mirrors the block as a dogfood.
