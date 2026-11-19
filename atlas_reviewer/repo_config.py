# SPDX-License-Identifier: MIT
"""The reviewed repo's **merge-base** `REVIEW.md` config parse (D81's S1):
the schema-validated read of the settings lines the reviewer consumes from
the file the reviewed repo carries its policy in.

The file name is one constant (`REVIEW_MD`), not a design commitment -- a
`.atlas.yml`-style file remains the alternative if the key set outgrows
one-line-per-key. D81 Q1 keeps `REVIEW.md` and extends it rather than
adding a second file, so the constant is the only thing a rename would
touch.

The schema is a **closed set, not a pass-through** (the plan's §4): the
parse yields a dollar amount, lens names, and controller notes, and
nothing else -- no config key can widen network, secret, or Sprite
access, because no key reaches any of that. Keys the build does not
carry parse as **unsupported with named notes**: a line in the `review_`
key namespace -- the namespace every setting line in this file lives in
-- that neither this module's schema nor the admission read
(`service_admit.py`, the default branch, #756/#761) carries is ignored
fail-open and named, the generalization of D68's unusable-line note.
Lines inside a fenced code block are examples, not configuration
attempts, and are skipped. Every note names the key,
the condition, and the default that stands, and **never echoes the raw
rejected value**: the value is unvalidated author-controlled input
(merge-base `REVIEW.md` is author-controllable in same-repo and stacked
PRs), only schema-validated numbers may be named (D68's ceiling note),
and the key name a note carries is validated to a markup-free shape at
parse -- the same trust boundary D69's lens-shaped validation draws --
so no note can carry markup into the controller text.

Config values are untrusted data everywhere they reach a model. The read
stays bounded: the file is read under `MAX_CHECKED_BYTES` (64 KiB), and
a file over the bound is not parsed cut, because a truncation inside a
value could read as a value it is not. Both D68 lines keep their
existing **merge-base** read -- the tree the PR branched from, not the
base-ref tip and never the PR head -- so a PR cannot move its own
values; admission-class keys read the default branch instead, which is
S4's surface (`service_admit.py`), not this module's.

Today's keys:

- `review_ceiling_usd:` (D68) -- the repo's per-review dollar ceiling;
  it wins over the operator's `ATLAS_REVIEW_CEILING_USD` outright, in
  either direction (D81 Q2 keeps D68's semantics), and the ceiling
  actually used is resolved by `review_wide.resolve_ceiling` and named
  in the draft and the post through D68's ceiling note.
- `review_lens_include:` / `review_lens_exclude:` (D69) -- the lens
  preference that overrides the picker's guideline, applied by
  `picker`, whose protection set is the manifest's whole `tier: floor`
  (D69's 5:13 PM CT update), not the critical tier alone.

The admission-class keys (`review_base_include:` /
`review_base_exclude:` / `review_skip_events:`, #756 and #761) are
`service_admit.py`'s -- read from the repo's default branch, a different
window on the same file -- and the scan knows them by name so it never
calls them unsupported.

The reads are pure functions of the merge-base tarball. `read_repo_config`
parses the whole file once; the per-line reads are the consumers'
windows over it.
"""

from __future__ import annotations

import io
import re
import tarfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from atlas_reviewer.picker import LENS_NAME, LensPreferences
from atlas_reviewer.quotes import refused_archive

# The file the reviewed repo sets its configuration in (D81 Q1). One
# constant, deliberately: extending this file is the decided shape, and
# a `.atlas.yml`-style rename stays the alternative the key set can grow
# into, not a second file to add beside it.
REVIEW_MD = "REVIEW.md"

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


@dataclass(frozen=True)
class CeilingRead:
    """What the reviewed repo's merge-base `REVIEW.md` said about the
    ceiling: `value` is the override, None when there is none; `note` is
    controller text, non-empty only when a ceiling line was seen and
    ignored, so "line present but unusable" can be told apart from "no
    line" (round-1 review of #717, m-5)."""

    value: Decimal | None
    note: str


@dataclass(frozen=True)
class LensPreferencesRead:
    """What the reviewed repo's merge-base `REVIEW.md` said about lens
    selection (D69): `preferences` is the override of the picker's
    guideline, None when there is none; `note` is controller text,
    non-empty only when preference lines were seen and ignored, so "lines
    present but unusable" can be told apart from "no lines"."""

    preferences: LensPreferences | None
    note: str


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


