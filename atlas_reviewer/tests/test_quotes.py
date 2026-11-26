# SPDX-License-Identifier: MIT
import io
import tarfile
from dataclasses import replace

import pytest

from atlas_reviewer import quotes
from atlas_reviewer.lens_contract import (
    Attribution,
    DesignRef,
    Finding,
    LineRange,
    PullBody,
    Route,
    Severity,
    Valence,
    WholeFile,
)
from atlas_reviewer.quotes import (
    QuoteSource,
    SourceText,
    Unverified,
    Verified,
    check_all,
    check_quote,
    read_sources,
)

from .helpers import source_tarball

HEAD_FILES = {
    "calc.py": (
        b"def total(xs):\n"
        b"    return sum(round(x, 2) for x in xs)\n"
        b"\n"
        b"def mean(xs):\n"
        b"    if not xs:\n"
        b"        return 0\n"
        b"    return total(xs) / len(xs)\n"
        b"}\n"
    ),
    "src/new_name.py": b"VALUE = 1\n",
}
DIFF = """\
diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def total(xs):
-    return sum(xs)
-    # no rounding here
+    return sum(round(x, 2) for x in xs)
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-import os
-os.system(cmd)
diff --git a/src/old_name.py b/src/new_name.py
similarity index 50%
rename from src/old_name.py
rename to src/new_name.py
--- a/src/old_name.py
+++ b/src/new_name.py
@@ -1 +1 @@
-VALUE = eval(raw)
+VALUE = 1
"""


def finding(location, evidence=""):
    return Finding(
        location,
        Severity.MAJOR,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "something is wrong",
        "fix it",
        evidence,
    )


def sources(paths=("calc.py", "src/new_name.py", "gone.py")):
    return read_sources(source_tarball(HEAD_FILES, "org-repo-abc1234"), DIFF, paths)


def check(location, evidence=""):
    return check_quote(finding(location, evidence), sources())


@pytest.mark.parametrize(
    ("start", "end", "evidence"),
    [
        (2, 2, "return sum(round(x, 2) for x in xs)"),
        (2, 2, "        return sum(round(x, 2) for x in xs)   "),
        (2, 2, "round(x, 2) for x"),
        (5, 6, "if not xs:\n    return 0"),
        (5, 6, "\n  if not xs:\nreturn 0\n\n"),
        (8, 8, "}"),
    ],
)
def test_a_quote_at_the_cited_head_range_is_verified(start, end, evidence):
    result = check(LineRange("calc.py", start, end), evidence)
    assert result == Verified(result.finding, QuoteSource.HEAD)


@pytest.mark.parametrize(
    ("start", "end", "evidence"),
    [
        (1, 3, "sum("),
        (4, 7, "if not xs:\n    return total(xs) / len(xs)"),
        (4, 7, "if not xs:\n        return 1"),
        (2, 2, "return sum(xs) + 1"),
    ],
)
def test_a_quote_not_at_the_cited_range_is_not_verified(start, end, evidence):
    """Line 2's whole-line text cited as 4-7 verifies now -- as a drifted
    match whose location is corrected (D64); it moved to
    `test_a_whole_line_quote_within_the_window_is_verified_as_drifted`."""
    assert isinstance(check(LineRange("calc.py", start, end), evidence), Unverified)


def test_a_head_file_outside_the_diff_can_be_added_once_read():
    tarball = source_tarball(HEAD_FILES, "t")
    narrow = read_sources(tarball, DIFF, ["calc.py"])
    wide = quotes.with_head_files(narrow, tarball, ["src/new_name.py", "calc.py"])
    assert set(wide.head) == {"calc.py", "src/new_name.py"}
    assert wide.removed == narrow.removed
    assert quotes.with_head_files(narrow, b"", ["src/new_name.py"]) is narrow
    assert (
        quotes.with_head_files(narrow, b"not a tarball", ["src/new_name.py"]) is narrow
    )
    unreadable = read_sources(b"not a tarball", DIFF, ["calc.py"])
    assert quotes.with_head_files(unreadable, tarball, ["calc.py"]) is unreadable


