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
checked is the separator and the presence of an intro, both of which a reader
uses to navigate and neither of which carries meaning of its own.
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
    """Headings using an em-dash where the house form is an arrow.

    Strip one trailing parenthetical first: an em-dash *inside* the qualifier
    ("(skipped - no user-facing surface)") is ordinary prose, not the separator
    between an example's label and its subject.
    """
    return [h for h in _section_headings(text) if " — " in _QUALIFIER_RE.sub("", h)]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_example_headings_use_the_arrow_separator(path: Path):
    bad = _mis_separated(path.read_text(encoding="utf-8"))
    assert not bad, (
        f"{path.relative_to(ROOT)}: example headings separate label from subject with "
        "an arrow, not an em-dash. Use `## Bad → ...` / `## Clean → ...`:\n"
        + "\n".join(f"  ## {h}" for h in bad)
    )


def _intro(text: str) -> str:
    """The prose between the H1 and the first section heading."""
    body = text.split("\n## ", 1)[0]
    return "\n".join(body.splitlines()[1:]).strip()


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_examples_open_with_a_reporting_convention_line(path: Path):
    assert _intro(path.read_text(encoding="utf-8")), (
        f"{path.relative_to(ROOT)}: needs an intro line between the title and the "
        "first example, stating this lens's reporting convention — what counts as "
        "one finding, and what 'No findings' requires. Without it a reader has to "
        "infer the convention from the examples, which is what the examples are "
        "supposed to illustrate."
    )


# --- the guards must fail on drift, not merely pass on a fixed tree ----------


@pytest.mark.parametrize(
    "heading, flagged",
    [
        ("Bad — declared contracts with no enforcement point", True),
        ("Clean — a healthy project (the proportionality guard)", True),
        ("Bad → finding", False),
        ("Good → no finding (skipped — no user-facing surface)", False),
        ("Output format", False),
        ("Contents", False),
    ],
)
def test_separator_check_flags_the_separator_not_the_prose(heading: str, flagged: bool):
    assert bool(_mis_separated(f"# Examples\n\n## {heading}\n\nbody\n")) is flagged


def test_intro_check_rejects_a_file_that_starts_with_a_heading():
    assert not _intro("# Examples — a-lens\n\n## Bad → finding\n\nbody\n")
    assert _intro("# Examples — a-lens\n\nReport each issue.\n\n## Bad → finding\n")
