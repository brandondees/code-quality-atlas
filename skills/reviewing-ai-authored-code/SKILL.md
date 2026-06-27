---
name: reviewing-ai-authored-code
description: 'Reviews a change for the failure signature of AI-/machine-authored code,
  independent of who wrote it: hallucinated or typosquatted dependencies (slopsquatting),
  invented or misused APIs and parameters, plausible-but-wrong constants and logic
  that reads fluently, hallucinated internal references to symbols that don''t exist
  here, over-helpful unrequested additions (scope creep as a generation artifact),
  the weak-default security signature, tests that assert the implementation instead
  of the spec, fabricated comments/citations, and duplication instead of reuse. Flags
  the signature and hands the deep verdict to the owning lens (#18 supply-chain, #14
  security, #1 correctness, #11 restraint). Use when reviewing AI-generated or AI-assisted
  code, a large or unfamiliar diff, or any change that adds dependencies or confident-looking
  constants and APIs — the defects are attribution-agnostic, so you need not know
  a model wrote it.'
provenance:
  taxonomy_version: v0.8
  built_from:
  - category: 34
    source: docs/research/cluster-4-runtime.md#34
    hash: 9f2471f9f7169cfe9db463dc1810029d26c174386df7e8008980bfa696450860
  - category: 18
    source: docs/research/cluster-5-verification.md#18
    hash: f876d3646ec45597347f3dd84153ef0d860abaf9eb3211d7d97cb8aca56cc9da
---

# reviewing-ai-authored-code

*Does this carry the AI-authored failure signature? Hallucinated/typosquatted packages, invented APIs, confident-but-wrong constants, over-helpful scope.*

## When to use

Reviews a change for the failure signature of AI-/machine-authored code, independent of who wrote it: hallucinated or typosquatted dependencies (slopsquatting), invented or misused APIs and parameters, plausible-but-wrong constants and logic that reads fluently, hallucinated internal references to symbols that don't exist here, over-helpful unrequested additions (scope creep as a generation artifact), the weak-default security signature, tests that assert the implementation instead of the spec, fabricated comments/citations, and duplication instead of reuse. Flags the signature and hands the deep verdict to the owning lens (#18 supply-chain, #14 security, #1 correctness, #11 restraint). Use when reviewing AI-generated or AI-assisted code, a large or unfamiliar diff, or any change that adds dependencies or confident-looking constants and APIs — the defects are attribution-agnostic, so you need not know a model wrote it.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Package is real and intended (slopsquat guard, xref #18):** Does every **newly added import or dependency** resolve to a package that actually **exists on the real index, predates this PR, and is the project you meant** — not a plausible-sounding hallucination or a one-character typosquat of a popular name? An unrecognized new dependency in a generated diff is a *supply-chain security event*: confirm existence + provenance, pin the version, and hand the reputation verdict to #18. Never assume a package is real because the code reads as if it is.
- **Confident-but-wrong constants and APIs:** Treat fluent, authoritative-looking code as *unverified*, not *correct*. Are invented or misused **APIs, methods, parameters, or flags** checked against the library's actual current signature (docs, not memory)? Are magic constants, regexes, format strings, status codes, crypto parameters, and limits **verified against the spec** rather than trusted because they look right? LLM defects are characteristically plausible — the review must distrust plausibility.
- **Over-helpful, unrequested additions (xref #11/#1):** Did the change add scope nobody asked for — extra endpoints, config knobs, "just in case" branches, defensive layers, a drive-by refactor — that widens the diff and the blast radius beyond the stated task? Over-helpfulness is the generated-code signature of premature generality; surface it (route to restraint for the verdict) and keep the change to its purpose.
- **Hallucinated internal references:** Do referenced **variables, functions, files, config keys, env vars, or imports actually exist in *this* codebase** with those exact names — or did the model invent a plausible-but-absent symbol (or use a name defined slightly differently elsewhere)? Inconsistent internal state — defined one way, used another — is a named LLM failure mode.
- **Plausible-but-wrong logic on the happy path:** Does the change *actually* implement what its description and comments claim, on every branch — or does it read correctly while quietly mishandling an edge, an ordering, an inverted condition, or an off-by-one? Re-derive the logic from intent rather than from the (fluent, confident) code; this is the #1 correctness check applied with extra suspicion to machine-authored prose.
- **Security-weakness signature (xref #14):** Does the change carry the weak-default classes generated code over-produces — unparameterized queries, unescaped output, missing authz checks, permissive CORS/TLS, disabled verification, weak / `Math.random` tokens, secrets inline? Flag the signature and hand the verdict to `sweeping-for-security`; ~45% of LLM code carries at least one such flaw, so this is a high-prior, not an edge case.
- **Tests that assert the bug, not the spec:** Were the change's tests written *against the implementation* (so they pass trivially, mirror the code's mistake, or assert a tautology) rather than against the intended behavior? Generated tests frequently encode "what the code does" as "what is correct." Confirm a failing case exists, the assertions are meaningful, and a regression test pins the actual requirement (route detail to `reviewing-test-quality`).
- **Fabricated comments, docs, and citations:** Do comments / docstrings describe behavior the code **actually has** (not an intended-but-absent feature), and do any cited issue numbers, RFCs, links, or "as documented in…" references **resolve to real, on-point sources**? A confident comment for code that does something else — or a dead / invented citation — is a strong tell to read the surrounding logic with extra care.
- Is the new dependency **necessary**, or could stdlib/a few lines do it (avoid trivial deps and transitive bloat)?
- Is it **healthy**: recently maintained, broadly used, reasonable Scorecard, not single-maintainer abandonware?

**Shared categories:** category #18 checks are shared with **auditing-dependencies-and-supply-chain** (their primary owner). When both lenses run on the same change, report each shared finding once, under the primary owner.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
