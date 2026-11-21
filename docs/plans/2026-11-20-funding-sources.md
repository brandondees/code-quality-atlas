# Plan: prioritized funding sources for the reviewer service

**Status: accepted 2026-11-20 — D94 records the decision; the F1–F4
stack implements it. Operator setup and the live check are not part of
this stack.** Brandon decided the order, the retention rule, and the
allowance shape on 2026-11-20. The design research is the same day's
funding-sources report, re-checked against `main` at `bf208f04`. Nothing
here was run live: no model call, no GitHub write, no Fly or secret
change.

The service spends the operator's model budget from an ordered list of
OpenRouter keys. Each Claude subscription's Anthropic key is attached,
by Brandon, through OpenRouter BYOK to its own OpenRouter key. A review
is pinned to one source when it is claimed. The service moves to the
next source only after a key refusal, and it re-queues the same head
there. Installation BYOK never sees the list.

## 1. What stays as it is

The child already reads one key and one route from its environment, and
the counts-BYOK settle path already exists (D41). One child process
still receives exactly one model credential (`service_run._CHILD_ALLOWED`).
A tenant-path child still receives the installation's own credentials
and still drops the operator key (D89). Neither path falls back to the
other. The per-repo daily budget (D81) still bounds spend, and every
attempt's settled bill counts toward it. The per-review ceiling is the
one child's cap for that attempt.
A 401 or a 402 is still a key refusal (D92). A 403 stays a per-call
error. A 429 with `retry-after` stays a transient retry (D49). A
non-200 answer still settles at $0, and a hold stays a hold (D93).

Unset `ATLAS_FUNDING_SOURCES` is that behavior exactly: one implicit
source equal to the environment the child already reads, no probe of a
second key, and no source name on the cost line.

## 2. A source

`ATLAS_FUNDING_SOURCES` is a JSON array, in spend order. Each element
names one source:

- `name` — a short token (`subs-a`, `pilot`). It is what the cost line,
  the progress record, and the daily ledger record.
- `key_env` — the name of the environment variable that holds the
  OpenRouter key. The registry stores the name, never the key. The
  name is `ATLAS_OPENROUTER_API_KEY` or a longer name under
  `ATLAS_FUNDING_` that is not the setting itself and not
  `ATLAS_FUNDING_SOURCE` or `ATLAS_FUNDING_BYOK`. A tenant variable, a
  GitHub variable, and the sprites token fall outside that shape and
  are refused, so a typo cannot send one of those secrets to
  OpenRouter as the bearer token. Two sources cannot share a name or
  a key variable.
- `providers` — the `provider.only` list for this source.
- `require_zdr` — whether this source sends `zdr: true`.
- `model_filter` — which model ids this source may serve. `*` matches
  every id. A vendor prefix `anthropic/*` matches an id that starts
  with `anthropic/`, including a dated revision such as
  `anthropic/claude-sonnet-5.5-20260928`. The slash is part of the
  match, so `anthropic-evil/x` does not match. Anything else is one
  exact id, so the undated id and its dated revision do not match
  each other.
- `key_ceiling_usd` — the preflight ceiling for this key, the same role
  as `ATLAS_KEY_CEILING_USD` on today's single key, with one extra
  bound the single-key parser does not have: at most 10000. A larger
  figure would make the claim-time over-ceiling check fail to skip
  any key. The app does not store OpenRouter's own monthly cap; it
  reads `limit_remaining`.
- `byok` — whether this source is a subscription BYOK key. The pilot
  source is not.

A present value that does not parse, or that names a missing key
variable, stops the process at boot. The boot error names the variable
and the defect. It does not quote the document, so a key pasted into
the setting does not appear in the message. An empty or absent
variable is unset, not an error.

The operator's order, once the keys exist, is the subscription whose
billing cycle ends first, then the other subscription, then `pilot`.
The cycle dates live in OpenRouter and the Console, not in this
setting: Brandon puts the sooner subscription first in the array.
The array is static, so when the sooner cycle flips he reorders the
Fly secret and restarts the process. A per-source cycle day that
would sort the list itself is deferred.

