# Examples — reviewing-conceptual-integrity

Report each distinct issue as its own numbered finding, and open every one with the **evidence gate**: name the concept the product already has, where it lives, and the one-sentence rule a user would apply to choose between it and the new one. No named existing concept, no finding — a genuinely new idea filling a real gap is not a defect for being new, and "that doesn't fit the model" is unfalsifiable when the model is never named. Say which of the two kinds each finding is: a **contradiction** with a rule the product already enforces is a defect with ordinary severity and an engineering fix; a **judgment** — whether the concept should exist, what to call it, whether to unify — is surfaced with its evidence and routed to product or design with no engineering verdict. Reporting nothing covers two cases and no others, and they take different forms. When the change introduces a concept and no existing one covers the same job, the entire response is exactly "No findings". When it introduces no user-facing concept at all, the lens did not apply — say that in one line rather than returning a bare "No findings" that reads as though the check ran and passed.

## Contents

- [Bad → finding (a second noun for an idea the product already has)](#bad--finding-a-second-noun-for-an-idea-the-product-already-has)
- [Bad → finding (a rule the product enforces everywhere else)](#bad--finding-a-rule-the-product-enforces-everywhere-else)
- [Bad → finding (the ninth option, justified against the eighth)](#bad--finding-the-ninth-option-justified-against-the-eighth)
- [Good → routed finding (a second path, surfaced and handed over)](#good--routed-finding-a-second-path-surfaced-and-handed-over)
- [Good → no finding (a genuinely new concept)](#good--no-finding-a-genuinely-new-concept)
- [Good → no finding (skipped — no user-facing concept)](#good--no-finding-skipped--no-user-facing-concept)

## Bad → finding (a second noun for an idea the product already has)

**Bad:** a PR adds a **Collection** entity — create, rename, add/remove documents,
share with a team. The product already ships **Folders**, which do all four.
Neither the PR nor the UI says how the two relate.

**Finding (judgment, `route: product`).** Run the evidence gate first, out loud,
because it is what separates this from a taste objection:

1. **The existing concept:** `Folder` — `models/folder.py`, the sidebar tree, the
   "Move to folder…" action on every document, and 14 strings in the message
   catalog.
2. **The overlap:** create, rename, add/remove documents, share. Four of four.
3. **The rule a user would apply to choose:** *there isn't one.* Nothing in the
   diff, the copy, or the docs tells a user when to reach for a Collection
   instead of a Folder. That absence is the finding, not the new entity.

The reviewable fact is narrow and not a matter of opinion: the product now has
two nouns covering one job and says nothing about the relationship. **The
decision is product's** — unify them, retire Folders, or keep both with a stated
distinction — and this review sets no engineering verdict on it.

One check to run before reporting, which kills a good share of false positives:
**is there a bounded context here?** Evans's counterweight — the same word
legitimately means different things on either side of a real boundary, so
billing's "account" and auth's "account" are not a finding. Two entities in the
*same* context, reachable from the same screen, are. Name the context or drop the
objection.

Note what this finding is **not**. `checking-restraint` may separately argue the
feature shouldn't ship at all; that is a different question with a different
answer, and if both fire the review reports it once.

## Bad → finding (a rule the product enforces everywhere else)

**Bad:** a new `Report` resource. Deleting a Report leaves its `ReportSection`
rows in place. Every other parent resource in the codebase — `Project`,
`Folder`, `Dashboard` — cascades to its children on delete, and the API docs say
"deleting a resource deletes everything inside it."

**Finding (defect, Major — and this is the half of the lens that sets a
verdict).** The user has been taught a rule by the other three resources and by
the documentation. This one breaks it silently: no warning, no docs note, no
error. A user who deletes a Report reasonably believes its sections are gone,
and they are not — they are orphaned rows that still count against quota and
still appear in search.

This is a **broken promise**, not a preference, which is why it takes ordinary
severity rather than routing. The general form: an unannounced exception to a
rule the product already enforces is a defect, because users and API consumers
generalize from what they have already seen — that is exactly what a coherent
model buys, and what an exception spends.

The fix is a product decision only in *which direction* it goes — cascade like
the siblings, or block the delete with an explanation. That there is a
contradiction is not up for discussion; which way to resolve it routes.

## Bad → finding (the ninth option, justified against the eighth)

**Bad:** the PR adds `--output-format=ndjson` to a CLI that already accepts
`--json`, `--pretty`, `--quiet`, `--verbose`, `--table`, `--csv`, `--no-color`,
and `--format`. The description says: "consistent with `--csv`, which we added
last quarter."

**Finding (judgment, `route: eng`).** Count it, because the count is the
evidence: this is the ninth output-shaping flag, and `--format` already takes a
value. The description justifies it against the most recent addition rather than
against a governing idea — which is Brooks's second-system effect in its
ordinary, undramatic form. Nobody decided the CLI should have nine output flags;
each one was reasonable next to the one before it.

Two facts worth stating plainly, since either could be the resolution:

1. `--format=<value>` already exists and could absorb `ndjson`, `csv`, `table`,
   and `json` as values, leaving one flag where there are now five.
2. If the flags are kept, nothing in `--help` tells a user what happens when
   `--json` and `--format=csv` are both passed. An undecided interaction between
   options is where accretion turns into a bug.

`checking-restraint` will likely reach the same place from the other side ("do
we need this flag"). **Same finding, report it once** — under whichever lens has
the concrete evidence, which here is this one, because the count and the
`--format` overlap are the argument.

## Good → routed finding (a second path, surfaced and handed over)

**Input:** a PR adds `myapp deploy rollback <id>`. Rollback is already reachable
as `myapp deploy --revert-to <id>`. Both call the same service method.

**Good output — one finding, correctly routed:**

```text
Nit [route: product] — cli/commands/rollback.py:14 adds a second path to an
outcome the CLI already reaches: `deploy --revert-to <id>` (cli/commands/deploy.py:88)
calls the same DeployService.revert(). Both now exist; nothing in the diff
deprecates the flag, and `--help` will list both with no note that they are the
same operation. Reviewable fact: two documented ways, one behavior, no stated
relationship. The decision — keep the subcommand and deprecate the flag, or
document them as aliases — is product's, not this review's.
```

What makes this right: it establishes the **checkable** part (both exist, same
service call, no stated relationship) and hands the decision over. It does not
argue that subcommands are better than flags, does not block the merge, and
does not assign engineering severity to a shape preference. Contrast with the
`Report` example above, where the code *contradicts* a rule the product already
enforces — that one is a defect the reviewer states plainly and does not route
away.

## Good → no finding (a genuinely new concept)

**Input:** a PR adds **Retention policies** — a rule attaching to a workspace
that deletes documents older than N days. The product has no concept of
scheduled or automatic deletion today; documents are deleted by hand.

**Good:**

```text
No findings
```

The evidence gate is what produces that answer, and running it is not optional:
searched for an existing concept covering "delete documents on a schedule" —
`Folder`, `Archive`, and `Trash` are the neighbours, and none of them removes
anything on a rule. `Archive` is the closest and is explicitly manual and
reversible. No overlap, so **no finding**: a new concept filling a real gap is
not incoherence, and reporting it as such would make this lens a tax on every
new feature.

Note that "new" was never the question. A product that cannot grow a concept has
a different problem, and the reviewer who flags every new noun gets this lens
muted before the change that actually needed it.

## Good → no finding (skipped — no user-facing concept)

**Input:** a PR extracts `PermissionChecker` from three call sites into a shared
service, with no change to behavior, copy, routes, or API fields.

**Good:**

```text
reviewing-conceptual-integrity: not applicable — internal refactor with no
user-facing concept, vocabulary, or surface introduced.
```

One line, and stop. Internal structure is `reviewing-module-design`'s question,
and code-level consistency is `checking-idioms-and-consistency`'s; a change that
alters neither the words a user reads nor the things a user must choose between
has nothing for this lens. Manufacturing a coherence argument from a refactor is
this lens's own failure mode, and it is more likely than the incoherence it
guards against.
