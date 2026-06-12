# Examples — auditing-config-and-build-hygiene

This skill is repo-shaped: its input is a scan of CI pipelines, build scripts, and
configuration. Report **each distinct defect as its own numbered finding** — never
fold several issues into one line, and never stop at the first one or two. When the
scan is healthy, the entire response is exactly this skill's no-finding sentence
given in the decision rule below — never a numbered list of findings for a healthy scan.

**Decision rule (apply before flagging):** a hygiene finding needs a concrete
defect — a secret in the repo/image, an unpinned action/toolchain, a base image on
`:latest`, a build that depends on machine-local state, a missing or soft-failed
merge gate (`continue-on-error`, `|| true`, `allow_failure`), env-specific code
branches, config read lazily without validation, or a flag with no owner (dead and
unreferenced → delete; live-but-ownerless → assign an owner + removal plan).
Enumerate **every** such defect present in the scan, each as its own finding — pinning
is per-artifact (action SHA, base-image digest, dependency lock are three separate
checks, not one). Do not demand tooling the project's size doesn't warrant. If the
gates run and are required, builds are pinned and reproducible, and config is
injected/validated, report exactly
"No findings: config and build hygiene are sound".

## Bad → finding (CI + image + config)

**Input (build/config scan):**
```text
ci.yml:        uses: actions/checkout@main; tests run but `continue-on-error: true`;
               docker build pulls base image python:latest
Dockerfile:    ENV STRIPE_KEY=sk-prod-...; pip install -r requirements.txt (no lock)
settings.py:   if ENV == "prod": payment_url = "https://pay.internal" else: "http://localhost"
               DEBUG defaults to True; config read at first use, KeyError at runtime
flags.yml:     enable_new_pricing: true  (owner: none, added 14 months ago)
```
**Expected finding:**
1. **Secret baked into the image:** the Stripe key in a Dockerfile `ENV` ships in
   every layer — inject at runtime from a secrets manager and rotate the exposed key.
2. **Unpinned action:** `actions/checkout@main` is a mutable tag — pin it to a full
   commit SHA.
3. **Unpinned base image:** `python:latest` is not reproducible — pin the base-image
   digest (never `:latest`).
4. **No dependency lock:** `pip install` with no lockfile makes the build
   unreproducible and supply-chain-exposed — commit and install from a lock.
5. **Soft-failed merge gate:** `continue-on-error: true` on the test job means a red
   run still merges — the gate enforces nothing; make it blocking, or track the
   exemption with an owner and an expiry.
6. **Env-specific code branch + unsafe default:** the `if ENV == "prod"` fork and
   `DEBUG=True` default break dev/prod parity and fail open — inject URLs via config,
   default to safe values, and validate all config at startup (fail fast, not
   first-use `KeyError`).
7. **Stale flag with no owner:** `enable_new_pricing` has been on 14 months with no
   owner — give flags an owner and a removal plan; this one should be removed.

## Bad → finding (build reproducibility + flags)

**Input (build/config scan):**
```text
build.gradle: java toolchain points at /usr/local/jdk-17 on the build box
install.sh:   wget -qO- https://deps.example/setup.sh | sh   (no version, no checksum)
flags.yml:    legacy_export: false  (owner none; referenced in 0 code paths; 18 months)
              dark_mode_v2: true    (owner none; both branches still maintained; 7 months)
```
**Expected finding:**
1. **Machine-local build dependency:** the Gradle toolchain hardcodes
   `/usr/local/jdk-17`, so the build only works on a box that already has that exact
   path — not hermetic/reproducible. Resolve the JDK through the build tool (a Gradle
   toolchain spec / `.tool-versions`) so any machine gets the same toolchain.
2. **Unpinned installer piped to a shell:** `wget … | sh` with no version pin or
   checksum runs whatever the URL serves at build time — unreproducible and a
   supply-chain risk. Pin a version and verify a checksum before executing.
3. **Dead flag:** `legacy_export` is referenced in zero code paths — delete it; a flag
   nothing reads is pure debt.
4. **Live but ownerless flag:** `dark_mode_v2` has no owner and both branches are
   still maintained — assign an owner and a removal plan so it doesn't rot like the
   dead one.

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