def test_internal_whitespace_does_not_reject_the_cited_line():
    evidence = "return  sum(round(x, 2)  for x in xs)"
    result = check(LineRange("calc.py", 2, 2), evidence)
    assert result == Verified(result.finding, QuoteSource.HEAD)


@pytest.mark.parametrize(
    ("start", "end", "evidence"),
    [
        (1, 1, "return sum(round(x, 2) for x in xs)"),
        (4, 4, "return sum(round(x, 2) for x in xs)"),
        (5, 5, "return sum(round(x, 2) for x in xs)"),
        (6, 7, "if not xs:\n    return 0"),
        (4, 4, "return total(xs) / len(xs)"),
        (8, 8, "return total(xs) / len(xs)"),
    ],
)
def test_a_whole_line_quote_within_the_window_is_verified_as_drifted(
    start, end, evidence
):
    """D64 widens D47's drift search: a whole-line quote may match a
    window of its own line count starting within three lines of the
    citation, so the off-by-one, the span mismatch and a two-line slip
    all verify, with the location corrected."""
    result = check(LineRange("calc.py", start, end), evidence)
    assert result.source is QuoteSource.HEAD_NEAR


def test_a_drifted_quote_takes_the_location_of_the_matched_lines():
    result = check(LineRange("calc.py", 4, 4), "return sum(round(x, 2) for x in xs)")
    assert result.finding.location == LineRange("calc.py", 2, 2)


def test_the_drift_is_the_distance_the_match_moved():
    """The posted tag is built from the match's own distance, not from
    the configured window (round-1 review of #703, Minor 1): the
    off-by-one says one line, the two-line slip says two, and a span
    correction at the citation's first line says so."""
    one = check(LineRange("calc.py", 1, 1), "return sum(round(x, 2) for x in xs)")
    assert one.drift == 1
    two = check(LineRange("calc.py", 4, 4), "return sum(round(x, 2) for x in xs)")
    assert two.drift == 2
    zero = check(LineRange("calc.py", 5, 8), "if not xs:\n    return 0")
    assert zero.drift == 0
    assert quotes.drift_label(0) == (
        "head at the citation's first line, span set by the quote"
    )
    assert quotes.drift_label(1) == "head within 1 line of the citation"
    assert quotes.drift_label(3) == "head within 3 lines of the citation"


def test_a_whole_line_quote_exactly_three_lines_off_is_the_window_edge():
    at_edge = check(LineRange("calc.py", 4, 4), "return total(xs) / len(xs)")
    assert at_edge.source is QuoteSource.HEAD_NEAR
    assert at_edge.drift == 3
    assert at_edge.finding.location == LineRange("calc.py", 7, 7)
    beyond = check(LineRange("calc.py", 1, 1), "return total(xs) / len(xs)")
    assert isinstance(beyond, Unverified)
    assert "not at that range" in beyond.reason


def test_the_nearest_match_wins_and_the_positive_direction_breaks_a_tie():
    """Both candidate lines hold the quote; the nearest start wins, and
    at equal distance the positive direction wins (deltas are tried 0,
    +1, -1, +2, -2, ...)."""
    files = {"m.py": b"a\ntarget line\nb\ntarget line\nc\n"}
    found = read_sources(source_tarball(files, "t"), "", ["m.py"])
    tie = check_quote(finding(LineRange("m.py", 3, 3), "target line"), found)
    assert tie.finding.location == LineRange("m.py", 4, 4)
    near = check_quote(finding(LineRange("m.py", 1, 1), "target line"), found)
    assert near.finding.location == LineRange("m.py", 2, 2)


