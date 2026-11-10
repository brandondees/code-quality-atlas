# SPDX-License-Identifier: MIT
"""The pull request's conversation as one bounded block for the model (D34, D37).

The block replaces the old 2,000-character PR body: the title, author, base
and head branches, draft flag, labels, requested reviewers and teams, the
body, every commit subject, and every review, review comment and
conversation comment, each labelled with its id, author, time and the
commit it was made at. It is all PR-written text, so it is redacted and
fenced as untrusted like the rest, and every free-text body is quoted with
`> ` so a body cannot forge another remark's heading.

Nothing is cut silently. The body, each commit subject and each remark have
their own cap, commit subjects and remarks keep the newest that fit their
budget, and the block as a whole is held to `total_chars`. Every cut and
everything left out is an `Omission`, which the draft lists and the model is
told about.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import accumulate

from atlas_reviewer.domain import Omission, PrEvent
from atlas_reviewer.evidence import (
    BODY_CHARS,
    PrCommit,
    PullInfo,
    Remark,
    parse_issue_comment,
    parse_review,
    parse_review_comment,
)
from atlas_reviewer.gather import Collected
from atlas_reviewer.notes import quote_untrusted
from atlas_reviewer.ports import BoundaryError, GitHubReader, Json, Listing
from atlas_reviewer.redact import RedactedText, Redactor

CONVERSATION_CHARS = 65_536
COMMIT_CHARS = 8_192
REMARK_CHARS = 4_000
SUBJECT_CHARS = 200
MAX_LISTED_IDS = 20
SOURCE = "pull request conversation"


@dataclass(frozen=True)
class ConversationBudget:
    """Characters, not bytes. Working defaults pending the owner (D37):
    about 64 KiB in all, at most 16 KiB of it body and 8 KiB commit
    subjects, the rest for remarks."""

    total_chars: int = CONVERSATION_CHARS
    body_chars: int = BODY_CHARS
    commit_chars: int = COMMIT_CHARS
    remark_chars: int = REMARK_CHARS

    def __post_init__(self) -> None:
        sizes = (
            self.total_chars,
            self.body_chars,
            self.commit_chars,
            self.remark_chars,
        )
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in sizes):
            raise ValueError("conversation budgets must be positive integers")


@dataclass(frozen=True)
class Conversation:
    """`inner_redactions` counts what was redacted from the commit subjects
    and remark bodies shown, before `text` was assembled and redacted again."""

    text: RedactedText
    omissions: tuple[Omission, ...]
    remarks_shown: int
    remarks_total: int
    inner_redactions: int = 0


Fetch = Callable[[GitHubReader, PrEvent], Listing]
Parse = Callable[[Json, str], Remark]

_SOURCES: tuple[tuple[str, Fetch, Parse], ...] = (
    ("reviews", lambda gh, e: gh.list_reviews(e.repo, e.pr_number), parse_review),
    (
        "review comments",
        lambda gh, e: gh.list_review_comments(e.repo, e.pr_number),
        parse_review_comment,
    ),
    (
        "conversation comments",
        lambda gh, e: gh.list_issue_comments(e.repo, e.pr_number),
        parse_issue_comment,
    ),
)


def fetch_remarks(
    event: PrEvent, github: GitHubReader, out: Collected
) -> tuple[Remark, ...]:
    """Every review, review comment and conversation comment GitHub lists,
    up to the client's page cap. A failed or cut-off list, and each entry
    that does not parse, is an omission; the rest are kept."""
    return tuple(
        remark
        for what, fetch, parse in _SOURCES
        for remark in _read(what, fetch, parse, github, event, out)
    )


def _read(
    what: str,
    fetch: Fetch,
    parse: Parse,
    github: GitHubReader,
    event: PrEvent,
    out: Collected,
) -> tuple[Remark, ...]:
    source = f"pull request {what}"
    try:
        listing = fetch(github, event)
    except BoundaryError as exc:
        out.notes.append(
            f"The pull request's {what} could not be fetched (error, quoted: "
            f"{quote_untrusted(str(exc), scrub=str)})."
        )
        out.omit(source, "fetch failed", "not read; the conversation block lacks them")
        return ()
    if listing.truncated:
        out.omit(
            source,
            f"page cap ({listing.pages_read} pages)",
            "further pages exist and were not read (GitHub lists oldest first, "
            "so the newest are the ones missing)",
        )
    return tuple(_parsed(source, listing.items, parse, event.head_sha, out))


def _parsed(
    source: str, entries: Sequence[Json], parse: Parse, head_sha: str, out: Collected
) -> list[Remark]:
    remarks = []
    for i, entry in enumerate(entries):
        try:
            remarks.append(parse(entry, head_sha))
        except BoundaryError as exc:
            out.omit(source, "malformed entry", f"entry {i} not shown: {exc}")
    return remarks


def build_conversation(
    pull: PullInfo,
    commits: Sequence[PrCommit],
    remarks: Sequence[Remark],
    head_sha: str,
    redactor: Redactor,
    budget: ConversationBudget,
) -> Conversation:
    """`pull.body` must have been parsed with `budget.body_chars`."""
    header = _header(pull)
    body = _body(pull.body)
    subjects = _commit_section(commits, head_sha, redactor, budget.commit_chars)
    room = budget.total_chars - sum(len(s) + 2 for s in (header, body, subjects.text))
    shown = _remark_section(remarks, redactor, budget, room)
    text = redactor(
        "\n\n".join((header, body, subjects.text, *shown.blocks)), budget.total_chars
    )
    omissions = (
        *_body_omission(pull.body, budget.body_chars),
        *subjects.omissions,
        *shown.omissions,
        *_total_omission(text, budget.total_chars),
    )
    return Conversation(
        text,
        omissions,
        len(shown.blocks),
        len(remarks),
        subjects.redactions + shown.redactions,
    )


@dataclass(frozen=True)
class _Section:
    blocks: tuple[str, ...]
    omissions: tuple[Omission, ...]
    redactions: int

    @property
    def text(self) -> str:
        return "\n".join(self.blocks)


def _header(pull: PullInfo) -> str:
    def names(values: tuple[str, ...]) -> str:
        return ", ".join(values) or "none"

    return "\n".join(
        (
            f"Title: {pull.title.text}",
            f"Author: {pull.author}",
            (
                f"Base branch: {pull.base_ref}; head branch: {pull.head_ref}; "
                f"draft: {'yes' if pull.draft else 'no'}"
            ),
            f"Labels: {names(pull.labels)}",
            (
                f"Requested reviewers: {names(pull.reviewers)}; "
                f"requested teams: {names(pull.teams)}"
            ),
        )
    )


def _quote_lines(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _body(body: RedactedText) -> str:
    return f"Body:\n{_quote_lines(body.text)}" if body.text else "Body: (empty)"


def _body_omission(body: RedactedText, cap: int) -> tuple[Omission, ...]:
    if body.truncated_from is None:
        return ()
    detail = f"kept {cap} of {body.truncated_from} characters"
    return (Omission("pull request body", f"{cap}-character cap", detail),)


def _newest_that_fit(sizes_newest_first: Sequence[int], room: int) -> int:
    """How many of the newest fit `room` together; the rest are older."""
    return sum(1 for total in accumulate(sizes_newest_first) if total <= room)


def _clip(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (f"{text[:limit]}...", True)


def _commit_section(
    commits: Sequence[PrCommit], head_sha: str, redactor: Redactor, budget: int
) -> _Section:
    redacted = [redactor(c.subject) for c in commits]
    clipped = [_clip(r.text, SUBJECT_CHARS) for r in redacted]
    lines = [
        f"- `{c.sha[:12]}`{' (reviewed head)' if c.sha == head_sha else ''} {subject}"
        for c, (subject, _) in zip(commits, clipped, strict=True)
    ]
    keep = _newest_that_fit([len(line) + 1 for line in reversed(lines)], budget)
    shown = lines[len(lines) - keep :]
    title = f"Commits ({len(commits)}, in the order GitHub lists them):"
    cut = sum(was_cut for _, was_cut in clipped[len(lines) - keep :])
    omissions = (
        *_count_omission(
            "pull request commits",
            f"{budget}-character budget for commit subjects",
            len(lines) - keep,
            f"of {len(lines)} oldest commit subject(s) not shown",
        ),
        *_count_omission(
            "pull request commits",
            f"{SUBJECT_CHARS}-character cap per subject",
            cut,
            "commit subject(s) cut",
        ),
    )
    return _Section(
        (title, *shown) if commits else ("Commits: none listed.",),
        omissions,
        sum(r.redaction_count for r in redacted[len(lines) - keep :]),
    )


def _count_omission(
    source: str, limit: str, count: int, what: str
) -> tuple[Omission, ...]:
    return (Omission(source, limit, f"{count} {what}"),) if count else ()


def _remark_section(
    remarks: Sequence[Remark],
    redactor: Redactor,
    budget: ConversationBudget,
    room: int,
) -> _Section:
    ordered = sorted(remarks, key=lambda r: (r.at, r.source_id))
    bodies = [redactor(r.body, budget.remark_chars) for r in ordered]
    blocks = [_remark(r, b) for r, b in zip(ordered, bodies, strict=True)]
    keep = _newest_that_fit([len(b) + 2 for b in reversed(blocks)], max(room, 0))
    dropped = ordered[: len(ordered) - keep]
    cut = [
        (r, b) for r, b in zip(ordered[len(dropped) :], bodies[len(dropped) :], strict=True)
        if b.truncated_from is not None
    ]  # fmt: skip
    return _Section(
        tuple(blocks[len(dropped) :]),
        (
            *_dropped_omission(dropped, len(ordered), budget.total_chars),
            *_cut_omission(cut, budget.remark_chars),
        ),
        sum(b.redaction_count for b in bodies[len(dropped) :]),
    )


def _remark(remark: Remark, body: RedactedText) -> str:
    text = _quote_lines(body.text) if body.text else "> (no text)"
    return (
        f"### {remark.source_id} by {quote_untrusted(remark.author, scrub=str)} at "
        f"{remark.at or 'an unreported time'}\n{remark.context}\n{text}"
    )


def _ids(remarks: Sequence[Remark]) -> str:
    shown = ", ".join(r.source_id for r in remarks[:MAX_LISTED_IDS])
    more = len(remarks) - MAX_LISTED_IDS
    return f"{shown} and {more} more" if more > 0 else shown


def _dropped_omission(
    dropped: Sequence[Remark], total: int, budget: int
) -> tuple[Omission, ...]:
    if not dropped:
        return ()
    detail = (
        f"{len(dropped)} of {total} oldest review(s) and comment(s) not shown, "
        f"oldest first: {_ids(dropped)}"
    )
    return (Omission(SOURCE, f"{budget}-character budget", detail),)


def _cut_omission(
    cut: Sequence[tuple[Remark, RedactedText]], cap: int
) -> tuple[Omission, ...]:
    if not cut:
        return ()
    listed = ", ".join(
        f"{r.source_id} (kept {cap} of {b.truncated_from} characters)"
        for r, b in cut[:MAX_LISTED_IDS]
    )
    more = len(cut) - MAX_LISTED_IDS
    detail = f"{len(cut)} cut: {listed}{f' and {more} more' if more > 0 else ''}"
    return (Omission(SOURCE, f"{cap}-character cap per review or comment", detail),)


def _total_omission(text: RedactedText, cap: int) -> tuple[Omission, ...]:
    if text.truncated_from is None:
        return ()
    detail = f"kept {cap} of {text.truncated_from} characters; the end was cut"
    return (Omission(SOURCE, f"{cap}-character total", detail),)
