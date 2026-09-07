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


# --- Bare (uncited) Surfaces-table path mentions (issue #474) -------------
#
# _CITATION_RE above only extracts a path when it's followed by `:N` or
# `::name` inside the same backtick span -- a bare `` `tooling/generate.py` ``
# mention with no separator at all is invisible to it. That's exactly the
# shape that went stale in practice: commit c7a91c0 deleted tooling/generate.py
# and split it into five successor modules, but a plain-prose Surfaces-table
# citation of the old name in three cards survived that PR and needed two
# separate follow-up commits (98ae8d7, 7b3464a) within the same PR #459 to
# catch by hand.
#
# Scoped to each card's own "## Surfaces" table specifically (not any bare
# backtick-quoted path anywhere in the file): a Surfaces row is a live,
# current-state assertion ("this module exists and does X"), whereas a bare
# path mentioned elsewhere in a card is very often something else entirely --
# a dated "Verified" trailer deliberately naming a since-deleted file for
# historical context ("`tooling/generate.py` (a re-export facade...) was
# deleted"), or a relative cross-reference to a sibling doc/pattern resolved
# against the citing card's own directory rather than the repo root
# (`evals/eval.json`, `routing.md`). Widening past Surfaces tables was tried
# and rejected: it produced only false positives from exactly those two
# legitimate patterns, with zero additional real drift caught.
_CODE_EXTENSIONS = ("py", "sh", "yaml", "yml", "json", "jsonc")
# The whole backtick span must be just a path (no `:`/`::` suffix -- those are
# already covered by _CITATION_RE above) containing at least one "/" (a bare
# filename like `routing.md` is a same-directory doc cross-reference, not a
# repo-root-relative module path) and ending in a code extension (deliberately
# excludes .md/.txt, the extensions the same-directory cross-reference pattern
# above almost always uses).
_BARE_SURFACES_PATH_RE = re.compile(
    r"`(?P<path>[\w.-]+(?:/[\w.-]+)+\.(?:" + "|".join(_CODE_EXTENSIONS) + r"))`"
)


_SURFACES_HEADING_RE = re.compile(r"^##\s+surfaces\s*$", re.IGNORECASE)


def _iter_surfaces_table_rows(md_path):
    """Yield (lineno, line) for every markdown table row under md_path's own
    top-level '## Surfaces' heading, if it has one. Matches the exact `##`
    level (not `#`/`###`/deeper) so a differently-scoped or nested heading
    that happens to say "Surfaces" can't widen or narrow what this checks."""
    in_surfaces = False
    for lineno, line in enumerate(
        md_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = line.strip()
        if stripped.startswith("#"):
            in_surfaces = bool(_SURFACES_HEADING_RE.match(stripped))
            continue
        if in_surfaces and stripped.startswith("|"):
            yield lineno, line


def _surfaces_bare_path_cases():
    cases = []
    for md_path in _iter_map_markdown_files():
        rel_md = md_path.relative_to(ROOT)
        for lineno, line in _iter_surfaces_table_rows(md_path):
            for m in _BARE_SURFACES_PATH_RE.finditer(line):
                path = m.group("path")
                cases.append(pytest.param(path, id=f"{rel_md}:{lineno}::{path}"))
    return cases


_SURFACES_BARE_PATH_CASES = _surfaces_bare_path_cases()


def test_at_least_one_surfaces_bare_path_found():
    """Regression guard on the extractor itself, mirroring
    test_at_least_one_citation_found above: if this drops to 0, the
    heading/table-row matching in _iter_surfaces_table_rows broke (or every
    Surfaces table stopped bare-citing a code module), and every case below
    would be a false "all green"."""
    assert len(_SURFACES_BARE_PATH_CASES) > 5, (
        f"only found {len(_SURFACES_BARE_PATH_CASES)} bare Surfaces-table path "
        "mentions -- expected more than a handful; the heading or table-row "
        "matching in this test may have broken"
    )


def test_no_surfaces_bare_paths_use_an_unlisted_code_extension():
    """Mirrors test_no_citations_use_an_unlisted_extension above, scoped to
    Surfaces-table rows: a bare path citing a code extension not in
    _CODE_EXTENSIONS is invisible to _BARE_SURFACES_PATH_RE (never extracted,
    never checked by test_surfaces_bare_path_exists), so drift into it would
    pass silently -- the same "false all green" risk this file already
    guards against for the sibling formal-citation extractor."""
    any_ext_re = re.compile(r"`(?P<path>[\w.-]+(?:/[\w.-]+)+\.(?P<ext>[A-Za-z0-9]+))`")
    unlisted = []
    for md_path in _iter_map_markdown_files():
        rel_md = md_path.relative_to(ROOT)
        for lineno, line in _iter_surfaces_table_rows(md_path):
            for m in any_ext_re.finditer(line):
                ext = m.group("ext")
                # md/txt are excluded deliberately, not a gap: see
                # _BARE_SURFACES_PATH_RE's own comment on why those two
                # extensions (the same-directory cross-reference pattern)
                # are out of scope for this check entirely.
                if ext not in _CODE_EXTENSIONS and ext not in ("md", "txt"):
                    unlisted.append(f"{rel_md}:{lineno}: `{m.group(0)}`")
    assert not unlisted, (
        "Surfaces-table bare path(s) use a code extension not in "
        "_CODE_EXTENSIONS, so _BARE_SURFACES_PATH_RE never extracts them and "
        "test_surfaces_bare_path_exists never checks them -- add the "
        "extension to _CODE_EXTENSIONS:\n" + "\n".join(unlisted)
    )


def test_iter_surfaces_table_rows_ignores_a_non_level_two_heading(tmp_path):
    """A '### Surfaces' (or '# Surfaces') heading must NOT be treated as the
    top-level Surfaces table -- only an exact '## Surfaces' does. Without
    this, a nested or differently-scoped heading that happens to say
    "Surfaces" could pull an unrelated table's bare paths into this check,
    or a real Surfaces table nested under the wrong level could be missed."""
    md_path = tmp_path / "synthetic.md"
    md_path.write_text(
        "# Some Card\n\n### Surfaces\n\n| Surface | Role |\n|---|---|\n"
        "| `tooling/this-module-does-not-exist.py` | nested, not top-level |\n",
        encoding="utf-8",
    )
    assert list(_iter_surfaces_table_rows(md_path)) == []


def _surfaces_bare_path_exists(path):
    return (ROOT / path).exists()


@pytest.mark.parametrize("path", _SURFACES_BARE_PATH_CASES)
def test_surfaces_bare_path_exists(path):
    """A Surfaces-table row citing `path` with no `:N`/`::name` suffix is
    still asserting that module exists right now. Catches the shotgun-surgery
    drift class formal citations miss entirely -- see issue #474."""
    assert _surfaces_bare_path_exists(path), (
        f"`{path}` is cited (with no line/anchor suffix) in a Surfaces table "
        "but no longer exists on disk -- likely renamed or deleted; update "
        "the row to name the actual successor module(s)"
    )


def test_surfaces_bare_path_does_not_exist_synthetic():
    """Synthetic bad-input case for _surfaces_bare_path_exists, mirroring
    test_citation_does_not_resolve below: asserts the checker's own failure
    path is exercised by CI rather than verified once by hand (a logic
    regression that makes this vacuously true would otherwise go
    undetected)."""
    assert not _surfaces_bare_path_exists("tooling/this-module-does-not-exist.py")


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
