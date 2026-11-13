# Webhook service mode — COMMENT-only reviews

**Status: implemented in this change, not deployed.** The receiver,
the COMMENT post, and the Fly service config are in the tree. This
repository does not create the Fly app, set a secret, or enable the
GitHub App webhook. Tests use fakes. No live GitHub, Fly, Sprite, or
model call was made for this change.

Decision: **D53** in [`../open-questions.md`](../open-questions.md).
The one-off path stays D37: [`../../atlas_reviewer/deploy-fly.md`](../../atlas_reviewer/deploy-fly.md)
and [`../../fly.toml`](../../fly.toml). The service runbook is
[`../../atlas_reviewer/deploy-service.md`](../../atlas_reviewer/deploy-service.md).

## What it does

GitHub App `pull_request` deliveries (`opened`, `synchronize`,
`ready_for_review`) hit `python -m atlas_reviewer.service`. The HMAC is
checked against `ATLAS_GITHUB_WEBHOOK_SECRET`. A draft is ignored. The
repository must be on `ATLAS_REVIEW_REPOS`, which defaults to
`brandondees/code-quality-atlas`. The dedupe key is repository, PR number,
and head SHA. A newer SHA for the same PR cancels the older review, and
the cancelled review is not posted.

The review is the existing `review` command, as a child process. That
child does not receive the webhook secret or the App private key. The
parent mints a read-only installation token and passes that instead. The
child does receive `ATLAS_OPENROUTER_API_KEY`, because it calls the model,
and `ATLAS_SPRITES_TOKEN`, because it creates and destroys the Sprite.
Neither of those is sent into the Sprite. The controller's own call and cost
caps are unchanged. Concurrency defaults to 1 and a value above 32 is
refused at startup, as a bad-configuration guard rather than a price cap.

A review that exits 0, 4, or 5 is posted as one pull-request review.
The create-review body is built in `comment_payload`, which has no event
argument and sends `COMMENT`. `comment_only` refuses `APPROVE` and
`REQUEST_CHANGES` before a request exists. The comment says the review is
advisory and not a substitute for the full Claude Code protocol review,
then lists lenses run, lenses not run, the controller's file-coverage
note, limit stops, and cost. The one-shot draft does not list every path
a model call saw; the files section is that coverage note, plus paths the
draft quotes as not reviewed in full.

A failed review posts nothing. The failure is a telemetry event. The
idempotency key `repo#pr#sha` is written only after GitHub accepts the
review, and a retry lists reviews and does not post when that marker is
already on one.

The posting token asks for `pull_requests: write` only. Any other
non-read grant is still refused. The read-only token the operator CLI
mints is unchanged.

## Deploy shape

A small always-on Machine on a second app, `atlas-reviewer-service`, in
org `personal`, region `iad`, `shared-cpu-1x` with 1024 MB.
`auto_stop_machines` is `off` and `auto_start_machines` is false.

GitHub requires a 2xx within 10 seconds and does not redeliver a timeout
on its own. Fly's configuration reference does not bound a stopped
Machine's start under that window, and it says auto-stop and auto-start
should be set together. The standing Machine is the shape that can answer
in time. Its compute price, from Fly's pricing page for `iad` on
2026-11-12, is the `shared-cpu-1x` with 1 GB row: $6.70 per 30 days. The
queue, the post ledger, and `service.jsonl` are on a 1 GB volume at
`/data` ($0.15 per month on that same page), so a restart keeps them.
The queue refuses a new job when 2,000 active jobs (`queued`, `running`, `post_pending`, `posting`) belong to other pull requests. A newer head of a pull request that already has an active job takes that slot. Replacing a job that is still `running` or `posting` can leave the count at 2,000 plus those superseded jobs, and that extra is at most the worker concurrency.
The dedupe list keeps every current head, so it can grow past 20,000 by
one key per pull request. A run directory is removed
when its job ends. A key is about 80 bytes, so 20,000 keys are about
1.6 MB, which fits the volume. The Machine's root disk does not keep
this state. The runbook records the citations.

## Open

A finished SHA stays a duplicate. A failed SHA can be queued again,
because GitHub does not redeliver a delivery that was already
acknowledged. A process restart requeues a job that was `running` when
the process stopped. A new commit is a new review.

The allowlist is enforced here, and the token is still one installation
id. A repository on another account needs a different installation, which
this process does not select.

The review that runs is the one-shot controller, not the per-lens agentic
loop. COMMENT-only stands until that path has full repository access, the
full diff, and per-lens fan-out.

## Overlap

PR #636 edits `atlas_reviewer/deploy-fly.md` and its test. This change
leaves that runbook alone and adds `deploy-service.md`. PR #637 edits the
agentic limits, `cli.py`, the README, and `docs/open-questions.md`. This
change does not edit `cli.py` or the agentic modules. It does edit the
README and adds D53 at the end of the decision list.
