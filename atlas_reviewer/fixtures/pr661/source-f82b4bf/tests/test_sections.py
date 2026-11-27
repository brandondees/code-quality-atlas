# SPDX-License-Identifier: MIT
# tests/test_sections.py
from pathlib import Path

from tooling.sections import (
    PRIORITY_MARKER,
    extract_section,
    is_priority,
    strip_priority,
)

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (ROOT / "tests" / "fixtures" / "research_sample.md").read_text()


def test_priority_marker_detection_and_stripping():
    assert is_priority(PRIORITY_MARKER + "Calendar time-bombs?")
    assert not is_priority("Are caches bounded?")
    # stripped at a bullet boundary and inline; a no-op when absent
    assert strip_priority(f"- {PRIORITY_MARKER}Calendar?") == "- Calendar?"
    # inline form (no "- " prefix) — the path top_checks takes on an already-
    # extracted bullet
    assert strip_priority(f"{PRIORITY_MARKER}Calendar?") == "Calendar?"
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
    assert "Release It!" not in heur  # references excluded
    assert "no-floating-promises" not in heur  # tooling excluded


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
    assert h2a == h2b  # deterministic
    assert h2a != h4  # section-specific
    assert len(h2a) == 64  # sha256 hex


def test_section_hash_changes_when_text_changes():
    edited = SAMPLE.replace(
        "Does every remote call have a timeout?",
        "Does every remote call have a timeout and deadline?",
    )
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
    assert "## #8" not in section  # stopped before next section
    h1 = section_hash(markdown, 7)
    h2 = section_hash(markdown, 7)
    assert h1 == h2  # deterministic
    assert len(h1) == 64  # SHA-256 hex


def test_last_section_stops_at_non_numbered_h2():
    """The last numbered section must terminate at a trailing non-numbered H2
    (e.g. `## Open threads`) — not absorb it into its text/hash (regression for
    the section-boundary bug)."""
    sec4 = extract_section(SAMPLE, 4)
    assert "Is every acquired resource released" in sec4  # its own content kept
    assert "Open threads" not in sec4  # trailing H2 excluded
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
    assert len(bullets) == 5
    assert all(not b.startswith("- ") for b in bullets)


def test_extract_bullets_joins_continuation_lines_and_skips_trailing_rule():
    text = "### Heading\n- First check spanning\n  two lines?\n- Second check?\n\n---\n"
    bullets = extract_bullets(text)
    assert bullets == ["First check spanning two lines?", "Second check?"]


# --- Fence-awareness (#368) ---
# All three MULTILINE-regex scanners below (extract_section, extract_subsection,
# extract_bullets) previously matched `## `/`### `/`- ` lines anywhere in the
# document, including inside a fenced code block — a fenced example truncated
# the section/subsection early or spawned a phantom bullet, and section_hash
# (built on extract_section) silently stopped covering anything after the
# fence, so drift went undetected.


def test_extract_section_skips_a_fenced_heading_and_keeps_content_after_it():
    markdown = (
        "# Doc\n\n"
        "## #7 Comments\n\n"
        "Good comments explain intent.\n\n"
        "```markdown\n"
        "## Instructions\n"
        "This looks like a heading but is fenced example content.\n"
        "```\n\n"
        "More real prose after the fence.\n\n"
        "## #8 Next section\n\nOther content.\n"
    )
    section = extract_section(markdown, 7)
    assert "Instructions" in section  # fenced example content is kept...
    assert (
        "More real prose after the fence." in section
    )  # ...and doesn't end the section
    assert "## #8" not in section  # still stops at the real next H2


def test_extract_subsection_skips_a_fenced_subheading():
    section = (
        "## #2 Error handling\n\n"
        "### Reviewable heuristics\n\n"
        "- Is any error swallowed?\n\n"
        "```yaml\n"
        "### Not a real subheading\n"
        "```\n\n"
        "- Does every remote call have a timeout?\n"
    )
    heur = extract_subsection(section, "heuristics")
    assert (
        "Not a real subheading" in heur
    )  # fenced text stays part of the subsection...
    assert (
        "Does every remote call have a timeout?" in heur
    )  # ...instead of truncating it


