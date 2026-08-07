# SPDX-License-Identifier: MIT
# tests/test_prepass.py
"""The deterministic-tool evidence pre-pass (map-gaps G34 Tier 1).

Three things are worth locking in mechanically, because each has a silent
failure mode that reads as "fine" in the generated output:

1. `grounds:` naming a lens that no longer exists — the table would ship a
   dangling pointer telling a reviewer to route hits to nothing.
2. The bundled `reference/tool-evidence.md` going stale or vanishing while the
   entrypoint still tells the reader to open it.
3. The discipline rules — especially "a clean run clears nothing" and the
   untrusted-branch rule — quietly dropping out of the generated skill. They are
   the difference between a pre-pass that improves a review and one that
   launders tool output into findings.
"""
import re
from pathlib import Path

import pytest
import yaml

from tooling.generate_collapsed import generate_collapsed
from tooling.generate_prepass import (
    build_collapsed_prepass,
    build_prepass_md,
    generate_prepass,
)
from tooling.manifest import ValidationError, load_manifest, validate

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = str(ROOT / "skills" / "manifest.yaml")


@pytest.fixture(scope="module")
def manifest():
    m = load_manifest(MANIFEST)
    validate(m, docs_root=str(ROOT))
    return m


def test_manifest_defines_a_prepass(manifest):
    assert manifest.prepass is not None
    assert manifest.prepass.name == "grounding-review-in-tool-output"


def test_every_grounded_lens_exists(manifest):
    """A `grounds:` entry is a routing instruction; a name with no lens behind
    it sends hits nowhere. validate() enforces this, so assert it *rejects* a
    bad name rather than only that today's names happen to be good."""
    names = {s.name for s in manifest.skills}
    for family in manifest.prepass.families:
        assert set(family.grounds) <= names, family.kind

    manifest.prepass.families[0].grounds.append("no-such-lens")
    try:
        with pytest.raises(ValidationError, match="grounds unknown skill"):
            validate(manifest, docs_root=str(ROOT))
    finally:
        manifest.prepass.families[0].grounds.pop()


def test_duplicate_composition_names_are_rejected(manifest):
    """router / prepass / synthesizer each generate into skills/<name>/, so two
    sharing a name would silently overwrite one another. Neither one's own
    validator can see the other, so this is checked across the three."""
    original = manifest.prepass.name
    manifest.prepass.name = manifest.synthesizer.name
    try:
        with pytest.raises(ValidationError, match="distinct names"):
            validate(manifest, docs_root=str(ROOT))
    finally:
        manifest.prepass.name = original


def test_generated_skill_keeps_the_load_bearing_discipline(manifest):
    md = build_prepass_md(manifest)
    # Each of these is a rule whose absence turns the pre-pass into a tool dump.
    for phrase in (
        "A clean run clears nothing",
        "Never introduce a tool the repo has not adopted",
        "Running the repo's tools runs the repo's code",
        "Check every hit against the diff before reporting it",
    ):
        assert phrase in md, f"missing discipline rule: {phrase}"
    # The three dispositions must be exhaustive and named.
    for disposition in ("**confirm**", "**contextualize**", "**dismiss**"):
        assert disposition in md
    # The coverage handoff is the part a reader cannot reconstruct.
    assert "No deterministic coverage:" in md


def test_generated_skill_has_parsable_frontmatter(manifest):
    md = build_prepass_md(manifest)
    assert md.startswith("---\n")
    front = yaml.safe_load(md.split("---\n", 2)[1])
    assert front["name"] == manifest.prepass.name
    # Built from the manifest alone, like the router and synthesizer — so the
    # docs-drift checker has nothing to track and never flags it.
    assert front["provenance"]["built_from"] == []
    assert front["provenance"]["taxonomy_version"] == manifest.taxonomy_version


def test_collapsed_form_strips_frontmatter_and_outbound_links(manifest):
    """The bundled copy is Read directly, not navigated from: its `Going deeper`
    links point outside the bundle (`../<router>/SKILL.md`) and would 404."""
    body = build_collapsed_prepass(manifest)
    assert not body.startswith("---")
    assert "## Going deeper" not in body
    assert "../choosing-review-lenses/SKILL.md" not in body
    # The procedure itself survives the strip.
    assert "## 1. Discover what the repo already runs" in body
    assert "A clean run clears nothing" in body


