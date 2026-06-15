# SPDX-License-Identifier: MIT
# tests/test_sections.py
from pathlib import Path
from tooling.sections import (extract_section, is_priority, strip_priority,
                             PRIORITY_MARKER)

SAMPLE = Path("tests/fixtures/research_sample.md").read_text()


def test_priority_marker_detection_and_stripping():
    assert is_priority(PRIORITY_MARKER + "Calendar time-bombs?")
    assert not is_priority("Are caches bounded?")
    # stripped at a bullet boundary and inline; a no-op when absent
    assert strip_priority(f"- {PRIORITY_MARKER}Calendar?") == "- Calendar?"
    assert strip_priority("- Are caches bounded?") == "- Are caches bounded?"

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


def test_extract_section_and_hash_with_unicode_heading():
    """extract_section and section_hash must handle em-dash and & in a heading."""
    markdown = (
        "# Doc\n\n"
        "## #7 Comments — why & how\n\n"
        "Good comments explain intent, not mechanics.\n\n"
        "## #8 Next section\n\n"
        "Some other content.\n"
    )
    section = extract_section(markdown, 7)
    assert "Comments — why & how" in section
    assert "## #8" not in section          # stopped before next section
    h1 = section_hash(markdown, 7)
    h2 = section_hash(markdown, 7)
    assert h1 == h2                        # deterministic
    assert len(h1) == 64                   # SHA-256 hex


def test_last_section_stops_at_non_numbered_h2():
    """The last numbered section must terminate at a trailing non-numbered H2
    (e.g. `## Open threads`) — not absorb it into its text/hash (regression for
    the section-boundary bug)."""
    sec4 = extract_section(SAMPLE, 4)
    assert "Is every acquired resource released" in sec4   # its own content kept
    assert "Open threads" not in sec4                      # trailing H2 excluded
    assert "## Open threads" not in sec4
    # editing the Open-threads block must NOT change section #4's hash
    edited = SAMPLE.replace("must NOT be absorbed", "must absolutely NOT be absorbed")
    assert section_hash(edited, 4) == section_hash(SAMPLE, 4)


def test_section_stops_at_non_numbered_h2_inline():
    markdown = (
        "# Doc\n\n"
        "## #1 Only section\n\nbody line\n\n"
        "## Open threads\n\ntrailing notes\n"
    )
    sec = extract_section(markdown, 1)
    assert "body line" in sec
    assert "trailing notes" not in sec
    assert "Open threads" not in sec


from tooling.sections import extract_bullets

def test_extract_bullets_from_heuristics_subsection():
    heur = extract_subsection(extract_section(SAMPLE, 2), "heuristics")
    bullets = extract_bullets(heur)
    assert bullets[0].startswith("Is any error swallowed")
    assert len(bullets) == 3
    assert all(not b.startswith("- ") for b in bullets)

def test_extract_bullets_joins_continuation_lines_and_skips_trailing_rule():
    text = (
        "### Heading\n"
        "- First check spanning\n"
        "  two lines?\n"
        "- Second check?\n"
        "\n---\n"
    )
    bullets = extract_bullets(text)
    assert bullets == ["First check spanning two lines?", "Second check?"]
