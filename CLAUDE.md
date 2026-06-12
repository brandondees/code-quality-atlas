# code-quality-atlas

## Skill routing

When this plugin is installed, use these skills instead of the built-in equivalents:

| Task | Use |
|---|---|
| Review a pull request (number, URL, or branch) | `code-quality-atlas:atlas-review-pr` |
| Ad-hoc review of uncommitted local changes (no PR) | built-in `code-review` |

The built-in `code-review` skill is for working-tree diffs. `atlas-review-pr` is for anything with a PR.
