# Examples — reviewing-pr-and-process-hygiene

This skill reviews the PR itself — its size, commits, description, and signals —
not just the code. Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code.

## Bad → finding

**Input (PR metadata):**

```text
Title: "updates"
Description: (empty)
Diff: +2,310 −840 across 47 files
  - adds the new invoice-export feature
  - reformats 19 unrelated files (prettier upgrade)
  - renames OrderSvc -> OrderService across the app
Commits: "wip", "more", "fix", "fix2", "address review"
Also in diff: console.log("HERE"), .env.staging with DB password
```

**Expected finding:**

1. **Oversized, mixed-purpose PR:** feature + mechanical reformat + rename in one
   2,310-LOC diff hides the logic change — split into three PRs (the mechanical
   ones merge fast and safely).
2. **Commit history is noise:** "wip"/"fix2" commits don't build a revertable,
   bisectable history — squash into logical commits with imperative, why-bearing
   messages linked to the ticket.
3. **Empty description on a risky change:** no blast radius, no rollback plan, no
   test notes — reviewers are flying blind.
4. **Debug leftover:** `console.log("HERE")`.
5. **Committed secret:** `.env.staging` with a database password — remove from
   history and rotate the credential now (merging doesn't fix an already-pushed
   secret).

## Bad → finding

**Input (PR metadata):**

```text
Title: "feat: cleaner customer endpoints"
Commits: feat: cleaner customer endpoints
Diff: removes GET /v1/customers/{id}/orders (replaced by /v1/orders?customer=)
Changelog: not updated. Docs: still reference the removed route.
```

**Expected finding:**

1. **Unsignaled breaking change:** removing a public route is breaking but the
   commit is typed plain `feat` — mark it (`feat!:` / `BREAKING CHANGE:` footer)
   with a migration note, since the type drives versioning and changelogs.
2. **Docs/changelog out of sync with the surface:** the removed endpoint is still
   documented and the changelog has no entry — update both in this same PR.

## Good → no finding

**Input (PR metadata):**

```text
Title: "fix: clamp page_size to prevent unbounded export queries (#812)"
Description: cause, fix, blast radius (export API only), tested: unit + manual,
rollback: revert cleanly.
Diff: +38 −6 in 3 files (fix + regression test + changelog entry)
Commits: one, imperative, body explains the why, links #812.
```

**Expected finding:** None — small, single-purpose, typed correctly, regression
test and changelog in the same diff, risk and rollback stated. Report
"No findings". Do NOT demand ceremony proportionate to a big change (ADRs, feature
flags, multi-reviewer sign-off) for a small well-described fix — hygiene findings
must scale with the PR's actual risk.

## Good → no finding (large but genuinely single-purpose)

**Input (PR metadata):**

```text
Title: "feat!: migrate auth to OAuth2 (BREAKING CHANGE)"
Diff: +1,800 −420, single commit
Description: rationale, blast radius (all auth endpoints), rollback plan
  (revert + flag), feature flag AUTH_OAUTH2_ENABLED, migration guide
  included as a new doc, ADR-0032 attached explaining the trade-off.
CODEOWNERS: auth/* owned by @platform-team — requested as reviewer.
Changelog: entry present, marked BREAKING. All tests updated. CI: green.
```

**Expected finding:** None, despite exceeding the ~400 net LOC guideline. The
size is justified by being one indivisible auth migration rather than several
unrelated concerns bundled together, and every other hygiene signal is present
and correct: breaking-change marker, ADR, rollback plan, correct CODEOWNERS
routing, changelog, migration docs. Report "No findings". Do NOT apply the LOC
threshold as a hard block — it is a heuristic for spotting *mixed*-purpose
diffs, not a ceiling on a PR that is large because the change genuinely is.

## Not applicable → outside this lens's scope

**Input:**

```python
def parse_config(path):
    with open(path) as f:
        return json.load(f)
```

No PR title, description, commit history, diff stats, issue link, or
changelog context accompanies this snippet.

**Expected finding:** This is outside this lens's scope — there is no
PR-level metadata (commits, description, size, changelog, ownership) here to
review, only a bare code snippet with no process context. Report "Not
applicable: no PR metadata (commits, description, diff stats) was provided
for this lens to review". Do NOT report "No findings: PR process hygiene is
healthy" — that sentence means a PR's structure was checked and found sound,
which implies there was a PR to check. There wasn't.
