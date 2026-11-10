# SPDX-License-Identifier: MIT
"""Load the chosen review lenses' bodies. Pure apart from reading the repo's
own skill bundle.

The model has no file tools, so naming a lens in a prompt is not running it:
the controller reads each chosen lens's `body.md` and inlines it. A lens is
inlined whole or not at all -- a cut lens is not doing the job it was
written for -- so a body that does not fit the remaining size budget is
NOT RUN, and a smaller lens after it can still fit. Which lenses ran and
which did not, and why, is reported in the draft. Choosing them is
`picker.py`'s job.
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


@dataclass(frozen=True)
class LensChoice:
    """A lens to load, in priority order, and why it was chosen."""

    name: str
    why: str


class LensStatus(Enum):
    RUN = "run whole"
    NOT_RUN = "NOT RUN"


@dataclass(frozen=True)
class LensUse:
    """`chars` is the whole body's length (0 when there is none). `reason`
    says why a NOT RUN lens did not run; `why` is why it was chosen."""

    name: str
    status: LensStatus
    chars: int
    why: str
    reason: str = ""


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
    if use.status is LensStatus.NOT_RUN:
        return f"{use.name} ({use.reason}; {use.why})"
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
    """Walk `ranked` in order, inlining each whole body that fits what is
    left of `budget_chars` until `max_lenses` have run; any other lens is NOT
    RUN with its reason. A name with no body takes no slot."""
    uses: list[LensUse] = []
    loaded: list[LoadedLens] = []
    left = budget_chars
    for choice in ranked:
        body = library.body(choice.name)
        skip = _skip_reason(
            body, len(loaded) >= max_lenses, left, max_lenses, budget_chars
        )
        if body is not None and skip is None:
            uses.append(LensUse(choice.name, LensStatus.RUN, len(body), choice.why))
            loaded.append(LoadedLens(choice.name, body))
            left -= len(body)
        else:
            size = 0 if body is None else len(body)
            uses.append(
                LensUse(choice.name, LensStatus.NOT_RUN, size, choice.why, skip or "")
            )
    return LensPlan(tuple(uses), tuple(loaded))


def _skip_reason(
    body: str | None, past_cap: bool, left: int, max_lenses: int, budget_chars: int
) -> str | None:
    if body is None:
        return "no body.md in the bundle"
    if past_cap:
        return f"below the cap of {max_lenses} lenses"
    if len(body) > left:
        return (
            f"did not fit the {budget_chars}-character lens budget whole "
            f"({len(body)} characters, {left} left)"
        )
    return None
