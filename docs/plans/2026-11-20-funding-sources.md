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
other. The per-review ceiling and the per-repo daily budget (D81) still
bound spend, and spend from a subscription source counts toward both.
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
  OpenRouter key. The registry stores the name, never the key. A name
  beginning with `ATLAS_TENANT` is refused. Two sources cannot share a
  name or a key variable.
- `providers` — the `provider.only` list for this source.
- `require_zdr` — whether this source sends `zdr: true`.
- `model_filter` — which model ids this source may serve (`*`,
  `anthropic/*`, or one model id).
- `key_ceiling_usd` — the preflight ceiling for this key, the same role
  as `ATLAS_KEY_CEILING_USD` on today's single key. The app does not
  store OpenRouter's own monthly cap; it reads `limit_remaining`.
- `byok` — whether this source is a subscription BYOK key. The pilot
  source is not.

A present value that does not parse, or that names a missing key
variable, stops the process at boot. An empty or absent variable is
unset, not an error.

The operator's order, once the keys exist, is the subscription whose
billing cycle ends first, then the other subscription, then `pilot`.
The cycle dates live in OpenRouter and the Console, not in this
setting: Brandon puts the sooner subscription first in the array.

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
The source name is passed as `ATLAS_FUNDING_SOURCE`. The child's
allowlist does not gain the subscription key variables, so a child
cannot see a key it was not given.

The priced D92 minimum — remaining credit against the smaller of one
call's largest reservation and the per-lens budget — still runs in the
child, because it needs the catalog the child already loads. A source
that passes the key probe and then fails that minimum is a key
refusal, and the advance rule below applies. The parent does not fetch
the catalog a second time.

A tenant run does not probe the list and does not receive
`ATLAS_FUNDING_SOURCE`. A tenant refusal does not advance.

## 4. One review, one source

The child keeps the key it was given for the whole review. A refusal
does not swap keys inside the process: the prompt cache is per
upstream account, and a mid-review swap would also change the
retention policy of a review that had already sent part of the diff.

When the child finishes with a key-refusal cause, the worker marks
that source unavailable, records the attempt's settled bill (D93: a
refused call is $0, and calls that were served before the refusal are
billed to that source), and puts the same head back on the queue once.
It does not post. The next claim probes again and takes the next
source that still has credit. Only when no source remains does the
worker post the D92 error, with the last refusal's cause.

Unavailable is process memory plus the next probe. A restart forgets
the memory and the probe decides again. A source whose OpenRouter key
still shows credit, but which Anthropic refused for a low balance, stays
unavailable for the life of the process so the next claim does not
pick it again.

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
| F3 | A key refusal re-queues the same head once on the next source and suppresses the intermediate error post. The BYOK credit-balance 400 is a refusal. |
| F4 | Ledger lines carry `source`, and `funding-spend` reports the day's spend by source. |
