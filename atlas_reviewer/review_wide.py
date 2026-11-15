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
in-flight call to settle, and only stops when the settled spend plus the
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
The resolution is one pure function (`resolve_ceiling`) that takes the
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
from atlas_reviewer.quotes import refused_archive

# The per-lens defaults are the 2026-11-11 review-wide defaults re-scoped
# per lens, so an unconfigured one-lens review keeps the numbers it always
# had.
DEFAULT_PER_LENS_CALLS = DEFAULT_MAX_CALLS
DEFAULT_PER_LENS_USD = DEFAULT_RESERVATION_USD
DEFAULT_REVIEW_CEILING_USD = Decimal("10.00")

# The `REVIEW.md` line the reviewed repo sets its ceiling with. The value
# runs to a `#` comment or the end of the line, as the file's other
# settings do; a bare `review_ceiling_usd:` with no value matches too --
# a line present with nothing usable in it.
CEILING_LINE = re.compile(r"^review_ceiling_usd:(?:[ \t]+([^#]*?))?[ \t]*(?:#.*)?$")
REVIEW_MD = "REVIEW.md"
# What a seen-but-unusable ceiling line says (round-1 review of #717,
# m-5): the fail-open fallback is not silent.
_UNUSABLE_NOTE = (
    f"the reviewed repo's merge-base {REVIEW_MD} carries a "
    "review_ceiling_usd: line that is not a positive dollar amount; it is "
    "ignored and the configured ceiling stands"
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
    if not base_tarball or refused_archive(base_tarball) is not None:
        return CeilingRead(None, "")
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
                    # A file past the read bound is not parsed cut: a
                    # truncation inside the value could read as a number
                    # it is not. Unparseable, so the default stands.
                    return CeilingRead(
                        None,
                        f"the reviewed repo's merge-base {REVIEW_MD} is over the "
                        f"{MAX_CHECKED_BYTES}-byte read bound, so its "
                        "review_ceiling_usd: line, if any, was not read; the "
                        "configured ceiling stands",
                    )
                return _ceiling_value(data.decode("utf-8", errors="replace"))
    except (tarfile.TarError, OSError, EOFError):
        return CeilingRead(None, "")
    return CeilingRead(None, "")


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
