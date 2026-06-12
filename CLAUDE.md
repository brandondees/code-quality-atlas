# code-quality-atlas

## Skill routing

When working in this repository, use these instead of the built-in equivalents. (Plugin consumers: copy the *Skill routing* section to your project's CLAUDE.md to apply this policy there — Claude Code reads CLAUDE.md from your working directory, not from plugin repos.)

| Task | Use |
|---|---|
| Review a pull request (number, URL, or branch) | the `/code-quality-atlas:atlas-review-pr` **command** |
| Ad-hoc review of uncommitted local changes (no PR) | built-in `code-review` |

`atlas-review-pr` is a **slash command** (`commands/atlas-review-pr.md`), not a Skill-tool skill — invoke it as `/code-quality-atlas:atlas-review-pr`. The built-in `code-review` skill is for working-tree diffs; the command is for anything with a PR. In routine/web sessions where slash commands don't resolve, read and follow `commands/atlas-review-pr.md` from the clone instead — see [`docs/runbooks/pr-review-automation.md`](docs/runbooks/pr-review-automation.md).
