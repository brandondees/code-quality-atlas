# Depth Modes & Relevance Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the router's 2–4 lens *cap* with a relevance-**ranked** list plus three depth **modes** (triage / review / comprehensive), each with a severity floor, all declared in a new manifest `modes:` section and rendered into the generated router and synthesizer — so a reviewer can ask for "all relevant lenses" and the long-tail findings actually surface.

**Architecture:** A new `Mode` dataclass + a `modes:` manifest section (generated content, `built_from: []`, like `router:`/`synthesizer:`). `tooling/manifest.py` parses and validates it; `tooling/generate.py` renders (a) a "Depth modes" section into `choosing-review-lenses/SKILL.md` that separates *relevance* (which lenses apply) from *breadth* (how many to run), and (b) a per-mode severity-floor policy into `synthesizing-review-findings/SKILL.md`. This is the first half of Q20 / resolves D16's relevance-vs-depth split; the collapsed-entrypoint emission is a separate follow-up plan that reuses this routing model. Spec: [`docs/collapsed-entrypoints-and-depth-modes.md`](../collapsed-entrypoints-and-depth-modes.md).

**Tech Stack:** Python 3.11+, PyYAML, pytest. Stdlib `dataclasses`, `pathlib`. Generated artifacts are plain markdown (model/harness-agnostic, D7).

---

## File Structure

- **`tooling/manifest.py`** — add `Mode` dataclass; add `modes: list[Mode]` to `Manifest`; parse `modes:` in `load_manifest`; validate modes in `validate`. (Existing file; follow its dataclass + validation idiom.)
- **`tooling/generate.py`** — add pure helpers `modes_section(manifest) -> str` and `mode_floor_policy(manifest) -> str`; call them from `build_router_md` and `build_synthesizer_md`. (Existing file.)
- **`skills/manifest.yaml`** — add the `modes:` section (triage / review / comprehensive).
- **`tests/test_manifest.py`**, **`tests/test_generate.py`** — new tests mirroring the existing `_skill()` / `tmp_path` idiom.
- **Regenerated:** `skills/choosing-review-lenses/SKILL.md`, `skills/synthesizing-review-findings/SKILL.md` (via `python -m tooling.cli generate`).

Each task produces a self-contained, committed change.

---

### Task 1: `Mode` dataclass + manifest parsing

**Files:**

- Modify: `tooling/manifest.py` (add dataclass near `Tension`/`Synthesizer` ~lines 81–101; extend `Manifest`; extend `load_manifest` ~lines 278–347)
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_manifest.py`:

```python
def _write_manifest(tmp_path, body: str) -> str:
    p = tmp_path / "manifest.yaml"
    p.write_text(
        "taxonomy_version: v0\n"
        "skills:\n"
        "  - name: hunting-silent-failures\n"
        "    description: x\n"
        "    shape: diff\n"
        "    wave: 1\n"
        "    built_from:\n"
        "      - { category: 2, source: tests/fixtures/research_sample.md#2 }\n"
        + body
    )
    return str(p)

def test_load_manifest_parses_modes(tmp_path):
    body = (
        "modes:\n"
        "  - name: triage\n"
        "    breadth: critical tier only\n"
        "    floor: Major\n"
        "    triggers: [triage, quick review]\n"
        "  - name: review\n"
        "    breadth: top 2-4 by relevance\n"
        "    floor: escalating\n"
        "    triggers: [review, review this PR]\n"
        "  - name: comprehensive\n"
        "    breadth: every relevant lens, uncapped\n"
        "    floor: Nit\n"
        "    triggers: [thorough, use all relevant lenses]\n"
    )
    m = load_manifest(_write_manifest(tmp_path, body))
    assert [mode.name for mode in m.modes] == ["triage", "review", "comprehensive"]
    assert m.modes[0].floor == "Major"
    assert m.modes[2].triggers == ["thorough", "use all relevant lenses"]

def test_load_manifest_defaults_modes_to_empty(tmp_path):
    m = load_manifest(_write_manifest(tmp_path, ""))
    assert m.modes == []