def test_a_removed_line_match_wins_over_a_head_line_within_the_window():
    """The removed side has no head line, so it is checked before the
    window -- including when the same text is also in the head file
    within the window of the citation."""
    files = {"m.py": b"a = 1\nkeep me now\nkeep me now\nb = 2\n"}
    diff = (
        "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
        "@@ -1,4 +1,3 @@\n a = 1\n-keep me now\n keep me now\n b = 2\n"
    )
    found = read_sources(source_tarball(files, "t"), diff, ["m.py"])
    result = check_quote(finding(LineRange("m.py", 1, 1), "keep me now"), found)
    assert result.source is QuoteSource.REMOVED


def test_a_span_mismatch_lets_the_quote_set_the_span():
    """The issue's span-mismatch cases: a quote whose line count differs
    from the cited span verifies when its lines start within the window,
    and the finding carries the corrected range (D64 amends D40's span
    rule)."""
    # A two-line quote cited as three lines (6-8), starting one above the
    # citation's first line.
    short = check(LineRange("calc.py", 6, 8), "if not xs:\n    return 0")
    assert short.source is QuoteSource.HEAD_NEAR
    assert short.drift == 1
    assert short.finding.location == LineRange("calc.py", 5, 6)
    # A four-line quote cited at one line, whose first line sits one above
    # the cited one.
    long = check(
        LineRange("calc.py", 6, 6),
        "if not xs:\n    return 0\n    return total(xs) / len(xs)\n}",
    )
    assert long.source is QuoteSource.HEAD_NEAR
    assert long.finding.location == LineRange("calc.py", 5, 8)
    # The same four-line quote whose citation is nowhere near it.
    far = check(
        LineRange("calc.py", 1, 1),
        "if not xs:\n    return 0\n    return total(xs) / len(xs)\n}",
    )
    assert isinstance(far, Unverified)


def test_the_window_is_configurable():
    quote = "return sum(round(x, 2) for x in xs)"
    zero = check_quote(finding(LineRange("calc.py", 4, 4), quote), sources(), 0)
    assert isinstance(zero, Unverified)
    one = check_quote(finding(LineRange("calc.py", 3, 3), quote), sources(), 1)
    assert one.source is QuoteSource.HEAD_NEAR
    assert one.finding.location == LineRange("calc.py", 2, 2)
    tight = check_quote(finding(LineRange("calc.py", 4, 4), quote), sources(), 1)
    assert isinstance(tight, Unverified)


def test_a_match_at_the_configured_window_is_tagged_with_its_distance():
    """The posted tag names the match's own distance even at a
    non-default window (round-1 review of #703, Minor 1): with the
    tolerance at 8, a quote eight lines from its citation verifies and
    the tag says eight."""
    files = {"m.py": b"a = 1\n" + b"\n" * 7 + b"value = 12345678\nother = 12345678\n"}
    found = read_sources(source_tarball(files, "t"), "", ["m.py"])
    # value = 12345678 sits on line 9; other = 12345678 on line 10.
    at_eight = check_quote(
        finding(LineRange("m.py", 1, 1), "value = 12345678"), found, 8
    )
    assert at_eight.source is QuoteSource.HEAD_NEAR
    assert at_eight.drift == 8
    assert quotes.drift_label(8) == "head within 8 lines of the citation"
    beyond = check_quote(finding(LineRange("m.py", 1, 1), "other = 12345678"), found, 8)
    assert isinstance(beyond, Unverified)


def test_the_window_zero_still_corrects_a_span_mismatch():
    """Tolerance 0 disables the offset search, not the span rule's
    amendment: a quote whose lines start at the citation still sets its
    own span."""
    result = check_quote(
        finding(LineRange("calc.py", 5, 8), "if not xs:\n    return 0"),
        sources(),
        0,
    )
    assert result.source is QuoteSource.HEAD_NEAR
    assert result.drift == 0
    assert result.finding.location == LineRange("calc.py", 5, 6)


