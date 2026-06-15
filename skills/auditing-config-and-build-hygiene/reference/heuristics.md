# Reviewable heuristics — auditing-config-and-build-hygiene

## Contents

- From category #19
- From category #26

## From category #19

### Reviewable heuristics (skill-checklist seeds)

- Does CI run the full gate on the diff — lint, format-check, type-check, tests, dep/security scan — and is passing **required** to merge?
- Beyond that required floor, are the **deterministic quality signals** this stack benefits from actually present — **coverage reporting** (with a branch/diff threshold, not a vanity global %), a **performance benchmark** on the hot paths, and **complexity/maintainability scoring**? Their absence is a **preference-tunable advisory** (`route: implementer`), not a floor-tier block: surface "no coverage gate / no perf benchmark / no complexity budget" as a gap worth wiring up, and let a repo that deliberately skips it suppress the note (cross #17, #21).
- Is the build **reproducible/hermetic** enough to not depend on machine-local state (pinned toolchain, lockfiles, no network in build)?
- Is CI **fast and reliable**? A new slow/flaky job is a defect — parallelized, cached, deterministic?
- Is any **quality gate disabled or soft-failed** (`continue-on-error`, `|| true`, `allow_failure`, a skipped/excluded check) — a deliberate, tracked decision or silent debt? A gate that's off because its tool broke on the current toolchain (language/runtime version, build) is a **gap to close**: fix it or swap in a maintained equivalent — often a younger, less well-known one — not a permanent `continue-on-error` (cross #21).
- Are **secrets** injected at runtime (not baked into the image/repo/CI logs) and least-privilege scoped (cross #14)?
- Risky change → is there a safe rollout (canary/flag) and a **tested rollback** path (cross #16, #20)?
- Is incomplete work integrated **behind a flag** (trunk-based), not a long-lived branch?
- Does the pipeline **build once and promote** the same artifact, not rebuild per environment?
- Are pre-commit/pre-push hooks present so obvious issues never reach CI?
- **IaC is code:** does infrastructure/config-as-code in the diff (Terraform, K8s manifests, Helm, Dockerfiles, CI workflows) pass the same gate as app code — linted (checkov/tflint/kube-linter/hadolint), reviewed, and `plan`ned in CI before apply?
- **Workflow injection:** does any `${{ }}` expression interpolate attacker-influenceable context (issue/PR titles and bodies, branch names, commit messages) directly into a `run:` script? Pass it through an env var instead — the template is expanded *before* the shell parses (template injection).
- **Action/workflow supply chain:** are third-party actions pinned to full commit SHAs (not mutable tags), and are workflow token `permissions:` explicitly declared and least-privilege (cross #18, #14)?
- **Container hygiene in the diff:** image versions pinned (no `:latest`), a non-root final `USER`, CPU/memory requests+limits set, read-only root filesystem where workable, no `privileged: true` or host namespace/docker-socket mounts without a documented reason.
- **Cloud misconfig in the diff:** does a new/changed IaC resource open public access (`0.0.0.0/0` ingress, public bucket ACL), disable encryption, or grant wildcard IAM? Deliberate-and-documented or a finding (security verdict owned by #14).

---

## From category #26

### Reviewable heuristics (skill-checklist seeds)

- Is config **separated from code** and injected via env — no secrets or env-specific values hardcoded/committed?
- Is config **validated at startup** (fail fast, clear message), not lazily at first use?
- Are **safe, secure defaults** used (deny-by-default, TLS on, debug off in prod — cross #14)?
- **Dev/prod parity**: does the change keep environments close (same backing services, same config shape), avoiding env-specific code branches?
- New **feature flag**: does it have an owner and a **removal plan**? Are stale/dead flags being cleaned up (debt — cross #21)?
- **Portability**: any hardcoded paths, OS/arch assumptions, locale/encoding/timezone assumptions, or non-portable shell?
- Are **secrets** sourced from a manager/env (never repo or logs) and rotatable?
- Is configuration **documented** (each var's purpose, required vs optional, default)?

---