```

Ensure `Mode` is importable: update the import line at the top of `tests/test_manifest.py` to include `Mode` (e.g. `from tooling.manifest import ..., Mode, ...`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest.py::test_load_manifest_parses_modes -v`
Expected: FAIL with `ImportError: cannot import name 'Mode'` (or `AttributeError: ... 'Manifest' object has no attribute 'modes'`).

- [ ] **Step 3: Add the `Mode` dataclass and `Manifest.modes` field**

In `tooling/manifest.py`, add after the `Tension` dataclass (~line 85), before `Synthesizer`:

```python
@dataclass
class Mode:
    """A review-depth mode: how *much* to run and at what severity floor.

    `breadth` is a human-readable selector label rendered into the router.
    `floor` is a severity level from the synthesizer's `severity_order`
    (pin the floor at that level) or the literal "escalating" (the
    round-based default). `triggers` are natural-language phrases that
    select this mode in the entrypoint/router body (D7-portable).
    """
    name: str
    breadth: str
    floor: str
    triggers: list[str]
    note: str = ""
```

Then extend `Manifest` (~lines 96–101) to add the field (keep existing fields):

```python
@dataclass
class Manifest:
    taxonomy_version: str
    skills: list[Skill]
    router: Router | None = None
    synthesizer: Synthesizer | None = None
    modes: list[Mode] = field(default_factory=list)
```

