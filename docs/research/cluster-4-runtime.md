# Research — Cluster IV: Cross-cutting runtime qualities
> Part of code-quality-atlas phase-1 research (see ../taxonomy.md). Drafted 2026-06-08 (from model knowledge, web-less subagent); **web-verified 2026-06-09 from the main loop.** Standards spines (OWASP Top 10 2021, OWASP LLM Top 10 2025, CWE Top 25 2024, ASVS 5.0, Core Web Vitals, lethal trifecta) and the high-traffic tool rule IDs (Bandit, gosec) are confirmed against live sources. Residual `(verify)` items are the less-stable ones (exact Semgrep/CodeQL query IDs, Sonar squids).

---

## #14 Security

### Key references
- **OWASP — OWASP Top 10:2021** — https://owasp.org/Top10/ → mine: the canonical risk buckets a review must screen for, in priority order: A01 Broken Access Control, A02 Cryptographic Failures, A03 Injection (XSS folded in here), A04 Insecure Design, A05 Security Misconfiguration, A06 Vulnerable & Outdated Components, A07 Identification & Authentication Failures, A08 Software & Data Integrity Failures (deserialization, supply chain), A09 Security Logging & Monitoring Failures, A10 Server-Side Request Forgery (SSRF). Use as the top-level checklist spine.
- **OWASP — Application Security Verification Standard (ASVS) 5.0** (released **May 2025**) — https://owasp.org/www-project-application-security-verification-standard/ → mine: ~350 testable, per-control requirements across **17 chapters** with a three-tier model. v5.0 **renumbered** vs. v4 and added modern coverage (V3 Web Frontend Security, V9 Self-Contained Tokens, V10 OAuth/OIDC, V17 WebRTC). Each requirement is already phrased as a checkable assertion — ideal seed text for skill checklist items. *(Note: the old V1 Architecture / V2 Auth / V4 Access Control numbering is v4; use 5.0 chapter numbers going forward.)*
- **MITRE — CWE Top 25 Most Dangerous Software Weaknesses (2024)** — https://cwe.mitre.org/top25/archive/2024/2024_cwe_top25.html → mine: weakness-level (not risk-level) granularity for grep/AST rules. **2024 top three: #1 CWE-79 (XSS) — up from #2; #2 CWE-787 (Out-of-bounds Write) — down from #1; #3 CWE-89 (SQL Injection).** Other high entries: CWE-352 (CSRF), CWE-22 (Path Traversal), CWE-78 (OS Command Injection), CWE-862 (Missing Authorization), CWE-918 (SSRF), CWE-502 (Deserialization), CWE-798 (Hardcoded Credentials), CWE-269 (Improper Privilege Management). (Scored frequency × severity over 31,770 CVEs from Jun 2023–Jun 2024.)
- **OWASP — Cheat Sheet Series** — https://cheatsheetseries.owasp.org/ → mine: concrete "do this / not that" remediation patterns (parameterized queries, output encoding contexts, password storage with bcrypt/argon2/scrypt, CSP construction) — the fix half of each finding.
- **OWASP — Proactive Controls** → mine: framing that reviewers should reward positive controls (parameterize, encode, validate, use vetted crypto) rather than only flag negatives.
- **NIST — SP 800-63B Digital Identity Guidelines** → mine: authoritative source for authn rules (password length over composition, no forced periodic rotation, breached-password checks, MFA guidance) — counters folklore review comments.

