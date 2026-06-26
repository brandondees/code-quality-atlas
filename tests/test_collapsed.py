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


# --- Task 5: entrypoint SKILL.md + collapsed synthesis ---
from tooling.manifest import Route, Router, Synthesizer, Mode
from tooling.generate import build_entrypoint_md, build_collapsed_synthesis


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


def test_build_collapsed_synthesis_drops_going_deeper_and_broken_links():
    # The standalone "Going deeper" links (../<router>/SKILL.md, ../../docs/...)
    # don't exist inside a collapsed bundle and would 404; they must be dropped.
    md = build_collapsed_synthesis(_full_manifest())
    assert "Going deeper" not in md                       # heading and dangling prose ref both gone
    assert "/SKILL.md" not in md
    assert "docs/runbooks/multi-repo-audit.md" not in md


# --- Task 6: generate_collapsed writes the tree + plugin manifest ---

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


# --- Task 8: drift/regeneration gate across the collapsed tree ---
import os


def test_committed_collapsed_matches_regeneration(tmp_path):
    from tooling.manifest import load_manifest, validate
    from tooling.generate import generate_collapsed
    # Regenerate ONLY the collapsed tree into tmp_path — generate_collapsed reads
    # the real committed skills/ (for each lens's examples.md) but writes nowhere
    # but tmp_path, so this never overwrites the live skills/ tree as a side effect.
    m = load_manifest("skills/manifest.yaml")
    validate(m, docs_root=".")
    generate_collapsed(m, docs_root=".", skills_root="skills", collapsed_root=str(tmp_path))
    # the generated plugin.json must match the committed one (catches manifest drift)
    gen_plugin = (tmp_path / ".claude-plugin" / "plugin.json").read_text()
    committed_plugin = (Path("collapsed") / ".claude-plugin" / "plugin.json").read_text()
    assert gen_plugin == committed_plugin, "drift in collapsed/.claude-plugin/plugin.json"
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
