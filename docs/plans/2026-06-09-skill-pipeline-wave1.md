# Skill Regeneration Pipeline (Wave 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the docs→skills regeneration pipeline (manifest → generate → drift → evals), declare the 6 wave-1 skills, generate their scaffolds, fully refine one exemplar, and prove the regenerate-after-docs-change loop.

**Architecture:** A small Python tool reads `skills/manifest.yaml` (the adaptation lever) plus the verified research in `docs/research/cluster-*.md`, and emits one directory per skill (`SKILL.md` + `reference/*.md` + `evals/`), stamping each source research section's SHA-256 into the skill's provenance frontmatter. A drift command recomputes those hashes against current docs to flag skills whose source changed. This realizes D6 (docs are source of truth; skills derived & regenerable), D7 (progressive disclosure, portable lean SKILL.md), and D8 (eval-first).

**Tech Stack:** Python 3.11+, PyYAML, pytest. Stdlib `hashlib`, `pathlib`, `re`, `dataclasses`, `argparse`. (Tooling language is dev-only and does not affect the model/harness-agnostic skill format.)

---

## File Structure

**Tooling (one responsibility per file):**
- `tooling/sections.py` — parse research markdown: extract a `## #n` section, its `### …` subsections, and hash them.
- `tooling/manifest.py` — `Manifest`/`Skill`/`Source` dataclasses; load + validate `skills/manifest.yaml`.
- `tooling/generate.py` — build a skill directory (SKILL.md + reference/* + eval stub) from a `Skill` + research.
- `tooling/drift.py` — compare stored provenance hashes against current docs; report drift.
- `tooling/evals.py` — load + validate `evals/eval.json` files.
- `tooling/cli.py` — argparse entry point: `generate` / `drift` / `eval`.

**Tests + fixtures:**
- `tests/fixtures/research_sample.md`, `tests/fixtures/manifest_sample.yaml`
- `tests/test_sections.py`, `tests/test_manifest.py`, `tests/test_generate.py`, `tests/test_drift.py`, `tests/test_evals.py`, `tests/test_cli.py`

**Artifacts produced:**
- `skills/manifest.yaml` — the 6 wave-1 skills.
- `skills/<name>/…` — generated scaffolds; `skills/hunting-silent-failures/` fully refined.
- `docs/runbooks/regenerating-skills.md` — the proven loop.

**Repo plumbing:** `requirements.txt`, root `conftest.py` (empty, so pytest puts repo root on `sys.path`), `tooling/__init__.py`.

---

## Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`, `conftest.py`, `tooling/__init__.py`, `tests/__init__.py`
- Create: `tests/fixtures/research_sample.md`, `tests/fixtures/manifest_sample.yaml`

- [ ] **Step 1: Create `requirements.txt`**

```text
PyYAML>=6.0
pytest>=8.0
```

- [ ] **Step 2: Create empty `conftest.py` and `tooling/__init__.py` and `tests/__init__.py`**

`conftest.py` (empty file — its presence makes pytest add the repo root to `sys.path` so `import tooling` works):

```python
```

`tooling/__init__.py`:

```python
```

`tests/__init__.py`:

```python
```

- [ ] **Step 3: Create `tests/fixtures/research_sample.md`** (a minimal stand-in for a cluster research file)

```markdown
# Research — Sample

## #2 Error handling & resilience

### Key references
- **Nygard — Release It!** → mine: timeouts, circuit breaker, bulkhead.

### Tooling rules worth lifting
- **typescript-eslint:** `no-floating-promises` (unhandled async error).
- **RuboCop:** `Lint/SuppressedException` (empty rescue).

### Reviewable heuristics (skill-checklist seeds)
- Is any error swallowed (empty catch/rescue, `except: pass`)?
- Does every remote call have a timeout?
- Are retries capped with backoff?

## #4 Resource & state management

### Key references
- **Nygard — Steady State** → mine: bound anything that grows.

### Tooling rules worth lifting
- **Go:** `bodyclose` (unclosed HTTP body).

### Reviewable heuristics (skill-checklist seeds)
- Is every acquired resource released on all paths?
- Are caches bounded with eviction/TTL?
```

- [ ] **Step 4: Create `tests/fixtures/manifest_sample.yaml`**

```yaml
taxonomy_version: v0.2
skills:
  - name: hunting-silent-failures
    description: >
      Reviews changes for swallowed errors and unsafe fallbacks. Use when
      reviewing error handling, try/catch, rescue, or resilience code.
    shape: diff
    wave: 1
    built_from:
      - { category: 2, source: tests/fixtures/research_sample.md#2 }
      - { category: 4, source: tests/fixtures/research_sample.md#4 }
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt conftest.py tooling/__init__.py tests/__init__.py tests/fixtures/
git commit -m "chore: scaffold tooling package, test fixtures, and deps"
```

---

## Task 2: `sections.extract_section`

**Files:**
- Create: `tooling/sections.py`
- Test: `tests/test_sections.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sections.py
from pathlib import Path
from tooling.sections import extract_section

SAMPLE = Path("tests/fixtures/research_sample.md").read_text()

def test_extract_section_returns_named_section_only():
    text = extract_section(SAMPLE, 2)
    assert text.startswith("## #2 Error handling & resilience")
    assert "circuit breaker" in text
    assert "## #4" not in text  # stops at the next section

def test_extract_section_missing_raises_keyerror():
    import pytest
    with pytest.raises(KeyError):
        extract_section(SAMPLE, 99)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sections.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tooling.sections'`

- [ ] **Step 3: Write minimal implementation**

```python
# tooling/sections.py
import re

_SECTION_START = re.compile(r"^## #(\d+)\b", re.MULTILINE)


def extract_section(markdown: str, n: int) -> str:
    """Return the text of the `## #n …` section, from its heading up to the
    next `## ` heading or end of document. Raises KeyError if not found."""
    starts = [(int(m.group(1)), m.start()) for m in _SECTION_START.finditer(markdown)]
    for i, (num, pos) in enumerate(starts):
        if num == n:
            end = starts[i + 1][1] if i + 1 < len(starts) else len(markdown)
            return markdown[pos:end].rstrip() + "\n"
    raise KeyError(f"section #{n} not found")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sections.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/sections.py tests/test_sections.py
git commit -m "feat(sections): extract a numbered research section"
```

---

## Task 3: `sections.extract_subsection`

**Files:**
- Modify: `tooling/sections.py`
- Test: `tests/test_sections.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_sections.py`)

```python
from tooling.sections import extract_subsection

def test_extract_subsection_heuristics():
    section = extract_section(SAMPLE, 2)
    heur = extract_subsection(section, "heuristics")
    assert "Is any error swallowed" in heur
    assert "Release It!" not in heur          # references excluded
    assert "no-floating-promises" not in heur # tooling excluded

def test_extract_subsection_absent_returns_empty():
    section = extract_section(SAMPLE, 4)
    # #4 has no references-with-this-marker beyond what's present; tooling exists
    assert extract_subsection(section, "tooling") != ""
    assert extract_subsection(section, "missing-kind-x") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sections.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_subsection'`

- [ ] **Step 3: Write minimal implementation** (append to `tooling/sections.py`)

```python
_SUBHEADINGS = {
    "references": "### Key references",
    "tooling": "### Tooling rules",
    "heuristics": "### Reviewable heuristics",
}
_SUB_START = re.compile(r"^### ", re.MULTILINE)


def extract_subsection(section_text: str, kind: str) -> str:
    """Return the body of a `### …` subsection matched by prefix for `kind`
    (references | tooling | heuristics). Empty string if absent or unknown kind."""
    prefix = _SUBHEADINGS.get(kind)
    if prefix is None:
        return ""
    starts = [m.start() for m in _SUB_START.finditer(section_text)]
    for i, pos in enumerate(starts):
        line_end = section_text.index("\n", pos)
        heading = section_text[pos:line_end]
        if heading.startswith(prefix):
            end = starts[i + 1] if i + 1 < len(starts) else len(section_text)
            return section_text[pos:end].rstrip() + "\n"
    return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sections.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/sections.py tests/test_sections.py
git commit -m "feat(sections): extract a typed subsection (refs/tooling/heuristics)"
```

---

## Task 4: `sections.section_hash`

**Files:**
- Modify: `tooling/sections.py`
- Test: `tests/test_sections.py`

- [ ] **Step 1: Write the failing test** (append)

```python
from tooling.sections import section_hash

def test_section_hash_is_stable_and_specific():
    h2a = section_hash(SAMPLE, 2)
    h2b = section_hash(SAMPLE, 2)
    h4 = section_hash(SAMPLE, 4)
    assert h2a == h2b                 # deterministic
    assert h2a != h4                  # section-specific
    assert len(h2a) == 64             # sha256 hex

def test_section_hash_changes_when_text_changes():
    edited = SAMPLE.replace("Does every remote call have a timeout?",
                            "Does every remote call have a timeout and deadline?")
    assert section_hash(edited, 2) != section_hash(SAMPLE, 2)
    assert section_hash(edited, 4) == section_hash(SAMPLE, 4)  # #4 untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sections.py -v`
Expected: FAIL with `ImportError: cannot import name 'section_hash'`

- [ ] **Step 3: Write minimal implementation** (append to `tooling/sections.py`; add `import hashlib` at top)

```python
import hashlib  # add with the other imports at the top of the file


def section_hash(markdown: str, n: int) -> str:
    """SHA-256 (hex) of the normalized text of section #n."""
    normalized = extract_section(markdown, n).strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sections.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/sections.py tests/test_sections.py
git commit -m "feat(sections): stable sha256 hash per research section"
```

---

## Task 5: `manifest` dataclasses + loader

**Files:**
- Create: `tooling/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manifest.py
from tooling.manifest import load_manifest, Manifest, Skill, Source

def test_load_manifest_parses_skill_and_sources():
    m = load_manifest("tests/fixtures/manifest_sample.yaml")
    assert isinstance(m, Manifest)
    assert m.taxonomy_version == "v0.2"
    assert len(m.skills) == 1
    skill = m.skills[0]
    assert isinstance(skill, Skill)
    assert skill.name == "hunting-silent-failures"
    assert skill.shape == "diff"
    assert skill.wave == 1
    assert [s.section for s in skill.built_from] == [2, 4]
    assert skill.built_from[0].path == "tests/fixtures/research_sample.md"

def test_source_parses_path_and_section():
    s = Source(category=2, source="docs/research/cluster-1-correctness.md#2")
    assert s.path == "docs/research/cluster-1-correctness.md"
    assert s.section == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tooling.manifest'`

- [ ] **Step 3: Write minimal implementation**

```python
# tooling/manifest.py
from __future__ import annotations
from dataclasses import dataclass, field
import yaml


@dataclass
class Source:
    category: int
    source: str  # "<path>#<n>"

    @property
    def path(self) -> str:
        return self.source.rsplit("#", 1)[0]

    @property
    def section(self) -> int:
        return int(self.source.rsplit("#", 1)[1])


@dataclass
class Skill:
    name: str
    description: str
    shape: str
    wave: int
    built_from: list[Source]
    primary_owner: int | None = None
    cross_ref: list[int] = field(default_factory=list)


@dataclass
class Manifest:
    taxonomy_version: str
    skills: list[Skill]


def load_manifest(path: str) -> Manifest:
    data = yaml.safe_load(open(path, encoding="utf-8"))
    skills = []
    for s in data["skills"]:
        built = [Source(category=b["category"], source=b["source"]) for b in s["built_from"]]
        skills.append(Skill(
            name=s["name"],
            description=s["description"].strip(),
            shape=s["shape"],
            wave=s["wave"],
            built_from=built,
            primary_owner=s.get("primary_owner"),
            cross_ref=s.get("cross_ref", []),
        ))
    return Manifest(taxonomy_version=data["taxonomy_version"], skills=skills)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_manifest.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/manifest.py tests/test_manifest.py
git commit -m "feat(manifest): load skill manifest into typed dataclasses"
```

---

## Task 6: `manifest.validate`

**Files:**
- Modify: `tooling/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test** (append)

```python
from tooling.manifest import validate, ValidationError
import pytest

def _skill(**kw):
    base = dict(name="hunting-silent-failures",
                description="x", shape="diff", wave=1,
                built_from=[Source(2, "tests/fixtures/research_sample.md#2")])
    base.update(kw)
    return Skill(**base)

def test_validate_accepts_good_manifest():
    validate(Manifest("v0.2", [_skill()]))  # no raise

def test_validate_rejects_reserved_word_in_name():
    with pytest.raises(ValidationError, match="reserved"):
        validate(Manifest("v0.2", [_skill(name="claude-helper")]))

def test_validate_rejects_bad_name_chars():
    with pytest.raises(ValidationError, match="name"):
        validate(Manifest("v0.2", [_skill(name="Hunting_Failures")]))

def test_validate_rejects_duplicate_names():
    with pytest.raises(ValidationError, match="duplicate"):
        validate(Manifest("v0.2", [_skill(), _skill()]))

def test_validate_rejects_unresolvable_source():
    bad = _skill(built_from=[Source(99, "tests/fixtures/research_sample.md#99")])
    with pytest.raises(ValidationError, match="section #99"):
        validate(Manifest("v0.2", [bad]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate'`

- [ ] **Step 3: Write minimal implementation** (append to `tooling/manifest.py`; add imports)

```python
import re
from pathlib import Path
from tooling.sections import extract_section

_NAME_RE = re.compile(r"^[a-z0-9-]+$")
_RESERVED = ("anthropic", "claude")


class ValidationError(Exception):
    pass


def validate(manifest: Manifest, docs_root: str = ".") -> None:
    seen = set()
    for s in manifest.skills:
        if not _NAME_RE.match(s.name) or len(s.name) > 64:
            raise ValidationError(f"invalid name: {s.name!r} (lowercase/hyphen, <=64)")
        if any(w in s.name for w in _RESERVED):
            raise ValidationError(f"name uses reserved word: {s.name!r}")
        if s.name in seen:
            raise ValidationError(f"duplicate skill name: {s.name!r}")
        seen.add(s.name)
        if not s.description or len(s.description) > 1024:
            raise ValidationError(f"{s.name}: description must be non-empty and <=1024 chars")
        if s.shape not in ("diff", "repo"):
            raise ValidationError(f"{s.name}: shape must be diff|repo, got {s.shape!r}")
        if not s.built_from:
            raise ValidationError(f"{s.name}: built_from must be non-empty")
        for src in s.built_from:
            text = Path(docs_root, src.path).read_text(encoding="utf-8")
            extract_section(text, src.section)  # raises KeyError -> wrap
```

Wrap the resolution error so the message matches the test (replace the bare `extract_section(...)` line above with):

```python
            try:
                extract_section(text, src.section)
            except KeyError:
                raise ValidationError(f"{s.name}: source not found: section #{src.section} in {src.path}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_manifest.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/manifest.py tests/test_manifest.py
git commit -m "feat(manifest): validate names, descriptions, shape, and source resolution"
```

---

## Task 7: `generate` reference-file builder

**Files:**
- Create: `tooling/generate.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_generate.py
from pathlib import Path
from tooling.manifest import Skill, Source
from tooling.generate import build_reference

def _skill():
    return Skill(name="hunting-silent-failures", description="x", shape="diff", wave=1,
                 built_from=[Source(2, "tests/fixtures/research_sample.md#2"),
                             Source(4, "tests/fixtures/research_sample.md#4")])

def test_build_reference_heuristics_concatenates_across_sources_with_headers():
    md = build_reference(_skill(), kind="heuristics", docs_root=".")
    assert "## From category #2" in md
    assert "## From category #4" in md
    assert "Is any error swallowed" in md
    assert "Is every acquired resource released" in md
    assert "## Contents" in md  # ToC because >100 lines? small here; still include ToC header

def test_build_reference_tooling_only_has_tooling():
    md = build_reference(_skill(), kind="tooling", docs_root=".")
    assert "no-floating-promises" in md
    assert "Is any error swallowed" not in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tooling.generate'`

- [ ] **Step 3: Write minimal implementation**

```python
# tooling/generate.py
from __future__ import annotations
from pathlib import Path
from tooling.manifest import Skill, Source
from tooling.sections import extract_section, extract_subsection

_KIND_TITLE = {
    "heuristics": "Reviewable heuristics",
    "tooling": "Tool rules to triage",
    "references": "References to mine",
}


def build_reference(skill: Skill, kind: str, docs_root: str = ".") -> str:
    """Concatenate the `kind` subsection from each source category into one
    reference file, each under a `## From category #n` header, with a ToC."""
    parts: list[str] = []
    for src in skill.built_from:
        text = Path(docs_root, src.path).read_text(encoding="utf-8")
        body = extract_subsection(extract_section(text, src.section), kind).strip()
        if body:
            parts.append(f"## From category #{src.section}\n\n{body}")
    toc = "\n".join(f"- From category #{s.section}" for s in skill.built_from)
    header = f"# {_KIND_TITLE[kind]} — {skill.name}\n\n## Contents\n{toc}\n"
    return header + "\n" + "\n\n".join(parts) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generate.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/generate.py tests/test_generate.py
git commit -m "feat(generate): build per-skill reference files from research subsections"
```

---

## Task 8: `generate` SKILL.md builder (with provenance)

**Files:**
- Modify: `tooling/generate.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write the failing test** (append)

```python
from tooling.generate import build_skill_md
import yaml

def test_build_skill_md_has_frontmatter_and_provenance_and_links():
    md = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    assert md.startswith("---\n")
    front = yaml.safe_load(md.split("---\n")[1])
    assert front["name"] == "hunting-silent-failures"
    assert front["description"]
    assert front["provenance"]["taxonomy_version"] == "v0.2"
    bf = front["provenance"]["built_from"]
    assert {b["category"] for b in bf} == {2, 4}
    assert all(len(b["hash"]) == 64 for b in bf)
    # body links one level deep
    assert "reference/heuristics.md" in md
    assert "reference/tool-rules.md" in md
    assert "examples.md" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generate.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_skill_md'`

- [ ] **Step 3: Write minimal implementation** (append to `tooling/generate.py`; add `import yaml` and `section_hash` import)

```python
import yaml  # add near top imports
from tooling.sections import section_hash  # add to the sections import line


def build_skill_md(skill: Skill, taxonomy_version: str, docs_root: str = ".") -> str:
    built_from = []
    for src in skill.built_from:
        text = Path(docs_root, src.path).read_text(encoding="utf-8")
        built_from.append({
            "category": src.section,
            "source": src.source,
            "hash": section_hash(text, src.section),
        })
    front = {
        "name": skill.name,
        "description": skill.description,
        "provenance": {"taxonomy_version": taxonomy_version, "built_from": built_from},
    }
    fm = yaml.safe_dump(front, sort_keys=False, default_flow_style=False).strip()
    body = (
        f"# {skill.name}\n\n"
        "## When to use\n\n"
        f"{skill.description}\n\n"
        "## Top checks\n\n"
        "Start with the full checklist, then escalate to the references as needed.\n\n"
        "- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.\n"
        "- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.\n"
        "- See [reference/sources.md](reference/sources.md) for the references behind each check.\n"
        "- See [examples.md](examples.md) for good/bad examples.\n"
    )
    return f"---\n{fm}\n---\n\n{body}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generate.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/generate.py tests/test_generate.py
git commit -m "feat(generate): build lean SKILL.md with provenance frontmatter"
```

---

## Task 9: `generate.generate_skill` writes the directory

**Files:**
- Modify: `tooling/generate.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write the failing test** (append)

```python
from tooling.generate import generate_skill
import json

def test_generate_skill_writes_full_tree(tmp_path):
    out = generate_skill(_skill(), taxonomy_version="v0.2", docs_root=".",
                         skills_root=str(tmp_path))
    assert (out / "SKILL.md").exists()
    assert (out / "reference" / "heuristics.md").exists()
    assert (out / "reference" / "tool-rules.md").exists()
    assert (out / "reference" / "sources.md").exists()
    assert (out / "examples.md").exists()
    eval_doc = json.loads((out / "evals" / "eval.json").read_text())
    assert eval_doc["skills"] == ["hunting-silent-failures"]
    assert isinstance(eval_doc["scenarios"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generate.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_skill'`

- [ ] **Step 3: Write minimal implementation** (append to `tooling/generate.py`; add `import json`)

```python
import json  # add near top imports


def generate_skill(skill: Skill, taxonomy_version: str,
                   docs_root: str = ".", skills_root: str = "skills") -> Path:
    out = Path(skills_root, skill.name)
    (out / "reference").mkdir(parents=True, exist_ok=True)
    (out / "evals").mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(
        build_skill_md(skill, taxonomy_version, docs_root), encoding="utf-8")
    (out / "reference" / "heuristics.md").write_text(
        build_reference(skill, "heuristics", docs_root), encoding="utf-8")
    (out / "reference" / "tool-rules.md").write_text(
        build_reference(skill, "tooling", docs_root), encoding="utf-8")
    (out / "reference" / "sources.md").write_text(
        build_reference(skill, "references", docs_root), encoding="utf-8")
    if not (out / "examples.md").exists():
        (out / "examples.md").write_text(
            f"# Examples — {skill.name}\n\n"
            "<!-- Add concrete good/bad input→finding pairs during refinement. -->\n",
            encoding="utf-8")
    if not (out / "evals" / "eval.json").exists():
        (out / "evals" / "eval.json").write_text(json.dumps(
            {"skills": [skill.name], "scenarios": []}, indent=2) + "\n", encoding="utf-8")
    return out
```

Note: `examples.md` and `evals/eval.json` are written only if absent, so refinement is not overwritten on regeneration. The `reference/*` files and `SKILL.md` ARE regenerated (they are derived; refinement happens in `examples.md` and the `Top checks`/`description` which we will keep in the manifest).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generate.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/generate.py tests/test_generate.py
git commit -m "feat(generate): write the full skill directory tree"
```

---

## Task 10: `drift.check_drift`

**Files:**
- Create: `tooling/drift.py`
- Test: `tests/test_drift.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drift.py
from pathlib import Path
from tooling.manifest import Skill, Source
from tooling.generate import generate_skill
from tooling.drift import check_drift, DriftReport

def _skill():
    return Skill(name="hunting-silent-failures", description="x", shape="diff", wave=1,
                 built_from=[Source(2, "tests/fixtures/research_sample.md#2")])

def test_no_drift_right_after_generation(tmp_path):
    generate_skill(_skill(), "v0.2", docs_root=".", skills_root=str(tmp_path))
    reports = check_drift(skills_root=str(tmp_path), docs_root=".")
    assert reports == []

def test_drift_detected_when_source_changes(tmp_path, monkeypatch):
    generate_skill(_skill(), "v0.2", docs_root=".", skills_root=str(tmp_path))
    # Simulate a docs edit by pointing drift at an altered copy of the docs root.
    altered = tmp_path / "docs_altered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = Path("tests/fixtures/research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace("Does every remote call have a timeout?",
                         "Does every remote call have a timeout and deadline?"))
    reports = check_drift(skills_root=str(tmp_path), docs_root=str(altered))
    assert len(reports) == 1
    assert isinstance(reports[0], DriftReport)
    assert reports[0].skill == "hunting-silent-failures"
    assert [s.section for s in reports[0].changed] == [2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_drift.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tooling.drift'`

- [ ] **Step 3: Write minimal implementation**

```python
# tooling/drift.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml
from tooling.manifest import Source
from tooling.sections import section_hash


@dataclass
class DriftReport:
    skill: str
    changed: list[Source]


def _read_provenance(skill_md: Path) -> tuple[str, list[dict]]:
    text = skill_md.read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---\n")[1])
    prov = front["provenance"]
    return front["name"], prov["built_from"]


def check_drift(skills_root: str = "skills", docs_root: str = ".") -> list[DriftReport]:
    reports: list[DriftReport] = []
    for skill_md in sorted(Path(skills_root).glob("*/SKILL.md")):
        name, built_from = _read_provenance(skill_md)
        changed: list[Source] = []
        for b in built_from:
            src = Source(category=b["category"], source=b["source"])
            current = section_hash(Path(docs_root, src.path).read_text(encoding="utf-8"),
                                   src.section)
            if current != b["hash"]:
                changed.append(src)
        if changed:
            reports.append(DriftReport(skill=name, changed=changed))
    return reports
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_drift.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/drift.py tests/test_drift.py
git commit -m "feat(drift): detect skills whose source research sections changed"
```

---

## Task 11: `evals` loader + validator

**Files:**
- Create: `tooling/evals.py`
- Test: `tests/test_evals.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evals.py
import json, pytest
from tooling.evals import load_evals, validate_evals, EvalError

def _write(tmp_path, doc):
    p = tmp_path / "eval.json"
    p.write_text(json.dumps(doc))
    return str(p)

def _good():
    return {"skills": ["hunting-silent-failures"], "scenarios": [
        {"query": "review this diff", "expected_behavior": ["flags empty rescue"]},
        {"query": "review this diff 2", "expected_behavior": ["flags missing timeout"]},
        {"query": "review this diff 3", "expected_behavior": ["flags swallowed error"]},
    ]}

def test_load_and_validate_good_evals(tmp_path):
    evals = load_evals(_write(tmp_path, _good()))
    validate_evals(evals)  # no raise
    assert len(evals.scenarios) == 3

def test_validate_requires_at_least_three(tmp_path):
    doc = _good(); doc["scenarios"] = doc["scenarios"][:2]
    with pytest.raises(EvalError, match="at least 3"):
        validate_evals(load_evals(_write(tmp_path, doc)))

def test_validate_requires_expected_behavior(tmp_path):
    doc = _good(); doc["scenarios"][0].pop("expected_behavior")
    with pytest.raises(EvalError, match="expected_behavior"):
        validate_evals(load_evals(_write(tmp_path, doc)))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_evals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tooling.evals'`

- [ ] **Step 3: Write minimal implementation**

```python
# tooling/evals.py
from __future__ import annotations
from dataclasses import dataclass
import json


class EvalError(Exception):
    pass


@dataclass
class EvalDoc:
    skills: list[str]
    scenarios: list[dict]


def load_evals(path: str) -> EvalDoc:
    data = json.loads(open(path, encoding="utf-8").read())
    return EvalDoc(skills=data["skills"], scenarios=data["scenarios"])


def validate_evals(doc: EvalDoc) -> None:
    if len(doc.scenarios) < 3:
        raise EvalError("a skill must ship at least 3 eval scenarios")
    for i, s in enumerate(doc.scenarios):
        if not s.get("query"):
            raise EvalError(f"scenario {i}: missing query")
        if not s.get("expected_behavior"):
            raise EvalError(f"scenario {i}: missing expected_behavior")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_evals.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add tooling/evals.py tests/test_evals.py
git commit -m "feat(evals): load and validate per-skill eval files (>=3 scenarios)"
```

---

## Task 12: `cli` entry point

**Files:**
- Create: `tooling/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from tooling.cli import main

def test_cli_generate_then_drift_reports_clean(tmp_path, capsys):
    rc = main(["generate", "--manifest", "tests/fixtures/manifest_sample.yaml",
               "--docs-root", ".", "--skills-root", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "hunting-silent-failures" / "SKILL.md").exists()

    rc = main(["drift", "--skills-root", str(tmp_path), "--docs-root", "."])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No drift" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tooling.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# tooling/cli.py
from __future__ import annotations
import argparse
from tooling.manifest import load_manifest, validate
from tooling.generate import generate_skill
from tooling.drift import check_drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skills")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate")
    g.add_argument("--manifest", default="skills/manifest.yaml")
    g.add_argument("--docs-root", default=".")
    g.add_argument("--skills-root", default="skills")

    d = sub.add_parser("drift")
    d.add_argument("--skills-root", default="skills")
    d.add_argument("--docs-root", default=".")

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        manifest = load_manifest(args.manifest)
        validate(manifest, docs_root=args.docs_root)
        for skill in manifest.skills:
            out = generate_skill(skill, manifest.taxonomy_version,
                                 docs_root=args.docs_root, skills_root=args.skills_root)
            print(f"generated {out}")
        return 0

    if args.cmd == "drift":
        reports = check_drift(skills_root=args.skills_root, docs_root=args.docs_root)
        if not reports:
            print("No drift: all skills are in sync with their source research.")
            return 0
        for r in reports:
            secs = ", ".join(f"#{s.section}" for s in r.changed)
            print(f"DRIFT: {r.skill} — changed sources: {secs}")
        return 1

    return 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
```

> **Note (added during execution):** the `if __name__ == "__main__"` guard is required — without it `python -m tooling.cli …` defines `main()` but never calls it, so Tasks 13/15 (which invoke the module) silently no-op. A subprocess regression test (`test_cli_runs_as_module`) locks this in, since the direct-`main()` unit test cannot catch a missing guard.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the whole suite and commit**

Run: `python -m pytest -q`
Expected: PASS (all tests, ~19 passed)

```bash
git add tooling/cli.py tests/test_cli.py
git commit -m "feat(cli): generate and drift subcommands"
```

---

## Task 13: Author the real manifest (6 wave-1 skills) and generate scaffolds

**Files:**
- Create: `skills/manifest.yaml`
- Generate: `skills/<6 skill dirs>/`

- [ ] **Step 1: Write `skills/manifest.yaml`** (real wave-1 skills; descriptions are third-person with explicit triggers per D7)

```yaml
taxonomy_version: v0.2
skills:
  - name: hunting-silent-failures
    description: >
      Reviews changes for swallowed or silently-handled errors — empty
      catch/rescue blocks, ignored returned errors, bare excepts, unhandled
      promise rejections, broad exception catches — and for unsafe fallbacks,
      missing timeouts, and absent retries/circuit-breakers. Use when reviewing
      error handling, exceptions, try/catch, rescue, fallback, resilience,
      timeouts, or resource cleanup on failure paths.
    shape: diff
    wave: 1
    built_from:
      - { category: 2, source: docs/research/cluster-1-correctness.md#2 }
      - { category: 4, source: docs/research/cluster-1-correctness.md#4 }

  - name: reviewing-naming-and-readability
    description: >
      Reviews code for naming and local readability: intention-revealing names
      vs placeholders, function length and cyclomatic/cognitive complexity, deep
      nesting, magic numbers/strings, mixed levels of abstraction, and comment
      accuracy. Use when reviewing readability, naming, complexity, nesting,
      magic values, or comments.
    shape: diff
    wave: 1
    built_from:
      - { category: 5, source: docs/research/cluster-2-readability.md#5 }
      - { category: 6, source: docs/research/cluster-2-readability.md#6 }
      - { category: 7, source: docs/research/cluster-2-readability.md#7 }

  - name: reviewing-module-design
    description: >
      Reviews module and type design: cohesion and coupling (via connascence),
      encapsulation, hard-to-misuse interfaces, and making illegal states
      unrepresentable. Use when reviewing class/module structure, interfaces,
      type or data modeling, coupling, or API ergonomics for callers.
    shape: diff
    wave: 1
    built_from:
      - { category: 9, source: docs/research/cluster-3-structure.md#9 }
      - { category: 10, source: docs/research/cluster-3-structure.md#10 }

  - name: checking-restraint
    description: >
      Reviews changes for over-engineering — premature abstraction, speculative
      generality, the wrong abstraction, and premature optimization without a
      profile. The restraint / brake-pedal lens. Use when a change adds
      abstraction layers, config knobs, generality, or hand-optimized code, or
      when asking whether a change is doing too much.
    shape: diff
    wave: 1
    built_from:
      - { category: 11, source: docs/research/cluster-3-structure.md#11 }
      - { category: 15, source: docs/research/cluster-4-runtime.md#15 }

  - name: reviewing-llm-integration
    description: >
      Reviews LLM/AI integration code for prompt-injection surface, the lethal
      trifecta, unvalidated model output, missing eval coverage, unpinned models,
      unbounded token/cost, and PII sent to third-party models. Use when
      reviewing code that calls an LLM or model API, builds prompts, parses
      model output, or wires up agents and tools.
    shape: diff
    wave: 1
    built_from:
      - { category: 25, source: docs/research/cluster-4-runtime.md#25 }
      - { category: 27, source: docs/research/cluster-6-evolution.md#27 }

  - name: finding-maintainability-hotspots
    description: >
      Scans a repository for maintainability hotspots: high churn × complexity
      files, change-coupling, bus-factor / knowledge concentration, and
      untracked tech debt. A repo-wide / scheduled scan rather than a single-diff
      review. Use when auditing maintainability, tech debt, refactoring targets,
      or risky areas across the codebase.
    shape: repo
    wave: 1
    built_from:
      - { category: 21, source: docs/research/cluster-6-evolution.md#21 }
```

- [ ] **Step 2: Validate the manifest against the real docs**

Run: `python -c "from tooling.manifest import load_manifest, validate; validate(load_manifest('skills/manifest.yaml'))"`
Expected: no output, exit 0 (every `built_from` source resolves to a real section).

- [ ] **Step 3: Generate the scaffolds**

Run: `python -m tooling.cli generate`
Expected: prints `generated skills/<name>` for all 6 skills; directories created.

- [ ] **Step 4: Confirm drift is clean immediately after generation**

Run: `python -m tooling.cli drift`
Expected: `No drift: all skills are in sync with their source research.`

- [ ] **Step 5: Commit**

```bash
git add skills/
git commit -m "feat(skills): declare 6 wave-1 skills and generate their scaffolds"
```

---

## Task 14: Refine the exemplar skill (`hunting-silent-failures`) with examples + evals

**Files:**
- Modify: `skills/hunting-silent-failures/examples.md`
- Modify: `skills/hunting-silent-failures/evals/eval.json`

- [ ] **Step 1: Write `examples.md`** with concrete good/bad pairs (these carry the most weight for small models, per D7)

```markdown
# Examples — hunting-silent-failures

## Bad → finding

**Input (diff):**
```python
try:
    charge = payments.charge(order.total)
except Exception:
    pass
order.mark_paid()
```
**Expected finding:** Swallowed exception: the `except Exception: pass` hides charge
failures, and `order.mark_paid()` runs even when the charge failed. Fail loud — let
the error propagate, or handle the specific failure and do NOT mark the order paid.

## Bad → finding

**Input (diff):**
```js
const res = await fetch(url);   // no timeout, no error handling
return res.json();
```
**Expected finding:** No timeout and no failure handling on a remote call. Add an
AbortController timeout and handle non-OK responses / network errors with a defined
fallback; bare `await fetch` can hang indefinitely.

## Good → no finding

**Input (diff):**
```python
try:
    charge = payments.charge(order.total)
except PaymentDeclined as e:
    log.warning("charge declined", order_id=order.id, reason=e.code)
    return CheckoutResult.declined(e.code)   # specific, surfaced, no false "paid"
order.mark_paid()
```
**Expected finding:** None — narrow exception, surfaced with context, no silent
fallthrough.
```

- [ ] **Step 2: Write `evals/eval.json`** with ≥3 scenarios

```json
{
  "skills": ["hunting-silent-failures"],
  "scenarios": [
    {
      "query": "Review this change:\n```python\ntry:\n    charge = payments.charge(order.total)\nexcept Exception:\n    pass\norder.mark_paid()\n```",
      "expected_behavior": [
        "Flags the empty `except Exception: pass` as a swallowed error",
        "Notes that order.mark_paid() runs even when the charge failed",
        "Recommends failing loud or handling the specific exception without marking paid"
      ]
    },
    {
      "query": "Review this change:\n```js\nconst res = await fetch(url);\nreturn res.json();\n```",
      "expected_behavior": [
        "Flags the missing timeout on the remote call",
        "Flags the missing handling of non-OK responses / network errors",
        "Suggests a timeout (e.g. AbortController) and a defined fallback"
      ]
    },
    {
      "query": "Review this change:\n```python\ntry:\n    charge = payments.charge(order.total)\nexcept PaymentDeclined as e:\n    log.warning('declined', order_id=order.id, reason=e.code)\n    return CheckoutResult.declined(e.code)\norder.mark_paid()\n```",
      "expected_behavior": [
        "Reports no silent-failure issue",
        "Recognizes the exception is narrow, surfaced with context, and avoids a false 'paid' state"
      ]
    }
  ]
}
```

- [ ] **Step 3: Validate the evals**

Run: `python -c "from tooling.evals import load_evals, validate_evals; validate_evals(load_evals('skills/hunting-silent-failures/evals/eval.json'))"`
Expected: no output, exit 0.

- [ ] **Step 4: Manually run the 3 scenarios against two model tiers**

For each scenario, load the skill and prompt a strong model (e.g. Opus/Sonnet) and a small/local-class model (e.g. an ~8B local model) with the skill available, and check the response against `expected_behavior`. Record pass/fail per scenario per model in the commit message body. (No automated grader exists yet — this is a manual gate; an automated runner is a later enhancement.)
Expected: all 3 scenarios pass on the strong model; note any small-model gaps to feed back into `reference/heuristics.md` explicitness.

- [ ] **Step 5: Commit**

```bash
git add skills/hunting-silent-failures/examples.md skills/hunting-silent-failures/evals/eval.json
git commit -m "feat(skills): refine hunting-silent-failures with examples and evals

Eval results: 3/3 pass on Sonnet; <record small-model results here>."
```

---

## Task 15: Prove the regeneration loop + write the runbook

**Files:**
- Create: `docs/runbooks/regenerating-skills.md`
- (Temporarily edit then revert a research section to demonstrate drift)

- [ ] **Step 1: Demonstrate drift detection**

Edit one heuristic in `docs/research/cluster-1-correctness.md` section `#2` (e.g. reword "Does every remote/IO call have a timeout?"). Then run:

Run: `python -m tooling.cli drift`
Expected: `DRIFT: hunting-silent-failures — changed sources: #2`

- [ ] **Step 2: Regenerate and confirm sync**

Run: `python -m tooling.cli generate && python -m tooling.cli drift`
Expected: regeneration prints `generated skills/...`; drift then prints `No drift: …`. Confirm `git diff skills/hunting-silent-failures/reference/heuristics.md` shows the reworded heuristic flowed through, and `examples.md`/`evals/eval.json` are unchanged (refinement preserved).

- [ ] **Step 3: Revert the demonstration edit to the research file**

Run: `git checkout docs/research/cluster-1-correctness.md`
Then regenerate so provenance hashes match the reverted docs:
Run: `python -m tooling.cli generate && python -m tooling.cli drift`
Expected: `No drift: …`

- [ ] **Step 4: Write `docs/runbooks/regenerating-skills.md`**

```markdown
# Runbook — Regenerating skills after a docs change

The taxonomy + `docs/research/cluster-*.md` are the source of truth. Skills are
derived. After you critique/improve a research section, flow it into the skills:

1. **See what's affected:** `python -m tooling.cli drift`
   Lists every skill whose source sections changed (by `#n`).
2. **Regenerate:** `python -m tooling.cli generate`
   Rebuilds each skill's `SKILL.md` + `reference/*` from current docs and
   re-stamps provenance hashes. `examples.md` and `evals/eval.json` are NOT
   overwritten (hand-refined content is preserved).
3. **Re-validate evals:** for each affected skill, re-run its `evals/eval.json`
   scenarios against your model tiers (see the skill's evals). Fix regressions
   by tightening `reference/heuristics.md` (via the docs) or `examples.md`.
4. **Confirm sync:** `python -m tooling.cli drift` → "No drift".
5. **Commit** the regenerated skills with the docs change.

Adapting granularity later: edit `skills/manifest.yaml` (merge/split skills or
re-map `built_from` categories), then run steps 2–4. No research edits needed.
```

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/regenerating-skills.md
git commit -m "docs: runbook for the docs->drift->regenerate->evals loop"
```

---

## Self-Review

**Spec coverage** (against `docs/phase-2-skill-suite-design.md`):
- §2.1 manifest → Tasks 5, 6, 13. §2.2 generator → Tasks 7–9, 13. §2.4 drift → Tasks 10, 15. §2.5 evals → Tasks 11, 14. §3 skill anatomy (lean SKILL.md + one-level-deep reference/* + examples + evals) → Tasks 8, 9, 14. §6 adaptation loop → Task 15 + runbook. §8 DoD: manifest with 6 ★ (Task 13), tooling end-to-end (Tasks 2–12), one fully-refined skill with ≥3 evals tested on two tiers (Task 14), regeneration runbook (Task 15). **Deferred (stated up front):** full refinement + cross-model eval tuning of skills 2–6 → follow-on plan. Provenance `taxonomy_version` carried via manifest (Task 5/8). G1 single-owner fields (`primary_owner`/`cross_ref`) are parsed (Task 5) but not yet enforced — acceptable for wave 1 (the 6 ★ don't collide); enforcement is a follow-on.
- **Placeholder scan:** every code step shows complete code; the only intentional human-judgment step is Task 14 Step 4 (manual cross-model eval run — unavoidable, no automated grader exists) and the `examples.md` content is fully provided.
- **Type consistency:** `extract_section(markdown, n)`, `extract_subsection(section_text, kind)`, `section_hash(markdown, n)`, `Source(category, source).path/.section`, `Skill`, `Manifest(taxonomy_version, skills)`, `validate(manifest, docs_root)`, `build_reference(skill, kind, docs_root)`, `build_skill_md(skill, taxonomy_version, docs_root)`, `generate_skill(skill, taxonomy_version, docs_root, skills_root)`, `check_drift(skills_root, docs_root)`, `DriftReport(skill, changed)`, `load_evals`/`validate_evals`/`EvalDoc`, `main(argv)` — names/signatures are consistent across tasks.
