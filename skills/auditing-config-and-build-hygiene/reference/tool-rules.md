# Tool rules to triage — auditing-config-and-build-hygiene

## Contents
- From category #19
- From category #26

## From category #19

### Tooling rules worth lifting
- **pre-commit** (multi-language hooks), **husky + lint-staged** (JS), **lefthook** — run lint/format/type-check before commit.
- **CI** (GitHub Actions/GitLab CI/Buildkite) — required status checks + branch protection as the merge gate.
- **Build** — Bazel/Buck (hermetic), Nix (reproducible envs), Docker multi-stage.
- **Gate the diff** with the project's linters + formatter (Prettier/Black/gofmt) + type-checker (tsc/mypy) — cross #8.
- **Deploy safety** — canary / blue-green / progressive delivery (Argo Rollouts, Flagger) + automated rollback.

## From category #26

### Tooling rules worth lifting
- **Config schema/validation:** envalid, zod env parsing, **Pydantic Settings**, viper, Spring `@ConfigurationProperties` validation, dotenv-linter.
- **Secret scanning:** Gitleaks, TruffleHog, detect-secrets (cross #14).
- **Feature-flag platforms:** LaunchDarkly, **Unleash**, Flagsmith, **OpenFeature** (vendor-neutral standard) — incl. stale-flag detection / flag-cleanup.
- **Portability/env:** ShellCheck (portable shell), `.editorconfig`; pinned container base images for parity.