def test_a_quote_of_a_removed_line_is_tagged_removed_even_near_the_citation():
    head = source_tarball({"calc.py": b"def total(xs):\n    return sum(xs)\n"}, "t")
    diff = (
        "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
        "@@ -1,2 +1,2 @@\n def total(xs):\n-    return sum(xs)\n"
        "+    return sum(round(xs))\n"
    )
    sources = read_sources(head, diff, ["calc.py"])
    result = check_quote(
        finding(LineRange("calc.py", 1, 1), "    return sum(xs)"), sources
    )
    assert result.source is QuoteSource.REMOVED


@pytest.mark.parametrize(
    ("start", "end", "evidence"),
    [
        (6, 6, "return sum(round(x, 2) for x in xs)"),
        (1, 1, "}"),
        (7, 7, "}"),
        (1, 1, "round(x, 2) for x"),
        (1, 1, "return total(xs) / len(xs)"),
    ],
)
def test_a_short_fragment_or_a_far_line_is_not_treated_as_drift(start, end, evidence):
    """A fragment never drifts, and a whole line more than the window
    away does not. (D64: the window is three lines, so `return 0` cited
    at 4 or 8, and line 2's text cited at 5, are drifted matches now --
    see `test_a_whole_line_quote_within_the_window_is_verified_as_drifted`.)"""
    assert isinstance(check(LineRange("calc.py", start, end), evidence), Unverified)


def test_a_quote_of_exactly_the_minimum_length_can_drift(tmp_path):
    """`xy = 12345` is 8 non-space characters, so it drifts; `xy = 1234` is 7."""
    files = {"m.py": b"a = 1\nb = 2\nxy = 12345\nxy = 1234\n"}
    found = read_sources(source_tarball(files, "t"), "", ["m.py"])
    at_floor = check_quote(finding(LineRange("m.py", 1, 1), "xy = 12345"), found)
    assert at_floor.source is QuoteSource.HEAD_NEAR
    assert at_floor.finding.location == LineRange("m.py", 3, 3)
    below = check_quote(finding(LineRange("m.py", 2, 2), "xy = 1234"), found)
    assert isinstance(below, Unverified)


def test_a_line_range_with_a_start_below_one_is_refused():
    with pytest.raises(ValueError, match="start"):
        LineRange("calc.py", 0, 1)
    with pytest.raises(ValueError, match="start"):
        LineRange("calc.py", -1, 1)


def test_a_doubled_space_on_the_head_side_does_not_reject_a_quote():
    files = {"m.py": b"a = 1\nreturn  total(xs)   /  len(xs)\nb = 2\n"}
    found = read_sources(source_tarball(files, "t"), "", ["m.py"])
    exact = check_quote(
        finding(LineRange("m.py", 2, 2), "return total(xs) / len(xs)"), found
    )
    assert exact.source is QuoteSource.HEAD
    drifted = check_quote(
        finding(LineRange("m.py", 3, 3), "return total(xs) / len(xs)"), found
    )
    assert drifted.source is QuoteSource.HEAD_NEAR


def test_a_doubled_space_on_a_removed_line_does_not_reject_a_quote():
    head = source_tarball({"m.py": b"a = 1\n"}, "t")
    diff = (
        "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
        "@@ -1,2 +1 @@\n a = 1\n-return  total(xs)   /  len(xs)\n"
    )
    found = read_sources(head, diff, ["m.py"])
    result = check_quote(
        finding(LineRange("m.py", 1, 1), "return total(xs) / len(xs)"), found
    )
    assert result.source is QuoteSource.REMOVED


def test_a_quote_that_sits_outside_its_cited_lines_is_not_verified():
    """The text is line 2; the citation is the last three lines of the file."""
    result = check(LineRange("calc.py", 6, 8), "return sum(round(x, 2) for x in xs)")
    assert isinstance(result, Unverified)
    assert "not at that range" in result.reason


