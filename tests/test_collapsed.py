# SPDX-License-Identifier: MIT
# tests/test_collapsed.py
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
    # Assert the bundle's *structure* (independent of research-fixture wording) so
    # the first red/green is for the right reason — function unimplemented, not a
    # mismatched fixture string.
    assert body.startswith("# hunting-silent-failures")  # H1 = lens name
    assert "## When to use" in body
    assert "## Checklist" in body
    assert "## From category #2" in body   # heuristics embedded (fixture's built_from category)
    assert "(tool-rules.md)" in body and "(sources.md)" in body   # deeper disclosure links


def test_generate_lens_bundle_writes_three_files(tmp_path):
    dest = generate_lens_bundle(_skill(), tmp_path, docs_root=".", skills_root="skills")
    assert (dest / "body.md").exists()
    assert (dest / "tool-rules.md").exists()
    assert (dest / "sources.md").exists()
