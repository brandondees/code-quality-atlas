# SPDX-License-Identifier: MIT
"""Decide whether one GitHub webhook delivery becomes a review job. Pure.

The body is untrusted. A delivery is admitted only when the HMAC matches,
the event is a non-draft ``pull_request`` of ``opened``, ``synchronize``
or ``ready_for_review``, and the repository is on the allowlist. Anything
else is ignored. The dedupe key is the repository, the PR number and the
head SHA; this module only names that commit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from atlas_reviewer.domain import InvalidEventError, PrEvent

ACCEPTED_ACTIONS = frozenset({"opened", "synchronize", "ready_for_review"})

# The repo-narrowed admission surface (config slice S4 of the
# user-configuration plan): a repo may narrow when the service reviews
# it -- base-branch include/exclude, and which of the three accepted
# events to skip -- via lines in the ``REVIEW.md`` on its **default
# branch**, read from the default branch the payload names (one
# read-only lookup recovers it when the payload omits it), never the PR
# head or the PR's own base branch: in a same-repo or stacked PR the
# author controls both of those, and the default branch changes only
# through reviewed merges, so a PR cannot move its own admission. The
# include/exclude match still runs against the delivery's base branch --
# which the author chose -- but the patterns it matches come from the
# default branch. A repo may only narrow the operator's admission
# envelope (non-draft, those three events, the allowlisted repos), never
# widen it: every check below can only remove a review, and a value
# that is unusable falls back to the default -- no narrowing of that
# kind -- with a named note. "Only removes" is not "safe": an event
# skip is a coverage-reducing opt-out the repo owner chooses, and what
# it removes can land unreviewed (see `RepoAdmission`). The parse and
# the narrowing are local and minimal here so the shared config parser
# (slice S1) can absorb them later.
SIGNATURE_HEADER = "X-Hub-Signature-256"
EVENT_HEADER = "X-GitHub-Event"
_SHA256_PREFIX = "sha256="
_DIGEST_CHARS = 64


@dataclass(frozen=True)
class Admitted:
    event: PrEvent
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Ignored:
    """A delivery that will not be reviewed. ``reason`` is a fixed label,
    never text from the payload."""

    reason: str


def signature_matches(body: bytes, header: str | None, secret: str) -> bool:
    """True when ``header`` is the lowercase hex HMAC-SHA256 of ``body``.

    GitHub sends ``sha256=<hex>`` in ``X-Hub-Signature-256``. A missing
    header, a non-sha256 scheme, or a wrong digest is False. The compare
    is constant-time for a well-formed header; a header of any other
    length is rejected before that compare.
    """
    if not secret or not header or not header.startswith(_SHA256_PREFIX):
        return False
    presented = header[len(_SHA256_PREFIX) :]
    if len(presented) != _DIGEST_CHARS:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(presented, digest)


def parse_delivery(body: bytes) -> Any | None:
    """The JSON value, or None when the body is not a JSON object."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def admit(payload: Mapping[str, Any], allowlist: frozenset[str]) -> Admitted | Ignored:
    """Admit one already-authenticated ``pull_request`` payload."""
    action = payload.get("action")
    if action not in ACCEPTED_ACTIONS:
        return Ignored("action")
    pull = payload.get("pull_request")
    repository = payload.get("repository")
    if not isinstance(pull, dict) or not isinstance(repository, dict):
        return Ignored("shape")
    if pull.get("draft") is not False:
        return Ignored("draft")
    repo = repository.get("full_name")
    base = pull.get("base")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    base_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    if not isinstance(repo, str) or repo != base_name:
        return Ignored("repository")
    if repo not in allowlist:
        return Ignored("allowlist")
    head = pull.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    number = pull.get("number")
    if (
        isinstance(number, bool)
        or not isinstance(number, int)
        or not isinstance(sha, str)
    ):
        return Ignored("event")
    try:
        event = PrEvent(repo=repo, pr_number=number, head_sha=sha)
    except InvalidEventError:
        return Ignored("event")
    return Admitted(event, _updated_at(pull.get("updated_at")))


def _updated_at(raw: object) -> datetime | None:
    """The pull request's ``updated_at``. A missing or naive value is
    unknown, and an unknown time does not cancel a head already accepted."""
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


REVIEW_MD = "REVIEW.md"
# The read bound the file is fetched under, the same 64 KiB
# ``review_wide.py`` reads its merge-base copy under. Named locally so
# this slice stands alone; slice S1 absorbs both.
MAX_ADMISSION_BYTES = 64 * 1024

