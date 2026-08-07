# Examples — reviewing-outcome-instrumentation

Report each distinct issue as its own numbered finding, citing the claim it attaches to. Whether a stated outcome is *observable* — and whether the code that would observe it is in this diff — is an engineering fact and an ordinary defect; which outcome is worth pursuing is surfaced with evidence and routed to product with no engineering verdict. Refactors, fixes, bumps, and internal work owe no hypothesis. When the change makes no user or business claim, or its claim is already observable, the entire response is exactly "No findings".

## Contents

- [Bad → finding (an output described as an outcome)](#bad--finding-an-output-described-as-an-outcome)
- [Bad → finding (instrumentation deferred to a follow-up)](#bad--finding-instrumentation-deferred-to-a-follow-up)
- [Bad → finding (a win metric with no guardrails)](#bad--finding-a-win-metric-with-no-guardrails)
- [Good → finding (ops instrumentation is not outcome instrumentation)](#good--finding-ops-instrumentation-is-not-outcome-instrumentation)
- [Good → routed finding (the proxy that became the target)](#good--routed-finding-the-proxy-that-became-the-target)
- [Good → no finding (skipped — no user or business claim)](#good--no-finding-skipped--no-user-or-business-claim)

## Bad → finding (an output described as an outcome)

**Bad:** PR title *"Add bulk CSV export to the reports page."* Description: *"Users
have been asking for this. Adds a Download All button, streams up to 100k rows,
tested with 3 fixtures."*

**Finding (defect, Minor).** The description says what was built and nothing that
reality could contradict. "Users have been asking for this" is a *reason*, not an
outcome — a description made only of outputs cannot be wrong about anything, which
is exactly the problem.

The fix is small and specific, not a measurement programme: name what this is meant
to move ("reduce the ~40 support tickets/month asking us to run exports manually")
and say what would show it (`report_export_completed` with `row_count` and
`source: bulk`, plus the existing support-ticket tag). One event, one sentence.

Note what is *not* the finding: whether reducing support tickets is the right goal
is product's call and routes with no verdict. Whether the stated goal is
**observable at all** is engineering's, always — and that is what is missing here.

## Bad → finding (instrumentation deferred to a follow-up)

**Bad:** the PR states the outcome well — *"we expect the new onboarding checklist
to lift 7-day activation from 31% to ~40%"* — and adds: *"Analytics events will
land in a follow-up PR next sprint."*

**Finding (defect, Major).** This is the characteristic failure of the category, and
it is worse than having no hypothesis at all, because it looks handled. The feature
goes live, it demonstrably works, the follow-up is deprioritised precisely
*because* the feature already works, and in six months nobody can say whether
activation moved or what else changed that quarter.

The instrumentation belongs in this diff. It does not need to be much — the
checklist's `step_completed` and `checklist_finished` events with the user's cohort
— but it needs to exist before the change it measures does. A feature that ships
ahead of its measurement is permanently unmeasured, not measured later.

## Bad → finding (a win metric with no guardrails)

**Bad:** an experiment behind `flag: aggressive_prefetch` rolls out to 50%. The PR
names one metric: *"success = search-results page views up 5%."*

**Finding (defect, Minor).** An experiment that can only be evaluated on the metric
it was designed to move cannot detect the damage it does. Prefetching plausibly
moves page views *and* increases p95 latency, error rate, and mobile data use —
none of which this experiment would notice.

Declare guardrails before the rollout, not after someone notices: p95 latency,
error rate, and (given prefetch) bytes transferred. Kohavi's point is that
guardrails are chosen up front precisely because choosing them afterward, once you
know which way things moved, is not a check.

Two adjacent things worth checking in the same read, because the diff contains the
assignment code:

- **Exposure is logged where the user sees the variant**, not where the flag is
  read. A flag read at app boot buckets users who never reached the feature and
  dilutes the effect toward zero.
- **Assignment is stable per user across sessions.** A hash of the session id
  rather than the user id re-buckets people on every visit; the experiment then
  measures nothing and does so convincingly.

Both are code properties, checkable now, and each silently invalidates the result
months later.

## Good → finding (ops instrumentation is not outcome instrumentation)

**Input:** a new "share to team" feature ships with a request counter, a latency
histogram, a structured log line per share, and an alert on the error rate.

**Good output:**

```text
Minor — features/share.ts ships thorough operational instrumentation (counter,
latency histogram, error alert) and no outcome signal. Those tell us the feature
*runs*; none of them tells us anyone shared anything they wouldn't have otherwise,
which is what the PR claims ("cut cross-team copy-paste"). Both are needed and
neither substitutes. Suggest a `document_shared` event with recipient count and
source surface, so the claim has something to be checked against.
```

What makes this right: it names the distinction rather than accepting the ops
metrics as coverage. A change can be fully observable and completely unmeasured —
that state is common, and it is invisible unless someone asks the question this
lens asks. `reviewing-observability-and-operability` owns the first half and has
nothing to say about the second.

## Good → routed finding (the proxy that became the target)

**Input:** a PR autoplays the next video and states *"success = +12% session
length."*

**Good output:**

```text
[route: product] — features/autoplay.ts. The stated metric is session length, a
proxy for "people are getting value from watching." Autoplay moves the proxy
directly whether or not it moves what the proxy stood for: a session gets longer
when someone leaves the tab open as much as when they choose to keep watching.
Two readings, both consistent with a win, and the metric cannot distinguish them.

Not a verdict from this review. Surfacing it so product decides knowingly, and
noting a check that would: pair session length with a chosen-continuation signal
(explicit next-video clicks, or completion rate on autoplayed items).

If the mechanism itself is designed to be hard to stop — no visible way to disable
autoplay, a countdown that cannot be cancelled — that is reviewing-ethical-design's
finding on its own terms and keeps its own severity. Flagged for that lens; not
adjudicated here.
```

What makes this right: Goodhart is surfaced with both readings named, the decision
is routed, no engineering verdict is set, and the possible dark-pattern half is
handed to the lens that owns it instead of being folded in or dropped.

## Good → no finding (skipped — no user or business claim)

**Input:** a PR extracts a shared validation helper and updates 14 call sites. No
behavior change, no user-facing claim.

**Good:**

```text
reviewing-outcome-instrumentation: not applicable — internal refactor with no user
or business claim to observe.
```

Refactors, bug fixes, dependency bumps, build work, and internal tooling owe no
outcome hypothesis. Demanding one is this lens's own failure mode and is more
likely than the failure it guards against — a lens that asks every commit for a
metric gets muted, and then it is not there for the change that needed it.
