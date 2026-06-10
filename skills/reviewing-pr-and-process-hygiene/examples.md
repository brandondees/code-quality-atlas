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
