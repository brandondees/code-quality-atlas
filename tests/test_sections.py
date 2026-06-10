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
