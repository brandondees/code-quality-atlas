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
