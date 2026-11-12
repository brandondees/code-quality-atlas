# Full-PR-context review rounds

**Status:** implemented with D52 (2026-11-12). Offline only. No live model,
Sprite or GitHub call was made.

Each agentic round reviews the current pull request in full. A prior
round is input to verify. It is not a scope limit, and a new head does
not drop the earlier round's findings.

## What each round gets

The first user turn is, in order:

1. The review target the controller names: repository, pull request
   number, and the current head SHA.
2. Fenced untrusted blocks. Prior atlas rounds for this pull request,
   when a round log is passed. Then the caller context. The PR
   description, comments and review threads are
   `conversation.review_context`: the same `Conversation` the one-shot
   path already builds, as one `pull-request` block, plus every
   omission that build recorded. The caller passes both into
   `review_lens`.
3. The current diff's file list, every changed file, highest risk
   first, with add and delete counts. No diff text. The lens reads the
   diff and the rest of the repository through the existing read-only
   tools (`diff_file`, `read_file`, `grep`, `list_files`).

The changed-file list is built from the current diff only. A prior
finding does not remove a file from it.

## Untrusted data

PR conversation text and prior findings are fenced with the per-review
nonce (`prompt.fence`). Prior finding lines are also quoted with
`quote_untrusted`, so a finding cannot open a line that reads as a
controller instruction. The controller writes the round record from
verified findings after scrubbing. It does not store the model's raw
reply as the next round's instructions.

## Where state lives

`rounds.RoundLog` is an append-only JSONL file, mode 0600, next to the
attestation ledger. A record is keyed by repository and pull request
number, and it carries the head SHA it was recorded at. The
attestation ledger stays keyed by head SHA, lens and body digest, so a
new head still runs the lens. The round log is what carries the
earlier findings across that boundary.

A superseded head stays in the log. Its block says it was recorded at
that SHA and is not this review's scope. The current round still lists
every file in the current diff.

A record that would exceed 8,192 characters stores no finding text and
names how many lines were left out. A line that does not parse is
counted. Prior blocks are kept whole, newest first, inside a
16,384-character budget. A record that does not fit is left out whole.
Every one of those gaps is an `Omission`.

## Approval

`AgenticReview.coverage_complete` is false when `context_omissions` is
non-empty, the same rule as an unread changed file (D36, D42). The
status line carries `context_omissions` as a count. The draft lists
each omission's source, limit and detail. The review event cannot be
`APPROVE` while that count is non-zero. A round with no omissions, a
clean lens and every changed file read can still approve.

## #646 and the webhook stack

#646 fans a review out across the selected lenses. Each lens's first
turn is this same full-PR turn: the conversation, the prior rounds and
every changed file. Fan-out does not assign a lens a slice of the diff.
This branch does not implement that fan-out. `review_lens` is still one
lens.

#639 queues one review per commit and #640 posts one comment. A new
commit is a new head SHA. The queue is not this log. This log is the
coordinator's memory of what it already reported on the pull request,
so the review of the new head still sees those findings. Neither
webhook PR is merged here, and this change does not post to GitHub.
