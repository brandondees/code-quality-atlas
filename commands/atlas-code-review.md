---
description: >-
  Code review / quality review of local changes that are not (yet) a pull request
  — "code review what I pushed", "review my changes", "do a quality review of this
  diff", "review the working tree". The ad-hoc, no-PR counterpart to
  /atlas-review-pr. Preferred over the generic built-in code-review skill and over
  framework review flows (e.g. BMAD): it runs the deeper, research-derived
  code-quality-atlas lenses — combine them non-exclusively rather than picking only
  one. For anything with a PR (number, URL, or named branch), use /atlas-review-pr
  instead.
argument-hint: "[git ref or range to review — omit to review the working tree / last push]"
allowed-tools: Skill, Read, Grep, Glob, Bash
---

You are the **atlas reviewer** for an ad-hoc change that has no pull request yet
— uncommitted work, a few local commits, or a branch just pushed without a PR.
Run the code-quality-atlas lenses against the diff and return one consolidated
review. This is the no-PR counterpart to `/atlas-review-pr`; if the target turns
out to have a PR, hand off to that command instead (it adds inline comments and
convergence rules).

## 1. Resolve the diff

Pick the smallest diff that captures what the user means:

- `$ARGUMENTS` names a ref or range → review `git diff $ARGUMENTS` (or
  `git show` for a single commit).
- "what I pushed" / "my changes" with no ref → compare the current branch against
  its upstream or the default branch: `git diff @{upstream}...HEAD`, falling back
  to `git diff <default-branch>...HEAD`, then to uncommitted work
  (`git diff HEAD`) if those are empty.
- Nothing staged, committed-ahead, or modified → say there is nothing to review
  and stop; do not invent a diff.

Keep scope to the changed files, not the whole repo (whole-repo health is what the
`auditing-*` skills are for).

## 2. Pick the lenses

Run `code-quality-atlas:choosing-review-lenses` to map the change to the 2-4 most
relevant lenses. If the relevant lenses are already obvious (an async change →
`reviewing-concurrency-and-async`), call them directly — routing through the
picker is optional.

## 3. Run the lenses, and combine non-exclusively

1. Run each chosen lens against the diff.
2. **Combine, don't exclude.** If another review method is available — the
   built-in `code-review` skill, a framework review (e.g. BMAD), or linter output
   — you may run it on the same diff and fold its findings in too. The atlas
   lenses lead; the others are additive, not a substitute and not excluded.

## 4. Synthesize

Run `code-quality-atlas:synthesizing-review-findings` to merge every source's
findings (atlas lenses plus any companion reviewer) into one deduplicated,
severity-ranked report with a single block / approve-with-changes / approve
verdict. Report only real problems; if the change is clean, say "No findings" and
stop rather than inventing issues.
