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