def test_a_range_that_ends_past_the_file_is_not_verified():
    """Line 6's text, cited from line 2 to past the file. No window of
    the quote's own length near the citation's start holds it, so the
    range's own over-run is what the reason names (D64: line 2's text
    cited as 2-9 verifies now -- the quote sets the span -- see
    `test_a_span_mismatch_lets_the_quote_set_the_span`)."""
    result = check(LineRange("calc.py", 2, 9), "return 0")
    assert isinstance(result, Unverified)
    assert "past the end of the head file (8 lines)" in result.reason


def test_a_one_line_quote_cited_across_the_file_verifies_when_it_starts_the_range():
    """D64: the quote's own line count sets the searched span, so a
    whole-line quote cited across a wider range verifies when its line
    starts within the window of the citation's first line, with the
    location corrected to the lines that hold it."""
    result = check(LineRange("calc.py", 2, 9), "return sum(round(x, 2) for x in xs)")
    assert result == Verified(result.finding, QuoteSource.HEAD_NEAR)
    assert result.finding.location == LineRange("calc.py", 2, 2)


def test_a_short_fragment_passes_only_as_the_whole_line():
    assert isinstance(check(LineRange("calc.py", 7, 7), "xs)"), Unverified)
    assert isinstance(check(LineRange("calc.py", 8, 8), "}"), Verified)


def test_a_one_line_quote_cited_across_the_file_is_not_verified():
    """Line 7's text, cited as lines 1-8. The line sits in that window."""
    evidence = "return total(xs) / len(xs)"
    result = check(LineRange("calc.py", 1, 8), evidence)
    assert isinstance(result, Unverified)
    assert "not at that range" in result.reason
    exact = check(LineRange("calc.py", 7, 7), evidence)
    assert exact == Verified(exact.finding, QuoteSource.HEAD)


def test_a_multi_line_quote_cited_over_a_wider_span_is_corrected():
    """Lines 5-6 cited as 4-7: the quote's own line count sets the span,
    so the match at 5-6 is found within the window and the location is
    corrected to it (D64)."""
    evidence = "if not xs:\n    return 0"
    wide = check(LineRange("calc.py", 4, 7), evidence)
    assert wide.source is QuoteSource.HEAD_NEAR
    assert wide.drift == 1
    assert wide.finding.location == LineRange("calc.py", 5, 6)
    exact = check(LineRange("calc.py", 5, 6), evidence)
    assert exact == Verified(exact.finding, QuoteSource.HEAD)


def test_a_quote_of_removed_code_is_verified_against_the_diffs_removed_lines():
    result = check(LineRange("calc.py", 2, 2), "return sum(xs)\n# no rounding here")
    assert result == Verified(result.finding, QuoteSource.REMOVED)


def test_removed_lines_of_a_deleted_file_and_of_a_rename_source_verify():
    deleted = check(LineRange("gone.py", 2, 2), "os.system(cmd)")
    old_side = check(LineRange("src/old_name.py", 1, 1), "VALUE = eval(raw)")
    new_side = check(LineRange("src/new_name.py", 1, 1), "VALUE = eval(raw)")
    for result in (deleted, old_side, new_side):
        assert result == Verified(result.finding, QuoteSource.REMOVED)


def test_a_removed_line_of_another_file_does_not_verify():
    assert isinstance(check(LineRange("calc.py", 1, 2), "os.system(cmd)"), Unverified)


def test_an_added_line_is_not_a_removed_line():
    result = check(LineRange("gone.py", 1, 1), "return sum(round(x, 2) for x in xs)")
    assert isinstance(result, Unverified)


def test_a_range_past_the_end_of_the_file_says_so():
    result = check(LineRange("calc.py", 40, 41), "return 0")
    assert isinstance(result, Unverified)
    assert "past the end of the head file (8 lines)" in result.reason


def test_a_quote_in_a_file_the_head_does_not_have_is_not_verified():
    result = check(LineRange("missing.py", 1, 1), "def total(xs):")
    assert isinstance(result, Unverified)


