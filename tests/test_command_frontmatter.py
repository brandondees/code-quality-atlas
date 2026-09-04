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

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_COMMANDS_DIR = _ROOT / "commands"
_COMMENT_RISK = re.compile(r"\s#")


def _frontmatter(command_md: Path) -> tuple[str, dict]:
    text = command_md.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    parts = text.split("---\n", 2)
    assert len(parts) >= 3 and not parts[0].strip(), (
        f"{command_md}: missing or malformed YAML frontmatter"
    )
    return parts[1], yaml.safe_load(parts[1])


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
    """Independent of the description-specific check above: no plain-scalar
    frontmatter line anywhere in `commands/*.md` may contain a bare ' #',
    since YAML would read it as a comment and drop the rest of the line."""
    for command_md in sorted(_COMMANDS_DIR.glob("*.md")):
        raw, _ = _frontmatter(command_md)
        for n, line in enumerate(raw.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            m = re.match(r"^([\w-]+):\s*(.*)$", line)
            if not m:
                continue
            value = m.group(2)
            if value[:1] in ('"', "'", ">", "|", ""):
                continue
            assert not _COMMENT_RISK.search(" " + value), (
                f"{command_md}:{n}: unquoted value contains ' #' — YAML reads it "
                "as a comment and silently truncates the value"
            )
