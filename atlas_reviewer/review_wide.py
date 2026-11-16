# SPDX-License-Identifier: MIT
"""D68: a multi-lens agentic review's review-wide limits, derived from the
planned lens count under one absolute per-review dollar ceiling.

The flat review-wide defaults -- 50 calls and a $5 reservation shared by
every lens, the picker and the continuations (D44) -- stopped a 12-lens
review near 50 calls with lenses unrun: a missing-lens failure. The
review-wide values are now derived from the per-lens values and the
planned lens count, so scaling the review scales its limits:

- `max_calls = per_lens_calls x planned lenses + the picker's calls`.
- `reservation_usd = per_lens_usd x planned lenses + the picker's
  committed dollars`, clamped to the absolute per-review ceiling.
- `review_wall_s` is the configured review wall raised to
  `lens_wall_s x waves`, where a wave is one pool-full of planned
  lenses. Never lowered: the derivation scales a review up, and a
  review that stops because its limits were not scaled is the
  missing-lens failure this exists to prevent.

The ceiling is the runaway guard, not a budget -- with one qualification
the clamp forces (round-1 review of #717, M-1): the reservation bounds
the review's worst-case *projections*, and a pool of concurrent first
turns projects several worst cases at once, so a clamped reservation can
be smaller than one wave's worst-case reservations. It does not stop a
lens for that: `Spend.reserve` waits, bounded by the review wall, for an
in-flight call to settle -- the wait's real-time backstop arms only when
the review clock itself stops moving across wakeups (round-2 review of
#717, M-1R), so on a healthy clock the wall is the bound, however long a
turn takes -- and only stops when the settled spend plus the
call's own worst case cannot fit even with nothing in flight. Total
spend never passes the ceiling. What the limits never do is size a
review cheaper than thoroughness needs. The default ceiling is $10
(`DEFAULT_REVIEW_CEILING_USD`); `ATLAS_REVIEW_CEILING_USD` or
`--review-ceiling-usd` sets it for the deployment, and the reviewed
repo's own `REVIEW.md` overrides both with a `review_ceiling_usd:` line,
read from the **merge-base** tree the review already fetches -- the tree
the PR branched from, not the base-ref tip -- so a PR cannot raise or
lower its own ceiling, and a ceiling the repo changes on the base tip
takes effect for pull requests branched after it. A line that is present
but not a positive dollar amount fails open to the default, with a note
the draft carries so it can be told apart from no line at all.
The same file carries the lens-selection preference lines (D69):
`review_lens_include:` and `review_lens_exclude:`, each a comma-separated
list of lens names. They override the picker's guideline by include and
exclude, are read from the same merge-base tree, and fail open the same
way: a line that is present but not a usable lens-name list is ignored,
with a note, and the guideline stands. The resolution is one pure
function (`resolve_ceiling`) that takes the
configured value and the repo override and returns the ceiling: a later
per-run policy adjusts the ceiling by computing the value it passes
there, with no redesign -- that is the seam, and no policy engine is
built here.

An operator-set `--max-calls`, `--reservation-usd` or
`--review-wall-seconds` still wins for that one limit
(`AgenticLimits.explicit` records which), and the ceiling clamps the
reservation even then. The per-lens values stay the knobs. Every stop
the derived limits produce names the derived values, the ceiling, the
observed value and the knob (`lens_loop.Derivation`).
"""

from __future__ import annotations

import io
import re
import tarfile
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

from atlas_reviewer.lens_loop import (
    DEFAULT_MAX_CALLS,
    DEFAULT_RESERVATION_USD,
    AgenticLimits,
    Derivation,
    Limits,
    _check_cross_limits,
)
from atlas_reviewer.picker import LENS_NAME, LensPreferences
from atlas_reviewer.quotes import refused_archive

# The per-lens defaults are the 2026-11-11 review-wide defaults re-scoped
# per lens, so an unconfigured one-lens review keeps the numbers it always
# had.
DEFAULT_PER_LENS_CALLS = DEFAULT_MAX_CALLS
DEFAULT_PER_LENS_USD = DEFAULT_RESERVATION_USD
DEFAULT_REVIEW_CEILING_USD = Decimal("10.00")

