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