def test_extract_bullets_does_not_split_on_a_fenced_bullet_line():
    text = (
        "### Heuristics\n"
        "- A check. Bad example:\n"
        "```yaml\n"
        "- name: not-a-check\n"
        "  run: echo hi\n"
        "```\n"
        "- Second real check?\n"
    )
    bullets = extract_bullets(text)
    assert len(bullets) == 2  # not 3 — no phantom bullet from the fence
    assert bullets[0].startswith("A check. Bad example:")
    assert "not-a-check" in bullets[0]  # fenced example folded into its parent bullet
    assert bullets[1] == "Second real check?"


def test_section_hash_covers_text_after_a_fenced_heading():
    base = (
        "# Doc\n\n"
        "## #3 Testing\n\n"
        "Some intro.\n\n"
        "```python\n"
        "## fake heading in code\n"
        "```\n\n"
        "Content after the fence that matters.\n\n"
        "## #4 Next\n\nOther.\n"
    )
    edited = base.replace(
        "Content after the fence that matters.",
        "Content after the fence that matters a lot more now.",
    )
    assert section_hash(edited, 3) != section_hash(base, 3)


# --- _FenceTracker edge cases (review findings on PR #403) ---
from tooling.sections import _FenceTracker


def test_fence_tracker_never_opens_on_a_tab_indented_delimiter():
    # A leading tab is 4 columns under CommonMark's tab-stop rule, so a
    # tab-indented "```" is a 4+-column indented line, not a fence opener —
    # `line.lstrip(" ")` alone leaves a leading tab untouched and would
    # otherwise misreport this line as indent 0.
    fence = _FenceTracker()
    assert fence.consume("\t```\n") is False
    assert fence.consume("plain text\n") is False  # confirms no fence is open


def test_fence_tracker_ignores_a_tab_indented_line_as_a_closer():
    fence = _FenceTracker()
    assert fence.consume("```\n") is True
    assert fence.consume("\t```\n") is True  # tab-indented: doesn't close it
    assert (
        fence.consume("still inside\n") is True
    )  # confirms the fence didn't close above
    assert fence.consume("```\n") is True  # this (unindented) line closes it
    assert fence.consume("outside now\n") is False  # confirms it actually closed


def test_fence_tracker_rejects_backtick_in_backtick_fence_info_string():
    # CommonMark: a backtick fence's info string may not itself contain a
    # backtick (ambiguous with inline code spans); a tilde fence has no such
    # restriction.
    fence = _FenceTracker()
    assert fence.consume("```has a ` backtick\n") is False
    assert fence.consume("plain text\n") is False  # confirms no fence is open


def test_fence_tracker_tilde_fence_info_string_may_contain_a_backtick():
    fence = _FenceTracker()
    assert fence.consume("~~~has a ` backtick\n") is True
    assert fence.consume("content\n") is True
    assert fence.consume("~~~\n") is True
    assert fence.consume("outside\n") is False


def test_extract_section_not_blinded_by_a_backtick_in_a_fence_info_string():
    # Before the fix, a backtick in a backtick-fence's info string was
    # accepted as a valid opener anyway. That "fence" never legitimately
    # closes (no real ``` follows), so every real heading after it —
    # including "## #2" below — read as fence content and was skipped.
    markdown = (
        "# Doc\n\n"
        "## #1 First\n\n"
        "Example: ```inline-ish info with a ` backtick, not a real fence\n\n"
        "## #2 Second\n\nReal content.\n"
    )
    section = extract_section(markdown, 1)
    assert "## #2" not in section
    sec2 = extract_section(markdown, 2)
    assert "Real content." in sec2


def test_extract_section_only_splits_lines_on_literal_newline():
    # atlas review finding on PR #403: str.splitlines() (unlike re.MULTILINE's
    # `^`, which the old whole-document regex scan relied on) also treats
    # \v, \f, \x1c-\x1e, NEL, U+2028/2029, and a lone \r as line breaks. A
    # "## " fragment immediately after one of those characters must NOT be
    # newly (mis)matched as its own heading line.
    markdown = (
        "# Doc\n\n"
        "## #1 First\n\n"
        "para one\x0c## fake heading, not a real line start\n\n"
        "## #2 Second\n\nReal content.\n"
    )
    section = extract_section(markdown, 1)
    assert "fake heading" in section  # stayed part of section #1's text...
    assert "## #2" not in section  # ...and still stops at the real next H2