def test_every_entrypoint_bundles_the_prepass_and_points_at_it(manifest):
    """Both halves, together: the file exists in every entrypoint *and* the
    entrypoint's own procedure tells the reader to open it. Either alone is a
    dead end — an unreferenced file nobody loads, or a pointer to nothing."""
    for ep in manifest.entrypoints:
        bundled = ROOT / "collapsed" / "skills" / ep.name / "reference" / "tool-evidence.md"
        assert bundled.exists(), f"{ep.name} is missing reference/tool-evidence.md"
        text = bundled.read_text(encoding="utf-8")
        assert "GENERATED by" in text.split("\n", 1)[0]
        assert "A clean run clears nothing" in text
        skill_md = (ROOT / "collapsed" / "skills" / ep.name / "SKILL.md").read_text(
            encoding="utf-8")
        assert "`reference/tool-evidence.md`" in skill_md, (
            f"{ep.name}'s SKILL.md bundles the pre-pass but never tells the "
            "reader to open it")


def test_dropping_the_prepass_prunes_the_bundled_copy(manifest, tmp_path):
    """A stale `tool-evidence.md` left behind after the manifest drops the block
    would keep advertising a step the entrypoint no longer describes — the same
    staleness the entrypoint/lens prunes already prevent."""
    collapsed = tmp_path / "collapsed"
    generate_collapsed(manifest, docs_root=str(ROOT), skills_root=str(ROOT / "skills"),
                       collapsed_root=str(collapsed))
    ep = manifest.entrypoints[0].name
    bundled = collapsed / "skills" / ep / "reference" / "tool-evidence.md"
    assert bundled.exists()

    original, manifest.prepass = manifest.prepass, None
    try:
        generate_collapsed(manifest, docs_root=str(ROOT),
                           skills_root=str(ROOT / "skills"),
                           collapsed_root=str(collapsed))
        assert not bundled.exists(), "the bundled pre-pass outlived the manifest block"
        skill_md = (collapsed / "skills" / ep / "SKILL.md").read_text(encoding="utf-8")
        assert "tool-evidence.md" not in skill_md
    finally:
        manifest.prepass = original


def test_generate_prepass_seeds_an_eval_stub_without_clobbering(manifest, tmp_path):
    out = generate_prepass(manifest, skills_root=str(tmp_path))
    stub = out / "evals" / "eval.json"
    assert stub.exists()
    stub.write_text('{"skills": ["x"], "scenarios": [{"query": "kept"}]}\n',
                    encoding="utf-8")
    generate_prepass(manifest, skills_root=str(tmp_path))
    assert "kept" in stub.read_text(encoding="utf-8"), (
        "regeneration overwrote a hand-authored eval suite")


@pytest.mark.parametrize("bad, expect", [
    ({"source": None, "tells": "x"}, "must be a non-empty string, got null"),
    ({"source": 12, "tells": "x"}, "must be a string, got int"),
    ({"tells": "x"}, "missing field 'source'"),
])
def test_prepass_prose_fields_reject_non_strings(tmp_path, bad, expect):
    """`str(value)` would have turned a bare `source:` into the literal "None",
    which then satisfies every non-empty check downstream and ships a table row
    reading "None"; a number would instead crash `.strip()` with a raw
    AttributeError. Both are malformed manifests and must say so."""
    doc = yaml.safe_load((ROOT / "skills" / "manifest.yaml").read_text(encoding="utf-8"))
    doc["prepass"]["discover"] = [bad]
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    with pytest.raises(ValidationError, match=re.escape(expect)):
        load_manifest(str(path))


def test_prepass_grounds_entries_must_be_strings(tmp_path):
    """A non-string `grounds` entry can never match a lens name, so it would
    slip past the unknown-skill check as a silently unroutable family."""
    doc = yaml.safe_load((ROOT / "skills" / "manifest.yaml").read_text(encoding="utf-8"))
    doc["prepass"]["families"][0]["grounds"] = ["checking-restraint", 7]
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    with pytest.raises(ValidationError, match="every 'grounds' entry must be a string"):
        load_manifest(str(path))