# A config attempt the schema does not carry: a line in the `review_`
# key namespace, the namespace every setting line in this file lives in.
# The key a note names is bounded and markup-free by the same regex, so
# naming it carries no author-controlled text past validation. Lines
# outside the namespace -- a policy file's ordinary prose, an uppercase
# variant -- are not config attempts in this grammar and stay unremarked,
# exactly as they read today.
_UNSUPPORTED_KEY_LINE = re.compile(r"^review_([a-z0-9_]{1,80}):")
# The keys the build carries. The first three are this module's own
# schema; the last three are the admission-class keys `service_admit.py`
# reads and honors from the repo's default branch (#756, #761) -- the
# same file serves both windows, so a key the admission read carries is
# supported by the build, and naming it "unsupported" here would be the
# false note the named-note pattern exists to prevent. They are checked
# against `service_admit._ADMISSION_KEYS` by a test, so a key added
# there without this set fails rather than drawing a false note. All of
# them match the unsupported scan's shape, so the scan excludes them by
# name.
_KNOWN_KEYS = frozenset(
    {
        "review_ceiling_usd",
        "review_lens_include",
        "review_lens_exclude",
        "review_base_include",
        "review_base_exclude",
        "review_skip_events",
    }
)
# How many distinct unsupported keys one note names; the remainder is
# counted, never listed, so the note is bounded controller text no
# matter how many unknown keys a file packs.
_UNSUPPORTED_KEYS_NAMED = 8


def _unsupported_notes(text: str) -> tuple[str, ...]:
    """The named note for the keys the schema does not carry: one note,
    naming each distinct unknown `review_` key (at most
    `_UNSUPPORTED_KEYS_NAMED` of them, the remainder counted), the
    condition, and the default that stands -- never any rejected value.
    The key names are validated markup-free by the scan's regex, so the
    note carries no author-controlled text past validation. Lines inside
    a fenced code block are skipped: a repo's policy file may document a
    future key in an example, and an example is not a configuration
    attempt. The fence walk is the same line-level toggle for every
    fence marker, so an unbalanced fence flips the state for the rest of
    the file -- a missed or an extra note, either way fail-open and
    bounded, never a wrong value: the known keys' own parsers are
    line-based and unchanged."""
    seen: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _UNSUPPORTED_KEY_LINE.match(line)
        if match is None:
            continue
        key = f"review_{match.group(1)}"
        if key in _KNOWN_KEYS or key in seen:
            continue
        seen.append(key)
    if not seen:
        return ()
    named = seen[:_UNSUPPORTED_KEYS_NAMED]
    listed = ", ".join(f"{key}:" for key in named)
    extra = len(seen) - len(named)
    if extra:
        listed += f", and {extra} more unsupported key(s)"
    if len(named) == 1:
        note = (
            f"the reviewed repo's merge-base {REVIEW_MD} carries a {listed} "
            "line, which this build does not support; it is ignored and "
            "the default stands"
        )
    else:
        note = (
            f"the reviewed repo's merge-base {REVIEW_MD} carries unsupported "
            f"setting lines {listed}, which this build does not support; "
            "they are ignored and the defaults stand"
        )
    return (note,)


@dataclass(frozen=True)
class RepoConfig:
    """The whole parse of the reviewed repo's **merge-base** `REVIEW.md`:
    `ceiling` and `lenses` are the D68/D69 reads, and `unsupported_notes`
    name the keys the schema does not carry, empty when there are none --
    a plain policy file reads exactly as it did before this module."""

    ceiling: CeilingRead
    lenses: LensPreferencesRead
    unsupported_notes: tuple[str, ...] = ()


def read_repo_config(base_tarball: bytes) -> RepoConfig:
    """The reviewed repo's merge-base `REVIEW.md`, parsed once against the
    closed schema: the D68/D69 lines and the unsupported keys' named
    notes. A tarball that fails the fail-closed archive check or no file
    at all reads as an empty config, silently; a file over the read bound
    is not parsed cut and names the bound on both reads."""
    text = _review_md_text(base_tarball)
    if isinstance(text, _OverBound):
        return RepoConfig(
            CeilingRead(
                None,
                f"the reviewed repo's merge-base {REVIEW_MD} is over the "
                f"{MAX_CHECKED_BYTES}-byte read bound, so its "
                "review_ceiling_usd: line, if any, was not read; the "
                "configured ceiling (default $10) stands",
            ),
            LensPreferencesRead(
                None,
                f"the reviewed repo's merge-base {REVIEW_MD} is over the "
                f"{MAX_CHECKED_BYTES}-byte read bound, so its "
                "review_lens_include: and review_lens_exclude: lines, if "
                "any, were not read; the picker's guideline stands",
            ),
        )
    if text is None:
        return RepoConfig(CeilingRead(None, ""), LensPreferencesRead(None, ""))
    return RepoConfig(
        _ceiling_value(text),
        _lens_preferences(text),
        _unsupported_notes(text),
    )


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
    return read_repo_config(base_tarball).ceiling


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
    return read_repo_config(base_tarball).lenses