(`field` is already imported in this module — it's used by `Skill.cross_ref`. If not, add `from dataclasses import dataclass, field`.)

- [ ] **Step 4: Parse `modes:` in `load_manifest`**

In `tooling/manifest.py`, inside `load_manifest` where `router` and `synthesizer` are constructed from the parsed YAML dict (~lines 320–345, just before `return Manifest(...)`), add:

```python
    modes: list[Mode] = []
    for i, raw_mode in enumerate(data.get("modes", []) or []):
        try:
            modes.append(Mode(
                name=raw_mode["name"],
                breadth=raw_mode["breadth"],
                floor=raw_mode["floor"],
                triggers=list(raw_mode.get("triggers", [])),
                note=raw_mode.get("note", ""),
            ))
        except (KeyError, TypeError) as e:
            raise ValidationError(f"modes[{i}] in {path}: malformed mode ({e})")
```

Then pass it through the existing `return Manifest(...)` call:

```python
    return Manifest(
        taxonomy_version=taxonomy_version,
        skills=skills,
        router=router,
        synthesizer=synthesizer,
        modes=modes,
    )
```

(Match the existing keyword/positional style of the current `return Manifest(...)` — only add `modes=modes`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_manifest.py -v -k modes`
Expected: PASS (both `test_load_manifest_parses_modes` and `test_load_manifest_defaults_modes_to_empty`).

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `python -m pytest -q`
Expected: all pass (was 112; now 114).

- [ ] **Step 7: Commit**

```bash
git add tooling/manifest.py tests/test_manifest.py
git commit -m "feat: parse modes: section into Mode dataclass on Manifest"
```

---

### Task 2: Validate modes

**Files:**

- Modify: `tooling/manifest.py` (`validate`, ~lines 112–231 — add a modes block near the synthesizer validation)
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_manifest.py` (the file already imports `Synthesizer`; add `Mode` if not already added in Task 1):

```python
def _syn():
    from tooling.manifest import Synthesizer
    return Synthesizer(name="synthesizing-review-findings", description="d",
                       severity_order=["Blocker", "Major", "Minor", "Nit"], tensions=[])

def test_validate_accepts_modes_with_known_floors():
    modes = [
        Mode(name="triage", breadth="critical tier only", floor="Major", triggers=["triage"]),
        Mode(name="review", breadth="top 2-4", floor="escalating", triggers=["review"]),
        Mode(name="comprehensive", breadth="all relevant", floor="Nit", triggers=["thorough"]),
    ]
    validate(Manifest("v0", [_skill()], synthesizer=_syn(), modes=modes), docs_root="/")  # no raise

def test_validate_rejects_unknown_mode_floor():
    bad = [Mode(name="triage", breadth="critical tier only", floor="Bogus", triggers=["triage"])]
    with pytest.raises(ValidationError, match="floor"):
        validate(Manifest("v0", [_skill()], synthesizer=_syn(), modes=bad), docs_root="/")

def test_validate_rejects_duplicate_mode_names():
    dup = [
        Mode(name="review", breadth="b", floor="escalating", triggers=["review"]),
        Mode(name="review", breadth="b2", floor="Nit", triggers=["thorough"]),
    ]
    with pytest.raises(ValidationError, match="duplicate mode"):
        validate(Manifest("v0", [_skill()], synthesizer=_syn(), modes=dup), docs_root="/")

def test_validate_rejects_mode_without_triggers():
    bad = [Mode(name="review", breadth="b", floor="escalating", triggers=[])]
    with pytest.raises(ValidationError, match="trigger"):
        validate(Manifest("v0", [_skill()], synthesizer=_syn(), modes=bad), docs_root="/")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_manifest.py -v -k "mode and validate"`
Expected: FAIL — `test_validate_rejects_unknown_mode_floor` etc. fail because `validate` does not yet check modes (the "accepts" test passes vacuously; the three "rejects" tests fail by not raising).

- [ ] **Step 3: Add modes validation to `validate`**

In `tooling/manifest.py`, inside `validate(...)`, after the synthesizer validation block (near the end, ~line 230, before the function returns), add:

```python
    if manifest.modes:
        allowed_floors = set()
        if manifest.synthesizer:
            allowed_floors = set(manifest.synthesizer.severity_order)
        allowed_floors.add("escalating")
        seen_modes: set[str] = set()
        for mode in manifest.modes:
            if mode.name in seen_modes:
                raise ValidationError(f"duplicate mode name: {mode.name}")
            seen_modes.add(mode.name)
            if not mode.breadth.strip():
                raise ValidationError(f"mode {mode.name}: breadth must be non-empty")
            if not mode.triggers:
                raise ValidationError(f"mode {mode.name}: needs at least one trigger phrase")
            if mode.floor not in allowed_floors:
                raise ValidationError(
                    f"mode {mode.name}: floor {mode.floor!r} is not a severity level "
                    f"in severity_order nor 'escalating' ({sorted(allowed_floors)})"
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_manifest.py -v -k "mode and validate"`
Expected: PASS (all four).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tooling/manifest.py tests/test_manifest.py
git commit -m "feat: validate modes — unique names, non-empty triggers/breadth, floor in severity_order"
```

---

### Task 3: Author the `modes:` section in the real manifest

**Files:**

- Modify: `skills/manifest.yaml` (add a top-level `modes:` section after `synthesizer:`)
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_manifest.py`:

```python
def test_real_manifest_declares_three_modes():
    m = load_manifest("skills/manifest.yaml")
    names = [mode.name for mode in m.modes]
    assert names == ["triage", "review", "comprehensive"]
    # comprehensive must pin the floor at the least-severe level so long-tail findings surface
    assert m.synthesizer is not None
    least_severe = m.synthesizer.severity_order[-1]
    comprehensive = next(mode for mode in m.modes if mode.name == "comprehensive")
    assert comprehensive.floor == least_severe
    review = next(mode for mode in m.modes if mode.name == "review")
    assert review.floor == "escalating"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest.py::test_real_manifest_declares_three_modes -v`
Expected: FAIL — `assert [] == ["triage", "review", "comprehensive"]` (no modes yet).

- [ ] **Step 3: Add the `modes:` section to `skills/manifest.yaml`**

Append at the top level of `skills/manifest.yaml` (after the `synthesizer:` section; same indentation level as `router:`/`synthesizer:`). Use block scalars for any value with punctuation to stay clear of the comment-truncation guard:

```yaml
modes:
  - name: triage
    breadth: >
      the critical tier only — correctness, security, data-safety, and concurrency
    floor: Major
    triggers: [triage, quick review, fast check, pre-merge gate]
    note: >
      A pre-merge gate: run only the critical-tier lenses and report Major and above.
  - name: review
    breadth: >
      the top 2-4 lenses by relevance (the default; overridable)
    floor: escalating
    triggers: [review, review this, code review, review this PR, review the diff]
    note: >
      Default per-PR depth: relevance-ranked top-N with the round-based escalating floor.
  - name: comprehensive
    breadth: >
      every relevant lens, uncapped — the full audit set at repo scope
    floor: Nit
    triggers: [thorough, comprehensive, deep review, use all relevant lenses, review everything]
    note: >
      On-demand or scheduled: run all relevant lenses and pin the floor at Nit so
      readability-class and other long-tail findings surface instead of being trimmed.
```

- [ ] **Step 4: Run test + validate the real manifest loads**

Run: `python -m pytest tests/test_manifest.py::test_real_manifest_declares_three_modes -v`
Expected: PASS.

Run: `python -m tooling.cli generate --manifest skills/manifest.yaml --docs-root . --skills-root skills`
Expected: exits 0 (validation passes — proves the new `modes:` block is well-formed and the floors are valid against `severity_order`). This regenerates skills; the router/synthesizer changes land in Tasks 4–5, so for now just confirm exit 0, then discard unintended regen noise:

```bash
git checkout -- skills/   # discard regen output; modes render is added in Tasks 4-5
```

- [ ] **Step 5: Commit (manifest data only)**

```bash
git add skills/manifest.yaml tests/test_manifest.py
git commit -m "feat: declare triage/review/comprehensive modes in manifest"
```

---

### Task 4: Render the Depth-modes section into the router

**Files:**

- Modify: `tooling/generate.py` (add `modes_section`; call it in `build_router_md`, ~lines 338–416)
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generate.py` (import what you need: `from tooling.manifest import Manifest, Route, Router, Mode, Skill, Source`; `from tooling.generate import build_router_md, modes_section`):

```python
def _router_manifest(modes=None):
    skill = _skill(picker="Where do errors vanish?")
    router = Router(
        name="choosing-review-lenses", description="route a change to lenses",
        routes=[Route(when="Bug fix", run=["hunting-silent-failures"])], body="",
    )
    return Manifest("v0", [skill], router=router, modes=modes or [])

def _modes():
    return [
        Mode(name="triage", breadth="the critical tier only", floor="Major", triggers=["triage", "quick review"]),
        Mode(name="review", breadth="the top 2-4 lenses by relevance", floor="escalating", triggers=["review"]),
        Mode(name="comprehensive", breadth="every relevant lens, uncapped", floor="Nit",
             triggers=["thorough", "use all relevant lenses"]),
    ]

def test_modes_section_renders_three_modes_and_triggers():
    md = modes_section(_router_manifest(_modes()))
    assert "## Depth modes" in md
    for name in ("triage", "review", "comprehensive"):
        assert name in md
    assert "every relevant lens, uncapped" in md
    assert "use all relevant lenses" in md           # a trigger phrase is shown
    assert "relevance" in md and "breadth" in md      # separates relevance from breadth

def test_modes_section_empty_when_no_modes():
    assert modes_section(_router_manifest([])) == ""

def test_build_router_md_includes_modes_section():
    md = build_router_md(_router_manifest(_modes()))
    assert "## Depth modes" in md
    assert "comprehensive" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generate.py -v -k modes`
Expected: FAIL — `ImportError: cannot import name 'modes_section'`.

- [ ] **Step 3: Implement `modes_section` and call it from `build_router_md`**

In `tooling/generate.py`, add this pure helper (place it above `build_router_md`):

```python
def modes_section(manifest: Manifest) -> str:
    """The 'Depth modes' block for the router: separates relevance (which lenses
    apply) from breadth (how many to run). Empty string when no modes declared."""
    if not manifest.modes:
        return ""
    lines = [
        "## Depth modes",
        "",
        "Routing first ranks **every** lens whose scope the change touches by "
        "**relevance** — it is no longer a hard 2-4 cap. A depth mode then sets the "
        "**breadth** (how far down the ranked list to run) and the severity floor. "
        "Pick the mode from the request; default to **review**.",
        "",
        "| Mode | Breadth | Triggers |",
        "|---|---|---|",
    ]
    for mode in manifest.modes:
        triggers = ", ".join(f"\"{t}\"" for t in mode.triggers)
        lines.append(f"| **{mode.name}** | {mode.breadth.strip()} | {triggers} |")
    return "\n".join(lines).rstrip() + "\n\n"   # block ends with a blank line; "" when no modes
```

`build_router_md` assembles one f-string `body` and ends with `return f"---\n{fm}\n---\n\n{body}"`. Insert the modes block immediately before the Routes table. **Find this exact line in `build_router_md`:**

```python
        + "\n## Routes\n\n"
```

**and replace it with:**

```python
        + "\n" + modes_section(manifest)
        + "## Routes\n\n"
```

When `manifest.modes` is empty, `modes_section` returns `""`, so this collapses to the original `"\n## Routes\n\n"` — byte-identical output, no regression for manifests without modes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_generate.py -v -k modes`
Expected: PASS (all three).

- [ ] **Step 5: Soften the legacy 2-4 "cap" wording in the router prose**

The "How to pick" text in `build_router_md` currently calls the 2-4 figure "this router's recommendation, not a hard cap." Update that sentence so it explicitly defers to the modes: change it to read (find the existing "The 2-4 figure is for focused single-change review only" sentence and adjust its tail) to end with: "— it is the **review** mode default; see **Depth modes** below for triage and comprehensive (all relevant lenses)."

Add an assertion to lock it in (append to `tests/test_generate.py`):

```python
def test_router_points_2to4_at_review_mode():
    md = build_router_md(_router_manifest(_modes()))
    assert "review** mode default" in md or "review mode default" in md
```

Run: `python -m pytest tests/test_generate.py::test_router_points_2to4_at_review_mode -v`
Expected: PASS (adjust the prose until it does).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tooling/generate.py tests/test_generate.py
git commit -m "feat: render Depth modes section into the router; relevance-rank not cap"
```

---

### Task 5: Render the per-mode severity-floor policy into the synthesizer

**Files:**

- Modify: `tooling/generate.py` (add `mode_floor_policy`; call it in `build_synthesizer_md`, ~lines 430–621)
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generate.py` (import `Synthesizer`, `Tension` as needed; `from tooling.generate import build_synthesizer_md, mode_floor_policy`):

```python
def _syn_manifest(modes=None):
    from tooling.manifest import Synthesizer
    syn = Synthesizer(name="synthesizing-review-findings", description="merge findings",
                      severity_order=["Blocker", "Major", "Minor", "Nit"], tensions=[])
    return Manifest("v0", [_skill(picker="p")], synthesizer=syn, modes=modes or [])

def test_mode_floor_policy_maps_each_mode_to_a_floor():
    md = mode_floor_policy(_syn_manifest(_modes()))
    assert "## Severity floor by mode" in md
    assert "triage" in md and "Major" in md
    assert "review" in md and "escalating" in md
    # comprehensive pins at the least-severe level
    assert "comprehensive" in md and "Nit" in md
    assert "pinned" in md.lower()      # comprehensive shows everything down to the floor

def test_mode_floor_policy_empty_when_no_modes():
    assert mode_floor_policy(_syn_manifest([])) == ""

def test_build_synthesizer_md_includes_floor_policy():
    md = build_synthesizer_md(_syn_manifest(_modes()))
    assert "## Severity floor by mode" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generate.py -v -k floor`
Expected: FAIL — `ImportError: cannot import name 'mode_floor_policy'`.

- [ ] **Step 3: Implement `mode_floor_policy` and call it from `build_synthesizer_md`**

In `tooling/generate.py`, add (above `build_synthesizer_md`):

```python
def mode_floor_policy(manifest: Manifest) -> str:
    """The synthesizer's per-mode severity-floor policy. Empty when no modes.
    `escalating` keeps today's round-based floor; any other value pins the floor
    at that severity level (findings below it are dropped from the merged report)."""
    if not manifest.modes:
        return ""
    lines = [
        "## Severity floor by mode",
        "",
        "The merged report's severity floor depends on the active depth mode. "
        "Below the floor, findings are omitted from the verdict.",
        "",
        "| Mode | Floor | Effect |",
        "|---|---|---|",
    ]
    for mode in manifest.modes:
        if mode.floor == "escalating":
            effect = "round-based escalation (as today) — later re-review rounds raise the floor"
        else:
            effect = f"pinned at {mode.floor} — report everything down to {mode.floor}, nothing below"
        lines.append(f"| **{mode.name}** | {mode.floor} | {effect} |")
    return "\n".join(lines).rstrip() + "\n\n"   # block ends with a blank line; "" when no modes
```

`build_synthesizer_md` also assembles one f-string `body` ending in `return f"---\n{fm}\n---\n\n{body}"`. Insert the floor policy just before the "Reviewer discipline" heading. **Find this exact fragment** (the tail of the Output-format paragraph followed by the heading literal, ~lines 605–609):

```python
        "originating lens's output, not restated here.\n\n"
        "## Reviewer discipline\n\n"
```

**and replace it with:**

```python
        "originating lens's output, not restated here.\n\n"
        + mode_floor_policy(manifest)
        + "## Reviewer discipline\n\n"
```

When `manifest.modes` is empty, `mode_floor_policy` returns `""` and the output is byte-identical to today's. (Adjacent string literals concatenate, and mixing `+ func() +` between them is valid Python.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_generate.py -v -k floor`
Expected: PASS (all three).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tooling/generate.py tests/test_generate.py
git commit -m "feat: render per-mode severity-floor policy into the synthesizer"
```

---

### Task 6: Regenerate, verify drift-clean, lint, and full-suite gate

**Files:**

- Regenerated: `skills/choosing-review-lenses/SKILL.md`, `skills/synthesizing-review-findings/SKILL.md`
- (No source changes — this task proves the generated output is in sync and well-formed.)

- [ ] **Step 1: Regenerate the suite**

Run: `python -m tooling.cli generate --manifest skills/manifest.yaml --docs-root . --skills-root skills`
Expected: exits 0, prints `generated skills/...` lines including the router and synthesizer.

- [ ] **Step 2: Confirm only the two composition skills changed**

Run: `git status --short skills/`
Expected: modifications limited to `skills/choosing-review-lenses/SKILL.md` and `skills/synthesizing-review-findings/SKILL.md` (the lens skills are unchanged — modes affect only the router/synthesizer renders). If other skills changed, investigate before continuing.

- [ ] **Step 3: Eyeball the rendered sections**

Run: `python -m pytest -q && grep -n "## Depth modes" skills/choosing-review-lenses/SKILL.md && grep -n "## Severity floor by mode" skills/synthesizing-review-findings/SKILL.md`
Expected: tests pass; both greps return a line number.

- [ ] **Step 4: Drift check is clean**

Run: `python -m tooling.cli drift --skills-root skills --docs-root .`
Expected: exit 0, "No drift" (modes are `built_from: []`, so they don't participate in source-hash drift; the two skills must just match their regenerated form).

- [ ] **Step 5: Markdownlint the regenerated skills**

Run: `npx --no-install markdownlint-cli2 skills/choosing-review-lenses/SKILL.md skills/synthesizing-review-findings/SKILL.md`
Expected: `0 error(s)`. If the rendered tables trip a rule (e.g. MD013 line length is disabled repo-wide; MD056 table columns), fix the helper's output in `tooling/generate.py`, regenerate, and re-lint.

- [ ] **Step 6: Commit the regenerated artifacts**

```bash
git add skills/choosing-review-lenses/SKILL.md skills/synthesizing-review-findings/SKILL.md
git commit -m "chore: regenerate router + synthesizer with depth modes"
```

- [ ] **Step 7: Final full-suite gate**

Run: `python -m pytest -q`
Expected: all pass (≈124 with the new tests).

---

## Done criteria

- `load_manifest("skills/manifest.yaml").modes` yields the three modes; `validate` enforces their invariants.
- `choosing-review-lenses/SKILL.md` carries a **Depth modes** section that frames the 2–4 figure as the *review* default and offers triage + comprehensive (all relevant lenses).
- `synthesizing-review-findings/SKILL.md` carries a **Severity floor by mode** policy (triage Major+, review escalating, comprehensive pinned at Nit).
- Drift-clean, markdownlint-clean, full test suite green.
- D16's relevance/depth separation is implemented on the standalone form. The **collapsed-entrypoint emission** (the second half of Q20) is the next plan and reuses `modes_section` / `mode_floor_policy`.
