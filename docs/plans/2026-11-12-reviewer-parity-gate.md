# Reviewer parity gate — when a draft may be submitted as APPROVE

**Status: decided for the submission rule; every criterion is unmet in the code on main at the time of writing (2026-11-12).**
Nothing here was run live. No model call, no GitHub write, and no Phoenix
or Fly resource was created. The comparison the rule uses is the Claude
Code routine in [`commands/atlas-review-pr.md`](../../commands/atlas-review-pr.md).
Scoring shape (issue hit, not text overlap) is the one already accepted in
[`../agentic-reviewer.md`](../agentic-reviewer.md). Hosting for the traces
that feed the score is D45 in [`../open-questions.md`](../open-questions.md).

## The rule

The service does not post reviews. A later poster may submit a GitHub
review event of `APPROVE` for a head SHA only when an offline
`python -m atlas_reviewer eval --fixtures <dir> --head <sha> --gate`
exits 0. The calibration set is the checked-in rows under
`atlas_reviewer/fixtures/eval-references/`. The directory must contain a
passing pair for every one of those rows, matched on repo, pull request,
round, and `reviewed_commit`. One passing pair must be for the head
being approved (`input.head_sha` or `input.reviewed_commit`), and one
passing pair must record `metadata.over_context_window` (a diff larger
than one model context window). A directory that holds only the pair for
that head does not open the gate. A new pull request has no protocol row
of its own, so the gate certifies the whole calibration set plus that
head's pair.

D36 still decides the draft's `review_event` line. That line is what a
person reads. It is not permission to post `APPROVE`.

`REQUEST_CHANGES` and `COMMENT` are outside this rule.

## Criteria

| Criterion | Today | Gate |
|---|---|---|
| Full repo access | Unmet | A reference finding whose path is outside the diff was read at head |
| Full diff, any size, no silent partial coverage | Unmet | `coverage_complete` is true and `unreviewed_files` is 0, including a diff larger than one context window |
| Per-lens fan-out, synthesis, verification | Unmet | Every lens the reference finding names was run, and the score uses only the candidate's findings |
| Recall and precision against protocol reviews | Unmet | No missed Major+ finding, no unmatched Major+ candidate finding, same verdict |

Major+ is `blocker` and `major`. A Minor or Nit that the reference has and
the candidate lacks does not fail the gate. An unmatched candidate finding
at Minor or Nit does not fail it either. Both are still counted in the
score JSON.

The reference set is the Claude Code protocol rounds on PRs #602–#637,
stored as Phoenix dataset rows in
[`atlas_reviewer/fixtures/eval-references/`](../../atlas_reviewer/fixtures/eval-references/).
Each row is `input` (repo, PR, `head_sha`, `reviewed_commit`, round),
`output` (verdict and findings), and `metadata`. `head_sha` is the pull's
head at fetch time. `reviewed_commit` is the commit on the GitHub review,
which is the commit that round judged. That is the example shape Phoenix
datasets use (`input`, `output`, `metadata`). This repo does not upload the rows. Where a PR in that range has no
protocol round, the fixture directory has no file for it, and the gap is
listed in that directory's `README.md`.

### 1. Full repo access

The routine's tool list is `Read`, `Grep`, `Glob`, and
`mcp__github__get_file_contents` (`commands/atlas-review-pr.md` frontmatter).
Step 4 scopes the judgment to the diff and then allows a whole-tree search
for the exact construct behind a confirmed defect.

The agentic bridge can read a path that is not in the diff.
`bridge._plan` builds `git cat-file blob <rev>:<path>` for `read_file`,
`git ls-tree` for `list_files`, and `git grep` for `grep`, at the staged
revision the controller fixed (`BASE`, `HEAD`, or `DEFAULT` when a third
tree was staged). The staged tree is the tarball, not the diff.
`bridge_args.MAX_READ_LINES` is 400, and `bridge.DEFAULT_LIMITS` gives
`read_file` 32 KiB, 10 seconds, and those 400 lines.
`bridge.SessionLimits` stops the session at 64 calls or 1 MiB of shown
output: `Bridge.call` returns `OVER_SESSION_LIMIT` and does not run the
command once either bound is spent. `source_archive.measure` refuses an
archive past 256 MiB or 50,000 members before a runner exists. D39 records
that fetching the default-branch tarball is not built, and that GitHub
tarballs apply `export-ignore` and `export-subst`.

The one-shot path never opens that bridge. `controller._fit` calls
`diffs.fit_diff` and the model sees the packed diff parts.

**Gap.** A lens is not required to open a file outside the diff, a read
past the session budget does not run, and there is no default-branch
snapshot. A file the tarball omitted cannot be read.

**Measure.** The candidate records `changed_files` and
`outside_diff_reads`. For every reference finding whose path is not in
`changed_files`, the gate fails unless that path is in
`outside_diff_reads`. `eval_harness.gate_failures` applies that check.

### 2. Full diff, any size, without a silent partial

The routine posts from the diff it fetched (`get_diff` in step 4). This
plan treats "any size" as: a diff that does not fit in one model context
window still has every changed file's diff read in full, and a file that
was not read cannot be approved.

One-shot: `diffs.fit_diff` shrinks the part until the largest prompt fits
the token bound, and `diffs.select_diff` leaves files that do not fit in
`unseen`. `controller._coverage_lines` says `PARTIAL` when files were cut
or unseen. `verdict.decide` turns a proposed `APPROVE` into `COMMENT` when
`FileCoverage` is incomplete (`controller._file_coverage`). The omission is
named. It is not silent. The diff is still truncated, and a diff that
cannot be packed is not reviewed in full.

