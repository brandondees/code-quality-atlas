# SPDX-License-Identifier: MIT
"""Load the chosen review lenses' bodies. Pure apart from reading the repo's
own skill bundle.

The model has no file tools, so naming a lens in a prompt is not running it:
the controller reads each chosen lens's `body.md` and inlines as much as the
size budget allows. Which lenses were included, truncated or omitted is
reported in the draft. Choosing them is `picker.py`'s job, which runs this
repo's own `choosing-review-lenses` skill rather than a code-side digest of
its route table.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from atlas_reviewer.prompt import LoadedLens

BUNDLE_ROOT = (
    Path(__file__).resolve().parent.parent
    / "collapsed"
    / "skills"
    / "reviewing-a-change"
)
# The top of review mode's 3-8 breadth (skills/manifest.yaml `modes:`).
MAX_LENSES = 8
LENS_BUDGET_CHARS = 60_000
MIN_TRUNCATED_CHARS = 4_000
TRUNCATION_NOTE = (
    "\n[... lens body truncated by atlas_reviewer: {kept} of {total} characters ...]\n"
)


@dataclass(frozen=True)
class LensChoice:
    """A lens to load, in rank order, and why it was chosen."""

    name: str
    why: str


class LensStatus(Enum):
    INCLUDED = "included"
    TRUNCATED = "truncated"
    OMITTED = "omitted"


@dataclass(frozen=True)
class LensUse:
    name: str
    status: LensStatus
    total_chars: int
    kept_chars: int
    why: str


@dataclass(frozen=True)
class LensPlan:
    uses: tuple[LensUse, ...]
    loaded: tuple[LoadedLens, ...]

    def coverage(self) -> str:
        parts = []
        for status in LensStatus:
            names = [_describe(u) for u in self.uses if u.status is status]
            if names:
                parts.append(f"{status.value}: {', '.join(names)}")
        return "; ".join(parts) or "no lens selected"


def _describe(use: LensUse) -> str:
    if use.status is LensStatus.TRUNCATED:
        return f"{use.name} ({use.kept_chars} of {use.total_chars} characters)"
    return use.name


class LensLibrary:
    def __init__(self, root: Path = BUNDLE_ROOT) -> None:
        self._lenses = root / "reference" / "lenses"

    def names(self) -> frozenset[str]:
        return frozenset(p.name for p in self._lenses.iterdir() if p.is_dir())

    def body(self, name: str) -> str | None:
        path = self._lenses / name / "body.md"
        return path.read_text(encoding="utf-8") if path.is_file() else None


def plan_lenses(
    library: LensLibrary,
    ranked: Iterable[LensChoice],
    max_lenses: int = MAX_LENSES,
    budget_chars: int = LENS_BUDGET_CHARS,
) -> LensPlan:
    uses: list[LensUse] = []
    loaded: list[LoadedLens] = []
    left = budget_chars
    for position, choice in enumerate(ranked):
        why = choice.why
        body = library.body(choice.name)
        if body is None:
            uses.append(
                LensUse(
                    choice.name, LensStatus.OMITTED, 0, 0, "no body.md in the bundle"
                )
            )
        elif position >= max_lenses:
            uses.append(
                LensUse(
                    choice.name,
                    LensStatus.OMITTED,
                    len(body),
                    0,
                    f"below the cap of {max_lenses} lenses ({why})",
                )
            )
        elif len(body) <= left:
            uses.append(
                LensUse(choice.name, LensStatus.INCLUDED, len(body), len(body), why)
            )
            loaded.append(LoadedLens(choice.name, body))
            left -= len(body)
        elif left >= MIN_TRUNCATED_CHARS:
            cut = _cut(body, left)
            note = TRUNCATION_NOTE.format(kept=len(cut), total=len(body))
            uses.append(
                LensUse(choice.name, LensStatus.TRUNCATED, len(body), len(cut), why)
            )
            loaded.append(LoadedLens(choice.name, cut + note))
            left = 0
        else:
            uses.append(
                LensUse(
                    choice.name,
                    LensStatus.OMITTED,
                    len(body),
                    0,
                    f"size budget of {budget_chars} characters spent ({why})",
                )
            )
    return LensPlan(tuple(uses), tuple(loaded))


def _cut(body: str, limit: int) -> str:
    head = body[:limit]
    newline = head.rfind("\n")
    return head[: newline + 1] if newline > 0 else head
