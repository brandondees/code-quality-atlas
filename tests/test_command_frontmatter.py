# SPDX-License-Identifier: MIT
# tests/test_command_frontmatter.py
"""`commands/*.md` frontmatter is hand-authored YAML, parsed by whatever reads
the slash command. A plain (unquoted, non-block) scalar value containing " #"
is read by YAML as starting a comment and silently truncates everything after
it — exactly the bug `tooling/manifest.py`'s `_check_comment_truncation` was
added for after PR #37 truncated two router notes at a bare `#16`/`#14`.
`manifest.py` only guards `skills/manifest.yaml`; nothing checked `commands/`
(#386), so `atlas-rebase-stale.md` carried a plain-scalar `description` (fixed
alongside this test) with nobody catching the class of bug that style invites.

Round 2 of this PR's own review (`code-quality-atlas:reviewing-test-quality`)
found the first two versions of the truncation-risk check below still missed
three real shapes: a `description:` whose value starts on the *next* line, a
YAML list item, and a dotted key — each demonstrated truncating for real
against `yaml.safe_load` while the guard stayed silent. The design here
replaces per-key-shape reconstruction with the simpler, complete rule that
review suggested: check every frontmatter line unless it is a block-scalar
body line (where `#` is literal) or a single-line, fully-quoted value (where
the quotes protect it) — matching YAML's actual truncation surface instead of
enumerating the shapes that can carry it.
"""

import re
from pathlib import Path

from tooling.frontmatter import read_frontmatter

_ROOT = Path(__file__).resolve().parent.parent
_COMMANDS_DIR = _ROOT / "commands"
_COMMENT_RISK = re.compile(r"\s#")
_KEY_LINE_RE = re.compile(r"^(\s*)(?:-\s+)?([\w.-]+):\s*(.*)$")
_BLOCK_SCALAR_INDICATOR = re.compile(r"^[|>][+-]?\d*$")


def _is_fully_quoted(value: str) -> bool:
    return (value.startswith('"') and value.endswith('"') and len(value) >= 2) or (
        value.startswith("'") and value.endswith("'") and len(value) >= 2
    )


def test_command_frontmatter_parses_and_has_description():
    command_files = sorted(_COMMANDS_DIR.glob("*.md"))
    assert command_files, f"no command files found under {_COMMANDS_DIR}"
    for command_md in command_files:
        _, front = read_frontmatter(command_md)
        assert isinstance(front, dict), f"{command_md}: frontmatter is not a mapping"
        assert front.get("description"), f"{command_md}: description must be non-empty"


def test_command_description_is_a_block_scalar():
    """A block scalar (`>-`/`>`/`|`) reads `#` literally; a plain scalar does
    not, and a future edit adding a bare `#123` cross-reference to a plain
    description would truncate silently. Require the safe form everywhere,
    matching every other command file's existing convention.

    An *empty* first-line value (`description:` with the scalar starting on
    the next line) is rejected, not accepted: that shape is a plain scalar
    with no indicator at all — the exact risky form this test exists to
    forbid, not a safe one (PR #407 review, round 2)."""
    for command_md in sorted(_COMMANDS_DIR.glob("*.md")):
        raw, _ = read_frontmatter(command_md)
        for line in raw.splitlines():
            m = re.match(r"^description:\s*(.*)$", line)
            if m:
                value = m.group(1).strip()
                assert value[:1] in (">", "|"), (
                    f"{command_md}: description is a plain scalar ({value[:20]!r}...) "
                    "— use a block scalar ('>-') so a bare ' #' in the text can't "
                    "silently truncate the value"
                )
                break
        else:
            raise AssertionError(f"{command_md}: no description: line found")


def test_command_frontmatter_has_no_comment_truncation_risk():
    """No line in `commands/*.md` frontmatter may contain a bare ' #' unless
    it is inside a block-scalar body (where '#' is literal text, not a YAML
    comment) or is a single-line value fully wrapped in quotes (where the
    quotes protect it) — those are the only two shapes YAML itself treats as
    safe. Every other line — a key's plain-scalar value, a wrapped
    continuation line, a list item, a dotted key — is checked verbatim,
    rather than re-deriving which specific shape it is: round 2 of this PR's
    own review demonstrated three shapes (next-line scalar, list item, dotted
    key) that a per-shape reconstruction missed while YAML still truncated
    them for real."""
    for command_md in sorted(_COMMANDS_DIR.glob("*.md")):
        raw, _ = read_frontmatter(command_md)
        block_scalar_indent: int | None = None
        for n, line in enumerate(raw.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if block_scalar_indent is not None:
                if indent > block_scalar_indent:
                    continue  # block-scalar body line — '#' here is literal
                block_scalar_indent = None  # dedented past the block scalar
            m = _KEY_LINE_RE.match(line)
            if m:
                key_indent, value = len(m.group(1)), m.group(3).strip()
                if _BLOCK_SCALAR_INDICATOR.match(value):
                    block_scalar_indent = key_indent
                    continue
                if _is_fully_quoted(value):
                    continue
            assert not _COMMENT_RISK.search(line), (
                f"{command_md}:{n}: unquoted content contains ' #' — YAML reads "
                "it as a comment and silently truncates the value"
            )
