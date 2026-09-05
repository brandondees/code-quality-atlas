# SPDX-License-Identifier: MIT
# tests/test_examples_conventions.py
"""Assert every skills/*/examples.md follows the two house conventions.

These files are hand-authored (the generator inlines them, it does not write
them), so `drift` has nothing to say about their shape. Both conventions below
were rediscovered by a *reviewer* on PR #208 — and checking the pattern rather
than the two files under review showed the same deviation in a third file merged
hours earlier. That is the signature of a convention that lives only in the
existing files: a session authors several at once and they drift together.

The lesson worth mechanizing is not "fix those files". It is that a convention
nobody checks is a convention that drifts once per authoring session, and a
reviewer finding it is the slowest possible feedback. Hence these guards.

Deliberately narrow. The *label* vocabulary is per-lens freedom — `Bad`, `Good`,
`Clean`, `Delegating`, `Refusing` all read fine and say different things. What is
checked is the separator and the *presence* of an intro, both of which a reader
uses to navigate and neither of which carries meaning of its own. What the intro
says is explicitly out of scope here — that is a semantic question, and asserting
a keyword proxy for it would be the failure mode a reviewer already caught once
in this same file (a count threshold standing in for the invariant).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
EXAMPLES = sorted(SKILLS.glob("*/examples.md"))
# a trailing parenthetical qualifier: "... (skipped - no user-facing surface)"
_QUALIFIER_RE = re.compile(r"\s*\([^)]*\)\s*$")


def test_every_skill_is_covered():
    """A glob that silently matches nothing would make every test below pass.

    Assert the invariant — one `examples.md` per skill — rather than a count
    threshold that merely approximates it. A threshold passes a glob that has
    gone half-blind, and goes stale as the suite grows.
    """
    skills = {p.parent.name for p in SKILLS.glob("*/SKILL.md")}
    covered = {p.parent.name for p in EXAMPLES}
    assert skills, "found no skills/*/SKILL.md — the glob is wrong, not the suite"
    assert skills == covered, (
        "every skill needs an examples.md and every examples.md needs a skill; "
        f"missing examples: {sorted(skills - covered)}; "
        f"orphaned examples: {sorted(covered - skills)}"
    )


def _section_headings(text: str) -> list[str]:
    return [ln[3:].strip() for ln in text.splitlines() if ln.startswith("## ")]


def _mis_separated(text: str) -> list[str]:
    r"""Headings using a dash where the house form is an arrow.

    Two things this must get right, both found by review after a first version
    matched the single literal `" — "`:

    - **Every spelling of the mistake, not the one that happened.** A spaced
      hyphen, en-dash, or em-dash all read as the separator, and an em/en-dash
      needs no spaces at all to act as one (`Bad—finding`). No separate
      normalization pass for exotic spacing: Python's `\s` already matches
      U+00A0 and friends, which the regression cases below pin.
    - **Not ordinary hyphenation.** `lethal-trifecta` and `user-facing` are
      words, so a bare ASCII hyphen between word characters is left alone —
      which is why the unspaced case is restricted to em/en dashes.

    A trailing parenthetical is stripped first: a dash *inside* the qualifier
    ("(skipped — no user-facing surface)") is prose, not the separator.
    """
    return [h for h in _section_headings(text) if _dash_separator(h)]


# spaced hyphen / en-dash / em-dash, or an unspaced em/en-dash between words
_SEPARATOR_RE = re.compile(r"\s[-–—]\s|\w[–—]\w")


def _dash_separator(heading: str) -> bool:
    return bool(_SEPARATOR_RE.search(_QUALIFIER_RE.sub("", heading)))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_example_headings_use_the_arrow_separator(path: Path):
    bad = _mis_separated(path.read_text(encoding="utf-8"))
    assert not bad, (
        f"{path.relative_to(ROOT)}: example headings separate label from subject with "
        "an arrow, not a dash. Use `## Bad → ...` / `## Clean → ...`:\n"
        + "\n".join(f"  ## {h}" for h in bad)
    )


def _intro(text: str) -> str:
    """The prose between the H1 and the first section heading."""
    body = text.split("\n## ", 1)[0]
    return "\n".join(body.splitlines()[1:]).strip()


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_examples_open_with_an_intro_line(path: Path):
    assert _intro(path.read_text(encoding="utf-8")), (
        f"{path.relative_to(ROOT)}: needs an intro line between the title and the "
        "first example. This guard checks only that one is there; what it must say "
        "— what counts as one finding, and what 'No findings' requires — is the "
        "author's job and standing authoring rule 2's (docs/research/README.md), "
        "because no test can tell whether a preamble agrees with the examples "
        "beneath it."
    )


# A file over this many lines gets a `## Contents` ToC, right after the intro
# and before the first example heading. Mirrors `_TOC_LINE_THRESHOLD` in
# tooling/generate_collapsed.py, which mechanizes the same convention for
# *generated* collapsed bundles — but examples.md is hand-authored (the
# generator inlines it, never writes it), so that generator threshold has
# nothing to say about these files. The convention here was set by precedent,
# not generation: PR #165 added the ToC to the first files that crossed 100
# lines, and the comment beside `_TOC_LINE_THRESHOLD` records why 100 was
# chosen. This guard is the missing third check for that already-adopted
# convention, alongside the arrow-separator and intro-line guards above.
_EXAMPLES_TOC_LINE_THRESHOLD = 100


def _github_anchor(heading: str) -> str:
    """Approximate GitHub's heading-anchor slug algorithm: lowercase, drop
    everything except word characters, whitespace, and hyphens, then turn
    whitespace into hyphens."""
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s", "-", slug)


def _expected_toc_entries(headings: list[str]) -> list[str]:
    """The `- [heading](#anchor)` lines a correct `## Contents` ToC contains,
    in order, with GitHub's duplicate-anchor suffixing (`-1`, `-2`, ...)."""
    seen: dict[str, int] = {}
    entries = []
    for h in headings:
        slug = _github_anchor(h)
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        anchor = slug if n == 0 else f"{slug}-{n}"
        entries.append(f"- [{h}](#{anchor})")
    return entries