A subscription source's route is `only: ["anthropic"]`, `require_zdr`
false, `byok` true, and a model filter of `anthropic/*`. The pilot
source keeps today's route: `google-vertex/global`, ZDR required, not
BYOK. No source is given a false ZDR declaration.

## 3. Claim-time selection

At claim time, on the operator path only, the worker probes
`GET /api/v1/key` for each source in order. It takes the first source
whose limit is within that source's ceiling, whose `limit_remaining`
is above zero, whose model filter matches the configured model, and
which has not been marked unavailable. The chosen key is copied into
the child's existing `ATLAS_OPENROUTER_API_KEY`, and the source's
providers, ZDR flag, and ceiling replace `ATLAS_PROVIDERS`,
`ATLAS_REQUIRE_ZDR`, and `ATLAS_KEY_CEILING_USD` for that child only.
The source name is passed as `ATLAS_FUNDING_SOURCE`, and the source's
`byok` flag is passed as `ATLAS_FUNDING_BYOK`. The child's allowlist
gains those two names and does not gain the subscription key
variables, so a child cannot see a key it was not given. The
credit-low HTTP 400 rule in §4 is classified in the child, where the
400 arrives, so the child has to be told the flag. `require_zdr` is
not a proxy for it.

Selection and the unavailable mark share one lock, and marking a
source that is already unavailable changes nothing. The key probe
runs outside that lock, so one claim's request does not stall another
claim or a refusal mark. The selector's probe-lock test pins both.

The priced D92 minimum — remaining credit against the smaller of one
call's largest reservation and the per-lens budget — still runs in the
child, because it needs the catalog the child already loads. A source
that passes the key probe and then fails that minimum stops the review
with the out-of-credit cause (`KEY_OUT_OF_CREDIT`), the same cause an
HTTP 402 reports. The advance rule below treats that cause as a key
refusal, so the minimum advances. An HTTP 401 reports
`KEY_AUTH_REFUSED` and advances the same way. The parent does not
fetch the catalog a second time.

A tenant run does not probe the list and does not receive
`ATLAS_FUNDING_SOURCE`. A tenant refusal does not advance.

## 4. One review, one source

The child keeps the key it was given for the whole review. A refusal
does not swap keys inside the process. Each pinned endpoint keeps its
own prompt cache (D63), and a mid-review swap would also change the
retention policy of a review that had already sent part of the diff.
Whether two OpenRouter keys also split that cache by account is not
something this repo has recorded.

