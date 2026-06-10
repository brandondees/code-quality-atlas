# Examples — auditing-config-and-build-hygiene

This skill is repo-shaped: its input is a scan of CI pipelines, build scripts, and
configuration. Report each distinct issue as its own numbered finding. When the scan is healthy, the entire response is exactly this skill's no-finding sentence given in the decision rule below — never a numbered list of findings for a healthy scan.

**Decision rule (apply before flagging):** a hygiene finding needs a concrete
defect — a secret in the repo/image, an unpinned toolchain or action, a missing
merge gate, env-specific code branches, config read lazily without validation, or
a stale flag with no owner. Do not demand tooling the project's size doesn't
warrant. If the gates run and are required, builds are pinned and reproducible,
and config is injected/validated, report exactly
"No findings: config and build hygiene are sound".

## Bad → finding

**Input (build/config scan):**
```text
ci.yml:        uses: actions/checkout@main; tests run but not required to merge;
               docker build pulls base image python:latest
Dockerfile:    ENV STRIPE_KEY=sk-prod-...; pip install -r requirements.txt (no lock)
settings.py:   if ENV == "prod": payment_url = "https://pay.internal" else: "http://localhost"
               DEBUG defaults to True; config read at first use, KeyError at runtime
flags.yml:     enable_new_pricing: true  (owner: none, added 14 months ago)
```
**Expected finding:**
1. **Secret baked into the image:** the Stripe key in a Dockerfile `ENV` ships in
   every layer — inject at runtime from a secrets manager and rotate the exposed
   key.
2. **Unpinned everything:** `checkout@main`, `python:latest`, and no lockfile make
   the build unreproducible and supply-chain-exposed — pin the action SHA, the
   base-image digest, and the dependency lock.
3. **CI gate not required:** tests run but a red build can merge — make the gate
   required.
4. **Env-specific code branch + unsafe default:** the `if ENV == "prod"` fork and
   `DEBUG=True` default break dev/prod parity and fail open — inject URLs via
   config, default to safe values, and validate all config at startup (fail fast,
   not first-use `KeyError`).
5. **Stale flag with no owner:** `enable_new_pricing` has been on for 14 months —
   give flags an owner and a removal plan; this one should be removed.

## Good → no finding

**Input (build/config scan):**
```text
ci.yml:        actions pinned by SHA; lint+type+test+audit required to merge; base
               image pinned by digest; artifact built once, promoted to stage/prod
config.py:     pydantic-settings: all vars validated at import, env-injected,
               documented; DEBUG default False; no secrets in repo (scanner clean)
flags.yml:     checkout_v2 (owner: @payments, removal: #931, expires 2026-08)
```
**Expected finding:** None — pinned and reproducible, gates required, fail-fast
validated config, owned flags with removal plans. Report
"No findings: config and build hygiene are sound". Do NOT demand extra
infrastructure (canaries, hermetic build systems) as a default — they're findings
only when the project's declared risk level calls for them.