def _actual_toc_entries(text: str) -> list[str]:
    """The `- [...](#...)` bullet lines inside the file's `## Contents`
    section, in order (empty if there's no such section)."""
    lines = text.splitlines()
    if "## Contents" not in lines:
        return []
    entries = []
    for line in lines[lines.index("## Contents") + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("- ["):
            entries.append(line)
    return entries


def _has_valid_contents_toc(text: str) -> bool:
    """True iff the first `## ` heading is `Contents` and its bullet list is
    exactly one correctly-anchored entry per subsequent `## ` heading, in
    order — not just that a `## Contents` heading exists somewhere. A ToC
    missing an entry, out of order, or pointing at the wrong anchor reads
    fine to a skim but silently misnavigates a reader (CodeRabbit, PR #425)."""
    headings = _section_headings(text)
    if not headings or headings[0] != "Contents":
        return False
    return _actual_toc_entries(text) == _expected_toc_entries(headings[1:])


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_long_examples_have_a_contents_toc(path: Path):
    text = path.read_text(encoding="utf-8")
    line_count = len(text.splitlines())
    if line_count <= _EXAMPLES_TOC_LINE_THRESHOLD:
        pytest.skip(
            f"{line_count} lines, at or under the {_EXAMPLES_TOC_LINE_THRESHOLD}-line threshold"
        )
    assert _has_valid_contents_toc(text), (
        f"{path.relative_to(ROOT)}: {line_count} lines (over "
        f"{_EXAMPLES_TOC_LINE_THRESHOLD}) needs a correct `## Contents` ToC — "
        "one bullet per `## ` heading, in order, each linking that heading's "
        "GitHub anchor — placed right after the intro and before the first "
        "example heading. See skills/auditing-deployment-and-trust-"
        "boundaries/examples.md for the reference format."
    )


# --- the guards must fail on drift, not merely pass on a fixed tree ----------


@pytest.mark.parametrize(
    "heading, flagged",
    [
        ("Bad — declared contracts with no enforcement point", True),
        ("Clean — a healthy project (the proportionality guard)", True),
        # every other spelling of the same mistake (CodeRabbit, #209)
        ("Bad - finding", True),
        ("Bad – finding", True),
        ("Bad—finding", True),
        ("Bad–finding", True),
        ("Bad\u00a0—\u00a0finding", True),  # no-break spaces around the dash
        ("Bad\u202f—\u202ffinding", True),  # narrow no-break spaces
        ("Bad → finding", False),
        ("Good → no finding (skipped — no user-facing surface)", False),
        # hyphenation is not a separator
        ("Bad → an agent design with an unwritten lethal-trifecta boundary", False),
        ("Good → no finding (skipped — no user-facing surface, CLI-only)", False),
        ("Output format", False),
        ("Contents", False),
    ],
)
def test_separator_check_flags_the_separator_not_the_prose(heading: str, flagged: bool):
    assert bool(_mis_separated(f"# Examples\n\n## {heading}\n\nbody\n")) is flagged


def test_intro_check_rejects_a_file_that_starts_with_a_heading():
    assert not _intro("# Examples — a-lens\n\n## Bad → finding\n\nbody\n")
    assert _intro("# Examples — a-lens\n\nReport each issue.\n\n## Bad → finding\n")


def test_toc_check_fails_without_a_toc_and_passes_with_one():
    """The guard must fail on a long file missing its ToC, catch a ToC with a
    missing entry, wrong order, or a wrong anchor, and pass a correct one —
    exercising `_has_valid_contents_toc` itself (the guard's actual check),
    not `_section_headings` directly, so a weakened guard can't silently
    keep passing this self-test (CodeRabbit, PR #425)."""
    filler = "\n".join(f"line {i}" for i in range(_EXAMPLES_TOC_LINE_THRESHOLD + 5))

    no_toc = f"# Examples — a-lens\n\nReport each issue.\n\n{filler}\n\n## Bad → finding\n\nbody\n\n## Good → no finding\n\nbody\n"
    assert len(no_toc.splitlines()) > _EXAMPLES_TOC_LINE_THRESHOLD
    assert not _has_valid_contents_toc(no_toc)

    correct_toc = (
        f"# Examples — a-lens\n\nReport each issue.\n\n{filler}\n\n"
        "## Contents\n\n- [Bad → finding](#bad--finding)\n"
        "- [Good → no finding](#good--no-finding)\n\n"
        "## Bad → finding\n\nbody\n\n## Good → no finding\n\nbody\n"
    )
    assert len(correct_toc.splitlines()) > _EXAMPLES_TOC_LINE_THRESHOLD
    assert _has_valid_contents_toc(correct_toc)

    missing_entry_toc = correct_toc.replace(
        "- [Good → no finding](#good--no-finding)\n", ""
    )
    assert not _has_valid_contents_toc(missing_entry_toc)

    wrong_order_toc = correct_toc.replace(
        "- [Bad → finding](#bad--finding)\n- [Good → no finding](#good--no-finding)\n",
        "- [Good → no finding](#good--no-finding)\n- [Bad → finding](#bad--finding)\n",
    )
    assert not _has_valid_contents_toc(wrong_order_toc)

    bad_anchor_toc = correct_toc.replace("#bad--finding", "#bad-finding")
    assert not _has_valid_contents_toc(bad_anchor_toc)

    short = "# Examples — a-lens\n\nReport each issue.\n\n## Bad → finding\n\nbody\n"
    assert len(short.splitlines()) <= _EXAMPLES_TOC_LINE_THRESHOLD
