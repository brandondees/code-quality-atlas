# SPDX-License-Identifier: MIT
"""Which files of a unified diff fit inside a character cap. Pure."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADER = re.compile(r"^diff --git a/(?P<old>.+?) b/(?P<new>.+)$", re.MULTILINE)


@dataclass(frozen=True)
class DiffCoverage:
    """`partial` is the file the cap cut through (None when the cut fell
    exactly between files); `unseen` starts after it."""

    total_files: int
    seen: tuple[str, ...]
    partial: str | None
    unseen: tuple[str, ...]


def diff_paths(diff: str) -> tuple[str, ...]:
    """New-side path of every file in the diff, in order."""
    return tuple(m.group("new") for m in _HEADER.finditer(diff))


def diff_coverage(diff: str, cap: int) -> DiffCoverage:
    """`diff` must be the same text the cap is applied to (post-redaction),
    so offsets here are offsets in what the model received."""
    headers = list(_HEADER.finditer(diff))
    ends = [h.start() for h in headers[1:]] + [len(diff)] * bool(headers)
    seen: list[str] = []
    partial: str | None = None
    unseen: list[str] = []
    for header, end in zip(headers, ends, strict=True):
        path = header.group("new")
        if end <= cap:
            seen.append(path)
        elif header.start() < cap:
            partial = path
        else:
            unseen.append(path)
    return DiffCoverage(len(headers), tuple(seen), partial, tuple(unseen))