# The `REVIEW.md` line the reviewed repo sets its ceiling with. The value
# runs to a `#` comment or the end of the line, as the file's other
# settings do; the separator after the colon is optional (`review_ceiling_usd:15`
# parses, round-2 review of #717, m-7), and a bare `review_ceiling_usd:`
# with no value matches too -- a line present with nothing usable in it.
CEILING_LINE = re.compile(r"^review_ceiling_usd:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$")
# The `REVIEW.md` lines the reviewed repo overrides the picker's guideline
# with (D69): each value is a comma-separated list of lens names, same
# value grammar as the ceiling line's.
LENS_INCLUDE_LINE = re.compile(
    r"^review_lens_include:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
LENS_EXCLUDE_LINE = re.compile(
    r"^review_lens_exclude:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
REVIEW_MD = "REVIEW.md"
# What a seen-but-unusable ceiling line says (round-1 review of #717,
# m-5): the fail-open fallback is not silent.
_UNUSABLE_NOTE = (
    f"the reviewed repo's merge-base {REVIEW_MD} carries a "
    "review_ceiling_usd: line that is not a positive dollar amount; it is "
    "ignored and the configured ceiling (default $10) stands"
)
# What a seen-but-unusable lens preference line says (D69): the
# guideline stands, and the note says the lines were seen and ignored.
_UNUSABLE_LENSES_NOTE = (
    f"the reviewed repo's merge-base {REVIEW_MD} carries a "
    "review_lens_include: or review_lens_exclude: line that is not a "
    "comma-separated list of lens names; it is ignored and the picker's "
    "guideline stands"
)
# Bound the file the ceiling line is read from, as `quotes` bounds the
# files it checks.
MAX_CHECKED_BYTES = 64 * 1024


def resolve_ceiling(
    configured: Decimal | None, repo_override: Decimal | None
) -> Decimal:
    """The review's absolute dollar ceiling (D68): the reviewed repo's
    `REVIEW.md` value wins over the operator's `ATLAS_REVIEW_CEILING_USD`
    or `--review-ceiling-usd`, which wins over the $10 default. A later
    per-run policy adjusts the ceiling by computing the value it passes
    here -- the documented seam, no policy engine."""
    if repo_override is not None:
        return repo_override
    if configured is not None:
        return configured
    return DEFAULT_REVIEW_CEILING_USD


class _OverBound:
    """The REVIEW.md marker a shared read returns when the file exists but
    is over the read bound: not parsed cut, because a truncation inside a
    value could read as a value it is not."""


_REVIEW_MD_OVER_BOUND = _OverBound()


def _review_md_text(base_tarball: bytes) -> str | _OverBound | None:
    """The text of the reviewed repo's **merge-base** `REVIEW.md`, or None
    when there is no readable one (no tarball, an archive the fail-closed
    check refuses, a read error, no such file), or `_OverBound` when the
    file exists but is over the read bound. Shared by every setting this
    file carries, so the walk exists once."""
    if not base_tarball or refused_archive(base_tarball) is not None:
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(base_tarball), mode="r:gz") as archive:
            for member in archive:
                path = member.name.partition("/")[2]
                if path != REVIEW_MD or not member.isfile():
                    continue
                raw = archive.extractfile(member)
                if raw is None:
                    continue
                data = raw.read(MAX_CHECKED_BYTES + 1)
                if len(data) > MAX_CHECKED_BYTES:
                    return _REVIEW_MD_OVER_BOUND
                return data.decode("utf-8", errors="replace")
    except (tarfile.TarError, OSError, EOFError):
        return None
    return None


def review_md_ceiling(base_tarball: bytes) -> CeilingRead:
    """The reviewed repo's `review_ceiling_usd:` line in its **merge-base**
    `REVIEW.md` (D68) -- the base tarball the review already fetches, the
    tree the PR branched from, not the base-ref tip; a ceiling the repo
    changes on the base tip takes effect for pull requests branched after
    it, and a PR cannot raise or lower its own ceiling either way. A
    tarball that fails the fail-closed archive check, a missing file, or
    no ceiling line read as `CeilingRead(None, "")` -- the default stands,
    silently, exactly as no override at all. A line that is present but
    not a positive dollar amount, more than one, or a file over the read
    bound read as `CeilingRead(None, note)`: the default still stands,
    fail-open, and the note says the line was seen and ignored."""
    text = _review_md_text(base_tarball)
    if isinstance(text, _OverBound):
        return CeilingRead(
            None,
            f"the reviewed repo's merge-base {REVIEW_MD} is over the "
            f"{MAX_CHECKED_BYTES}-byte read bound, so its "
            "review_ceiling_usd: line, if any, was not read; the "
            "configured ceiling (default $10) stands",
        )
    if text is None:
        return CeilingRead(None, "")
    return _ceiling_value(text)


@dataclass(frozen=True)
class LensPreferencesRead:
    """What the reviewed repo's merge-base `REVIEW.md` said about lens
    selection (D69): `preferences` is the override of the picker's
    guideline, None when there is none; `note` is controller text,
    non-empty only when preference lines were seen and ignored, so "lines
    present but unusable" can be told apart from "no lines"."""

    preferences: LensPreferences | None
    note: str


def review_md_lens_preferences(base_tarball: bytes) -> LensPreferencesRead:
    """The reviewed repo's `review_lens_include:` and
    `review_lens_exclude:` lines in its **merge-base** `REVIEW.md` (D69) --
    the same tree the ceiling is read from, so a PR cannot move its own
    override either. No lines read as `LensPreferencesRead(None, "")`: the
    guideline stands, exactly as no override at all. Lines that are
    present but not comma-separated lists of lens-shaped names, a key
    repeated, or a file over the read bound read as
    `LensPreferencesRead(None, note)`: the guideline still stands,
    fail-open, and the note says the lines were seen and ignored. A name
    that is lens-shaped but matches no bundle lens is kept: an include
    shows up as its own NOT RUN line and an exclude as the recorded
    override, never silently guessed or dropped."""
    text = _review_md_text(base_tarball)
    if isinstance(text, _OverBound):
        return LensPreferencesRead(
            None,
            f"the reviewed repo's merge-base {REVIEW_MD} is over the "
            f"{MAX_CHECKED_BYTES}-byte read bound, so its "
            "review_lens_include: and review_lens_exclude: lines, if any, "
            "were not read; the picker's guideline stands",
        )
    if text is None:
        return LensPreferencesRead(None, "")
    return _lens_preferences(text)


@dataclass(frozen=True)
class CeilingRead:
    """What the reviewed repo's merge-base `REVIEW.md` said about the
    ceiling: `value` is the override, None when there is none; `note` is
    controller text, non-empty only when a ceiling line was seen and
    ignored, so "line present but unusable" can be told apart from "no
    line" (round-1 review of #717, m-5)."""

    value: Decimal | None
    note: str


def _ceiling_value(text: str) -> CeilingRead:
    """The `review_ceiling_usd:` line's value. One line, one value; no
    line reads as absent (empty note); a line that is present but not a
    positive dollar amount -- or more than one -- reads as unusable, with
    the note that says so."""
    found: Decimal | None = None
    seen_line = False
    for line in text.splitlines():
        match = CEILING_LINE.match(line)
        if match is None:
            continue
        if found is not None:
            return CeilingRead(None, _UNUSABLE_NOTE)
        seen_line = True
        raw = match.group(1)
        if raw is None or not raw.strip():
            return CeilingRead(None, _UNUSABLE_NOTE)
        try:
            found = Decimal(raw)
        except InvalidOperation:
            return CeilingRead(None, _UNUSABLE_NOTE)
    if found is None or not found.is_finite() or found <= 0:
        if seen_line:
            return CeilingRead(None, _UNUSABLE_NOTE)
        return CeilingRead(None, "")
    return CeilingRead(found, "")


def _lens_preferences(text: str) -> LensPreferencesRead:
    """The `review_lens_include:` and `review_lens_exclude:` lines' values
    (D69). One line per key; no line for a key reads as absent. Any line
    that is present but carries no comma-separated list of lens-shaped
    names, or a key that appears twice, makes the whole read unusable: the
    guideline stands, fail-open, with the note that says so."""
    values: dict[str, list[str]] = {}
    for pattern, key in (
        (LENS_INCLUDE_LINE, "include"),
        (LENS_EXCLUDE_LINE, "exclude"),
    ):
        for line in text.splitlines():
            match = pattern.match(line)
            if match is None:
                continue
            if key in values:
                return LensPreferencesRead(None, _UNUSABLE_LENSES_NOTE)
            raw = match.group(1)
            names = _lens_names(raw)
            if names is None:
                return LensPreferencesRead(None, _UNUSABLE_LENSES_NOTE)
            values[key] = names
    if not values:
        return LensPreferencesRead(None, "")
    return LensPreferencesRead(
        LensPreferences(
            include=tuple(values.get("include", ())),
            exclude=tuple(values.get("exclude", ())),
        ),
        "",
    )


def _lens_names(raw: str | None) -> list[str] | None:
    """A comma-separated list of lens-shaped names, deduplicated in file
    order, or None when the value is empty or any name is not lens-shaped.
    Whitespace around a name is the list's separator at work, not part of
    one."""
    if raw is None or not raw.strip():
        return None
    names: list[str] = []
    for piece in raw.split(","):
        name = piece.strip()
        if not LENS_NAME.fullmatch(name) or len(name) > 80:
            return None
        if name not in names:
            names.append(name)
    return names


def derive_review_wide(
    limits: AgenticLimits,
    planned_lenses: int,
    picker_calls: int = 0,
    picker_usd: Decimal = Decimal(0),
    repo_ceiling: Decimal | None = None,
    repo_ceiling_note: str = "",
) -> tuple[Limits, Derivation]:
    """The review-wide limits a multi-lens review runs on (D68), derived
    from `limits`' per-lens values and `planned_lenses`, with the picker's
    already-committed calls and dollars added and the reservation clamped
    to the ceiling (`repo_ceiling` wins, then the configured
    `review_ceiling_usd`, then the default). Returns the derived limits --
    every field but the three review-wide ones is the resolved value
    unchanged -- with the `Derivation` record the limit stops read.

    An operator-set `max_calls`, `reservation_usd` or `review_wall_s`
    (`limits.explicit`) wins for that one limit; the reservation is still
    clamped to the ceiling, which is absolute. A derived call budget below
    the per-lens turn cap is refused before any lens runs: the limits
    guard against runaway loops and costly failures, never against
    thoroughness. Every refusal this function can raise is planned-count
    independent -- the same refusal a one-planned-lens derivation raises
    -- so a caller can validate before its picker spends (round-1 review
    of #717, m-3)."""
    resolved = limits.resolve(cross_limits=False)
    if (
        isinstance(planned_lenses, bool)
        or not isinstance(planned_lenses, int)
        or planned_lenses < 1
    ):
        raise ValueError("planned_lenses must be a positive integer")
    if picker_calls < 0 or picker_usd < 0:
        raise ValueError("the picker's committed spend cannot be negative")
    ceiling = resolve_ceiling(resolved.review_ceiling_usd, repo_ceiling)
    waves = -(-planned_lenses // resolved.pool_size)
    per_lens_calls = resolved.per_lens_calls or DEFAULT_PER_LENS_CALLS
    per_lens_usd = resolved.per_lens_usd or DEFAULT_PER_LENS_USD
    calls_derived = "max_calls" not in limits.explicit
    if calls_derived:
        if per_lens_calls < resolved.max_turns:
            raise ValueError(
                f"per_lens_calls ({per_lens_calls}) must be at least "
                f"max_turns ({resolved.max_turns}), so one attempt always fits"
            )
        max_calls = per_lens_calls * planned_lenses + picker_calls
    else:
        max_calls = resolved.max_calls
    reservation_derived = "reservation_usd" not in limits.explicit
    derived_usd = per_lens_usd * planned_lenses + picker_usd
    raw_reservation = derived_usd if reservation_derived else resolved.reservation_usd
    clamped = raw_reservation > ceiling
    reservation = min(raw_reservation, ceiling)
    wall_derived = "review_wall_s" not in limits.explicit
    review_wall_s = (
        max(resolved.review_wall_s, resolved.lens_wall_s * waves)
        if wall_derived
        else resolved.review_wall_s
    )
    derived = replace(
        resolved,
        max_calls=max_calls,
        reservation_usd=reservation,
        review_wall_s=review_wall_s,
    )
    # The per-lens-against-review-wide relations, checked against the
    # totals this review runs on: structurally satisfied by a derived
    # call budget (it is at least the per-lens budget) and a derived wall
    # (at least lens_wall_s x waves), and refused here when an explicit
    # review-wide value sits below its per-lens budget.
    _check_cross_limits(derived)
    record = Derivation(
        planned_lenses=planned_lenses,
        waves=waves,
        per_lens_calls=per_lens_calls,
        per_lens_usd=per_lens_usd,
        picker_calls=picker_calls,
        picker_usd=picker_usd,
        ceiling=ceiling,
        max_calls=max_calls,
        reservation_usd=reservation,
        review_wall_s=review_wall_s,
        calls_derived=calls_derived,
        reservation_derived=reservation_derived,
        clamped=clamped,
        ceiling_note=repo_ceiling_note,
    )
    return derived, record