Agentic: `bridge._plan` pages `diff_file` with `tail -c` from the requested
offset, capped at 32 KiB. `lens_loop._DiffPages.note` accepts a file only
when a `diff_file` chain starts at offset 0 and follows each truncated
page's `next_offset` to a page that was not cut. `lens_loop._final` adds
`Cause.FILES_UNREAD` when any changed file is outside that chain.
`coordinator.AgenticReview.event` returns `COMMENT` instead of `APPROVE`
when `coverage_complete` is false, which includes unread paths and a
missing changed-file count. A diff larger than
`SessionLimits.max_output_bytes` (1 MiB) cannot finish that chain:
`Bridge.call` refuses the next call with `OVER_SESSION_LIMIT`.
`lens_loop.run_attempt` keeps every tool result in `messages` and sends
the whole list on the next turn. There is no compaction step. D43 records
the owner's report that the input cap, on the #631 slope, is reached at
about a 135 KB diff read in full. This plan does not remeasure that slope.

**Gap.** Partial coverage cannot approve, and the unread files are named.
A diff past the session budget, or past the context window the history
occupies, still cannot be read in full. That is the unmet half of "any
size".

**Measure.** The candidate records `coverage_complete` and
`unreviewed_files`. The gate requires `true` and `0`. A passing run on a
fixture whose diff is larger than the model's context window is part of
the same requirement; no such candidate is recorded yet, so the gate stays
red.

### 3. Per-lens fan-out, synthesis, and verification

The routine's step 4 runs each selected lens against the diff, then step 4
item 8 runs `synthesizing-review-findings` to merge, rank, and set one
verdict. The command does not require a separate subagent process. The
capability this criterion names is the one the agentic plan describes: one
tool loop per selected lens, then the controller merges and checks.

`coordinator.review_lens` takes one lens name. Each of its three
`synthesize` calls passes a one-element list. `coordinator.synthesize`
can rank a sequence of `LensResult`s, and nothing in the package calls it
with more than one lens outside tests that also pass one.
`coordinator.mint` drops an attempt that is not attested.
`coordinator.decide` sets the verdict from verified, verdict-setting
findings only. `lens_loop._final` calls `quotes.check_all`, and a finding
that fails the quote check is stored unverified. `lens_loop.run_attempt`
checks `check_delivery` before the first model call and returns
`NOT_DELIVERED` without a call when the body did not arrive whole.
Pool size stays 1 (D40).

**Gap.** One lens runs. The other lenses the routine would have selected
do not. There is no cross-lens merge of several attested replies. Quote
verification and the mechanical verdict exist for the single lens that
did run.

**Measure.** Every lens name on a reference finding must appear in the
candidate's `lenses_run`. The score is computed from the candidate
findings the caller recorded, which are the verified findings the
coordinator would have minted. A candidate that omits `lenses_run` fails
the gate. Each reference row records `metadata.run`: `lens-fan-out` when
the coverage section names lenses it ran, loaded, or re-ran;
`coordinator-verified` when the round says that (fan-out did not finish);
`unrecorded` when the body says neither. A coordinator-verified row is
flagged and does not clear this criterion, so it cannot by itself make
`--gate` exit 0. Pull 637 has no protocol review in the 2026-11-12 fetch,
and pull 636's fetch has rounds 1 and 2 only, so the cited
coordinator-verified rounds (637 round 2, 636 round 4) are not rows in
this set.

### 4. Recall and precision against the protocol reviews

The reference reviews are the rounds whose body starts with `## Round N`
and carries `<!-- atlas-review round:N ... -->`, posted on PRs #602–#637.
Inline comments whose first line is `**Severity · lens**` are the
findings. `eval_harness.protocol_review` reads that shape, skips a
CodeRabbit comment (`coderabbit-ai-generated`), and redacts the summary.
The match key in `eval_harness.score` is severity, path, and an
overlapping line span. A finding with no line matches only a finding of
the same severity and path that also has no line. Each candidate finding
is used once.

**Gap.** No candidate review of those PRs is stored, so nothing is scored
and `--gate` exits 1. The scorer itself is covered by the hand-built
fixture under `atlas_reviewer/fixtures/eval-score/`.

**Measure.** `missed_major_or_above` is 0, `false_positives_major_or_above`
is 0, and `verdict_agrees` is true, on every scored pair. The reference
is one reviewer's report. A real defect that the protocol round did not
write down counts as an unmatched Major+ finding and fails the gate.
That is the bar this plan sets. Loosening it is a new decision.

Verdict strings are the GitHub events `APPROVE`, `COMMENT`, and
`REQUEST_CHANGES`. The review's GitHub state wins: `APPROVED` is
`APPROVE` and `CHANGES_REQUESTED` is `REQUEST_CHANGES`. A `COMMENTED`
review uses the heading. A heading that contains `APPROVE` is `APPROVE`.
A heading that contains `REQUEST_CHANGES` or "request changes" is
`REQUEST_CHANGES`. The clean-round heading "no new findings at or above
this round's floor" is `APPROVE`. Every other heading is `COMMENT`,
including "Minor findings, not blocking merge".

## What is still Brandon's

- Whether an unmatched Major+ finding should fail the gate when he
  believes the protocol round missed a real defect. This plan counts it
  as a failure.
- The numeric Fly size in D45 is a published price, not a measured
  Phoenix resident set. He picks the Machine size when he provisions it.
