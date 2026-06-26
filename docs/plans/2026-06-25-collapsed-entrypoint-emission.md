# Collapsed Entrypoint Emission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second emission target — a **collapsed form** of 4 entrypoint skills (`reviewing-a-change`, `auditing-a-repository`, `reviewing-a-decision`, `reviewing-an-artifact`) that bundle the suite's lenses as on-demand `reference/lenses/<lens>/body.md` files — so the suite installs into cloud/account-skill and context-budget-constrained surfaces as 4 skills instead of 35, while the standalone 35 keep shipping unchanged.

**Architecture:** Dual-emit from the one manifest (D6, no drift): keep `generate_skill`/`generate_router`/`generate_synthesizer` as-is; add `generate_collapsed(manifest)` writing a committed `collapsed/` tree (its own `.claude-plugin/plugin.json`, generated) listed as a second plugin in `marketplace.json`. Each entrypoint's `SKILL.md` carries the shape-scoped trigger, the relevance-ranked routing + depth modes (reusing Plan 1's `modes_section`), and instructions to `Read` a lens bundle; lens bundles preserve progressive disclosure (`body.md` → deeper `tool-rules.md`/`sources.md`). Depends on **Plan 1** (`Mode`, `modes_section`, `mode_floor_policy`). Spec: [`docs/collapsed-entrypoints-and-depth-modes.md`](../collapsed-entrypoints-and-depth-modes.md).

**Tech Stack:** Python 3.11+, PyYAML, pytest; Bash 3.2 (distribution scripts). Generated artifacts are plain markdown + JSON.

**Prerequisite:** Plan 1 (depth modes) is merged — `modes_section`, `mode_floor_policy`, and the `Mode`/`modes:` machinery exist.

---

## File Structure

- **`tooling/manifest.py`** — add `Entrypoint` dataclass; `Manifest.entrypoints: list[Entrypoint]`; parse `entrypoints:`; validate them.
- **`tooling/generate.py`** — add `entrypoint_lenses`, `lens_bundle_body`, `generate_lens_bundle`, `build_entrypoint_md`, `build_collapsed_synthesis`, `collapsed_plugin_manifest`, `generate_collapsed`.
- **`tooling/cli.py`** — `generate` also emits the collapsed tree (new `--collapsed-root`, default `collapsed`).
- **`skills/manifest.yaml`** — add the `entrypoints:` section (4 entries).
- **`.claude-plugin/marketplace.json`** — add the static second plugin entry.
- **`collapsed/`** — generated tree (committed): `skills/<entrypoint>/…` + `.claude-plugin/plugin.json`.
- **`tooling/package-account-zips.sh`, `tooling/vendor-skills.sh`** — `--collapsed` flag.
- **`docs/distribution.md`, `docs/install.md`** — which form for which surface; install one form.
- **Tests:** `tests/test_manifest.py`, `tests/test_generate.py`, new `tests/test_collapsed.py`.

---

### Task 1: `Entrypoint` dataclass + parsing

**Files:**

- Modify: `tooling/manifest.py` (add dataclass after `Mode`; extend `Manifest`; extend `load_manifest`)
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_manifest.py` (reuse the `_write_manifest` helper from Plan 1; ensure `Entrypoint` is imported):

```python
def test_load_manifest_parses_entrypoints(tmp_path):
    body = (
        "entrypoints:\n"
        "  - name: reviewing-a-change\n"
        "    description: review a diff/PR/change\n"
        "    shapes: [diff]\n"
        "  - name: reviewing-a-decision\n"
        "    description: review an ADR/RFC/decision\n"
        "    shapes: [decision]\n"
        "    include_design: true\n"
    )
    m = load_manifest(_write_manifest(tmp_path, body))
    assert [e.name for e in m.entrypoints] == ["reviewing-a-change", "reviewing-a-decision"]
    assert m.entrypoints[0].shapes == ["diff"]
    assert m.entrypoints[1].include_design is True
    assert m.entrypoints[0].include_design is False  # default

def test_load_manifest_defaults_entrypoints_to_empty(tmp_path):
    assert load_manifest(_write_manifest(tmp_path, "")).entrypoints == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest.py -v -k entrypoint`
Expected: FAIL — `ImportError: cannot import name 'Entrypoint'`.

- [ ] **Step 3: Add the `Entrypoint` dataclass and `Manifest.entrypoints` field**

In `tooling/manifest.py`, add after the `Mode` dataclass:

```python
@dataclass
class Entrypoint:
    """A collapsed-form entrypoint skill that bundles a review shape's lenses.

    Membership = skills whose `shape` is in `shapes`, plus (when `include_design`)
    the design-capable lenses regardless of shape (so the decision entrypoint can
    carry the ◆ diff lenses). `body` is optional richer when-to-use text."""
    name: str
    description: str
    shapes: list[str]
    include_design: bool = False
    body: str = ""
```

Extend `Manifest` to add the field (keep existing fields + the `modes` field from Plan 1):

```python
    entrypoints: list[Entrypoint] = field(default_factory=list)
