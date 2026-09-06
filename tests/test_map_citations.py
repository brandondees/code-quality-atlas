# SPDX-License-Identifier: MIT
# tests/test_map_citations.py
"""docs/map/** cards cite specific locations in files that keep growing
(skills/manifest.yaml, docs/open-questions.md, commands/atlas-review-pr.md,
...) -- every edit above a cited line silently invalidates the citation, and
nothing caught it except a manual, periodic whole-repo audit (issue #376
alone found nine citations that had drifted ~800 lines; a prior fix to
docs/map/objects/command.md had already re-drifted by the time #376 was
filed). This test parses every citation out of docs/map/**/*.md and asserts
each one still resolves, so drift fails CI instead of waiting for the next
audit (issue #424).

Citation syntax (documented for authors in docs/map/CONTEXT.md's "Citation
syntax" section -- keep both in sync if either changes):

- `path:N` or `path:N-M`, comma-separable (`path:N,M-K,...`) -- a raw line
  or range citation. Cheap to write, cheap to drift (the recurring failure
  mode above). Checked here only for bounds: does `path` exist, and does it
  have at least as many lines as the highest number cited? That does NOT
  catch content that quietly moved to a different line while staying inside
  the file -- weaker than the anchor form below by design; that gap is
  exactly why #424 prefers migrating a citation to an anchor over relying on
  this check to catch every drift.
- `path::name` -- a named-anchor citation (the `::` borrowed from pytest's
  own `path::test_name` node-id syntax, first used this way in #423). `name`
  is anything a plain-text search of `path` would find literally: a
  function/class/test name, a YAML key, a markdown heading, a skill name.
  Checked here by literal substring search -- immune to line drift as long
  as `name` itself isn't renamed.

Both forms require `path` to end in one of a fixed set of real file
extensions (every citation observed uses one) so an unrelated
backtick-quoted `word:digit` span -- a model tag like `qwen2.5-coder:7b`
(itself containing a dot, so a bare "has a dot" check isn't enough), a port
like `localhost:11434` -- doesn't parse as a citation nobody wrote."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAP_ROOT = ROOT / "docs" / "map"

# Extensions actually used by citations under docs/map/** today (verified via
# grep before writing this test). Widen if a citation into a new file type
# is ever added and this test starts under-matching.
_CITABLE_EXTENSIONS = ("md", "py", "sh", "yaml", "yml", "json", "jsonc", "txt")

# A backtick-quoted `path:spec` or `path::name`, where path ends in one of
# _CITABLE_EXTENSIONS so a stray `word:digit` span isn't mistaken for one.
_CITATION_RE = re.compile(
    r"`(?P<path>[\w./-]+\.(?:" + "|".join(_CITABLE_EXTENSIONS) + r"))"
    r"(?P<sep>::?)(?P<rest>[\w.,-]+)`"
)
# One line-form segment: N or N-M.
_LINE_SEGMENT_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


def _iter_map_markdown_files():
    return sorted(MAP_ROOT.rglob("*.md"))


def _extract_citations(md_path):
    """Yield (path, sep, rest, lineno) for every citation-shaped backtick
    span in md_path, lineno being md_path's own line (for error messages)."""
    text = md_path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in _CITATION_RE.finditer(line):
            yield m.group("path"), m.group("sep"), m.group("rest"), lineno


def _citation_cases():
    cases = []
    for md_path in _iter_map_markdown_files():
        rel_md = md_path.relative_to(ROOT)
        for path, sep, rest, lineno in _extract_citations(md_path):
            cases.append(
                pytest.param(
                    path,
                    sep,
                    rest,
                    id=f"{rel_md}:{lineno}::{path}{sep}{rest}",
                )
            )
    return cases


_CASES = _citation_cases()


def test_at_least_one_citation_found():
    """A regression guard on the extractor itself: if this drops to 0, the
    regex broke (or docs/map/ emptied out) and every case below is a false
    "all green" -- the #421-style failure mode of a gate that silently
    stops checking anything."""
    assert len(_CASES) > 20, (
        f"only found {len(_CASES)} citations under docs/map/** -- expected "
        "several dozen; the extractor regex in this test may have broken"
    )


@pytest.mark.parametrize("path,sep,rest", _CASES)
def test_citation_resolves(path, sep, rest):
    target = ROOT / path
    assert target.exists(), f"cited file does not exist: {path}"

    if sep == "::":
        # Named-anchor form: `rest` must appear literally somewhere in the
        # target file. Immune to line drift by construction.
        content = target.read_text(encoding="utf-8")
        assert rest in content, (
            f"{path}::{rest} does not resolve -- '{rest}' no longer appears "
            f"anywhere in {path}. Update the citation (or, if the anchor was "
            f"renamed, retarget it)."
        )
        return

    # Line form: every comma-separated segment must be a sane N or N-M
    # within the target's current line count.
    line_count = len(target.read_text(encoding="utf-8").splitlines())
    for segment in rest.split(","):
        m = _LINE_SEGMENT_RE.match(segment)
        assert m, f"{path}:{rest} -- '{segment}' is not a line number or range"
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        assert start >= 1 and end >= start, (
            f"{path}:{rest} -- '{segment}' is not a sane line range"
        )
        assert end <= line_count, (
            f"{path}:{segment} has drifted -- {path} now has only "
            f"{line_count} lines. Re-check what this citation should point "
            f"at and update the line number (consider a `{path}::name` "
            f"anchor instead if the target has one, per docs/map/CONTEXT.md)."
        )
