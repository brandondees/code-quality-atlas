---
name: reviewing-install-and-upgrade-experience
description: 'Reviews a change for the experience of the people who consume this software
  — installing, configuring, and upgrading it — distinct from the decision-lifecycle
  lens''s "should we adopt this dependency" call and from end-user product UX. Covers
  setup friction and undocumented prerequisites; configuration ergonomics (safe defaults,
  schema validation, fail-fast actionable errors, backward-compatible keys); and upgrade/migration
  smoothness — especially whether a consumer or a code agent can complete and verify
  the upgrade from the docs alone: a codemod or migration command, SemVer-correct
  breaking-change signaling, deprecation windows over silent removals, and a downgrade
  path. Use when reviewing installers, setup/init scripts, packaging, CLI and config
  surfaces, upgrade or migration guides, or release/versioning changes — or anything
  a downstream project adopts (a tool, plugin, template, or library). Skip when the
  change has no consumer-facing install, config, or upgrade surface.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 33
    source: docs/research/cluster-6-evolution.md#33
    hash: 981ca2966964786ae06af8253605a5e9e7a1c505d2ad1427de9205bfd424c6e0
---

# reviewing-install-and-upgrade-experience

*Can a consumer install, configure, and upgrade this cleanly — even hand it to an agent? Setup friction, config UX, version-bump smoothness, migration path.*

## When to use

Reviews a change for the experience of the people who consume this software — installing, configuring, and upgrading it — distinct from the decision-lifecycle lens's "should we adopt this dependency" call and from end-user product UX. Covers setup friction and undocumented prerequisites; configuration ergonomics (safe defaults, schema validation, fail-fast actionable errors, backward-compatible keys); and upgrade/migration smoothness — especially whether a consumer or a code agent can complete and verify the upgrade from the docs alone: a codemod or migration command, SemVer-correct breaking-change signaling, deprecation windows over silent removals, and a downgrade path. Use when reviewing installers, setup/init scripts, packaging, CLI and config surfaces, upgrade or migration guides, or release/versioning changes — or anything a downstream project adopts (a tool, plugin, template, or library). Skip when the change has no consumer-facing install, config, or upgrade surface.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Upgrade is mechanical and hand-off-able:** can a consumer move from the previous version to this one by following a single documented path — ideally a codemod / `migrate` command, otherwise a copy-pasteable checklist — without reverse-engineering the diff? A change that renames, moves, or removes a consumer-facing knob needs an automated migration or an explicit "to upgrade: …" note, not just a changelog line. This is the gap between a version bump an agent can complete-and-verify and one a human must babysit.
- **The consumer path was actually exercised:** for a tool, plugin, template, or library, was the install/upgrade run against a real sample consumer (a fresh-adopter dry run), not only unit-tested in-repo? The smoothest adoptions come from dogfooding the exact path a new adopter — or their agent — will take.
- **Install from scratch still works:** following only the documented steps from a clean checkout / empty environment, does setup succeed — no undocumented prerequisite, no manual step the change silently introduced? A new setup step with no installer or doc update is an adoption regression (cross #22 README front-door).
- **Breaking changes are signaled and versioned:** is every consumer-facing break (config key, CLI flag, public default, file layout, output format) reflected in a SemVer-major bump and called out as `BREAKING` with before→after, so SemVer-aware upgrade tooling and agents can detect and gate on it (cross #13, #24)? A break under a patch/minor bump silently breaks every automated upgrade.
- **Config is validated, fail-fast, and actionable:** is new configuration validated at startup against a schema, failing with a message that names the offending key *and the fix* — not a deep stack trace, and not a silent wrong default that surfaces much later (cross #26)?
- **Existing config keeps working or is migrated:** does a current adopter's existing configuration still load after this change — new keys optional with safe defaults, no silent semantic change to an existing key — or is there an automatic migration and a clear rename path?
- **Safe defaults; zero-config common case:** does the change work out of the box for the common case with little or no configuration, keeping new complexity behind optional knobs, rather than requiring the adopter to set several values before first success (cross #11 restraint — a new *required* knob is the friction to question)?
- **Time-to-first-success stays low:** does the quickstart still get a new adopter to a working result in a few steps, and does this change avoid adding required steps to that path? Prefer a quickstart that runs in CI so it cannot rot (cross #22 runnable example).
- **Deprecate, don't yank:** is a removed or renamed consumer surface kept working for a deprecation window with a runtime warning that names the replacement, rather than removed in place (cross #29 retirement-on-a-schedule)?
- **Install / setup is idempotent and reproducible:** is the installer / `init` safe to re-run — no duplicate writes, no clobbering of the consumer's own edits — and does it pin what it installs so two adopters get the same result? An `init` that overwrites a consumer's customizations on re-run is a trap.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