When the child finishes with a key-refusal cause, the worker marks
that source unavailable, records the attempt's settled bill (D93: a
refused call is $0, and calls that were served before the refusal are
billed to that source), drops that attempt's run directory, and puts
the same head back on the queue. It does not post. The queue answers
`DUPLICATE` for a head it already holds or has finished, and that
answer is keyed on `(repo, pr_number, head_sha)`. The re-queue is
`release_claim`, which puts the running job back to queued. It does
not enqueue the head a second time, which the queue would refuse.
Each source is tried at most once while the worker process remembers
the refusal, so a list of three sources can advance twice. The next
claim takes the next source that still has credit. Exhaustion is
decided in two places. A refusal whose source is the last eligible
one ends the advance: the worker posts and does not release the claim
again. A claim that finds no eligible source is exhausted at claim
time and does not release the claim either. When every source whose model filter matches is already marked
unavailable and nothing is remembered for that head, the worker posts
the selector's notice: `no funding source is available: `, then each
matching source as `name: cause`, joined by `; `, in spend order. The
cause is the recorded refusal, or `unavailable` when the mark stored
none. A source the filter excludes is left out. The notice carries no
key. The post is the selector's current state, not a refusal of
this head. The selector keeps each refused source's cause. The worker
also records the first refused source's cause for the head that
advanced, keyed by repository, pull request, and head, and clears the
record when the job settles. When a later claim of that same head
ends without a review — the next probe fails, the key is blank, the
key is over its ceiling, the daily budget skips the claim, or every
source is already unavailable — the worker posts the cause recorded
for that head, so the earlier refusal is not left unposted. A
different head does not receive that head's cause. A probe that
fails, a blank key, or a key over its ceiling does not mark the
source unavailable. A claim that ends that way with nothing
remembered for the head fails and posts nothing: the source can be
tried again, and a post would say the sources are exhausted when they
are not. Its telemetry names the skipped sources. A daily-budget stop
with nothing remembered posts nothing for the same reason. F3's test
that every source refused posts the error, its test that a later
probe failure still posts that head's cause, its test that a later
head's first claim after exhaustion posts the selector's state, and
its test that another repository's budget stop or probe skip posts
nothing, pin those endings. The test that a transient probe posts
nothing is #810's
`test_a_probe_failure_fails_the_review_and_names_each_source`, not
F3's. Each advance records one `refusal
advance` telemetry event naming the source and the cause and carrying
no key. Unsetting `ATLAS_FUNDING_SOURCES` and restarting is the
rollback to today's single key.

The memory is the worker process. It survives the re-queue, because
the next claim is the same process, and a restart forgets it. The
probe then decides again. A source whose OpenRouter key still shows
credit, but which Anthropic refused for a low balance, stays
unavailable until the process restarts, so the next claim does not
pick it again. Restart is the recovery, not a timer: a topped-up key
is probed again on the next start, and a mark does not expire while
the process runs. Revisit that when an operator needs a marked source
to return without a restart, for example after a monthly credit
renewal that should not wait for a deploy. The outcome of that
revisit is an update note on D94.

The re-queued attempt is a new child with its own per-review ceiling.
It does not inherit the earlier attempt's bill. That bill is already
on the daily ledger, and the next claim's preflight reads the ledger,
so the per-repo daily budget is what stops a repo after the sum of
the attempts crosses it. One head can pay one review ceiling for each
source that runs.

On a BYOK source only, an HTTP 400 whose body carries
`invalid_request_error` and the phrase "credit balance is too low"
is the same out-of-credit refusal. The match only ever stops spending.
On the pilot source the same body stays a per-call error, which is
what a 400 is today.

## 5. The ledger

Daily-ledger lines gain an optional `source` field. The reader that
sums the day already ignores fields other than `committed_usd`, so a
line written before this change still counts, and a line without
`source` is spend that was not attributed. `funding-spend` is a
read-only command that prints the day's settled spend grouped by
source. It does not call a model and it does not write the ledger.
The post sent when the list is exhausted names the first refused
source's D92 cause and does not name a key.

## 6. What this stack does not do

Brandon links each subscription to a Console organization, creates the
keys, attaches them as BYOK with no shared capacity, caps each
OpenRouter key, and sets the Fly secrets. That setup, and the one live
review that checks that the promotional balance actually moves, are
his. A native Anthropic Messages adapter is deferred unless that live
check shows OpenRouter BYOK does not draw the subscription credits. An
ordered list of an installation's own endpoints is deferred until
someone asks for it.

## 7. Slices

| Slice | What lands |
|---|---|
| F0 | This plan and D94. Docs only. |
| F1 | `funding.py` parses `ATLAS_FUNDING_SOURCES`, fails closed, and treats unset as no registry. |
| F2 | The worker selects a source at claim time, the child receives it through the existing variables, and the cost line and the progress record name it. A tenant run never sees it. |
| F3 | A key refusal (HTTP 401, HTTP 402, or the child's priced-minimum out-of-credit cause) marks that source unavailable, releases the claim so the same head is queued again, and suppresses the intermediate error post. Each source is tried at most once while the worker remembers. The D92 post waits until no source remains. The BYOK credit-balance 400 is a refusal only when the child was handed `ATLAS_FUNDING_BYOK=true`. |
| F4 | Ledger lines carry `source`, and `funding-spend` reports the day's spend by source. |