# The default-branch ``REVIEW.md`` lines a repo narrows admission with. Each
# value is a comma-separated list, one line per key, running to a ``#``
# comment or the end of the line -- the same value grammar the file's
# review-side settings use.
#
# Deliberately absent: any rule keyed on the pull request's labels or
# its head branch. The PR author controls both, so a skip rule matching
# them would let an author opt their own PR out of review -- the shape
# D81's answer on PR-level overrides rules out. Those filters are
# deferred with that question; only inputs the author cannot control
# narrow here.
_ADMISSION_KEYS = (
    "review_base_include",
    "review_base_exclude",
    "review_skip_events",
)
_KEY_LINES = {
    key: re.compile(rf"^{key}:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$")
    for key in _ADMISSION_KEYS
}

# This schema's own bounds, not GitHub's: a branch entry is at most 64
# characters, and a line carries at most 32 entries. One key can be
# named unusable at most once, so with three keys the notes never
# exceed three and need no cap of their own.
_MAX_ENTRY_CHARS = 64
_MAX_ENTRIES = 32
# A base-branch entry is a branch name, optionally with one trailing
# ``*`` that matches any branch with the prefix before it. Anything else
# a glob could do stays out of the grammar.
_BRANCH_PATTERN = re.compile(r"[A-Za-z0-9._/-]+\*?")

# The fixed skip reasons. Never text from the payload or the config.
SKIP_EVENT_REASON = "repo-skip-event"
BASE_BRANCH_REASON = "repo-base-branch"

# The default-branch ``REVIEW.md`` reader behind the narrowing: given
# the reviewed repo and the default branch to read (empty when the
# payload did not name one, in which case the reader recovers it with
# one read-only lookup), the file's bytes, or None when there is no
# file there. Any other failure raises; the caller treats a raise as a
# gap and stands on the operator's envelope.
AdmissionReader = Callable[[str, str], bytes | None]


@dataclass(frozen=True)
class RepoAdmission:
    """A repo's own narrowing of when it is reviewed, parsed from the
    ``REVIEW.md`` on its default branch.

    ``base_include`` is the base branches review is for, ``base_exclude``
    the ones it is not -- exclude wins; ``skip_events`` the accepted
    events the repo does not want a review on. ``skip_events`` is a
    coverage-reducing opt-out, not a safety feature: the coverage the
    skipped event alone would have provided is lost and can land
    unreviewed. Skipping ``synchronize`` means the reviews that do run
    see the state at ``opened`` -- or, for a PR opened as a draft, at
    ``ready_for_review`` -- and every push after that, up to and
    including what merges, lands unreviewed; skipping
    ``ready_for_review`` defers a draft-opened PR's first review to its
    first push after becoming ready, which covers the whole diff, so
    only a PR that becomes ready and merges with no further push is
    never reviewed; skipping ``opened`` defers a non-draft PR's first
    review to its first push (that review covers the whole diff, not
    just the delta), and a draft-opened PR's first review lands at the
    ready transition; skipping all three means the repository is never
    reviewed. The draft state and the
    head branch are never narrowable here: the PR author controls both,
    and a rule on either would let an author opt their own PR out of
    review. ``notes`` names the unusable lines, non-empty only when some
    line was seen and ignored, so "line present but unusable" can be
    told apart from "no line"."""

    base_include: tuple[str, ...] = ()
    base_exclude: tuple[str, ...] = ()
    skip_events: frozenset[str] = frozenset()
    notes: tuple[str, ...] = ()


NO_NARROWING = RepoAdmission()