```

- [ ] **Step 4: Parse `entrypoints:` in `load_manifest`**

In `load_manifest`, next to the `modes` parsing block (from Plan 1), add:

```python
    entrypoints: list[Entrypoint] = []
    for i, raw_ep in enumerate(data.get("entrypoints", []) or []):
        try:
            shapes = raw_ep["shapes"]
            if not isinstance(shapes, list) or not all(isinstance(x, str) for x in shapes):
                raise ValidationError(
                    f"entrypoints[{i}] in {path}: 'shapes' must be a list of strings "
                    f"(got {shapes!r}) — use 'shapes: [diff]', not 'shapes: diff'")
            entrypoints.append(Entrypoint(
                name=raw_ep["name"],
                description=raw_ep["description"],
                shapes=list(shapes),
                include_design=bool(raw_ep.get("include_design", False)),
                body=raw_ep.get("body", ""),
            ))
        except (KeyError, TypeError) as e:
            raise ValidationError(f"entrypoints[{i}] in {path}: malformed entrypoint ({e})")
```

Pass `entrypoints=entrypoints` into the `return Manifest(...)` call.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_manifest.py -v -k entrypoint`
Expected: PASS (both).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tooling/manifest.py tests/test_manifest.py
git commit -m "feat: parse entrypoints: section into Entrypoint dataclass"
```

---

### Task 2: Validate entrypoints

**Files:**

- Modify: `tooling/manifest.py` (`validate` — add an entrypoints block)
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing tests**

```python
def _eps():
    return [
        Entrypoint(name="reviewing-a-change", description="d", shapes=["diff"]),
        Entrypoint(name="auditing-a-repository", description="d", shapes=["repo"]),
        Entrypoint(name="reviewing-a-decision", description="d", shapes=["decision"], include_design=True),
        Entrypoint(name="reviewing-an-artifact", description="d", shapes=["artifact"]),
    ]

def test_validate_accepts_well_formed_entrypoints():
    skills = [_skill(name="hunting-silent-failures", shape="diff", picker="p")]
    validate(Manifest("v0", skills, entrypoints=_eps()), docs_root="/")  # no raise

def test_validate_rejects_entrypoint_name_colliding_with_skill():
    eps = [Entrypoint(name="hunting-silent-failures", description="d", shapes=["diff"])]
    with pytest.raises(ValidationError, match="collides"):
        validate(Manifest("v0", [_skill(picker="p")], entrypoints=eps), docs_root="/")

def test_validate_rejects_unknown_entrypoint_shape():
    eps = [Entrypoint(name="reviewing-a-change", description="d", shapes=["bogus"])]
    with pytest.raises(ValidationError, match="shape"):
        validate(Manifest("v0", [_skill(picker="p")], entrypoints=eps), docs_root="/")

