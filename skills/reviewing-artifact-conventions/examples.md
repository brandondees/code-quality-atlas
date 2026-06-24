# Examples — reviewing-artifact-conventions

This lens is **presence-activated**: first detect a supported artifact (the Artifacts
table in `SKILL.md`), then open that artifact's rubric (`reference/<slug>.md`) and
review the artifact against it. Report each deviation as its own numbered finding,
naming the specific rule of the standard it breaks. When the artifact is well-formed —
or when no supported artifact is present in the change — the whole response is exactly
"No findings". This is **authoring quality**, distinct from doc-drift (#22) and runtime
agent-safety (#32).

## Bad → finding (SKILL.md — weak frontmatter description)

**Input (a changed `SKILL.md` frontmatter):**

```yaml
---
name: helper
description: I help with reviewing things.
---
```

**Expected findings:**

1. **Frontmatter description is not a trigger (rubric: frontmatter limits):** the
   `description` is **first-person** ("I help…"), vague, and names **no concrete
   situations, file types, or keywords**, so the model cannot tell when to activate the
   skill. Rewrite it third-person and specific — what it reviews, the triggers, and a
   skip clause (e.g. "Reviews X for Y; use when …; skip when …").
2. **`name` is not a gerund (rubric: frontmatter limits):** `helper` is a noun; the
   standard wants a gerund, lowercase-hyphen name (e.g. `reviewing-helpers`).

## Bad → finding (SKILL.md — no progressive disclosure)

**Input:** a `SKILL.md` whose body is ~700 lines, inlining the full checklist, every
tool rule, and all references, with **no bundled `reference/` files**.

**Expected finding:**

1. **Body violates progressive disclosure (rubric: lean entry point):** the `SKILL.md`
   body far exceeds the ~500-line target and inlines detail that belongs in **bundled,
   one-level-deep files loaded on demand**. An inlined mega-body taxes every session's
   context, not just the reviewing one. Move the full heuristics, tool rules, and
   references into `reference/*.md` and keep the body to when-to-use plus a short
   checklist.

## Good → no finding (well-formed SKILL.md)

**Input:** a `SKILL.md` with a gerund `name`, a specific third-person `description`
(≤1024 chars) carrying triggers and a skip clause, a ~90-line body, bundled
`reference/heuristics.md` + `examples.md`, three eval scenarios, and no time-sensitive
text.

**Expected finding:** No findings

Note: the artifact already meets the authoring standard on every rubric line. Do NOT
invent a deviation on a well-formed artifact.

## Good → no finding (no supported artifact present)

**Input:** a diff that only touches `src/payments.ts` — no `SKILL.md` or other listed
artifact anywhere in the change.

**Expected finding:** No findings

Note: this lens is presence-activated; with none of its artifacts in the change there is
nothing for it to review — the source code itself is the other lenses' job. Do not
review `.ts` source against an artifact rubric.