def test_a_path_not_asked_for_is_not_read():
    narrow = read_sources(source_tarball(HEAD_FILES, "t"), DIFF, ["calc.py"])
    assert set(narrow.head) == {"calc.py"}


@pytest.mark.parametrize("path", ["calc.py", "gone.py", "src/old_name.py"])
def test_a_whole_file_finding_on_a_head_or_diffed_path_is_verified(path):
    result = check(WholeFile(path))
    assert result == Verified(result.finding, QuoteSource.NOT_NEEDED)


def test_a_whole_file_finding_on_an_unknown_path_is_not_verified():
    result = check(WholeFile("nowhere.py"))
    assert result == Unverified(
        result.finding, "the path is not in the head tree or the diff"
    )


def test_a_design_reference_needs_no_quote():
    result = check(DesignRef("component:billing"))
    assert result == Verified(result.finding, QuoteSource.NOT_NEEDED)


def test_an_unreadable_head_tree_fails_every_quote_that_needs_it():
    bad = read_sources(b"not a tarball", DIFF, ["calc.py"])
    head_quote, removed_quote = check_all(
        [
            finding(LineRange("calc.py", 2, 2), "return sum(round(x, 2) for x in xs)"),
            finding(LineRange("calc.py", 2, 2), "return sum(xs)"),
        ],
        bad,
    )
    assert isinstance(head_quote, Unverified)
    assert head_quote.reason.startswith("the head tree is refused")
    assert removed_quote == Verified(removed_quote.finding, QuoteSource.REMOVED)


def test_a_head_file_over_the_size_cap_is_not_read(monkeypatch):
    monkeypatch.setattr(quotes, "MAX_CHECKED_FILE_BYTES", 10)
    capped = read_sources(source_tarball(HEAD_FILES, "t"), DIFF, ["calc.py"])
    assert "calc.py" not in capped.head


def test_a_symlink_at_head_is_not_followed_as_the_file():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        top = tarfile.TarInfo("t")
        top.type = tarfile.DIRTYPE
        archive.addfile(top)
        data = b"def total(xs):\n"
        real = tarfile.TarInfo("t/real.py")
        real.size = len(data)
        archive.addfile(real, io.BytesIO(data))
        link = tarfile.TarInfo("t/calc.py")
        link.type = tarfile.SYMTYPE
        link.linkname = "real.py"
        archive.addfile(link)
    linked = read_sources(buffer.getvalue(), "", ["calc.py", "real.py"])
    assert linked.unreadable == ""
    assert set(linked.head) == {"real.py"}


def test_a_blank_quote_is_not_verified():
    result = check(LineRange("calc.py", 3, 3), " \n ")
    assert result == Unverified(result.finding, "the evidence quotes nothing")


def test_a_pull_request_body_finding_verifies_against_the_held_body():
    """The body finding's quote verifies against the description the
    controller held (issue #713's harness-parity slice), the way a file
    quote verifies against the head file."""
    body_finding = Finding(
        PullBody(),
        Severity.MINOR,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "the CI line names a head this PR no longer has",
        "update the gate line to the current head",
        evidence="`gate` on `61273b4f` (run 43429340358)",
    )
    held = "`gate` on `61273b4f` (run 43429340358). This pull request targets main."
    (check,) = check_all([body_finding], SourceText({}), body=held)
    assert isinstance(check, Verified)
    assert check.source is QuoteSource.PR_BODY
    (changed,) = check_all(
        [replace(body_finding, evidence="`gate` on `deadbeef` (run 1)")],
        SourceText({}),
        body=held,
    )
    assert not isinstance(changed, Verified)
    assert "not in the pull-request description" in changed.reason
    (no_body,) = check_all([body_finding], SourceText({}), body="")
    assert not isinstance(no_body, Verified)
    assert "not available" in no_body.reason