def test_validate_rejects_orphaned_lens():
    # a diff lens exists but no entrypoint covers the diff shape → orphan
    skills = [_skill(name="hunting-silent-failures", shape="diff", picker="p")]
    eps = [Entrypoint(name="auditing-a-repository", description="d", shapes=["repo"])]
    with pytest.raises(ValidationError, match="not covered by any entrypoint"):
        validate(Manifest("v0", skills, entrypoints=eps), docs_root="/")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_manifest.py -v -k "entrypoint and validate"`
Expected: FAIL (the three "rejects" tests do not raise).

- [ ] **Step 3: Add entrypoints validation to `validate`**

Add after the modes block in `validate`:

```python
    if manifest.entrypoints:
        skill_names = {s.name for s in manifest.skills}
        reserved = set(skill_names)
        if manifest.router:
            reserved.add(manifest.router.name)
        if manifest.synthesizer:
            reserved.add(manifest.synthesizer.name)
        seen_eps: set[str] = set()
        covered: set[str] = set()
        for ep in manifest.entrypoints:
            if ep.name in seen_eps:
                raise ValidationError(f"duplicate entrypoint name: {ep.name}")
            seen_eps.add(ep.name)
            if ep.name in reserved:
                raise ValidationError(
                    f"entrypoint {ep.name} collides with an existing skill/router/synthesizer name")
            if not re.fullmatch(r"[a-z0-9-]{1,64}", ep.name):
                raise ValidationError(
                    f"entrypoint {ep.name!r}: name must be 1-64 lowercase letters, digits, "
                    "or hyphens (it becomes a directory under collapsed/skills/)")
            if len(ep.description) > 1024:
                raise ValidationError(f"entrypoint {ep.name}: description exceeds 1024 chars")
            if not ep.shapes:
                raise ValidationError(f"entrypoint {ep.name}: shapes must be non-empty")
            for shape in ep.shapes:
                if shape not in {"diff", "repo", "decision", "artifact"}:
                    raise ValidationError(f"entrypoint {ep.name}: unknown shape {shape!r}")
            for s in manifest.skills:
                if s.shape in ep.shapes or (ep.include_design and s.design):
                    covered.add(s.name)
        orphans = skill_names - covered
        if orphans:
            raise ValidationError(
                f"lenses not covered by any entrypoint: {sorted(orphans)}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_manifest.py -v -k "entrypoint and validate"`
Expected: PASS (all four).

- [ ] **Step 5: Full suite + commit**

Run: `python -m pytest -q` (expected: all pass)

```bash
git add tooling/manifest.py tests/test_manifest.py
git commit -m "feat: validate entrypoints — name collisions, shapes, full lens coverage"
```

---

### Task 3: Author the `entrypoints:` section in the real manifest

**Files:**

- Modify: `skills/manifest.yaml`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
def test_real_manifest_declares_four_entrypoints_covering_all_lenses():
    m = load_manifest("skills/manifest.yaml")
    assert {e.name for e in m.entrypoints} == {
        "reviewing-a-change", "auditing-a-repository",
        "reviewing-a-decision", "reviewing-an-artifact"}
    covered = set()
    for ep in m.entrypoints:
        for s in m.skills:
            if s.shape in ep.shapes or (ep.include_design and s.design):
                covered.add(s.name)
    assert {s.name for s in m.skills} <= covered   # every lens covered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest.py::test_real_manifest_declares_four_entrypoints_covering_all_lenses -v`
Expected: FAIL (no entrypoints yet).

- [ ] **Step 3: Add the `entrypoints:` section to `skills/manifest.yaml`**

Append at the top level (after `modes:`). Keep descriptions ≤1024 chars and trigger-rich:

```yaml
entrypoints:
  - name: reviewing-a-change
    description: >
      Review a diff, pull request, or code change with the code-quality-atlas
      lenses. Use for "review this PR / diff / change / what I pushed". Ranks the
      relevant diff lenses by relevance and runs them at the chosen depth
      (review = top few; comprehensive = all relevant), then synthesizes one
      verdict. The collapsed, repo-independent entrypoint for change review.
    shapes: [diff]
  - name: auditing-a-repository
    description: >
      Run a whole-repository health audit with the code-quality-atlas repo-shaped
      audits (architecture, dependencies, config/build, docs, compliance,
      enforcement, infrastructure-as-code, maintainability hotspots). Use for a
      scheduled or on-demand repo audit, not a single diff. Runs the applicable
      audits and synthesizes one report.
    shapes: [repo]
  - name: reviewing-a-decision
    description: >
      Review a decision rather than code — an ADR, RFC, design doc, dependency or
      technology adoption, build-vs-buy or vendor choice, or a deprecation/sunset
      plan. Reviews the choice and its record (rationale, lock-in, exit, revisit
      trigger) with the decision lens plus the design-capable lenses for the
      decision's domain.
    shapes: [decision]
    include_design: true
  - name: reviewing-an-artifact
    description: >
      Review a standardized authored artifact against its own published standard
      rather than as application code — e.g. a SKILL.md / agent-skill definition.
      Detects the artifact and applies its rubric. The collapsed entrypoint for
      artifact-shaped review.
    shapes: [artifact]
```

- [ ] **Step 4: Validate + test**

Run: `python -m pytest tests/test_manifest.py::test_real_manifest_declares_four_entrypoints_covering_all_lenses -v`
Expected: PASS.

Run: `python -m tooling.cli generate --manifest skills/manifest.yaml --docs-root . --skills-root skills`
Expected: exit 0 (validation passes — proves coverage + no name collisions). Then discard any standalone regen noise: `git checkout -- skills/`.

- [ ] **Step 5: Commit**

```bash
git add skills/manifest.yaml tests/test_manifest.py
git commit -m "feat: declare the 4 collapsed entrypoints in manifest"
```

---

### Task 4: Lens-bundle composition

**Files:**

- Modify: `tooling/generate.py` (add `entrypoint_lenses`, `lens_bundle_body`, `generate_lens_bundle`)
- Test: `tests/test_collapsed.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_collapsed.py`:

```python
import json
from pathlib import Path
from tooling.manifest import Entrypoint, Manifest, Skill, Source
from tooling.generate import entrypoint_lenses, lens_bundle_body, generate_lens_bundle


def _skill(**kw):
    base = dict(name="hunting-silent-failures", description="x", shape="diff", wave=1,
                picker="Where do errors vanish?",
                built_from=[Source(2, "tests/fixtures/research_sample.md#2")])
    base.update(kw)
    return Skill(**base)


def test_entrypoint_lenses_membership_by_shape_and_design():
    diff_plain = _skill(name="a", shape="diff", design=False)
    diff_design = _skill(name="b", shape="diff", design=True)
    repo = _skill(name="c", shape="repo")
    m = Manifest("v0", [diff_plain, diff_design, repo])
    ep_change = Entrypoint(name="reviewing-a-change", description="d", shapes=["diff"])
    ep_decision = Entrypoint(name="reviewing-a-decision", description="d",
                             shapes=["decision"], include_design=True)
    assert {s.name for s in entrypoint_lenses(m, ep_change)} == {"a", "b"}
    assert {s.name for s in entrypoint_lenses(m, ep_decision)} == {"b"}  # design-capable only


def test_lens_bundle_body_has_checklist_and_deeper_links():
    body = lens_bundle_body(_skill(), docs_root=".", skills_root="skills")
    assert "## When to use" in body
    assert "## Checklist" in body
    assert "Is any error swallowed" in body            # heuristics from the fixture/docs
    assert "(tool-rules.md)" in body and "(sources.md)" in body   # deeper disclosure links


def test_generate_lens_bundle_writes_three_files(tmp_path):
    dest = generate_lens_bundle(_skill(), tmp_path, docs_root=".", skills_root="skills")
    assert (dest / "body.md").exists()
    assert (dest / "tool-rules.md").exists()
    assert (dest / "sources.md").exists()
```

(Adjust the `"Is any error swallowed"` assertion to a string that actually appears in `docs/research/cluster-1-correctness.md#2` — confirm with `grep` while implementing.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_collapsed.py -v`
Expected: FAIL — `ImportError: cannot import name 'entrypoint_lenses'`.

- [ ] **Step 3: Implement the three functions**

In `tooling/generate.py`, add (reusing the existing `build_reference` and `_scope_line`):

```python
def entrypoint_lenses(manifest: Manifest, entrypoint) -> list[Skill]:
    """The lenses an entrypoint bundles: by shape, plus design-capable lenses
    when include_design (e.g. the decision entrypoint carries the ◆ diff lenses)."""
    out = []
    for s in manifest.skills:
        if s.shape in entrypoint.shapes or (entrypoint.include_design and s.design):
            out.append(s)
    return out


def lens_bundle_body(skill: Skill, docs_root: str = ".", skills_root: str = "skills") -> str:
    """The `body.md` an entrypoint loads for one lens: when-to-use + the full
    heuristics checklist + curated examples + links to the deeper bundled files.
    Examples come from the standalone tree's hand-refined examples.md (canonical);
    tool-rules/sources are a further disclosure level, linked not inlined."""
    picker = f"{skill.picker}\n\n" if skill.picker else ""
    heuristics = build_reference(skill, "heuristics", docs_root=docs_root)
    examples_path = Path(skills_root, skill.name, "examples.md")
    examples = examples_path.read_text(encoding="utf-8") if examples_path.exists() else ""
    examples_block = f"## Examples\n\n{examples.strip()}\n\n" if examples.strip() else ""
    return (
        f"# {skill.name}\n\n"
        f"{picker}"
        "## When to use\n\n"
        f"{_scope_line(skill)}\n\n"
        "## Checklist\n\n"
        f"{heuristics.strip()}\n\n"
        f"{examples_block}"
        "## Going deeper\n\n"
        "- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical "
        "subset; for wiring linters, not needed for the judgment review.\n"
        "- [sources.md](sources.md) — the research behind each check; for provenance.\n"
    )


def generate_lens_bundle(skill: Skill, lenses_dir: Path, docs_root: str = ".",
                         skills_root: str = "skills") -> Path:
    """Write reference/lenses/<skill>/{body,tool-rules,sources}.md and return the dir."""
    dest = Path(lenses_dir, skill.name)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "body.md").write_text(lens_bundle_body(skill, docs_root, skills_root), encoding="utf-8")
    (dest / "tool-rules.md").write_text(build_reference(skill, "tooling", docs_root), encoding="utf-8")
    (dest / "sources.md").write_text(build_reference(skill, "references", docs_root), encoding="utf-8")
    return dest
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_collapsed.py -v`
Expected: PASS (adjust the heuristics-content assertion to a real string first).

- [ ] **Step 5: Full suite + commit**

```bash
git add tooling/generate.py tests/test_collapsed.py
git commit -m "feat: lens-bundle composition (body.md + deeper tool-rules/sources)"
```

---

### Task 5: Entrypoint SKILL.md + collapsed synthesis

**Files:**

- Modify: `tooling/generate.py` (add `build_entrypoint_md`, `build_collapsed_synthesis`)
- Test: `tests/test_collapsed.py`

- [ ] **Step 1: Write the failing test**

```python
from tooling.manifest import Route, Router, Synthesizer
from tooling.generate import build_entrypoint_md, build_collapsed_synthesis
# reuse _modes() pattern — import Mode
from tooling.manifest import Mode


def _full_manifest():
    a = _skill(name="hunting-silent-failures", shape="diff", picker="Where do errors vanish?")
    router = Router(name="choosing-review-lenses", description="route",
                    routes=[Route(when="Bug fix", run=["hunting-silent-failures"])], body="")
    syn = Synthesizer(name="synthesizing-review-findings", description="merge",
                      severity_order=["Blocker", "Major", "Minor", "Nit"], tensions=[])
    modes = [Mode(name="review", breadth="top 2-4", floor="escalating", triggers=["review"]),
             Mode(name="comprehensive", breadth="all relevant", floor="Nit", triggers=["thorough"])]
    ep = Entrypoint(name="reviewing-a-change", description="review a change", shapes=["diff"])
    return Manifest("v0", [a], router=router, synthesizer=syn, modes=modes, entrypoints=[ep])


def test_build_entrypoint_md_has_trigger_routing_modes_and_load_instructions():
    m = _full_manifest()
    md = build_entrypoint_md(m, m.entrypoints[0])
    assert md.startswith("---\n")                       # frontmatter
    assert "name: reviewing-a-change" in md
    assert "## Depth modes" in md                       # reuses modes_section
    assert "reference/lenses/hunting-silent-failures/body.md" in md  # load instruction
    assert "reference/synthesis.md" in md               # synthesize pointer
    assert "Bug fix" in md                              # the in-shape route


def test_build_collapsed_synthesis_carries_floor_policy_without_frontmatter():
    md = build_collapsed_synthesis(_full_manifest())
    assert not md.startswith("---")                     # bundled body, no frontmatter
    assert "## Severity floor by mode" in md            # reuses mode_floor_policy
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_collapsed.py -v -k "entrypoint_md or collapsed_synthesis"`
Expected: FAIL — import error for `build_entrypoint_md`.

- [ ] **Step 3: Implement both functions**

```python
def build_collapsed_synthesis(manifest: Manifest) -> str:
    """The synthesizer procedure as a bundled reference file (no frontmatter).
    Reuses build_synthesizer_md (which already includes mode_floor_policy) and
    strips only the LEADING YAML frontmatter block so an entrypoint can Read it
    directly — robust even if the synthesis body itself contains a '---' line."""
    full = build_synthesizer_md(manifest)
    if full.startswith("---\n"):
        end = full.find("\n---\n", len("---\n"))   # closing fence of the first block only
        if end != -1:
            return full[end + len("\n---\n"):].lstrip("\n")
    return full


def build_entrypoint_md(manifest: Manifest, entrypoint) -> str:
    lenses = entrypoint_lenses(manifest, entrypoint)
    lens_names = {s.name for s in lenses}
    front = {
        "name": entrypoint.name,
        "description": entrypoint.description,
        "provenance": {"taxonomy_version": manifest.taxonomy_version, "built_from": []},
    }
    fm = yaml.safe_dump(front, sort_keys=False, default_flow_style=False,
                        allow_unicode=True).strip()

    # Routes from the router that touch this entrypoint's lenses.
    rows = []
    if manifest.router:
        for route in manifest.router.routes:
            if any(lens in lens_names for lens in route.run):
                run = ", ".join(f"`{lens}`" for lens in route.run if lens in lens_names)
                rows.append(f"| {route.when} | {run} |")
    routes_table = "\n".join(rows) if rows else "| (any item in scope) | all lenses below |"

    catalog = "\n".join(
        f"- `{s.name}`{' ◆' if s.design else ''}" + (f" — {s.picker}" if s.picker else "")
        for s in lenses)

    body = (
        f"# {entrypoint.name}\n\n"
        "## When to use\n\n"
        f"{entrypoint.body or entrypoint.description}\n\n"
        "## How this works\n\n"
        "Rank the relevant lenses below by relevance to what is being reviewed, "
        "pick the breadth from the depth mode (default **review**), then for each "
        "selected lens **load its bundle** and apply it:\n\n"
        "- Read `reference/lenses/<lens>/body.md` — the lens's checklist and examples. "
        "Open `reference/lenses/<lens>/tool-rules.md` or `sources.md` only if deeper "
        "tooling/provenance is called for.\n"
        "- After the lenses run, merge their findings with the procedure in "
        "`reference/synthesis.md` — one deduplicated, ranked report with a single verdict.\n\n"
        + modes_section(manifest)
        + "## Routes\n\n"
        "| When reviewing… | Run |\n"
        "|---|---|\n"
        f"{routes_table}\n\n"
        "## Lenses\n\n"
        "◆ = design-capable.\n\n"
        f"{catalog}\n"
    )
    return f"---\n{fm}\n---\n\n{body}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_collapsed.py -v -k "entrypoint_md or collapsed_synthesis"`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add tooling/generate.py tests/test_collapsed.py
git commit -m "feat: build_entrypoint_md + build_collapsed_synthesis (reuse modes/floor)"
```

---

### Task 6: `generate_collapsed` — write the tree + plugin manifest

**Files:**

- Modify: `tooling/generate.py` (add `collapsed_plugin_manifest`, `generate_collapsed`)
- Test: `tests/test_collapsed.py`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_collapsed_writes_full_tree(tmp_path):
    from tooling.generate import generate_collapsed
    m = _full_manifest()
    outs = generate_collapsed(m, docs_root=".", skills_root="skills",
                              collapsed_root=str(tmp_path))
    ep_dir = tmp_path / "skills" / "reviewing-a-change"
    assert (ep_dir / "SKILL.md").exists()
    assert (ep_dir / "reference" / "synthesis.md").exists()
    assert (ep_dir / "reference" / "lenses" / "hunting-silent-failures" / "body.md").exists()
    assert (ep_dir / "evals" / "eval.json").exists()              # draft scaffold
    plugin = json.loads((tmp_path / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["name"] == "code-quality-atlas-collapsed"
    assert any(p == ep_dir for p in outs)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_collapsed.py::test_generate_collapsed_writes_full_tree -v`
Expected: FAIL — import error for `generate_collapsed`.

- [ ] **Step 3: Implement**

```python
def collapsed_plugin_manifest(root_plugin_path: str = ".claude-plugin/plugin.json") -> dict:
    """Derive the collapsed plugin manifest from the root one (single source) so
    metadata stays in sync; only name/displayName/description differ."""
    p = Path(root_plugin_path)
    if not p.exists():
        raise FileNotFoundError(
            f"root plugin manifest not found at {root_plugin_path}; "
            "cannot derive the collapsed plugin manifest")
    base = json.loads(p.read_text(encoding="utf-8"))
    base["name"] = "code-quality-atlas-collapsed"
    base["displayName"] = base.get("displayName", "Code Quality Atlas") + " (collapsed)"
    base["description"] = ("Collapsed 4-entrypoint form of the code-quality-atlas "
                           "suite for cloud / account-skill / context-budget installs. "
                           "Lenses are bundled and loaded on demand.")
    return base


def generate_collapsed(manifest: Manifest, docs_root: str = ".", skills_root: str = "skills",
                       collapsed_root: str = "collapsed") -> list[Path]:
    """Emit the collapsed form: 4 entrypoint skills (each bundling its shape's
    lenses + synthesis) plus a generated .claude-plugin/plugin.json. Prunes any
    entrypoint directory no longer in the manifest so the committed tree can't go
    stale (requires `import shutil` at the top of generate.py)."""
    written: list[Path] = []
    skills_dir = Path(collapsed_root, "skills")
    current = {ep.name for ep in manifest.entrypoints}
    if skills_dir.exists():
        for child in skills_dir.iterdir():
            if child.is_dir() and child.name not in current:
                shutil.rmtree(child)   # prune a removed entrypoint
    for ep in manifest.entrypoints:
        out = Path(collapsed_root, "skills", ep.name)
        (out / "reference" / "lenses").mkdir(parents=True, exist_ok=True)
        (out / "evals").mkdir(parents=True, exist_ok=True)
        (out / "SKILL.md").write_text(build_entrypoint_md(manifest, ep), encoding="utf-8")
        (out / "reference" / "synthesis.md").write_text(
            build_collapsed_synthesis(manifest), encoding="utf-8")
        for skill in entrypoint_lenses(manifest, ep):
            generate_lens_bundle(skill, out / "reference" / "lenses",
                                 docs_root=docs_root, skills_root=skills_root)
        if not (out / "evals" / "eval.json").exists():
            (out / "evals" / "eval.json").write_text(
                json.dumps({"skills": [ep.name], "scenarios": []}, indent=2) + "\n",
                encoding="utf-8")
        written.append(out)
    pm_dir = Path(collapsed_root, ".claude-plugin")
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "plugin.json").write_text(
        json.dumps(collapsed_plugin_manifest(), indent=2) + "\n", encoding="utf-8")
    return written
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_collapsed.py::test_generate_collapsed_writes_full_tree -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add tooling/generate.py tests/test_collapsed.py
git commit -m "feat: generate_collapsed writes the 4-entrypoint tree + plugin.json"
```

---

### Task 7: Wire into the CLI + emit the real `collapsed/` tree

**Files:**

- Modify: `tooling/cli.py` (generate also emits collapsed)
- Modify: `.claude-plugin/marketplace.json` (static second plugin entry)
- Create (generated, committed): `collapsed/**`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_cli_generate_emits_collapsed(tmp_path):
    from tooling.cli import main
    rc = main(["generate", "--manifest", "skills/manifest.yaml", "--docs-root", ".",
               "--skills-root", str(tmp_path / "skills"),
               "--collapsed-root", str(tmp_path / "collapsed")])
    assert rc == 0
    assert (tmp_path / "collapsed" / "skills" / "reviewing-a-change" / "SKILL.md").exists()
    assert (tmp_path / "collapsed" / ".claude-plugin" / "plugin.json").exists()
```

(Note: the entrypoint lenses' `examples.md` are read from `--skills-root`; generating into a temp skills-root first populates them, so generate skills before collapsed within the same run — the CLI already iterates skills before the collapsed step below.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_cli_generate_emits_collapsed -v`
Expected: FAIL — `unrecognized arguments: --collapsed-root`.

- [ ] **Step 3: Wire the CLI**

In `tooling/cli.py`: add the import and the arg + emission.

- Update the import: `from tooling.generate import (generate_collapsed, generate_router, generate_skill, generate_synthesizer, primary_owners)`
- Add the arg under the `generate` subparser (after line 20):

```python
    g.add_argument("--collapsed-root", default="collapsed")
```

- In the `generate` branch, after the synthesizer block (after line 46, before `return 0`):

```python
        if manifest.entrypoints:
            for out in generate_collapsed(manifest, docs_root=args.docs_root,
                                          skills_root=args.skills_root,
                                          collapsed_root=args.collapsed_root):
                print(f"generated {out}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_cli.py::test_cli_generate_emits_collapsed -v`
Expected: PASS.

- [ ] **Step 5: Generate the real committed `collapsed/` tree**

Run: `python -m tooling.cli generate --manifest skills/manifest.yaml --docs-root . --skills-root skills`
Expected: exit 0, prints `generated collapsed/skills/...` for all 4 entrypoints.

Run: `npx --no-install markdownlint-cli2 "collapsed/skills/**/*.md"`
Expected: `0 error(s)` (fix generator output if a table/heading trips a rule, regenerate, re-lint).

- [ ] **Step 6: Add the static second plugin to `marketplace.json`**

Edit `.claude-plugin/marketplace.json` — add a second entry to the `plugins` array (after the existing one):

```json
    {
      "name": "code-quality-atlas-collapsed",
      "source": "collapsed/",
      "description": "Collapsed 4-entrypoint form for cloud / account-skill / context-budget installs — lenses bundled and loaded on demand. Install this OR the standalone plugin, not both.",
      "category": "code-review",
      "tags": ["code-review", "code-quality", "audit"]
    }
```

- [ ] **Step 7: Validate both plugin manifests**

Run: `claude plugin validate . && claude plugin validate collapsed/` (if the `claude` CLI is available; otherwise `python -c "import json; json.load(open('collapsed/.claude-plugin/plugin.json'))"` to confirm valid JSON).
Expected: both valid.

- [ ] **Step 8: Commit**

```bash
git add tooling/cli.py tests/test_cli.py .claude-plugin/marketplace.json collapsed/
git commit -m "feat: emit committed collapsed/ tree + second marketplace plugin"
```

---

### Task 8: Drift/regeneration gate across both trees

**Files:**

- Modify: `tests/test_collapsed.py` (a regenerate-and-compare guard)
- Modify: CI config if present (`.github/workflows/*` or `.pre-commit-config.yaml`)

- [ ] **Step 1: Write the failing test**

The collapsed tree is fully generated, so the guard is "regenerating into a temp dir reproduces the committed tree." Add to `tests/test_collapsed.py`:

```python
import filecmp, os

def test_committed_collapsed_matches_regeneration(tmp_path):
    from tooling.cli import main
    rc = main(["generate", "--manifest", "skills/manifest.yaml", "--docs-root", ".",
               "--skills-root", "skills", "--collapsed-root", str(tmp_path)])
    assert rc == 0
    # compare every generated SKILL.md / body.md against the committed collapsed/ tree
    for root, _dirs, files in os.walk(tmp_path / "skills"):
        for f in files:
            gen = Path(root) / f
            rel = gen.relative_to(tmp_path)
            committed = Path("collapsed") / rel
            assert committed.exists(), f"missing committed file: {committed}"
            # eval.json drafts are scaffolds; skip if hand-authored later
            if gen.name == "eval.json":
                continue
            assert gen.read_text() == committed.read_text(), f"drift in {rel}"
    # reverse: every committed non-eval file must have a regenerated counterpart
    # (catches a stale file left in collapsed/ that generation no longer produces)
    for root, _dirs, files in os.walk(Path("collapsed") / "skills"):
        for f in files:
            committed = Path(root) / f
            if committed.name == "eval.json":
                continue
            rel = committed.relative_to("collapsed")
            assert (tmp_path / rel).exists(), f"stale committed file (not regenerated): {committed}"
```

- [ ] **Step 2: Run to verify it passes (tree already committed in Task 7)**

Run: `python -m pytest tests/test_collapsed.py::test_committed_collapsed_matches_regeneration -v`
Expected: PASS (the committed tree was just generated). If it FAILS, regenerate and recommit — that *is* the drift the gate catches.

- [ ] **Step 3: Add the gate to CI**

If `.github/workflows/` exists, add a step to the existing test/lint workflow (after checkout + install):

```yaml
      - name: Generated trees are in sync
        run: |
          python -m tooling.cli generate --manifest skills/manifest.yaml --docs-root . --skills-root skills
          git diff --exit-code skills/    || { echo "::error::standalone skills/ drifted — regenerate and commit"; exit 1; }
          git diff --exit-code collapsed/ || { echo "::error::collapsed/ drifted — regenerate and commit"; exit 1; }
```

(If CI lives in `.pre-commit-config.yaml` instead, add an equivalent local hook; match the repo's existing pattern.)

- [ ] **Step 4: Full suite + commit**

```bash
git add tests/test_collapsed.py .github/
git commit -m "test+ci: gate that committed collapsed/ matches regeneration"
```

---

### Task 9: Distribution scripts `--collapsed` + docs

**Files:**

- Modify: `tooling/package-account-zips.sh`, `tooling/vendor-skills.sh`
- Modify: `docs/distribution.md`, `docs/install.md`

- [ ] **Step 1: Add `--collapsed` to `package-account-zips.sh`**

The script currently iterates `skills/*/SKILL.md` from the repo root. Add a `--collapsed` flag that sets the skills source to `collapsed/skills`. In the arg-parse `case`, add:

```bash
      --collapsed) SKILLS_SUBDIR="collapsed/skills" ;;
```

Add `SKILLS_SUBDIR="skills"` to the defaults near the top, and change the skill-discovery glob and the `(cd skills && zip ...)` calls to use `"$SKILLS_SUBDIR"` instead of the literal `skills`. Update `usage()` to document `--collapsed` ("package the 4 collapsed entrypoints instead of the 35 standalone skills").

- [ ] **Step 2: Verify**

Run: `tooling/package-account-zips.sh --collapsed --out "$(mktemp -d)"`
Expected: prints 4 zips (`reviewing-a-change.zip`, `auditing-a-repository.zip`, `reviewing-a-decision.zip`, `reviewing-an-artifact.zip`); each contains `<entrypoint>/SKILL.md` and `<entrypoint>/reference/...`.

- [ ] **Step 3: Add `--collapsed` to `vendor-skills.sh`**

Same pattern: a `--collapsed` flag pointing the source at `collapsed/skills`. In its arg `case`, add `--collapsed) SRC_SUBDIR="collapsed/skills" ;;`, default `SRC_SUBDIR="skills"`, and have `collect_skill_names`/`vendor_one` read from `"$SRC_SUBDIR"`. Update `usage()`.

- [ ] **Step 4: Verify**

Run: `TGT=$(mktemp -d); (cd "$TGT" && git init -q); tooling/vendor-skills.sh "$TGT" --collapsed`
Expected: vendors 4 entrypoints into `$TGT/.claude/skills/`.

- [ ] **Step 5: Update docs**

In `docs/distribution.md`: in the channel matrix and channel sections, note the collapsed plugin (`code-quality-atlas-collapsed`) and that `--collapsed` packages/vendors the 4 entrypoints; restate **install one form, not both**. In `docs/install.md`: add the collapsed plugin install line (`/plugin install code-quality-atlas-collapsed@code-quality-atlas`) and which surface each form suits.

- [ ] **Step 6: Lint + commit**

Run: `npx --no-install markdownlint-cli2 docs/distribution.md docs/install.md` (expected: 0 errors)

```bash
git add tooling/package-account-zips.sh tooling/vendor-skills.sh docs/distribution.md docs/install.md
git commit -m "feat: --collapsed for package/vendor scripts; document the collapsed form"
```

---

### Task 10: Author entrypoint routing evals + final gate

**Files:**

- Modify: `collapsed/skills/<entrypoint>/evals/eval.json` (replace draft scaffolds)
- Test: full suite + `eval` validation

- [ ] **Step 1: Author ≥3 scenarios per entrypoint**

Replace each empty `scenarios: []` with ≥3 scenarios validating routing + mode behavior. Example for `collapsed/skills/reviewing-a-change/evals/eval.json`:

```json
{
  "skills": ["reviewing-a-change"],
  "scenarios": [
    {
      "query": "Review this PR:\n```python\ntry:\n    charge(order)\nexcept Exception:\n    pass\norder.mark_paid()\n```",
      "expected_behavior": [
        "Selects correctness + silent-failure lenses by relevance",
        "Loads reference/lenses/hunting-silent-failures/body.md and flags the swallowed exception",
        "Produces one synthesized verdict via reference/synthesis.md"
      ]
    },
    {
      "query": "Do a thorough review of this change — use all relevant lenses: <diff>",
      "expected_behavior": [
        "Recognizes 'thorough / all relevant lenses' as comprehensive mode",
        "Runs every relevant lens, not just the top 2-4",
        "Applies the comprehensive Nit-pinned severity floor"
      ]
    },
    {
      "query": "Quick triage of this hotfix before merge: <diff>",
      "expected_behavior": [
        "Recognizes triage mode",
        "Runs only the critical-tier lenses (correctness/security/data/concurrency)",
        "Reports at the Major+ floor"
      ]
    }
  ]
}
```

Author equivalent ≥3-scenario sets for `auditing-a-repository`, `reviewing-a-decision`, `reviewing-an-artifact` (each exercising relevance + at least one mode).

> Newlines in a `query` must be escaped as `\n` (the example above is valid JSON as written); backticks need no escaping. `python -m tooling.cli eval` (Step 2) will surface a malformed JSON file.

- [ ] **Step 2: Validate evals**

Run: `python -m tooling.cli eval --skills-root collapsed/skills`
Expected: `OK: reviewing-a-change (3 scenarios)` … for all 4; exit 0.

- [ ] **Step 3: Regenerate, confirm the committed eval.json survive**

`generate_collapsed` only writes a draft eval.json when one is missing, so re-running generate must NOT overwrite the authored scenarios. Verify:

Run: `python -m tooling.cli generate --manifest skills/manifest.yaml && git diff --stat collapsed/skills/*/evals/`
Expected: no changes to the eval.json files.

- [ ] **Step 4: Final gate**

Run: `python -m pytest -q` (expected: all pass)
Run: `python -m tooling.cli drift --skills-root skills --docs-root .` (expected: No drift)
Run: `npx --no-install markdownlint-cli2 "collapsed/**/*.md" docs/distribution.md docs/install.md` (expected: 0 errors)

- [ ] **Step 5: Commit**

```bash
git add collapsed/skills/*/evals/eval.json
git commit -m "test: author routing + mode evals for the 4 collapsed entrypoints"
```

---

## Done criteria

- `python -m tooling.cli generate` emits both the standalone `skills/` (35) and the committed `collapsed/` (4 entrypoints + generated `plugin.json`); CI gate proves `collapsed/` matches regeneration.
- `marketplace.json` offers `code-quality-atlas-collapsed`; either plugin installs and auto-updates.
- Each entrypoint loads lenses via `reference/lenses/<lens>/body.md` with deeper `tool-rules.md`/`sources.md`, and synthesizes via `reference/synthesis.md` (carrying the per-mode floor policy from Plan 1).
- `package-account-zips.sh --collapsed` → 4 zips; `vendor-skills.sh <repo> --collapsed` → 4 entrypoints; docs say which form per surface and "install one form, not both."
- Each entrypoint has ≥3 routing/mode evals. Full suite green, drift clean, markdownlint clean.
- Q20 fully resolved (dual-emit + collapsed form), building on Plan 1's depth modes.
