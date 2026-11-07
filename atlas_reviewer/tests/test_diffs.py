# SPDX-License-Identifier: MIT
from atlas_reviewer.diffs import diff_coverage, diff_paths


def file_diff(path: str, body: str = "x" * 20) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n+{body}\n"


DIFF = file_diff("a.py") + file_diff("b/c.py") + file_diff("d.md")


def test_paths_are_the_new_side_in_order_including_renames():
    renamed = "diff --git a/old name.py b/new name.py\nsimilarity index 100%\n"
    assert diff_paths(DIFF + renamed) == ("a.py", "b/c.py", "d.md", "new name.py")


def test_everything_fits_under_the_cap():
    cov = diff_coverage(DIFF, len(DIFF))
    assert (cov.seen, cov.partial, cov.unseen) == (("a.py", "b/c.py", "d.md"), None, ())


def test_cap_through_the_middle_of_a_file_marks_it_partial_and_the_rest_unseen():
    first = len(file_diff("a.py"))
    cov = diff_coverage(DIFF, first + 10)
    assert cov.seen == ("a.py",)
    assert cov.partial == "b/c.py"
    assert cov.unseen == ("d.md",)
    assert cov.total_files == 3


def test_cap_exactly_between_files_has_no_partial_file():
    first = len(file_diff("a.py"))
    cov = diff_coverage(DIFF, first)
    assert (cov.seen, cov.partial, cov.unseen) == (
        ("a.py",),
        None,
        ("b/c.py", "d.md"),
    )


def test_cap_inside_the_first_file_sees_nothing_in_full():
    cov = diff_coverage(DIFF, 5)
    assert (cov.seen, cov.partial, cov.unseen) == ((), "a.py", ("b/c.py", "d.md"))


def test_a_diff_without_file_headers_has_no_files():
    cov = diff_coverage("not a diff", 3)
    assert cov.total_files == 0
