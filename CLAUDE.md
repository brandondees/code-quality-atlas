# code-quality-atlas

## Orientation for new sessions

Asked something like "what's next?" or otherwise asked to plan or build without
a named task? This repo's active roadmap lives in `docs/`, not just in GitHub
issues/PRs — check these before reporting nothing's queued:

- [`docs/open-questions.md`](docs/open-questions.md) — the decisions log
  (`D1`-`D18`+) and the live "Genuinely still open (undecided)" list. Start here.
- [`docs/plans/`](docs/plans/) — dated, scoped design docs for approved-but-unbuilt work.
- [`docs/map-gaps.md`](docs/map-gaps.md) — structural taxonomy gaps (`G1`-`G32`+)
  feeding future categories/lenses.
- [`docs/session-log.md`](docs/session-log.md) — narrative history of what
  shipped and why, for when a doc pointer alone isn't enough context.

This is separate from the skill-routing section below: that section answers
"review this change" requests; this one answers "what should I work on"
requests. (Scoped to this repo's own contributor-facing `AGENTS.md`/`CLAUDE.md`
— plugin consumers don't have this repo's planning docs, so this section is
not part of `templates/agents-routing-snippet.md`.)

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