def parse_repo_admission(text: str | None) -> RepoAdmission:
    """The narrowing lines of one ``REVIEW.md`` text.

    No lines, or no text at all, read as ``NO_NARROWING``, exactly as no
    file. A line that is present but not usable -- no value, an entry
    outside its key's grammar, more entries than the cap, or a key that
    appears twice -- falls back to that key's default, which narrows
    nothing, and is named in ``notes``. A key's default can only narrow
    less than what was written, so fail-open here cannot widen the
    operator's envelope. A leading byte-order mark is not prose: it is
    stripped before the first line is read, so a BOM'd first key line
    still parses or is still named, not silently swallowed."""
    if text is None:
        return NO_NARROWING
    values: dict[str, tuple[str, ...]] = {}
    unusable: set[str] = set()
    notes: list[str] = []
    for line in text.removeprefix("\ufeff").splitlines():
        found = _matching_key(line)
        if found is None:
            continue
        key, raw = found
        if key in values or key in unusable:
            if key not in unusable:
                unusable.add(key)
                del values[key]
                notes.append(_unusable_note(key))
            continue
        entries = _entries(key, raw)
        if entries is None:
            unusable.add(key)
            notes.append(_unusable_note(key))
            continue
        values[key] = entries
    return RepoAdmission(
        base_include=values.get("review_base_include", ()),
        base_exclude=values.get("review_base_exclude", ()),
        skip_events=frozenset(values.get("review_skip_events", ())),
        notes=tuple(notes),
    )


def _matching_key(line: str) -> tuple[str, str | None] | None:
    """The admission key the line sets and its raw value, or None for a
    line that sets none. Other lines -- prose, the file's review-side
    settings, an unknown key -- are not admission's to name; the shared
    config parser names those."""
    for key, line_re in _KEY_LINES.items():
        match = line_re.match(line)
        if match is not None:
            return key, match.group(1)
    return None


def _unusable_note(key: str) -> str:
    return (
        f"the reviewed repo's default-branch {REVIEW_MD} carries a {key}: line "
        "that is present but not usable; it is ignored and the default "
        f"(no {key.removeprefix('review_').replace('_', ' ')}) stands"
    )


def _entries(key: str, raw: str | None) -> tuple[str, ...] | None:
    """The comma-separated entries of one line's value, or None when the
    line is present but not usable: no value, more entries than the cap,
    or an entry outside its key's grammar."""
    if raw is None or not raw.strip():
        return None
    entries = tuple(entry.strip() for entry in raw.split(","))
    if not all(entries) or len(entries) > _MAX_ENTRIES:
        return None
    if not all(_entry_ok(key, entry) for entry in entries):
        return None
    return entries


def _entry_ok(key: str, entry: str) -> bool:
    if not entry or len(entry) > _MAX_ENTRY_CHARS or not entry.isprintable():
        return False
    if key == "review_skip_events":
        return entry in ACCEPTED_ACTIONS
    return _BRANCH_PATTERN.fullmatch(entry) is not None


def narrow(payload: Mapping[str, Any], admission: RepoAdmission) -> Ignored | None:
    """One delivery ``admit`` already accepted, narrowed by the repo's
    own admission. Returns the ``Ignored`` with its fixed reason, or
    None when the delivery stays admitted.

    The checks run in a fixed order -- skip event, base branch -- and
    the first hit wins. Every check can only remove a review. The
    patterns come from the default branch, which changes only through
    reviewed merges; what they match is the delivery's base branch,
    which the author chose but cannot rewrite -- the config source, not
    the match target, is what keeps the author from opting out. A base
    ref the shape does not carry matches nothing. Removing a review is
    the point and the risk: a skipped event's coverage is gone with it,
    and the skipped changes can land unreviewed."""
    action = payload.get("action")
    if isinstance(action, str) and action in admission.skip_events:
        return Ignored(SKIP_EVENT_REASON)
    ref = base_ref(payload)
    if admission.base_include and not _matches(ref, admission.base_include):
        return Ignored(BASE_BRANCH_REASON)
    if _matches(ref, admission.base_exclude):
        return Ignored(BASE_BRANCH_REASON)
    return None


def base_ref(payload: Mapping[str, Any]) -> str:
    """The pull request's base branch name from the payload, the empty
    string when the shape does not carry one. The match target for the
    include/exclude patterns, never the config's source ref."""
    pull = payload.get("pull_request")
    base = pull.get("base") if isinstance(pull, dict) else None
    ref = base.get("ref") if isinstance(base, dict) else None
    return ref if isinstance(ref, str) else ""


def default_branch(payload: Mapping[str, Any]) -> str:
    """The repository's default branch name from the payload, the empty
    string when the shape does not carry one -- the caller recovers an
    empty one with a read-only lookup, because the config is read from
    this branch, never from one the PR author controls."""
    repository = payload.get("repository")
    branch = repository.get("default_branch") if isinstance(repository, dict) else None
    return branch if isinstance(branch, str) and branch else ""


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    return any(_pattern_matches(pattern, name) for pattern in patterns)


def _pattern_matches(pattern: str, name: str) -> bool:
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return name == pattern
