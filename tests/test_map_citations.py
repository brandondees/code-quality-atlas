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
# is ever added and this test starts under-matching -- test_no_citations_use_
# an_unlisted_extension below fails loudly when that happens instead of
# letting this allowlist silently narrow what gets checked.
_CITABLE_EXTENSIONS = ("md", "py", "sh", "yaml", "yml", "json", "jsonc", "txt")

# A backtick-quoted `path:spec` or `path::name`, where path ends in one of
# _CITABLE_EXTENSIONS so a stray `word:digit` span isn't mistaken for one.
_CITATION_RE = re.compile(
    r"`(?P<path>[\w./-]+\.(?:" + "|".join(_CITABLE_EXTENSIONS) + r"))"
    r"(?P<sep>::?)(?P<rest>[\w.,-]+)`"
)
# Same citation shape as _CITATION_RE but with no extension restriction --
# used only to catch a citation into an extension _CITATION_RE's allowlist
# doesn't cover, which would otherwise be invisible to it (issue #424 review,
# the same "false all green" shape as #421, one layer down: the allowlist
# itself silently narrowing coverage rather than the extractor breaking).
_ANY_EXTENSION_CITATION_RE = re.compile(
    r"`(?P<path>[\w./-]+\.(?P<ext>[A-Za-z0-9]+))(?P<sep>::?)[\w.,-]+`"
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


def test_no_citations_use_an_unlisted_extension():
    """Guards _CITABLE_EXTENSIONS itself: a citation into a file type not on
    that list is invisible to _CITATION_RE (never extracted, never checked
    by test_citation_resolves below), so drift into it would pass silently.
    Fails loudly instead, naming the extension to add."""
    unlisted = []
    for md_path in _iter_map_markdown_files():
        rel_md = md_path.relative_to(ROOT)
        text = md_path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in _ANY_EXTENSION_CITATION_RE.finditer(line):
                if m.group("ext") not in _CITABLE_EXTENSIONS:
                    unlisted.append(f"{rel_md}:{lineno}: `{m.group(0)}`")
    assert not unlisted, (
        "citation(s) use a file extension not in _CITABLE_EXTENSIONS, so "
        "_CITATION_RE never extracts them and test_citation_resolves never "
        "checks them -- add the extension to _CITABLE_EXTENSIONS:\n"
        + "\n".join(unlisted)
    )


def _resolves(path, sep, rest):
    """True if citation (path, sep, rest) resolves against the tree rooted
    at ROOT. Shared by test_citation_resolves (real citations, should all
    pass) and test_citation_does_not_resolve (synthetic bad input, should
    all fail) so both are checked against the same logic."""
    target = ROOT / path
    if not target.exists():
        return False

    if sep == "::":
        # Named-anchor form: `rest` must appear literally somewhere in the
        # target file. Immune to line drift by construction.
        return rest in target.read_text(encoding="utf-8")

    # Line form: every comma-separated segment must be a sane N or N-M
    # within the target's current line count.
    line_count = len(target.read_text(encoding="utf-8").splitlines())
    for segment in rest.split(","):
        m = _LINE_SEGMENT_RE.match(segment)
        if not m:
            return False
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if not (start >= 1 and end >= start):
            return False
        if end > line_count:
            return False
    return True


@pytest.mark.parametrize("path,sep,rest", _CASES)
def test_citation_resolves(path, sep, rest):
    assert _resolves(path, sep, rest), (
        f"{path}{sep}{rest} has drifted or no longer resolves -- see "
        "docs/map/CONTEXT.md's 'Citation syntax' section for what makes "
        "each form resolve, and consider a `path::name` anchor (immune to "
        "line drift) over a raw line number if the target has a namable one."
    )


@pytest.mark.parametrize(
    "path,sep,rest",
    [
        pytest.param("docs/map/CONTEXT.md", ":", "999999", id="line-past-eof"),
        pytest.param("docs/map/CONTEXT.md", ":", "abc", id="malformed-segment"),
        pytest.param(
            "docs/map/CONTEXT.md",
            "::",
            "this-anchor-definitely-does-not-exist-anywhere",
            id="anchor-not-found",
        ),
        pytest.param(
            "docs/map/this-file-does-not-exist.md",
            ":",
            "1",
            id="nonexistent-file",
        ),
    ],
)
def test_citation_does_not_resolve(path, sep, rest):
    """Synthetic bad-input cases for _resolves, so the checker's own failure
    paths are asserted by CI rather than verified once by hand before
    merge (a regex/logic regression that makes resolution vacuously true
    would otherwise go undetected)."""
    assert not _resolves(path, sep, rest)
