# SPDX-License-Identifier: MIT
"""Possible committed secrets in the PR diff, by file and line (D33). Pure.

The diff is sent to the model unredacted: what it holds is already in the
repository, so a secret in it needs flagging and rotating, not hiding.
Each file section is scanned on its own with `redact.detect_secrets`, so a
private-key BEGIN in one file never pairs with an END in another. Nothing
is removed from the diff, and no finding carries the matched value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from atlas_reviewer.diffs import split_files
from atlas_reviewer.redact import detect_secrets

_HUNK = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class CommittedSecret:
    """`line` is the file's line number: the new side for an added or
    context line, the old side for a removed one, None outside a hunk (a
    file header)."""

    path: str
    line: int | None
    side: str
    label: str


@dataclass(frozen=True)
class DiffSecrets:
    """`values` exist only to scrub published output; never render them."""

    findings: tuple[CommittedSecret, ...] = ()
    values: tuple[str, ...] = field(default=(), repr=False)


def scan_diff(diff: str) -> DiffSecrets:
    findings: list[CommittedSecret] = []
    values: list[str] = []
    for f in split_files(diff):
        scan = detect_secrets(f.text)
        lines = _file_lines(f.text)
        for hit in scan.hits:
            side, line = lines[hit.line - 1]
            findings.append(CommittedSecret(f.path, line, side, hit.label))
        values.extend(scan.values)
    return DiffSecrets(tuple(findings), tuple(dict.fromkeys(values)))


def _file_lines(text: str) -> list[tuple[str, int | None]]:
    """(side, file line number) for every line of one file's diff section."""
    out: list[tuple[str, int | None]] = []
    old = new = 0
    in_hunk = False
    for line in text.split("\n"):
        hunk = _HUNK.match(line)
        if hunk:
            old, new, in_hunk = int(hunk.group(1)), int(hunk.group(2)), True
            out.append(("header", None))
        elif not in_hunk or line.startswith("\\"):
            out.append(("header", None))
        elif line.startswith("+"):
            out.append(("added", new))
            new += 1
        elif line.startswith("-"):
            out.append(("removed", old))
            old += 1
        else:
            out.append(("context", new))
            old, new = old + 1, new + 1
    return out