### Tooling rules worth lifting
- **Semgrep** `tainted-sql-string` / registry `python.lang.security.audit.formatted-sql-query` — taint-flow from request input into a SQL string (SQLi). `(verify)` exact rule IDs.
- **Bandit** (Python) — `B608` `hardcoded_sql_expressions` (string-built SQL → SQLi); `B602` `subprocess_popen_with_shell_equals_true` (command injection); `B301` `pickle` on untrusted data (unsafe deserialization); `B307` `eval` on untrusted data (code injection); `B105`–`B107` hardcoded password string/funcarg/default; `B501` `request_with_no_cert_validation` (`verify=False`, TLS disabled); `B303`/`B324` `hashlib` weak hash (MD5/SHA1). *(plugin names verified against bandit.readthedocs.io)*
- **ESLint `eslint-plugin-security`** `detect-non-literal-fs-filename` (path traversal), `detect-child-process` (command injection), `detect-eval-with-expression`, `detect-non-literal-regexp` (ReDoS surface), `detect-object-injection`.
- **ESLint (React)** `react/no-danger` / `react/no-danger-with-children` — flags `dangerouslySetInnerHTML` (XSS sink).
- **SonarQube / SonarSource** hotspot & vuln rules, e.g. `javascript:S5122` (permissive CORS), `javascript:S2076`/`S2078` (OS command / LDAP injection), `java:S2068` (hardcoded credentials), `java:S5547` (weak/insecure cipher). `(verify)` exact squids.
- **CodeQL** query packs: `js/sql-injection`, `js/path-injection`, `js/reflected-xss`, `js/request-forgery` (SSRF), `py/command-line-injection`, `java/unsafe-deserialization`. `(verify)` exact query IDs.
- **Gitleaks / TruffleHog / `detect-secrets`** — entropy + regex detection of committed API keys, tokens, private keys, connection strings.
- **gosec** (Go) — `G201`/`G202` SQL string format/concat (CWE-89), `G204` subprocess from variable (CWE-78), `G401` weak crypto + `G501` import-blocklist `crypto/md5` (MD5/DES), `G101` hardcoded credentials, `G402`/`G403` insecure TLS / weak RSA (<2048), `G107` HTTP request with variable URL (SSRF surface, CWE-88). *(IDs/CWE mappings verified against securego/gosec)*
- **npm audit / `pip-audit` / OWASP Dependency-Check / Trivy / Grype** — known-CVE detection in declared & transitive deps (maps A06). Trivy also flags IaC misconfig and secrets.
- **brakeman** (Rails) — `SQL`, `CrossSiteScripting`, `MassAssignment`, `Redirect` (open redirect), `RemoteCodeExecution` warning categories.

