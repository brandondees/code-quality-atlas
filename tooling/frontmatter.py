# SPDX-License-Identifier: MIT
# tooling/frontmatter.py
"""Shared helper for reading the `---`-fenced YAML frontmatter block used at
the top of this repo's markdown files (SKILL.md, commands/*.md, ...).
Extracted after a PR #407 review found `drift.py`'s `_read_provenance` and
`tests/test_command_frontmatter.py`'s own helper had drifted into
near-verbatim copies of the same fence-parsing logic."""

from __future__ import annotations

from pathlib import Path

import yaml


def read_frontmatter(path: Path) -> tuple[str, dict]:
    """Return `(raw_frontmatter_text, parsed_yaml)` for the `---`-fenced
    block at the top of `path`. Raises `ValueError` if the file has no
    well-formed frontmatter fence.

    The parsed value is typed as `dict` because every caller treats it as a
    mapping; `yaml.safe_load` can technically return any YAML scalar, so a
    malformed frontmatter block (not a mapping at all) still needs its own
    `isinstance` check at the call site rather than relying on this
    annotation (PR #407 review, round 2).

    `utf-8-sig` drops a BOM and `\\r\\n` -> `\\n` normalizes a Windows
    checkout, so the `---\\n` fence split works regardless of line
    endings/encoding mark. The split is limited to 2 so a `---` in the body
    can't shift the parse.
    """
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    parts = text.split("---\n", 2)
    if len(parts) < 3 or parts[0].strip():
        raise ValueError(f"{path}: missing or malformed YAML frontmatter")
    return parts[1], yaml.safe_load(parts[1])
