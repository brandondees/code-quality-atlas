# Examples — reviewing-agent-legibility

Report each distinct issue as its own numbered finding. When the change is already agent-legible, the entire response is exactly "No findings" — never manufacture a legibility finding for correct, self-contained code.

## Bad → finding (stale agent onboarding)

**Input (diff):** a PR renames the test target but leaves `AGENTS.md` pointing at the old command.

```diff
# Makefile
- test:
-     pytest tests/
+ check:
+     python -m tooling.cli eval && pytest tests/
```

`AGENTS.md` still says: "Run the tests with `make test` before pushing."

**Expected finding:**

1. **Agent-onboarding file now misleads an agent:** the change renamed `make test`
   to `make check` (and added the eval gate), but `AGENTS.md` still documents
   `make test`. An autonomous agent following the onboarding front-door will run a
   dead target and skip the new gate. Keeping the agent onboarding accurate and
   scoped is owned here (the agent analog of #22's README front-door); update
   `AGENTS.md`/`CLAUDE.md` in this same PR.

## Bad → finding (context economy / AST-navigability)

**Input (diff):** a new export format wired through a stringly-keyed registry.

```python
# formats/registry.py  (existing)
REGISTRY = {}
def register(name):
    def deco(fn): REGISTRY[name] = fn; return fn
    return deco

# exporters/csv_v2.py  (new)
@register("csv_v2")
def _export(rows): ...

# api/handler.py  (new branch)
fmt = request.args.get("format")
return REGISTRY[fmt](rows)   # reached only when fmt == "csv_v2"
```

**Expected finding:**

1. **Not a depth-first slice (context economy):** understanding or safely modifying
   the new `csv_v2` path forces an agent to load three distant files — registry,
   exporter, handler — joined only by a bare string. That fragmented read defeats a
   context budget (models retrieve worst from the middle of a long context).
2. **Stringly-typed dispatch defeats navigation:** a grep for `"csv_v2"` is the only
   way to find the binding; an agent can't follow the call statically from handler
   to exporter. Make the binding structurally addressable (direct import or a typed
   enum) and co-locate the slice.

## Bad → finding (agent-hostile megafile + duplication)

**Input (diff):** a PR vendors a 6,200-line generated client as one file and
re-implements an existing helper.

```diff
+ client_generated.py        # 6,200 lines, single file, checked into src
  # api/users.py
+ def _retry(fn, n=3):        # near-duplicate of utils.retry, slightly different
+     for _ in range(n):
+         try: return fn()
+         except Exception: pass
```

**Expected finding:**

1. **Context-budget hazard (giant single file):** the 6,200-line `client_generated.py`
   makes an agent scan a file far larger than a sensible context window to work
   nearby. Split it, or keep the generated artifact out of the navigable tree
   (generate-on-build, or a separate package).
2. **Duplicated parallel copy:** `_retry` diverges from the existing `utils.retry`,
   inviting an agent to edit the wrong one — a legibility regression (xref #21
   change-amplification, #34 duplication). Import the existing helper; route the
   duplication-vs-reuse detail to `checking-idioms-and-consistency` / restraint.

## Good → no finding

**Input (diff):**

```python
# pricing.py  (new module)
def cents_to_display(amount_cents: int, *, currency: str = "USD") -> str:
    """Format integer minor units as a display string. Pure; no I/O."""
    return f"{amount_cents / 100:.2f} {currency}"
```

```diff
# AGENTS.md
  ## Modules
+ - `pricing.py` — money formatting helpers (pure functions).
```

**Expected finding:** None — a self-contained depth-first slice (typed signature, a
local contract docstring, no distant context needed), a retrieval-friendly name, and
the onboarding file kept accurate and scoped. Report "No findings". Do NOT invent
agent-legibility findings on correct code, and do NOT demand an `llms.txt` index or
extra structure this small change doesn't need.
