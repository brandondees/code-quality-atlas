# Examples — reviewing-usability-and-interaction

Report each distinct issue as its own numbered finding, naming the interaction principle it violates and citing the code. Say which of the two kinds each one is: a **gap** the code actually produces (an unhandled state, an unrecoverable destructive action, lost input, absent feedback) is a defect with ordinary severity, and a **judgment** (which pattern, which words, whether the flow should exist) is surfaced with its evidence and routed to design or product with no engineering verdict. When the change has no user-facing surface, or the flow handles its states and its consequences, the entire response is exactly "No findings".

## Contents

- [Bad → finding (three states the code reaches, one designed)](#bad--finding-three-states-the-code-reaches-one-designed)
- [Bad → finding (a destructive action that names nothing)](#bad--finding-a-destructive-action-that-names-nothing)
- [Bad → finding (the error path eats the form)](#bad--finding-the-error-path-eats-the-form)
- [Good → routed finding (the gap is a defect, the pattern is not)](#good--routed-finding-the-gap-is-a-defect-the-pattern-is-not)
- [Good → no finding (skipped — no user-facing surface)](#good--no-finding-skipped--no-user-facing-surface)

## Bad → finding (three states the code reaches, one designed)

**Bad:**

```tsx
function ProjectList() {
  const { data } = useProjects();
  return <ul>{data.map(p => <ProjectRow key={p.id} project={p} />)}</ul>;
}
```

**Finding (defect, Major).** Enumerate from the code, not the mockup. `useProjects`
can be pending, can reject, and can resolve to an empty array — so this component
reaches four states and renders one. Concretely: while pending, `data` is
`undefined` and `.map` throws; on rejection, nothing catches it; on an empty
result, the user gets a blank region with no explanation of whether they have no
projects or something broke.

Three of these are engineering defects, not design preferences — the code produces
the state whether or not anyone designed it. What a *good* empty state says
("Create your first project", with a button) is design's call and routes; that it
must exist does not.

The durable fix is to make the missing branch a compiler error rather than a
review finding — a discriminated union over `loading | empty | error | ready`
instead of `data`-plus-two-booleans, **plus an exhaustiveness check**: a `switch`
whose `default` hands the value to an `assertNever(x: never)`, or the stack's own
equivalent. The union alone does not get you there — an `if`/`else if` chain over
it compiles perfectly well with a variant unhandled, which is this same defect
wearing a type. With the check, adding a fifth state fails the build at every
site that renders one. That's `reviewing-module-design`'s
illegal-states-unrepresentable move aimed at UI state, and it's the only
mechanization this category has that scales.

## Bad → finding (a destructive action that names nothing)

**Bad:** a new "Remove workspace" button opens a dialog reading *"Are you sure?
This action cannot be undone."* with **Cancel** and **Remove** buttons, styled
identically, side by side.

**Finding (defect, Major).** Two separate failures, and reviews usually catch only
the first:

1. **The confirmation names nothing.** "Are you sure?" is a click users are
   trained to dismiss. Error prevention requires naming the consequence —
   "Remove *Acme Production* and its 12 projects, 340 files, and 6 member
   invitations?" A user who cannot tell from the dialog what they are about to
   lose has not been warned.
2. **The slip case is unaddressed.** A destructive control identical in size,
   colour, and position to its safe neighbour will be hit by accident regardless
   of how good the copy is — that's Norman's *slip*, a right intention executed
   wrongly, and it is a design defect rather than user error. Check it separately
   from the *mistake* case the copy addresses.

Prefer **undo** over confirmation **when the effect is genuinely deferrable** —
a soft-delete with a 10-second "Workspace removed — Undo" costs the careful user
nothing and saves the careless one, which no dialog does.

Check that condition rather than assuming it. Undo is the wrong instrument when
the effect leaves the system the moment it fires or must not be delayed: a
deletion that propagates to an external system or a search index, one that
starts a retention or legal-hold workflow, or anything that *revokes*
authorization — a 10-second undo window on "revoke API key" means the
compromised key stays live for ten more seconds, which is the opposite of what
was asked for. There, a confirmation that names what will be lost is the
correct control, and it is not a weaker one.

## Bad → finding (the error path eats the form)

**Bad:**

```js
async function onSubmit(values) {
  setForm(EMPTY_FORM);              // clear immediately for responsiveness
  const res = await createInvoice(values);
  if (!res.ok) setError("Something went wrong. Please try again.");
}
```

**Finding (defect, Major — and it is not a copy problem).** On failure the user is
told to try again, and every field they filled is gone. That is a **defect, not a
preference**: the fact that it surfaces as a bad experience does not demote it.
Clear the form on *success*, not on submit.

**On the severity, deliberately.** `REVIEW.md`'s scale puts *data loss* at
**Blocker**, and this is Major — the difference is recoverability. Blocker-tier
data loss is durable and unrecoverable: rows deleted, a backfill that overwrites,
a migration with no down path. Here the data is the user's *unsaved input*, and
the user can retype it — costly and infuriating, never silent, and gone only from
that session. Rate it Blocker when the lost input cannot be reproduced by the user
(an uploaded file with no local copy, a long-form draft with no autosave, a
one-time code) — then it *is* the durable kind and takes the higher band.

The copy is separately weak ("Something went wrong" says what happened, not why or
what to do next), but that half **routes to design** and sets no engineering
verdict. Two findings, two dispositions, from one code path — say which is which.

## Good → routed finding (the gap is a defect, the pattern is not)

**Input:** a PR adds a fourth date picker to the codebase, hand-rolled, in a new
booking flow. The other three use the design system's `<DateField>`.

**Good output — one finding, correctly routed:**

```text
Nit [route: design] — booking/DateRange.tsx:22 introduces a fourth date-picker
implementation; DateField (design system) is used at checkout/, billing/, and
reports/. Users have been taught one interaction for picking a date and this one
differs (no keyboard entry, different week-start). Reviewable fact: an equivalent
exists in this codebase and this one behaves differently. The decision — adopt
DateField here, or change all four — is design's, not this review's.
```

What makes this right: the review establishes the **checkable** part (an
equivalent exists; the behavior differs) and hands the *decision* over. It does
not argue that the design system is better, does not block the merge, and does not
assign engineering severity to a pattern preference. Contrast with the three
examples above, where the gap — an unhandled state, an unnamed consequence, lost
input — is a defect the reviewer states plainly and does not route away.

## Good → no finding (skipped — no user-facing surface)

**Input:** a PR refactors a queue consumer and its retry policy. No UI, no CLI, no
user-facing flow.

**Good:**

```text
reviewing-usability-and-interaction: not applicable — no user-facing surface in
this change (queue consumer and retry policy only).
```

One line, no findings. A backend diff will always yield *something* if you look
hard enough for it, and manufacturing usability findings from one is the fastest
way to get this lens muted. Note that a **CLI is** a user interface — prompts,
progress on long operations, confirmation before destruction, and `--help` all
fall inside this lens's scope even with no pixels involved.
