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
