# SPDX-License-Identifier: MIT
# tests/test_ruff_rule_count_comment_sync.py
"""`pyproject.toml`'s `[tool.ruff.lint]` comment cites exact numeric facts
about the pinned ruff (the default-enabled rule count, the count once this
repo's own `extend-select` is applied, and how many `# noqa: TRY004`
suppressions that implicit surface forces in `tooling/run_evals.py`) and
tells a future editor to re-derive them by hand after a version bump rather
than trusting the text. Nothing mechanically enforced that instruction, and
it was wrong at least twice even when someone deliberately refreshed it:
PR #581 fixed a stale pair of counts, PR #582 then had to fix an off-by-one
in that very refresh, and a single routine `ruff` dependency bump (#578,
#584) has twice fanned out into 2-3 follow-up comment-only PRs (#581/#582,
#585). See issue #588 for the full incident history.

This closes that gap the same way test_precommit_ci_version_sync.py closes
the analogous markdownlint-cli2 drift: by deriving the real numbers (via
`ruff check --isolated/--show-settings .`, the exact commands the comment
itself names) and failing loudly, with the re-derivation command in the
message, whenever the comment's claim stops matching them -- rather than
regenerating the comment outright (unlike test_doc_counts.py's #372
mechanism), since this is prose explaining a tradeoff, not a rendered
template occurrence.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"
RUN_EVALS = ROOT / "tooling" / "run_evals.py"

_PINNED_VERSION_RE = re.compile(r"Verified against the exact pinned ruff==([\d.]+)")
_DEFAULT_COUNT_RE = re.compile(r"already enables (\d+) rules")
_WITH_EXTEND_SELECT_COUNT_RE = re.compile(
    r"\((\d+) once this repo's own `extend-select` below is applied"
)
_TRY004_COUNT_WORD_RE = re.compile(
    r"the (\w+) `# noqa: TRY004` suppressions in\s*\n#\s*tooling/run_evals\.py"
)
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _comment_text() -> str:
    """The `[tool.ruff.lint]` section's leading comment block, i.e. everything
    between that table header and the `extend-select = [...]` line it
    introduces."""
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r"\[tool\.ruff\.lint\]\n(.*?)\nextend-select = ", text, re.DOTALL)
    assert match, (
        "couldn't find a '[tool.ruff.lint]' section followed by "
        "'extend-select = ' in pyproject.toml -- has the section been "
        "restructured? Update this test's extraction either way."
    )
    return match.group(1)


def _pinned_ruff_version() -> str:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    match = re.search(r"^ruff==([\d.]+)", text, re.MULTILINE)
    assert match, f"no 'ruff==X.Y.Z' pin found in {REQUIREMENTS}"
    return match.group(1)


def _installed_ruff_version() -> str:
    assert shutil.which("ruff"), (
        "no 'ruff' binary on PATH -- install the pinned dev dependencies "
        "first (`pip install -r requirements.txt`)."
    )
    proc = subprocess.run(
        ["ruff", "--version"], capture_output=True, text=True, check=True
    )
    match = re.search(r"ruff (\d+\.\d+\.\d+)", proc.stdout)
    assert match, f"couldn't parse a version out of 'ruff --version': {proc.stdout!r}"
    return match.group(1)


def _count_enabled_rules(show_settings_text: str) -> int:
    lines = show_settings_text.splitlines()
    try:
        start = next(
            i
            for i, line in enumerate(lines)
            if line.strip() == "linter.rules.enabled = ["
        )
    except StopIteration:
        raise AssertionError(
            "'ruff check --show-settings .' output has no "
            "'linter.rules.enabled = [' block -- has ruff's --show-settings "
            "format changed? Update this test's parsing either way."
        ) from None
    for count, line in enumerate(lines[start + 1 :]):
        if line.strip() == "]":
            return count
    raise AssertionError(
        "'linter.rules.enabled = [' block in --show-settings output never "
        "closed with a ']' line -- update this test's parsing."
    )


def _enabled_rule_count(*extra_args: str) -> int:
    proc = subprocess.run(
        ["ruff", "check", *extra_args, "--show-settings", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return _count_enabled_rules(proc.stdout)


def test_pyproject_comment_cites_the_installed_ruff_version():
    """Running the two counts below against a different ruff than the comment
    claims would make a real drift indistinguishable from a version
    mismatch -- so the version citation itself must stay current too."""
    match = _PINNED_VERSION_RE.search(_comment_text())
    assert match, (
        'no "Verified against the exact pinned ruff==X.Y.Z" sentence found '
        "in the [tool.ruff.lint] comment -- has its wording changed? Update "
        "this test's regex either way."
    )
    cited, installed = match.group(1), _installed_ruff_version()
    pinned = _pinned_ruff_version()
    assert installed == pinned, (
        f"the ruff on PATH is {installed} but requirements.txt pins "
        f"{pinned} -- install the pinned version first "
        "(`pip install -r requirements.txt`); this test's rule-count "
        "comparisons are only meaningful against the pinned ruff."
    )
    assert cited == pinned, (
        f"pyproject.toml's [tool.ruff.lint] comment says its counts were "
        f"verified against ruff=={cited}, but requirements.txt now pins "
        f"ruff=={pinned} -- the pin moved (#578/#584) without refreshing "
        "the comment (the #581/#582/#585 pattern issue #588 tracks). "
        "Re-run `ruff check --isolated --show-settings .` and "
        "`ruff check --show-settings .`, update the version and both "
        "counts below, and commit."
    )


def test_default_enabled_rule_count_matches_comment():
    match = _DEFAULT_COUNT_RE.search(_comment_text())
    assert match, (
        "no 'already enables N rules' sentence found in the "
        "[tool.ruff.lint] comment -- has its wording changed? Update this "
        "test's regex either way."
    )
    claimed = int(match.group(1))
    actual = _enabled_rule_count("--isolated")
    assert claimed == actual, (
        f"pyproject.toml's [tool.ruff.lint] comment claims ruff's built-in "
        f"default enables {claimed} rules, but "
        "`ruff check --isolated --show-settings .` currently reports "
        f"{actual} -- count the `linter.rules.enabled = [...]` block's "
        "actual entries (not by eye) and update the comment, per its own "
        "instruction."
    )


def test_extend_select_enabled_rule_count_matches_comment():
    match = _WITH_EXTEND_SELECT_COUNT_RE.search(_comment_text())
    assert match, (
        "no '(N once this repo's own `extend-select` below is applied' "
        "clause found in the [tool.ruff.lint] comment -- has its wording "
        "changed? Update this test's regex either way."
    )
    claimed = int(match.group(1))
    actual = _enabled_rule_count()
    assert claimed == actual, (
        f"pyproject.toml's [tool.ruff.lint] comment claims {claimed} rules "
        "are enabled once this repo's own `extend-select` is applied, but "
        "`ruff check --show-settings .` currently reports "
        f"{actual} -- count the `linter.rules.enabled = [...]` block's "
        "actual entries (not by eye) and update the comment, per its own "
        "instruction."
    )


def test_try004_suppression_count_in_run_evals_matches_comment():
    match = _TRY004_COUNT_WORD_RE.search(_comment_text())
    assert match, (
        "no 'the <N> `# noqa: TRY004` suppressions in tooling/run_evals.py' "
        "sentence found in the [tool.ruff.lint] comment -- has its wording "
        "changed? Update this test's regex either way."
    )
    claimed_word = match.group(1)
    assert claimed_word in _NUMBER_WORDS, (
        f"couldn't parse the spelled-out count {claimed_word!r} in the "
        "[tool.ruff.lint] comment's TRY004 sentence -- extend _NUMBER_WORDS "
        "or reword the comment to use a number this test recognizes."
    )
    claimed = _NUMBER_WORDS[claimed_word]
    actual = len(
        re.findall(r"#\s*noqa:\s*TRY004", RUN_EVALS.read_text(encoding="utf-8"))
    )
    assert claimed == actual, (
        f"pyproject.toml's [tool.ruff.lint] comment says tooling/run_evals.py "
        f"has {claimed_word!r} (={claimed}) `# noqa: TRY004` suppressions, "
        f"but it currently has {actual} -- update the comment's spelled-out "
        "count to match."
    )
