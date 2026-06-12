# code-quality-atlas

## Skill routing

When working in this repository, use these skills instead of the built-in equivalents. (Plugin consumers: copy the *Skill routing* section to your project's CLAUDE.md to apply this policy there — Claude Code reads CLAUDE.md from your working directory, not from plugin repos.)

| Task | Use |
|---|---|
| Review a pull request (number, URL, or branch) | `code-quality-atlas:atlas-review-pr` |
| Ad-hoc review of uncommitted local changes (no PR) | built-in `code-review` |

The built-in `code-review` skill is for working-tree diffs. `atlas-review-pr` is for anything with a PR.
