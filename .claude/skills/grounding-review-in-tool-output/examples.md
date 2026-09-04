# Examples — grounding-review-in-tool-output

This pass reports no findings of its own. Every tool hit is confirmed, contextualized, or dismissed by the lens that owns it, and what leaves this pass is an evidence bundle per lens plus the three-fact coverage line. When the repo configures no deterministic tools, or none could run, say so under coverage rather than reporting nothing at all.

## Contents

- [Good → the repo's own tools, triaged](#good--the-repos-own-tools-triaged)
- [Bad → finding (a tool the repo never adopted)](#bad--finding-a-tool-the-repo-never-adopted)
- [Bad → finding (a clean run read as an approval)](#bad--finding-a-clean-run-read-as-an-approval)
- [Bad → finding (running the repo's tools on an untrusted branch)](#bad--finding-running-the-repos-tools-on-an-untrusted-branch)
- [Good → the coverage line when nothing could run](#good--the-coverage-line-when-nothing-could-run)

## Good → the repo's own tools, triaged

**Input:** a Python/TypeScript service. `.pre-commit-config.yaml` runs `ruff`
and `mypy`; `.github/workflows/ci.yml` additionally gates on `semgrep --config
.semgrep.yml` and `tsc --noEmit`. The PR adds an endpoint that reads a signed
token and writes an audit row.

**Inventory** (step 1), written down before anything runs:

```text
ruff      pre-commit  ruff.toml            gated in CI
mypy      pre-commit  pyproject.toml       gated in CI
semgrep   CI only     .semgrep.yml         gated in CI
tsc       CI only     tsconfig.json        gated in CI
```

**Run** (step 2), scoped to the six changed files, each under the repo's own
config — not a default rule set. Raw output, four hits:

```text
ruff     api/tokens.py:31   B008  function call in default argument
mypy     api/tokens.py:47   arg-type: "str | None" not assignable to "str"
semgrep  api/tokens.py:52   local.logging-sensitive-data
semgrep  api/audit.py:19    local.raw-sql-query
```

**Triage** (steps 3-4) — every hit gets exactly one disposition:

```text
confirm       api/tokens.py:47  mypy arg-type — the None branch is reachable when the
                                header is absent; tracing-correctness-and-invariants
                                owns it, mypy is the evidence.        → Major
confirm       api/tokens.py:52  semgrep local.logging-sensitive-data — the raw token is
                                logged at INFO; sweeping-for-security owns it.  → Major
contextualize api/tokens.py:31  ruff B008 — real, but the default is an immutable
                                sentinel, so it can't leak state between calls.  → Nit
dismiss       api/audit.py:19   semgrep local.raw-sql-query — the SQL is a constant with no
                                interpolation; the rule matches the call shape, not a
                                real injection path. Dismissed, and said so.
```

**Coverage line handed to the synthesizer:**

```text
Tools run: ruff (ruff.toml), mypy, semgrep (.semgrep.yml), tsc --noEmit — over the 6 changed files.
Not run: none.
No deterministic coverage: reviewing-module-design, reviewing-test-quality, checking-restraint — judgment only.
```

What makes this right: the two confirmed hits are reported **as lens findings
with a rule id as evidence**, the dismissal is written down rather than silently
dropped, and the last coverage line names what no tool could speak to — the part
a reader cannot reconstruct.

## Bad → finding (a tool the repo never adopted)

**Bad:** the repo has no JavaScript linter configured. The pre-pass runs
`eslint` with its own recommended config anyway, gets 41 hits, and reports them
as findings on the PR.

**Finding:** *Never introduce a tool the repo has not adopted.* Those 41 hits
are about a rule set this team never chose — most are style preferences, not
defects in this codebase, and shipping them buries the two findings that
matter. The correct output is one `route: eng` suggestion that the repo has no
JS linter, if the review judges that worth raising at all.

## Bad → finding (a clean run read as an approval)

**Bad:** `ruff`, `mypy`, and `semgrep` all exit 0 on the changed files, so the
pre-pass reports "static analysis clean — no security or correctness findings"
and the security and correctness lenses are skipped.

**Finding:** *A clean run clears nothing.* No linter has an opinion on whether
the authorization check is on the right object, whether the invariant the code
assumes is the one the caller guarantees, or whether the change should exist.
Absence of tool output is absence of evidence, not evidence of absence — every
selected lens still runs in full, and the clean run is a line under coverage,
not a verdict.

## Bad → finding (running the repo's tools on an untrusted branch)

**Bad:** reviewing a fork PR from a first-time contributor, the pre-pass runs
`make lint` in the review session to gather evidence. The PR's diff includes a
one-line edit to the `lint` target.

**Finding:** *Running the repo's tools runs the repo's code.* A `Makefile`
target is a shell command, an `eslint.config.js` is JavaScript, and a
pre-commit hook fetches and executes a remote repository — all of them
attacker-controlled on a fork branch, and all of them running wherever the
review session's credentials are. Either run the pre-pass only in the isolation
CI already uses for untrusted branches, or skip it and record
`Not run: all — untrusted branch` under coverage. A grounding pre-pass must
never be the reason untrusted code executes with credentials in scope.

## Good → the coverage line when nothing could run

**Input:** a Go repo whose CI gates on `golangci-lint`, reviewed in a session
with no Go toolchain installed.

**Good:** don't guess at what the linter would have said, and don't quietly
omit it:

```text
Tools run: none.
Not run: golangci-lint (.golangci.yml, gated in CI) — Go toolchain not available in this session.
No deterministic coverage: every selected lens — judgment only.
```

The lenses then run exactly as they would have without a pre-pass. The value
delivered here is not evidence; it is an honest edge on the review, which is
what a reader needs to decide how much the verdict is worth.

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/grounding-review-in-tool-output/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
