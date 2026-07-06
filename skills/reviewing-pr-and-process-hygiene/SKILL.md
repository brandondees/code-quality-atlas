---
name: reviewing-pr-and-process-hygiene
description: 'Reviews the PR itself rather than just the code: size and single purpose
  (~<=400 net LOC), atomic commits with imperative why-bearing messages, correct conventional
  type and breaking-change signaling, risk and rollback notes, docs/changelog updated
  with the API surface, no drive-by scope creep, no committed secrets or debug leftovers.
  Use when reviewing a pull request''s structure, commits, description, changelog,
  or readiness to merge.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 24
    source: docs/research/cluster-6-evolution.md#24
    hash: 7ba96b8ae8b10dc443c956072cb7f7592d18812eaea8ccdb1696862a03299e1e
  - category: 22
    source: docs/research/cluster-6-evolution.md#22
    hash: a7e66646fdd831a46d37765f29794abebc92ef33369b97723210bcdc9647d25d
---

# reviewing-pr-and-process-hygiene

*Is the PR itself reviewable? Size, atomic commits, description, scope creep, changelog.*

## When to use

Reviews the PR itself rather than just the code: size and single purpose (~<=400 net LOC), atomic commits with imperative why-bearing messages, correct conventional type and breaking-change signaling, risk and rollback notes, docs/changelog updated with the API surface, no drive-by scope creep, no committed secrets or debug leftovers. Use when reviewing a pull request's structure, commits, description, changelog, or readiness to merge.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Claims vs. evidence:** is every claim the PR makes checkable against evidence *in the diff*? "Fixes X" / "closes #N" wants a regression test that fails without the change; "faster" / "optimizes" wants a benchmark or profile, not an assertion; "no behavior change" / "pure refactor" wants the diff to be genuinely behavior-preserving (no logic quietly changed alongside the move). An unsupported claim is itself a finding — flag it and name the missing evidence rather than taking the description's word (generalizes the perf lens's profile-demand; cross #1 stated-intent, #15 perf, #17 tests).
- **Closing-keyword syntax, one per issue:** when the PR body or a commit message links **more than one** issue with a closing keyword (`closes`/`fixes`/`resolves`, any tense), does **every** linked issue carry its **own** keyword — not a keyword followed by a bare comma/`and`-separated list? `Closes #12, #13, #14` only auto-closes #12; the rest silently stay open at merge. Correct forms repeat the keyword per issue (`Closes #12, closes #13, closes #14`, or one per line). Distinct from claims-vs-evidence above: this is a GitHub-parsing correctness check (does the stated linkage actually take effect), not a does-the-fix-have-a-test check — and it is the single most common way an AI-authored PR description silently under-delivers on "closes #A, #B, #C."
- **Agent-native parity:** does a new user-facing action also have a programmatic path (API/CLI/tool), and is it documented for automation — not UI-only?
- **PR size & focus:** is the PR small and single-purpose (roughly ≤~400 net LOC, one concern)? If it mixes refactor + feature + format churn, suggest splitting — mixed diffs hide bugs.
- **Atomic commits:** does each commit represent one logical change that builds and (ideally) passes tests on its own, enabling clean `revert`/`bisect`? No "fix typo"/"wip"/"address review" noise left in final history.
- **Commit message hygiene:** imperative-mood subject within length limit; body explains *why* and trade-offs, not a restatement of the diff; links the issue/ticket.
- **Conventional type & scope:** is the commit/PR typed correctly (`fix` vs `feat` vs `refactor`) — because it drives versioning and changelog?
- **Breaking-change signaling:** if the change alters a public API/contract/schema/config, is it marked breaking (`!` / `BREAKING CHANGE:`) and is the migration noted? Silent breaking changes are a top review failure.
- **Risk signaling:** does the PR description state blast radius, rollback plan, feature-flag status, and what was/wasn't tested? Risky areas (auth, money, migrations, concurrency) called out for closer review.
- **API surface ↔ docs parity:** does every new/changed public function, endpoint, CLI flag, or config key have a docstring/doc updated in the same diff? Stale signature-vs-doc = drift.
- **Docstring accuracy:** do param names, types, return, and `raises`/`throws` in the docstring match the actual signature *after* this change? (params renamed but docstring not — flag.)

**Shared categories:** category #22 checks are shared with **auditing-documentation-health** (their primary owner). When both lenses run on the same change, report each shared finding once, under the primary owner.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
