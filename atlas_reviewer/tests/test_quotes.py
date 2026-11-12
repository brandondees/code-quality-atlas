# SPDX-License-Identifier: MIT
import io
import tarfile

import pytest

from atlas_reviewer import quotes
from atlas_reviewer.lens_contract import (
    Attribution,
    DesignRef,
    Finding,
    LineRange,
    Route,
    Severity,
    Valence,
    WholeFile,
)
from atlas_reviewer.quotes import (
    QuoteSource,
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
        (4, 7, "return sum(round(x, 2) for x in xs)"),
        (1, 3, "sum("),
        (4, 7, "if not xs:\n    return total(xs) / len(xs)"),
        (4, 7, "if not xs:\n        return 1"),
        (2, 2, "return sum(xs) + 1"),
    ],
)
def test_a_quote_not_at_the_cited_range_is_not_verified(start, end, evidence):
    assert isinstance(check(LineRange("calc.py", start, end), evidence), Unverified)


def test_internal_whitespace_does_not_reject_the_cited_line():
    evidence = "return  sum(round(x, 2)  for x in xs)"
    result = check(LineRange("calc.py", 2, 2), evidence)
    assert result == Verified(result.finding, QuoteSource.HEAD)


@pytest.mark.parametrize(
    ("start", "end", "evidence"),
    [
        (1, 1, "return sum(round(x, 2) for x in xs)"),
        (4, 4, "return sum(round(x, 2) for x in xs)"),
        (6, 7, "if not xs:\n    return 0"),
    ],
)
def test_a_whole_line_quote_within_two_lines_is_verified_as_drifted(
    start, end, evidence
):
    result = check(LineRange("calc.py", start, end), evidence)
    assert result == Verified(result.finding, QuoteSource.HEAD_NEAR)


@pytest.mark.parametrize(
    ("start", "end", "evidence"),
    [
        (6, 6, "return sum(round(x, 2) for x in xs)"),
        (1, 1, "}"),
        (7, 7, "}"),
        (1, 1, "round(x, 2) for x"),
    ],
)
def test_a_short_fragment_or_a_far_line_is_not_treated_as_drift(start, end, evidence):
    assert isinstance(check(LineRange("calc.py", start, end), evidence), Unverified)


def test_a_quote_that_sits_outside_its_cited_lines_is_not_verified():
    """The text is line 2; the citation is the last three lines of the file."""
    result = check(LineRange("calc.py", 6, 8), "return sum(round(x, 2) for x in xs)")
    assert isinstance(result, Unverified)
    assert "not at that range" in result.reason


@pytest.mark.parametrize("end", [9, 10_000_000])
def test_a_range_that_ends_past_the_file_is_not_verified(end):
    """Line 2's text, cited from line 2 to past the file. The slice of that
    range would be the rest of the file, and the quote would match."""
    result = check(LineRange("calc.py", 2, end), "return sum(round(x, 2) for x in xs)")
    assert isinstance(result, Unverified)
    assert "past the end of the head file (8 lines)" in result.reason


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


def test_a_multi_line_quote_needs_a_span_of_its_own_length():
    """Lines 5-6, cited as lines 4-7. Both lines sit in that window."""
    evidence = "if not xs:\n    return 0"
    wide = check(LineRange("calc.py", 4, 7), evidence)
    assert isinstance(wide, Unverified)
    assert "not at that range" in wide.reason
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
