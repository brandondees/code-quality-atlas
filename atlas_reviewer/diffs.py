# SPDX-License-Identifier: MIT
"""Split a unified diff into files, rank them by risk, and pack them into
parts that each fit one model call. Pure.

Selection is risk-first, not diff-order-first: when the whole diff cannot
be reviewed within the call cap, what goes unseen is the lowest-risk
material (tests, fixtures, docs), and every unseen file is named.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import reduce

_HEADER = re.compile(r"^diff --git a/(?P<old>.+?) b/(?P<new>.+)$", re.MULTILINE)
UNPARSED_PATH = "(diff text without file headers)"
CUT_MARKER = "\n[... file diff cut by atlas_reviewer to fit one model call ...]\n"


@dataclass(frozen=True)
class RiskTier:
    rank: int
    label: str
    pattern: str


SECURITY = RiskTier(
    0,
    "security, auth, secrets and redaction",
    r"secur|auth(?!or)|redact|secret|token|credential|crypt|permission|polic|"
    r"sanitiz|escap|\bkeys?\b|_key",
)
BOUNDARY = RiskTier(
    1,
    "runner, sandbox, HTTP and model boundary",
    r"runner|sandbox|sprite|exec|http|transport|client|_api\b|api\.|network|"
    r"request|fetch|download|upload|webhook|ledger|openrouter|provider|prompt|llm",
)
SOURCE = RiskTier(2, "other code", r"")
CONFIG = RiskTier(
    3,
    "config, CI and build",
    r"(^|/)\.github/|\.ya?ml$|\.toml$|\.cfg$|\.ini$|requirements[^/]*$|"
    r"(^|/)Dockerfile|(^|/)Makefile$|\.lock$",
)
TESTS = RiskTier(
    4,
    "tests and fixtures",
    r"(^|/)(tests?|spec|__tests__|fixtures?)/|(^|/)test_[^/]*$|_test\.[a-z]+$|"
    r"\.(test|spec)\.[a-z]+$|(^|/)conftest\.py$",
)
DOCS = RiskTier(5, "docs", r"\.(md|rst|txt|adoc)$|(^|/)docs?/|(^|/)(LICENSE|NOTICE)")
RISK_TIERS = (SECURITY, BOUNDARY, SOURCE, CONFIG, TESTS, DOCS)
# Precedence differs from rank: tests/test_redact.py is a test, and
# docs/security.md is a doc, whatever their names suggest.
_MATCH_ORDER = (TESTS, CONFIG, DOCS, SECURITY, BOUNDARY)


def risk_tier(path: str) -> RiskTier:
    return next(
        (t for t in _MATCH_ORDER if re.search(t.pattern, path, re.IGNORECASE)),
        SOURCE,
    )


@dataclass(frozen=True)
class FileDiff:
    """`text` is what a model call gets; `full_chars` is the file's whole
    diff length, so `text` shorter than that means the file was cut."""

    path: str
    text: str
    full_chars: int
    tier: RiskTier

    @property
    def cut(self) -> bool:
        return len(self.text) < self.full_chars

    @property
    def shown_chars(self) -> int:
        return len(self.text) - len(CUT_MARKER) if self.cut else len(self.text)


@dataclass(frozen=True)
class DiffPart:
    files: tuple[FileDiff, ...]

    @property
    def chars(self) -> int:
        return sum(len(f.text) for f in self.files)

    @property
    def text(self) -> str:
        return "".join(f.text for f in self.files)


@dataclass(frozen=True)
class DiffSelection:
    total_files: int
    total_chars: int
    parts: tuple[DiffPart, ...]
    unseen: tuple[FileDiff, ...]

    @property
    def cut(self) -> tuple[FileDiff, ...]:
        return tuple(f for p in self.parts for f in p.files if f.cut)

    @property
    def full(self) -> tuple[FileDiff, ...]:
        return tuple(f for p in self.parts for f in p.files if not f.cut)

    @property
    def kept_chars(self) -> int:
        return sum(p.chars for p in self.parts)

    @property
    def complete(self) -> bool:
        return not self.unseen and not self.cut


def diff_paths(diff: str) -> tuple[str, ...]:
    """New-side path of every file in the diff, in order."""
    return tuple(m.group("new") for m in _HEADER.finditer(diff))


def split_files(diff: str) -> tuple[FileDiff, ...]:
    """Every file section in diff order. Text before the first header (or a
    diff with no headers at all) becomes one pseudo-file, so no input
    character is silently dropped."""
    headers = list(_HEADER.finditer(diff))
    starts = [h.start() for h in headers]
    bounds = zip(starts, [*starts[1:], len(diff)][: len(starts)], strict=True)
    files = [
        _file(h.group("new"), diff[a:b])
        for h, (a, b) in zip(headers, bounds, strict=True)
    ]
    preamble = diff[: starts[0]] if starts else diff
    return tuple([_file(UNPARSED_PATH, preamble)] * bool(preamble.strip()) + files)


def _file(path: str, text: str) -> FileDiff:
    return FileDiff(path, text, len(text), risk_tier(path))


def by_risk(files: tuple[FileDiff, ...]) -> tuple[FileDiff, ...]:
    """Highest risk first; diff order within a tier."""
    return tuple(sorted(files, key=lambda f: f.tier.rank))


@dataclass(frozen=True)
class _Packing:
    parts: tuple[DiffPart, ...] = ()
    unseen: tuple[FileDiff, ...] = ()


def select_diff(diff: str, max_parts: int, part_chars: int) -> DiffSelection:
    """First-fit packing in risk order into at most `max_parts` parts of at
    most `part_chars` characters. A file larger than one part is cut to fit
    a part of its own; a file that fits nowhere once every part is in use
    is unseen."""
    files = split_files(diff)

    def place(acc: _Packing, f: FileDiff) -> _Packing:
        return _place(acc, f, max_parts, part_chars)

    packed = reduce(place, by_risk(files), _Packing())
    return DiffSelection(len(files), len(diff), packed.parts, packed.unseen)


def _place(acc: _Packing, f: FileDiff, max_parts: int, budget: int) -> _Packing:
    slot = next(
        (i for i, p in enumerate(acc.parts) if p.chars + len(f.text) <= budget), None
    )
    if slot is not None:
        grown = DiffPart((*acc.parts[slot].files, f))
        return replace(acc, parts=(*acc.parts[:slot], grown, *acc.parts[slot + 1 :]))
    if len(acc.parts) >= max_parts:
        return replace(acc, unseen=(*acc.unseen, f))
    return replace(acc, parts=(*acc.parts, DiffPart((_fit(f, budget),))))


def describe_by_risk(files: tuple[FileDiff, ...], limit: int) -> str:
    """`[tier] path, path; [tier] path` for the first `limit` files in risk
    order, then a count of the rest."""
    shown = by_risk(files)[:limit]
    groups = ((tier, [f.path for f in shown if f.tier is tier]) for tier in RISK_TIERS)
    listed = "; ".join(
        f"[{t.label}] {', '.join(paths)}" for t, paths in groups if paths
    )
    more = len(files) - len(shown)
    return listed + (f"; and {more} more" if more > 0 else "")


def _fit(f: FileDiff, budget: int) -> FileDiff:
    if len(f.text) <= budget:
        return f
    head = f.text[: max(budget - len(CUT_MARKER), 0)]
    newline = head.rfind("\n")
    kept = head[: newline + 1] if newline > 0 else head
    return replace(f, text=kept + CUT_MARKER)
