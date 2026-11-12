# SPDX-License-Identifier: MIT
"""Quote checks (D31, D34 (2); `synthesis.md`'s quote-the-line gate). Pure
apart from reading the head tarball in memory.

A `file:line` finding is verified only when its evidence is the cited
lines of the head file, or among the PR diff's removed lines of that file
(code the PR deletes is not in the head). The head files are the changed
ones plus, through `with_head_files`, any file the lens read at head. The cited span is the quote's
own line count: one line of evidence needs `start == end`, and several
lines need a range of that many lines. A wider range is not searched, so
a quote cannot verify against a line the citation does not name. A range
that runs past the end of the file is not trimmed to the file and
searched, since that would let a quote match anywhere in it. A whole-file
finding is verified when the path is in the head tree or the diff. A
design reference has no line to quote. Anything else is unverified and
never reported as a verified finding.

Matching collapses internal whitespace and strips the ends of a line,
so indentation, line endings and a doubled space do not decide it. A
one-line quote may be a fragment of that one cited line, but a fragment
shorter than `MIN_FRAGMENT_CHARS` non-space characters must be the whole
line, so a quote such as `}` cannot pass by luck. A quote of several
lines must be those cited lines, after that whitespace collapse. A quote
of whole lines whose text is at least `MIN_FRAGMENT_CHARS` non-space
characters may also match the same number of lines starting within
`QUOTE_DRIFT` lines of the citation. That match is tagged as drifted, and
the verified finding's location becomes the matched head lines, so the
location names the lines that hold the quote. A shorter quote, including
`}`, does not get that search, and a wider cited range is still not
searched. Removed lines match within one run of consecutive `-` lines of
one hunk, at any line of the file's diff, with the same whitespace
collapse, and the span rule does not apply to them: D31 checks the head
at the cited range, and the removed side has no head line. A removed
match is checked before a drifted head match, so a quote of a removed
line is tagged as removed even when the same text sits near the citation.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from atlas_reviewer.diffs import split_files
from atlas_reviewer.lens_contract import DesignRef, Finding, LineRange, WholeFile
from atlas_reviewer.runner import refused_archive

MIN_FRAGMENT_CHARS = 8
# A whole-line quote may sit this many lines off the citation.
QUOTE_DRIFT = 2
MAX_CHECKED_FILE_BYTES = 8 * 1024 * 1024
_HUNK_START = "@@ "


class QuoteSource(StrEnum):
    HEAD = "head"
    HEAD_NEAR = f"head, within {QUOTE_DRIFT} lines of the citation"
    REMOVED = "removed lines"
    NOT_NEEDED = "no line to quote"


@dataclass(frozen=True)
class Verified:
    finding: Finding
    source: QuoteSource


@dataclass(frozen=True)
class Unverified:
    finding: Finding
    reason: str


QuoteCheck = Verified | Unverified


@dataclass(frozen=True)
class SourceText:
    """What the checks read: the head tree's lines for the cited paths
    (a path that is not a regular file at head is absent), each diffed
    path's runs of removed lines, and every path the diff names. When
    `unreadable` is set the head tree could not be read and every check
    that needs it fails."""

    head: Mapping[str, tuple[str, ...]]
    removed: Mapping[str, tuple[tuple[str, ...], ...]] = field(default_factory=dict)
    diffed: frozenset[str] = frozenset()
    unreadable: str = ""


def read_sources(head_tarball: bytes, diff: str, paths: Iterable[str]) -> SourceText:
    """The head files at `paths` (repository-relative; the tarball's one
    top-level directory is dropped) and the diff's removed lines. The
    tarball is checked with the same fail-closed archive check as an
    upload before any member is read."""
    removed, diffed = _removed_runs(diff)
    refused = refused_archive(head_tarball)
    if refused is not None:
        return SourceText({}, removed, diffed, f"the head tree is refused: {refused}")
    try:
        head = _head_lines(head_tarball, frozenset(paths))
    except (tarfile.TarError, OSError, EOFError) as exc:
        return SourceText({}, removed, diffed, f"the head tree is unreadable: {exc}")
    return SourceText(head, removed, diffed)


def with_head_files(
    sources: SourceText, head_tarball: bytes, paths: Iterable[str]
) -> SourceText:
    """`sources` plus the head lines of `paths` it does not already hold:
    files the lens read at head that the pull request does not change.
    With no head tree, or one that cannot be read, `sources` is unchanged."""
    extra = frozenset(paths) - set(sources.head)
    if not extra or not head_tarball or sources.unreadable:
        return sources
    if refused_archive(head_tarball) is not None:
        return sources
    try:
        found = _head_lines(head_tarball, extra)
    except (tarfile.TarError, OSError, EOFError):
        return sources
    return SourceText({**sources.head, **found}, sources.removed, sources.diffed)


def _head_lines(data: bytes, wanted: frozenset[str]) -> dict[str, tuple[str, ...]]:
    found: dict[str, tuple[str, ...]] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            path = member.name.partition("/")[2]
            if path not in wanted or not member.isfile():
                continue
            if member.size > MAX_CHECKED_FILE_BYTES:
                continue
            raw = archive.extractfile(member)
            if raw is not None:
                found[path] = _lines(raw.read().decode("utf-8", errors="replace"))
    return found


def _lines(text: str) -> tuple[str, ...]:
    lines = text.split("\n")
    return tuple(lines[:-1] if lines and lines[-1] == "" else lines)


def _removed_runs(
    diff: str,
) -> tuple[dict[str, tuple[tuple[str, ...], ...]], frozenset[str]]:
    """Each file's runs of consecutive removed lines, keyed by both sides
    of a rename; and every path the diff names."""
    runs: dict[str, tuple[tuple[str, ...], ...]] = {}
    diffed: set[str] = set()
    for section in split_files(diff):
        sides = _sides(section.path, section.text)
        diffed.update(sides)
        found = _runs(section.text)
        for side in sides:
            runs[side] = (*runs.get(side, ()), *found)
    return runs, frozenset(diffed)


def _sides(path: str, text: str) -> tuple[str, ...]:
    header = text.split("\n" + _HUNK_START, 1)[0].split("\n")
    old = next(
        (
            line.removeprefix(prefix)
            for line in header
            for prefix in ("rename from ", "--- a/")
            if line.startswith(prefix)
        ),
        None,
    )
    return (path,) if old is None or old == path else (path, old)


def _runs(text: str) -> tuple[tuple[str, ...], ...]:
    runs: list[tuple[str, ...]] = []
    run: list[str] = []
    in_hunk = False
    for line in text.split("\n"):
        in_hunk = in_hunk or line.startswith(_HUNK_START)
        if in_hunk and line.startswith("-"):
            run.append(line[1:])
            continue
        if run:
            runs.append(tuple(run))
            run = []
    if run:
        runs.append(tuple(run))
    return tuple(runs)


def check_quote(finding: Finding, sources: SourceText) -> QuoteCheck:
    location = finding.location
    match location:
        case DesignRef():
            return Verified(finding, QuoteSource.NOT_NEEDED)
        case WholeFile(path=path):
            if path in sources.head or path in sources.diffed:
                return Verified(finding, QuoteSource.NOT_NEEDED)
            if sources.unreadable:
                return Unverified(finding, sources.unreadable)
            return Unverified(finding, "the path is not in the head tree or the diff")
        case LineRange():
            return _check_range(finding, location, sources)


def _check_range(finding: Finding, where: LineRange, sources: SourceText) -> QuoteCheck:
    quote = _quote_lines(finding.evidence)
    if not quote:
        return Unverified(finding, "the evidence quotes nothing")
    head = sources.head.get(where.path)
    window = None if head is None else _cited_lines(head, where)
    # The span is the quote's own line count. A wider window would let a
    # one-line quote verify against any line inside it.
    span_matches = where.end - where.start + 1 == len(quote)
    if window is not None and span_matches and _found(quote, window):
        return Verified(finding, QuoteSource.HEAD)
    if any(_found(quote, run) for run in sources.removed.get(where.path, ())):
        return Verified(finding, QuoteSource.REMOVED)
    near = None if head is None or not span_matches else _near(quote, head, where)
    if near is not None:
        return Verified(replace(finding, location=near), QuoteSource.HEAD_NEAR)
    if head is None and sources.unreadable:
        return Unverified(finding, sources.unreadable)
    if head is not None and window is None:
        return Unverified(
            finding,
            f"the range runs past the end of the head file ({len(head)} lines), "
            "and the quote is not among the diff's removed lines",
        )
    return Unverified(
        finding,
        "the quote is not at that range of the head file, or among the "
        "diff's removed lines of that file",
    )


def _cited_lines(head: tuple[str, ...], where: LineRange) -> tuple[str, ...] | None:
    """The cited lines, when the range fits in the file. A range that runs
    past the end is not a window: the slice of it would be the rest of the
    file, and a one-line quote would then match anywhere in the file."""
    if where.start > len(head) or where.end > len(head):
        return None
    return head[where.start - 1 : where.end]


def _quote_lines(evidence: str) -> tuple[str, ...]:
    lines = [line.strip() for line in evidence.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return tuple(lines)


def _found(quote: tuple[str, ...], window: Iterable[str]) -> bool:
    lines = tuple(_squash(line) for line in window)
    quote = tuple(_squash(part) for part in quote)
    if len(quote) == 1:
        return any(_fragment_of(quote[0], line) for line in lines)
    return any(
        lines[i : i + len(quote)] == quote for i in range(len(lines) - len(quote) + 1)
    )


def _fragment_of(quote: str, line: str) -> bool:
    if quote == line:
        return True
    long_enough = len(quote.replace(" ", "")) >= MIN_FRAGMENT_CHARS
    return long_enough and quote in line


def _squash(line: str) -> str:
    return " ".join(line.split())


def _near(
    quote: tuple[str, ...], head: tuple[str, ...], where: LineRange
) -> LineRange | None:
    """The head lines a whole-line quote matches within `QUOTE_DRIFT`
    lines of the citation, or None. A fragment does not qualify: it would
    match a nearby line that merely contains the words."""
    joined = "".join(_squash(line).replace(" ", "") for line in quote)
    if len(joined) < MIN_FRAGMENT_CHARS:
        return None
    wanted = tuple(_squash(line) for line in quote)
    for delta in range(1, QUOTE_DRIFT + 1):
        for sign in (1, -1):
            start = where.start + sign * delta
            if start < 1:
                continue
            shifted = LineRange(where.path, start, where.end + sign * delta)
            window = _cited_lines(head, shifted)
            if window is not None and tuple(_squash(line) for line in window) == wanted:
                return shifted
    return None


def check_all(
    findings: Iterable[Finding], sources: SourceText
) -> tuple[QuoteCheck, ...]:
    return tuple(check_quote(f, sources) for f in findings)
