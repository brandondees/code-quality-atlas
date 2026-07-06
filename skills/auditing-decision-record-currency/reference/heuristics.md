# Reviewable heuristics — auditing-decision-record-currency

## Contents

- From category #39

## From category #39

### Reviewable heuristics (skill-checklist seeds)

- **Status-graph consistency:** does any decision record's status contradict another's — two `accepted` records making incompatible choices with no `supersedes`/`superseded-by` link between them — or is a record marked `accepted` for a choice the codebase has visibly reversed (the named technology is no longer a dependency, no longer referenced in config/infra)?
- **Revisit-trigger condition plausibly met:** where a record names a concrete, checkable revisit condition (a scale threshold, a team-size figure, a vendor-support date), does anything visible in the repo (config, infra manifests, dependency graph, `CODEOWNERS` size) suggest that condition may now hold — flagged as "revisit due," not resolved unilaterally?
- **No checkable revisit-trigger recorded:** does the record state only a vague "revisit periodically" with no date or measurable condition — the base case the sweep can't check further, worth flagging once per record rather than silently skipping?
- **Adopted technology now EOL or on Hold:** does a record's chosen dependency/framework/platform appear on an end-of-life feed, or would the adoption read as `Hold` on a technology-radar-style scale today, with no revisit noted since?
- **Orphaned or contradicted record:** is a decision record referenced by nothing else in the repo (no code, config, or doc still implements what it decided) and left `accepted` rather than marked `superseded`/`deprecated` — a stale entry cluttering the log worse than an absent one (per Azure Well-Architected's framing)?
- **Escalate the judgment call, don't resolve it:** a plausibly-met revisit-trigger or an EOL adoption is evidence a human should re-open the decision, not a verdict that the original choice was wrong — report the signal and route to the decision's owner (cross #29, the G8 boundary), never assert the ADR should be reversed.

---
