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
"""

import re
from pathlib import Path

from tooling.frontmatter import read_frontmatter

_ROOT = Path(__file__).resolve().parent.parent
_COMMANDS_DIR = _ROOT / "commands"
_COMMENT_RISK = re.compile(r"\s#")
_KEY_RE = re.compile(r"^(\s*)([\w-]+):\s*(.*)$")


def _frontmatter(command_md: Path) -> tuple[str, dict]:
    return read_frontmatter(command_md)


def test_command_frontmatter_parses_and_has_description():
    command_files = sorted(_COMMANDS_DIR.glob("*.md"))
    assert command_files, f"no command files found under {_COMMANDS_DIR}"
    for command_md in command_files:
        _, front = _frontmatter(command_md)
        assert isinstance(front, dict), f"{command_md}: frontmatter is not a mapping"
        assert front.get("description"), f"{command_md}: description must be non-empty"


def test_command_description_is_a_block_scalar():
    """A block scalar (`>-`/`>`/`|`) reads `#` literally; a plain scalar does
    not, and a future edit adding a bare `#123` cross-reference to a plain
    description would truncate silently. Require the safe form everywhere,
    matching every other command file's existing convention."""
    for command_md in sorted(_COMMANDS_DIR.glob("*.md")):
        raw, _ = _frontmatter(command_md)
        for line in raw.splitlines():
            m = re.match(r"^description:\s*(.*)$", line)
            if m:
                value = m.group(1).strip()
                assert value[:1] in (">", "|", ""), (
                    f"{command_md}: description is a plain scalar ({value[:20]!r}...) "
                    "— use a block scalar ('>-') so a bare ' #' in the text can't "
                    "silently truncate the value"
                )
                break
        else:
            raise AssertionError(f"{command_md}: no description: line found")


def test_command_frontmatter_has_no_comment_truncation_risk():
    """No plain-scalar frontmatter value anywhere in `commands/*.md` may
    contain a bare ' #', on its first line or on a wrapped continuation line
    — YAML would read either as a comment and silently drop the rest.
    Tracks `prose_indent` across continuation lines the same way
    `tooling/manifest.py`'s `_check_comment_truncation` does, generalized to
    every key rather than a fixed allowlist: unlike `manifest.yaml`,
    `commands/*.md` frontmatter has no fixed schema, so any key could turn
    into a wrapped plain scalar (PR #407 review, round 1, nit)."""
    for command_md in sorted(_COMMANDS_DIR.glob("*.md")):
        raw, _ = _frontmatter(command_md)
        prose_indent: int | None = None
        for n, line in enumerate(raw.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                prose_indent = None
                continue
            m = _KEY_RE.match(line)
            if m:
                indent, value = len(m.group(1)), m.group(3)
                if value[:1] in ('"', "'", ">", "|", ""):
                    prose_indent = None
                else:
                    assert not _COMMENT_RISK.search(" " + value), (
                        f"{command_md}:{n}: unquoted value contains ' #' — YAML "
                        "reads it as a comment and silently truncates the value"
                    )
                    prose_indent = indent
                continue
            # a continuation line of the current plain-scalar value
            if (
                prose_indent is not None
                and len(line) - len(line.lstrip()) > prose_indent
            ):
                assert not _COMMENT_RISK.search(line), (
                    f"{command_md}:{n}: unquoted value continuation contains ' #' "
                    "— YAML reads it as a comment and silently truncates the value"
                )
            else:
                prose_indent = None
