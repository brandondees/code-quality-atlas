# SPDX-License-Identifier: MIT
# tests/test_generate.py
from pathlib import Path
from tooling.manifest import Manifest, Route, Router, Skill, Source
from tooling.generate import build_reference


def _skill(**kw):
    base = dict(name="hunting-silent-failures", description="x", shape="diff", wave=1,
                built_from=[Source(2, "tests/fixtures/research_sample.md#2"),
                            Source(4, "tests/fixtures/research_sample.md#4")])
    base.update(kw)
    return Skill(**base)


def test_build_reference_heuristics_concatenates_across_sources_with_headers():
    md = build_reference(_skill(), kind="heuristics", docs_root=".")
    assert "## From category #2" in md
    assert "## From category #4" in md
    assert "Is any error swallowed" in md
    assert "Is every acquired resource released" in md
    assert "## Contents" in md  # ToC is always emitted


def test_build_reference_tooling_only_has_tooling():
    md = build_reference(_skill(), kind="tooling", docs_root=".")
    assert "no-floating-promises" in md
    assert "Is any error swallowed" not in md


def test_tooling_reference_leads_with_tool_selection_principle():
    # The named tools are starting points; the standing preamble must steer a
    # reviewer to pick/verify for their stack rather than cargo-cult a default.
    tooling = build_reference(_skill(), kind="tooling", docs_root=".")
    assert "Selecting tools for this stack" in tooling
    assert "verify it actually runs on your toolchain" in tooling
    # ...and only on tool lists, not the heuristics/reference files.
    heuristics = build_reference(_skill(), kind="heuristics", docs_root=".")
    assert "Selecting tools for this stack" not in heuristics


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


from tooling.generate import top_checks


def test_top_checks_are_inlined_so_skill_md_is_self_sufficient():
    md = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    # head of the heuristics checklist appears directly in the body
    assert "Is any error swallowed" in md
    assert "Is every acquired resource released" in md


def test_top_checks_cap_cross_ref_categories():
    # #4 is a cross_ref: it must contribute at most 2 checks; #2 (primary) leads
    checks = top_checks(_skill(cross_ref=[4]), docs_root=".")
    assert checks[0].startswith("Is any error swallowed")
    from_4 = [c for c in checks if "acquired resource" in c or "caches bounded" in c.lower()]
    assert len(from_4) <= 2


def test_scope_line_marks_design_capability():
    plain = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    assert "not meant for design docs" in plain
    design = build_skill_md(_skill(design=True), taxonomy_version="v0.2", docs_root=".")
    assert "design-capable" in design
    repo = build_skill_md(_skill(shape="repo"), taxonomy_version="v0.2", docs_root=".")
    assert "Shape: repo" in repo


def test_cross_ref_note_names_primary_owner():
    md = build_skill_md(_skill(cross_ref=[4]), taxonomy_version="v0.2", docs_root=".",
                        owners={2: "hunting-silent-failures", 4: "some-other-skill"})
    assert "shared with **some-other-skill**" in md
    assert "report each shared finding once" in md
    # without an owners map (or without cross_refs) no note is emitted
    assert "Shared categories" not in build_skill_md(
        _skill(), taxonomy_version="v0.2", docs_root=".",
        owners={2: "hunting-silent-failures"})


from tooling.generate import build_router_md, generate_router


def _manifest_with_router():
    return Manifest(
        taxonomy_version="v0.2",
        skills=[_skill(picker="Where do errors vanish?", design=True)],
        router=Router(
            name="choosing-review-lenses",
            description="Picks lenses.",
            routes=[Route(when="Bug fix", run=["hunting-silent-failures"]),
                    Route(when="Repo audit", run=["hunting-silent-failures"],
                          note="run independently")],
        ))


def test_build_router_md_routes_table_and_catalog():
    md = build_router_md(_manifest_with_router())
    front = yaml.safe_load(md.split("---\n")[1])
    assert front["name"] == "choosing-review-lenses"
    assert front["provenance"]["built_from"] == []   # manifest-derived: no docs drift
    assert "| Bug fix | `hunting-silent-failures` |" in md
    assert "— run independently |" in md
    assert "- `hunting-silent-failures` ◆ — Where do errors vanish?" in md


def test_generate_router_writes_skill_and_draft_eval(tmp_path):
    out = generate_router(_manifest_with_router(), skills_root=str(tmp_path))
    assert (out / "SKILL.md").exists()
    eval_doc = json.loads((out / "evals" / "eval.json").read_text())
    assert eval_doc["skills"] == ["choosing-review-lenses"]


from tooling.generate import build_synthesizer_md, generate_synthesizer
from tooling.manifest import Synthesizer, Tension


def _manifest_with_synthesizer():
    m = _manifest_with_router()
    m.skills.append(_skill(name="checking-restraint",
                           picker="brake pedal", design=True))
    m.synthesizer = Synthesizer(
        name="synthesizing-review-findings",
        description="Merges lens findings.",
        severity_order=["Blocker", "Major", "Minor", "Nit"],
        tensions=[Tension(between=["hunting-silent-failures", "checking-restraint"],
                          about="brake vs. resilience", resolve="favor safety")],
    )
    return m


def test_build_synthesizer_md_carries_severity_tensions_and_no_provenance():
    md = build_synthesizer_md(_manifest_with_synthesizer())
    front = yaml.safe_load(md.split("---\n")[1])
    assert front["name"] == "synthesizing-review-findings"
    assert front["provenance"]["built_from"] == []   # manifest-derived: no docs drift
    assert "**Blocker** > **Major** > **Minor** > **Nit**" in md
    assert "`hunting-silent-failures` ↔ `checking-restraint`" in md
    assert "favor safety" in md
    # closes the loop back to the router
    assert "choosing-review-lenses" in md


def test_router_points_forward_to_synthesizer_when_present():
    assert "synthesizing-review-findings" in build_router_md(_manifest_with_synthesizer())
    # and stays silent when there is no synthesizer
    assert "synthesizing-review-findings" not in build_router_md(_manifest_with_router())


def test_generate_synthesizer_writes_skill_and_draft_eval(tmp_path):
    out = generate_synthesizer(_manifest_with_synthesizer(), skills_root=str(tmp_path))
    assert (out / "SKILL.md").exists()
    eval_doc = json.loads((out / "evals" / "eval.json").read_text())
    assert eval_doc["skills"] == ["synthesizing-review-findings"]