### Reviewable heuristics (skill-checklist seeds)
- Does any query/command/HTML/path get built by string concatenation or interpolation of request-derived data? If so, demand parameterized queries / contextual output encoding / allow-listed path resolution.
- Every state-changing or data-returning endpoint: is there an explicit authorization check tied to the *resource owner*, not just authentication? (IDOR = authenticated but not authorized.) Object references taken from the request (IDs, filenames) must be authorized, never trusted.
- Are secrets (keys, tokens, passwords, connection strings) absent from source, config-in-repo, and log output? Real secrets belong in a secrets manager / env injected at runtime.
- Is crypto delegated to a vetted library with modern algorithms (AES-GCM/ChaCha20-Poly1305, argon2/bcrypt/scrypt for passwords, ECDSA/Ed25519)? Flag homegrown crypto, ECB mode, MD5/SHA1 for security, static IVs/nonces, and `Math.random()`/non-CSPRNG for tokens.
- Is untrusted input ever deserialized with a format that can instantiate arbitrary types (Java/Python `pickle`/PHP unserialize/unsafe YAML)? Prefer data-only formats (JSON) with schema validation.
- For any server-side fetch of a URL/host derived from user input: is the target allow-listed and are internal/metadata addresses (169.254.169.254, link-local, RFC1918, localhost) blocked? (SSRF / A10.)
- Are state-changing requests protected against CSRF (same-site cookies + token, or non-cookie auth)? Are cookies `HttpOnly`, `Secure`, `SameSite`?
- Is PII/sensitive data minimized, encrypted at rest/in transit, and kept out of logs, URLs, and error messages? (Cross-links #27 and #16.)
- Safe defaults: deny-by-default access, TLS verification on, debug/stack traces off in prod, CORS not `*` with credentials, no default/sample credentials shipped.
- Least privilege: does the code/service request the narrowest scopes, file perms, DB grants, and cloud IAM roles it needs? Flag wildcard IAM policies and over-broad DB users.
- New/updated dependency: is it from a reputable source, recently maintained, free of known CVEs, and pinned via lockfile? (Cross-links #18.)
- Is security-relevant activity (auth success/failure, access-control denials, high-value mutations) logged in a way that's actually monitorable (A09) — without logging the sensitive payload itself?

---

## #15 Performance & efficiency

### Key references
- **Brendan Gregg — Systems Performance (and the USE method)** — http://www.brendangregg.com/usemethod.html → mine: measure before optimizing; for each resource check Utilization, Saturation, Errors. Anchors the "profile, don't guess" discipline reviews should enforce.
- **Donald Knuth — "Structured Programming with go to Statements" (1974)** → mine: the actual provenance of "premature optimization is the root of all evil (97% of the time)" — and its often-dropped corollary: *do* optimize the critical 3%. Use to keep the counterweight balanced, not absolutist.
- **Martin Fowler — "Yet Another Optimization Article" / refactoring + performance writing** → mine: optimize against a measured performance profile, not intuition; keep code clean first because clean code is easier to make fast.
- **Brendan Gregg — Flame Graphs** — https://www.brendangregg.com/flamegraphs.html → mine: hot-path identification is visual and data-driven; a review claiming a perf problem should be able to point at a profile, not a vibe.
- **web.dev — Core Web Vitals (LCP, INP, CLS)** — https://web.dev/articles/vitals/ → mine: the canonical, user-centric frontend perf budget, judged at the **p75** of real users. Thresholds: **LCP ≤ 2.5s** (loading), **INP ≤ 200ms** (responsiveness — **replaced FID on 2024-03-12**), **CLS ≤ 0.1** (visual stability). Bundle/startup work should be justified against these.
- **AWS / FinOps Foundation — FinOps Framework** — https://www.finops.org/ → mine: cloud-cost as a first-class efficiency axis (right-sizing, egress, idle resources, per-request cost) — the FinOps facet of #15.

### Tooling rules worth lifting
- **ESLint `eslint-plugin-react`** `react/jsx-no-bind` and **`react-hooks/exhaustive-deps`** — inline closures / wrong deps cause needless re-renders & re-allocation on the render hot path.
- **ESLint** `no-await-in-loop` — sequential awaits in a loop (serialized I/O round-trips that often should be batched/`Promise.all`).
- **RuboCop Performance** cop family, e.g. `Performance/Detect`, `Performance/Count`, `Performance/RedundantMerge`, `Performance/StringReplacement`, `Performance/CollectionLiteralInLoop`, `Performance/MapCompact` — idiomatic-but-slow patterns and allocation in loops.
- **SonarQube** `java:S2864` (don't call both `keySet()` and `get()` — iterate `entrySet()`), and the general "this loop is O(n²)" / "string concatenation in loop" hotspot rules. `(verify)` exact squids.
- **golangci-lint** `prealloc` (slice not preallocated before append in a loop), `bodyclose` (HTTP response body not closed → leak/perf), `ineffassign`, and `gocritic`'s `rangeValCopy`/`hugeParam` (large struct copies).
- **Database / ORM N+1 detectors:** Rails **Bullet** gem (N+1 query and unused-eager-loading detection); Django `nplusone` / `django-debug-toolbar` SQL panel; Hibernate `hibernate.generate_statistics` + N+1 alerts; ent/Prisma query logging. Lift the *pattern*: a list view that issues one query per row.
- **Lighthouse / `lighthouse-ci`** budgets — performance score plus `total-byte-weight`, `unused-javascript`, `render-blocking-resources`, `largest-contentful-paint`, `interaction-to-next-paint` audits as CI gates.
- **`bundlesize` / `size-limit` / webpack-bundle-analyzer** — enforce a max gzipped bundle budget per entrypoint; fail CI on regressions.
- **clippy** (Rust) `clippy::needless_collect`, `clippy::redundant_clone`, `clippy::or_fun_call` (eager arg evaluation) — avoidable allocation/work.
- **DB `EXPLAIN`/`EXPLAIN ANALYZE`** + tools like `pganalyze` / pt-query-digest — surface seq scans, missing indexes, and the literal cost of the hot query.

### Reviewable heuristics (skill-checklist seeds)
- Is there a loop that issues a query/RPC/HTTP call per iteration? (N+1.) Push to a single batched/`IN`/join query or a bulk endpoint. Flag `await` inside `for` over independent items.
- What is the worst-case complexity on the hot path as input grows? Flag accidental O(n²) (nested loops over the same collection, `Array.includes` inside a loop → use a Set/Map), and unbounded growth.
- Is the same expensive value (DB read, computed result, parsed config, compiled regex) recomputed when it could be hoisted or memoized? Conversely, is anything memoized that's cheap and rarely reused (premature)?
- Caching correctness: is there a clear invalidation story (TTL, event-based, or write-through)? A cache without an invalidation answer is a future stale-data bug. Check key construction includes everything that affects the value (tenant, locale, version).
- I/O batching: are round-trips minimized (batch reads/writes, pipelining, HTTP keep-alive/connection pooling) rather than chatty per-item calls?
- Streaming vs buffering: for large payloads/files, is data streamed rather than fully loaded into memory? Flag "read entire file/response into a string then process."
- Allocation/GC pressure on hot paths: avoidable per-iteration allocations, boxing, large defensive copies, building huge intermediate collections? (Especially in tight loops and request handlers.)
- Lazy vs eager: is work deferred until needed (and *only* the needed work done), without re-triggering N+1 via lazy loading inside a loop?
- Frontend: does this change grow the bundle or block startup (new heavy dep, non-code-split route, render-blocking resource, large synchronous work on the main thread hurting INP)? Is the dep tree-shakeable and the import scoped?
- Cloud cost (FinOps): does the change add per-request cost that scales badly (chatty cross-AZ/egress traffic, unbounded fan-out, over-provisioned instances, polling instead of events)?
- **Premature-optimization smell test (counterweight):** Is this off a measured hot path, justified by no profile/benchmark, and does it trade real readability/correctness risk for unmeasured gains (hand-rolled cache, micro-bit-twiddling, denormalization, custom data structure)? If yes, push back and ask for a profile or a benchmark. "Make it correct and clear first; optimize the measured 3%."
- Did a perf claim (either "this is slow" or "this is faster") come with a number — benchmark, profile, or Big-O argument — rather than intuition?

---

## #16 Observability & operability

### Key references
- **Google — Site Reliability Engineering (SRE Book) & SRE Workbook** — https://sre.google/books/ → mine: SLI/SLO/error-budget framing; the "four golden signals" (latency, traffic, errors, saturation) as the default metric set; alert on symptoms (SLO burn) not causes.
- **Charity Majors, Liz Fong-Jones, George Miranda — Observability Engineering (Honeycomb/O'Reilly)** — https://www.honeycomb.io/ → mine: structured, high-cardinality, wide events over unstructured log lines; the ability to ask new questions of production without shipping new code ("unknown-unknowns").
- **OpenTelemetry — specification & semantic conventions** — https://opentelemetry.io/docs/ → mine: vendor-neutral traces/metrics/logs; standardized span/attribute naming and trace-context propagation so observability is portable and correlated.
- **Twelve-Factor App — Logs (factor XI)** — https://12factor.net/logs → mine: treat logs as an event stream written to stdout; the app should not manage log routing/rotation. (Cross-links #26.)
- **Google SRE — "Implementing SLOs" chapter** → mine: error budgets convert reliability into a quantitative, reviewable contract; instrument what the SLO needs (good-vs-total events).
- **RFC 5424 (syslog severities)** → mine: the canonical log-level ladder (DEBUG/INFO/NOTICE/WARNING/ERROR/CRITICAL...) so "what level should this be" has an objective answer.

### Tooling rules worth lifting
- **ESLint** `no-console` — raw `console.log` instead of the project's structured logger (and noise/PII leakage risk). Often paired with a custom rule banning the logger's `debug` in prod paths.
- **`eslint-plugin-no-secrets`** / log-content linters — heuristic detection of secrets or high-entropy strings being logged.
- **golangci-lint** `bodyclose` & `contextcheck` — unclosed resources and missing `context.Context` propagation (the latter breaks trace propagation, deadlines, and cancellation → poor operability).
- **`err113` / `wrapcheck` / `errorlint`** (Go) — errors created/returned without wrapping context (`fmt.Errorf("...: %w", err)`) → unactionable, context-poor errors.
- **SonarQube** rules for logger usage, e.g. `java:S2629` (don't build log message strings when the level is disabled) and rules against logging-and-rethrowing (double logging) / swallowing exceptions silently. `(verify)` squids.
- **`pylint` / `flake8-logging-format` (`G` codes)** — use lazy `%`-style logging args, don't pre-format; don't use f-strings in logging calls (`logging-fstring-interpolation`).
- **`structlog` / Zap / Serilog / SLF4J + Logback** conventions — not linters but the de-facto "structured logging" baseline; a review can require the project's structured logger over `print`/`console`/`puts`.
- **Health-check conventions** — Kubernetes `livenessProbe` vs `readinessProbe` vs `startupProbe`; Spring Boot Actuator `/actuator/health` (liveness & readiness groups). Lift: distinct liveness (am I alive) vs readiness (can I serve traffic) endpoints.
- **OpenTelemetry / Prometheus client linters & `promtool check rules`** — validate metric/recording/alerting rule definitions; enforce metric naming conventions (unit suffixes like `_seconds`, `_bytes`, `_total`).

### Reviewable heuristics (skill-checklist seeds)
- Are logs structured (key-value/JSON) with consistent fields (timestamp, level, service, request/trace ID) rather than interpolated prose? Can you grep/query by field in production?
- Is the log *level* appropriate (no INFO spam in hot loops; real failures at ERROR; nothing security/PII-sensitive logged at any level)? Is there a correlation/trace ID threaded through so one request's logs are linkable?
- Do new failure paths emit a context-rich error (what operation, which inputs/IDs — non-sensitive, the wrapped cause) rather than a bare `error`/stack with no story? Errors should wrap, not swallow, and not be both logged *and* rethrown (double-logging).
- For any new meaningful operation: is it instrumented with at least one of the four golden signals (latency histogram, error counter, throughput)? Are spans created and trace context propagated across service/async boundaries?
- Does a new service/endpoint expose liveness and readiness checks, and do readiness checks actually reflect dependency health (DB/cache reachable) without being so strict they flap?
- Risky/irreversible behavior change: is it behind a feature flag or kill switch so it can be disabled in prod without a redeploy? Is there a documented rollback?
- Startup/shutdown: does the service start only after dependencies are ready, and on shutdown drain in-flight work, stop accepting new requests, flush logs/metrics, and close connections (handle SIGTERM)? (Graceful shutdown.)
- Is there an SLI/SLO implied by this change, and is the data to measure it being emitted (good-event and total-event counts)? Don't alert on causes you can fix later; alert on user-facing symptoms.
- Cardinality discipline: are high-cardinality values (user IDs, raw URLs, emails) used as *event attributes*, not as Prometheus metric *labels* (which explode series count and cost)?
- Are timeouts, retries, and deadlines observable (logged/metered with reason) so on-call can see *why* something is slow or failing, not just that it is?

---

## #25 AI/LLM-integration quality

> Newest and least tooling-covered category — covered deeper per scope. Today there is little mature static analysis here; most "rules" are framework-level validators, eval harnesses, and emerging security scanners rather than classic linters, so the heuristics carry more weight than the tooling list.

### Key references
- **OWASP — Top 10 for LLM Applications (2025)** — https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/ → mine: the security spine for LLM features. **Verified 2025 list:** LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Supply Chain, LLM04 Data and Model Poisoning, LLM05 Improper Output Handling, LLM06 Excessive Agency, LLM07 System Prompt Leakage, LLM08 Vector and Embedding Weaknesses, LLM09 Misinformation, LLM10 Unbounded Consumption. (LLM06 Excessive Agency was notably expanded into excessive *functionality*, *permissions*, and *autonomy*.)
- **NIST — AI Risk Management Framework (AI RMF 1.0, SP 100-1) + Generative AI Profile (NIST-AI-600-1)** — https://www.nist.gov/itl/ai-risk-management-framework → mine: the Govern / Map / Measure / Manage functions and the GenAI-specific risk profile — a governance/eval vocabulary for "did we test the nondeterministic behavior and bound the risk."
- **Anthropic / OpenAI — prompt-engineering & safety best-practices docs** — e.g. https://docs.anthropic.com/ → mine: delimit and label untrusted input, separate system vs user instructions, structured/tool-use outputs over free-text parsing, and refusal/guardrail design. (Provider-specific model IDs and pricing should be checked against current docs, not memory.)
- **Simon Willison — "The lethal trifecta for AI agents" (2025-06-16)** — https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ → mine: prompt injection is unsolved by prompting alone; the *lethal trifecta* = (access to private data) + (exposure to untrusted content) + (ability to communicate/exfiltrate externally). If a design has all three, treat it as exploitable by default. (Aug 2025 disclosures in Cursor, GitHub Copilot, Claude Code, Devin, Google Jules followed this exact pattern.)
- **Microsoft — Responsible AI / Azure AI Content Safety + "LLM-as-judge" eval guidance** → mine: layered guardrails (input + output classifiers) around the model, not just inside the prompt; using a separate model/rubric to grade outputs at scale.
- **Eugene Yan — "Patterns for Building LLM-based Systems & Products" / "evals" writing** — https://eugeneyan.com/ → mine: concrete engineering patterns — evals first, guardrails, caching, defensive UX for wrong answers, and keeping a golden-set regression suite for prompts.
- **Chip Huyen — "Building LLM applications for production" / *AI Engineering*** — https://huyenchip.com/ → mine: production concerns — prompt versioning, eval pipelines, cost/latency tradeoffs, and treating prompts + models as versioned, testable artifacts.

### Tooling rules worth lifting
*(This space is young; many "rules" are validators/frameworks/scanners rather than classic lint IDs. IDs `(verify)`.)*
- **Pydantic / `instructor` / Zod / OpenAI structured outputs / JSON-Schema response_format** — enforce a schema on model output and reject/repair non-conforming responses. The reviewable rule: *no model output is consumed without schema validation.*
- **Guardrails AI** (`guardrails-ai`) — declarative output validators/"validators" (regex, JSON schema, PII, toxicity, competitor-mention, on-topic) with re-ask on failure. Lift the catalog of validator types as checklist items.
- **NeMo Guardrails** (NVIDIA) — programmable input/output "rails" (topical, safety, jailbreak-detection rails) wrapping the LLM call.
- **Rebuff / LLM Guard (Protect AI) / Lakera Guard / `promptmap`** — prompt-injection & jailbreak detection, plus PII/secret scrubbing on inputs and outputs. LLM Guard is a modular input/output scanner layer (sanitization, prompt-injection resistance, secret filtering, data-leak prevention); input scanners include `PromptInjection`, `Anonymize`, `BanSubstrings` and output scanners include `Sensitive`, `NoRefusal`, `Relevance` `(verify exact scanner names)`.
- **garak** (NVIDIA) — LLM vulnerability scanner: probes for prompt injection, jailbreak, data leakage, toxicity — an automated red-team in CI.
- **Eval harnesses** — `promptfoo` (declarative test cases + assertions + red-team, CI-friendly), OpenAI **Evals**, **DeepEval** (`deepeval`, pytest-style metrics: faithfulness, answer-relevancy, hallucination, G-Eval), **Ragas** (RAG metrics: faithfulness, context precision/recall), **TruLens**. Lift: prompts ship with a regression eval suite and assertion thresholds.
- **LangSmith / Langfuse / Phoenix (Arize) / Helicone** — tracing, prompt/version tracking, token-cost accounting, and dataset-backed evals for LLM calls (observability for #25, overlapping #16).
- **Semgrep / CodeQL emerging LLM rules** — e.g. flagging untrusted/user data concatenated directly into a prompt template, or model output passed to `eval`/shell/SQL without validation (LLM05 Improper Output Handling). `(verify)` — coverage is partial and rule IDs unstable.
- **`detect-secrets` / DLP scanners on the request path** — ensure PII/secrets aren't shipped to a third-party model API (overlaps #14/#27).

### Reviewable heuristics (skill-checklist seeds)
- **Untrusted-input surface:** Is any content the model sees that originates from an untrusted source (user text, retrieved docs/RAG, web pages, tool results, file uploads) clearly *delimited and labeled as data, not instructions*? Assume it can contain injected instructions; the system prompt must not say "do whatever the document says."
- **Lethal-trifecta check:** Does this feature combine access to private/sensitive data + exposure to untrusted content + an ability to exfiltrate or take consequential actions (send email, call tools, make requests)? If all three, treat injection as exploitable and require mitigations (human-in-the-loop, egress allow-list, capability scoping). (Maps LLM01/LLM06 Excessive Agency.)
- **Structured-output validation:** Is every model output that drives code/decisions validated against a schema (types, enums, ranges) and safely handled on validation failure (re-ask, fallback, reject) — never trusted as free text or blindly `JSON.parse`d? (Maps LLM05.)
- **Output as a sink:** Is model output ever passed to a dangerous sink (shell, SQL, `eval`, HTML render, file path, code exec, downstream API auth) without the same treatment you'd give raw user input? It must be sanitized/encoded/parameterized exactly like untrusted input.
- **Eval coverage for nondeterminism:** Is there an eval/regression suite (golden set + assertions/metrics) so prompt or model changes can be measured, not vibe-checked? Are there test cases for failure modes (refusals, hallucination, injection attempts, malformed output)?
- **Model & prompt versioning/pinning:** Is the model identifier pinned (not a floating "latest" alias) and is the prompt template versioned in source control? Can you reproduce a past output's prompt+model? Is there a plan for provider model deprecations?
- **Determinism discipline:** Is `temperature` (and top-p/seed where available) set deliberately — low/zero for extraction/classification/tool-routing, higher only where creativity is wanted? Don't leave a default temperature on a task that needs reproducibility.
- **Timeouts / retries / fallbacks:** Does every model call have a timeout, bounded retries with backoff (idempotent-safe), and a defined fallback when the model is slow/unavailable/over budget (cached answer, smaller model, deterministic path, graceful "can't do that right now")? (Maps LLM10 Unbounded Consumption.)
- **Cost & token efficiency:** Are token usage and spend bounded and observable — context trimmed/summarized, `max_tokens` capped, retrieval top-k bounded, prompt-caching used where supported, batching where possible? Is there a per-user/per-request budget guard against runaway loops (agent step caps)?
- **PII / data egress to third-party models:** Is sensitive data (PII, secrets, regulated data) minimized or redacted before being sent to an external model API? Is the provider's data-retention/training-use setting appropriate, and is this allowed under the data's compliance constraints? (Overlaps #14/#27.)
- **Response caching correctness:** If responses are cached, does the cache key include the full prompt, model, and all params (so a prompt/model change doesn't serve stale outputs), and is caching disabled/scoped for user-specific or sensitive responses?
- **Guardrails & refusal handling:** Are there input *and* output guardrails (moderation/PII/topic/jailbreak) outside the prompt, and does the app handle a refusal or a low-confidence answer gracefully (don't render a refusal as data; have a fallback path)?
- **Graceful degradation when the model is wrong:** Does the UX/flow assume the model can be confidently wrong? Are high-stakes outputs gated by human review, confidence thresholds, citations/grounding, or a deterministic cross-check rather than auto-applied?
- **System-prompt secrecy (don't over-rely):** System prompts and "hidden" instructions can leak (LLM07) — don't put secrets, credentials, or the only security control inside the prompt. Treat the prompt as visible.
- **Supply chain (LLM03/LLM04):** Are third-party models, fine-tunes, embeddings, and prompt/tool plugins from trusted, pinned sources? Untrusted models/datasets can be poisoned.

---

## Open threads (gaps / mis-placements / sub-topics worth deeper research)

- **Sourcing status (was a gap):** the draft's standards spines and high-traffic rule IDs are now **web-verified (2026-06-09)** — CWE 2024 ranks, ASVS 5.0 (17 chapters), OWASP LLM Top 10 2025, Bandit/gosec IDs, Core Web Vitals, lethal trifecta. Residual `(verify)`: exact Semgrep/CodeQL query IDs, Sonar squids, LLM-Guard scanner names — these churn fastest and should be confirmed at skill-build time.
- **Security ↔ Dependencies/Supply chain (#14 ↔ #18):** A06 Vulnerable Components and CVE scanning live in both #14 and #18; LLM03 (LLM supply chain) and #25 also overlap. Decide which skill *owns* dependency-CVE review so it isn't done twice or dropped between them.
- **Security ↔ Compliance/PII (#14 ↔ #27):** PII handling, data residency/retention, and "PII sent to third-party models" (#25) straddle #14, #25, and #27. The map currently has PII handling under #14 and regulatory obligations under #27 — a review skill will need an explicit hand-off rule.
- **Observability ↔ Configuration (#16 ↔ #26):** Twelve-factor logging, feature-flag lifecycle/stale-flag cleanup, and graceful startup/shutdown appear in both #16 and #26. The taxonomy already notes flags live in #12/#16/#26 — worth a single canonical home for "feature-flag hygiene."
- **SLO/error-budget straddles #16 and #24:** As the taxonomy's residual-candidates note flags, SLO/error-budget framing is partly a process concern. The observability skill should *instrument* SLIs; the process skill should own the budget policy. Clarify the seam.
- **Performance counterweight is hard to lint:** "Premature optimization" is almost entirely a heuristic/judgment call with essentially no tooling support (unlike most categories). The skill will likely need an LLM-judgment check ("is there a profile/benchmark justifying this?") rather than a rule — note for phase-2 skill design, and mirrors the #11 premature-abstraction counterweight problem.
- **#25 is tooling-thin and fast-moving:** Unlike #14–#16, classic static analysis barely covers LLM integration; the leverage is in eval harnesses, output-schema enforcement, and guardrail frameworks. Tool/IDs here will churn fastest of any category — design the skill to assert *behaviors* (validate output, pin model, bound cost, label untrusted input) rather than name specific tools.
- **Agentic/tool-use risk may deserve its own factor:** "Excessive Agency" (LLM06) + the lethal-trifecta pattern (autonomous tool-calling agents acting on untrusted input) is arguably bigger than a sub-bullet of #25 and cross-cuts #14 (authz of tool actions) and #13 (API contracts the agent calls). Candidate for promotion or an explicit cross-link as agent features proliferate.
