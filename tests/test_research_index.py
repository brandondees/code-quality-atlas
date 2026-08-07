# SPDX-License-Identifier: MIT
# tests/test_research_index.py
"""Assert docs/research/README.md's Index lists each cluster file's real categories.

The Index is how a research agent finds where a category lives. It was written
once and then not updated across ten promotions (#28-#41), so four of six rows
were wrong and 14 of 41 categories pointed at the wrong file or nowhere. Nothing
caught it, because the Index is prose and the categories are headings.

Compare *sets*, not the rendered string: the Index compresses runs into ranges
("#5-#8, #35") and which runs are worth compressing is a formatting choice, not
a fact. Only membership is the fact.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "docs" / "research"

# "## #40 Data-engineering & data-contract quality" -> 40
_HEADING_RE = re.compile(r"^## #(\d+)\b", re.MULTILINE)
# An Index row: | [`cluster-5-verification.md`](cluster-5-verification.md) | V - ... | #17-#20, ... |
# Capture the link *destination* as well as the label. Reading only the label
# would let `[`cluster-5-verification.md`](cluster-4-runtime.md)` satisfy every
# assertion below while sending a reader to the wrong file — the exact failure
# this module exists to prevent.
_ROW_RE = re.compile(
    r"^\|\s*\[`(?P<label>cluster-[^`]+\.md)`\]\((?P<href>[^)]+)\)[^|]*\|[^|]*\|(?P<cats>[^|]*)\|",
    re.MULTILINE,
)
# a token in the Categories cell: "#17-#20" (en-dash or hyphen) or "#26"
_SPAN_RE = re.compile(r"#(\d+)\s*[-–—]\s*#?(\d+)|#(\d+)")


def _rows() -> list[re.Match]:
    return list(_ROW_RE.finditer((RESEARCH / "README.md").read_text(encoding="utf-8")))


def _declared() -> dict[str, set[int]]:
    """Category ids the Index claims for each cluster file, keyed by link label."""
    out: dict[str, set[int]] = {}
    for m in _rows():
        ids: set[int] = set()
        for lo, hi, single in _SPAN_RE.findall(m.group("cats")):
            if single:
                ids.add(int(single))
            else:
                ids.update(range(int(lo), int(hi) + 1))
        out[m.group("label")] = ids
    return out


def test_index_links_point_at_the_file_they_name():
    """A row's link destination must be the file its label names."""
    mismatched = [
        f"label `{m.group('label')}` links to `{m.group('href')}`"
        for m in _rows()
        if Path(m.group("href")).name != m.group("label")
    ]
    assert not mismatched, (
        "docs/research/README.md's Index names one file and links to another:\n"
        + "\n".join(mismatched)
    )


def _actual() -> dict[str, set[int]]:
    """Category ids each cluster file actually defines."""
    return {
        p.name: {int(n) for n in _HEADING_RE.findall(p.read_text(encoding="utf-8"))}
        for p in sorted(RESEARCH.glob("cluster-*.md"))
    }


def test_index_lists_every_cluster_file():
    assert set(_declared()) == set(_actual()), (
        "docs/research/README.md's Index and docs/research/cluster-*.md disagree on "
        "which cluster files exist"
    )


def test_index_categories_match_headings():
    declared, actual = _declared(), _actual()
    problems = []
    for fname, real in sorted(actual.items()):
        claimed = declared.get(fname, set())
        if missing := sorted(real - claimed):
            problems.append(f"{fname}: defines {missing} but the Index omits them")
        if phantom := sorted(claimed - real):
            problems.append(f"{fname}: Index claims {phantom} but the file has no such section")
    assert not problems, (
        "docs/research/README.md's Index is stale — update it when promoting a category:\n"
        + "\n".join(problems)
    )


def test_no_category_is_defined_in_two_files():
    """G1 single-owner, at the file level: one category, one research section."""
    seen: dict[int, str] = {}
    dupes = []
    for fname, ids in sorted(_actual().items()):
        for cid in sorted(ids):
            if cid in seen:
                dupes.append(f"#{cid} defined in both {seen[cid]} and {fname}")
            seen[cid] = fname
    assert not dupes, "a category has more than one research section:\n" + "\n".join(dupes)
