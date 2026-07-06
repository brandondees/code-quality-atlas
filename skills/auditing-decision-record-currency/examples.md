# Examples — auditing-decision-record-currency

This skill is repo-shaped: its input is a decision-record scan (an ADR/RFC
directory index). Report each distinct currency defect as its own numbered
finding. When the scan is healthy, the entire response is exactly this skill's
no-finding sentence given in the decision rule below — never a numbered list of
findings for a healthy scan.

**Decision rule (apply before flagging):** flag a record only for a concrete
currency signal the scan actually shows — a status-graph contradiction, a
revisit-trigger whose stated condition current repo signals suggest may now
hold, a technology now end-of-life with no revisit noted, or a record nothing
in the repo still implements. Cite only signals the scan contains: an empty
`revisit_trigger` column means there is NO recorded trigger — never invent a
scale figure, a team size, or an EOL date the scan does not show. Do not
re-judge whether the *original* adoption call was right (that's
`reviewing-decision-lifecycle`'s job, at authoring time, not this audit's) —
only whether time has invalidated an *existing* record. A plausibly-met
revisit-trigger or an EOL adoption is evidence to route to the decision's
owner, never a verdict that the record should be reversed. If every record's
status is internally consistent, every stated trigger's condition is
unmet, no adopted technology is EOL, and every record is still referenced,
report exactly "No findings: decision records are current".

## Bad → finding

**Input (decision-record scan; repo has 27 contributors per CODEOWNERS, no `redis` in current lockfile):**

```text
id      status     supersedes  technology   revisit_trigger                        last_touched  notes
ADR-3   accepted   -           MongoDB      -                                      3 years ago   "session store, subsystem: billing"
ADR-9   accepted   -           PostgreSQL   -                                      4 months ago  "session store, subsystem: billing"
ADR-12  accepted   -           -            "revisit if team > 20 engineers"       2 years ago   -
ADR-5   accepted   -           AngularJS    -                                      5 years ago   "EOL 2022, no successor recorded"
ADR-2   accepted   -           Redis        -                                      2 years ago   "adopted for caching layer"
ADR-7   accepted   -           Kafka        "revisit periodically"                 1 year ago    -
```

**Expected finding:**

1. **Status-graph contradiction:** ADR-3 (MongoDB) and ADR-9 (PostgreSQL) both remain `accepted` for the same subsystem (billing session store) with no `supersedes`/`superseded-by` link between them — one should be marked superseded, or the contradiction explained.
2. **Revisit-trigger plausibly met:** ADR-12's trigger ("team > 20 engineers") appears satisfied — CODEOWNERS lists 27 contributors — flag as revisit due; route to the decision's owner rather than reopening it here.
3. **Adopted technology past end-of-life:** ADR-5 adopted AngularJS, already noted EOL in 2022, with no revisit recorded since — flag for re-evaluation.
4. **Orphaned / reversed record:** ADR-2 adopted Redis for caching, but Redis no longer appears in the current lockfile — the decision was apparently reversed with no update to the record's status.
5. **No checkable revisit-trigger:** ADR-7's trigger ("revisit periodically") names no date or measurable condition — flag once that the record can't be swept for currency, not a defect in the original decision.

## Good → no finding

**Input (decision-record scan; repo has 6 contributors per CODEOWNERS):**

```text
id      status      supersedes  technology   revisit_trigger                     last_touched  notes
ADR-1   accepted    -           PostgreSQL   "revisit if write volume > 10k/s"   1 month ago   "current volume ~200/s, in dependency manifest"
ADR-4   superseded  ADR-1       -            -                                    1 month ago   "superseded-by: ADR-1"
ADR-6   accepted    -           Terraform    -                                    2 weeks ago   "still in infra/, active use"
```

**Expected finding:** None — no status-graph contradictions (ADR-4 correctly
marked superseded-by ADR-1), ADR-1's revisit-trigger condition is unmet
(current volume far below the stated threshold), no adopted technology is
EOL, and every record is still referenced by the repo. Report "No findings:
decision records are current". Do NOT flag a record merely for being old, or
for a revisit-trigger whose condition the scan shows is not yet met.
