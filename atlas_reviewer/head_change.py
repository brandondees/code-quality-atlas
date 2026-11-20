# SPDX-License-Identifier: MIT
"""The keep-or-cancel decision for a push that lands while a review runs
(#702, D79).

When a pull request's head moves while the service's review of the
previous head is still running, the service decides per push whether to
let that review finish or cancel it and restart on the new head. The
owner's direction (Brandon, Nov 14 and Nov 16, 2026): the default is to
let it finish and follow with a delta review; cancel-and-restart is the
narrower exception, taken only when the push changes code under review
and the running review is still early -- roughly under half its lenses
or budget spent -- so most of its remaining spend would be on stale code.

Three inputs drive the decision, each degraded safely:

- **What the push changes.** The parent fetches GitHub's comparison of
  the reviewed head and the new head, plus the pull request's base, and
  `classify_push` reduces it to one of three kinds: a merge of the base
  branch, a docs-or-tests-only change, or code. Every commit of the
  range whose second parent is not the newest base commit the range
  carries counts as code, so a merge of a feature branch is never read
  as a base merge. Where the evidence is missing -- a fetch that failed,
  a comparison whose commit list was cut, a merge whose base side cannot
  be identified -- the kind is `CODE`: the benign kinds are claimed only
  on evidence, never by default. An undecidable push therefore keeps the
  running review (the owner's default), and the gap is recorded.
- **What the review is still reading.** The review child records one
  telemetry event per settled lens in the run directory's events file
  (`progress` / `lens settled`), carrying the lens count, the spend so
  far and the paths the lenses without a clean run are still reading.
  `read_progress` reads those events back, and `last_run_progress` reads
  the same events scoped to the file's last run, with the attempt-scoped
  key the service's crash backfill deduplicates on (r2 review of #773).
  A push that touches no file
  the review is still reading is benign however late it lands.
- **How early the review is.** `decide` compares the fraction of lenses
  settled and the fraction of budget spent against the configured
  threshold. Missing progress reads as zero progress -- a review that
  has settled nothing is early -- which is the cancel direction, taken
  only once the push is known to change code.

The decision itself is a pure function over that data, so tests pin it
without any GitHub or model call. The service applies it where the
supersede used to be decided (`service.handle_delivery`) and records it
as telemetry, tagged with both heads, so the cost lines the worker logs
when the kept review settles can be read against it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from atlas_reviewer.diffs import DOCS, TESTS, risk_tier
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.funding import accepted_source_name
from atlas_reviewer.ports import BoundaryError, GitHubReader, Json

PROGRESS_PHASE = "progress"
# The progress record's field names, the wire contract between the
# review child's writer and the service's reader -- one home, so a
# renamed field cannot drift between the sides (round-2 review of
# #747, R2-F13).
FIELD_LENS = "lens"
FIELD_LENSES_DONE = "lenses_done"
FIELD_LENSES_TOTAL = "lenses_total"
FIELD_CALLS = "calls"
FIELD_COMMITTED_USD = "committed_usd"
FIELD_SETTLED_USD = "settled_usd"
FIELD_HELD_USD = "held_usd"
FIELD_RESERVATION_USD = "reservation_usd"
FIELD_READING = "reading"
FIELD_SOURCE = "source"
LENS_SETTLED_STEP = "lens settled"
PROGRESS_REVIEW_STEP = "review progress"

# The reading set one progress event carries is capped so a pull request
# with a very large diff cannot balloon the events file. Truncation reads
# as a shorter reading set, which classifies a push as benign more
# readily -- the owner's default direction -- never as a cancel.
READING_CHARS = 4_096

# The events file the child appends to is read back with a byte cap: it is
# our own telemetry, but it is a file on disk, and a rotated pair is all
# the progress there is.
PROGRESS_MAX_BYTES = 1_048_576

DEFAULT_CANCEL_FRACTION = 0.5
POLICY_KEEP = "keep"
POLICY_CANCEL = "cancel"
POLICIES = (POLICY_KEEP, POLICY_CANCEL)
POLICY_ENV = "ATLAS_HEAD_CHANGE_POLICY"
CANCEL_FRACTION_ENV = "ATLAS_HEAD_CHANGE_CANCEL_FRACTION"

DECISION_KEEP = "keep"
DECISION_CANCEL = "cancel"
"""The decision event's recorded outcomes. Named apart from
`POLICY_KEEP`/`POLICY_CANCEL` -- same values, different meanings -- so a
caller cannot pass one where the other is meant (round-2 review of
#747, R2-F14)."""


def head_change_policy(env: Mapping[str, str]) -> str:
    """The configured keep-or-cancel policy: `keep` when unset, `cancel`
    for the blanket supersede this policy replaced. An unknown value
    raises, so a typo stops the service instead of silently picking a
    policy (the mode setting's precedent)."""
    raw = env.get(POLICY_ENV, "")
    if not raw:
        return POLICY_KEEP
    if raw not in POLICIES:
        raise ValueError(
            f"{POLICY_ENV} must be {POLICY_KEEP} or {POLICY_CANCEL}, not {raw!r}"
        )
    return raw


def cancel_fraction(env: Mapping[str, str]) -> float:
    """The "early" threshold the cancel branch compares the lens and
    spend fractions against: 0.0 to 1.0, 0.5 when unset -- roughly under
    half its lenses or budget spent, as the issue phrased it."""
    raw = env.get(CANCEL_FRACTION_ENV, "")
    if not raw:
        return DEFAULT_CANCEL_FRACTION
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"{CANCEL_FRACTION_ENV} must be a number between 0.0 and 1.0, not {raw!r}"
        ) from None
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(
            f"{CANCEL_FRACTION_ENV} must be a number between 0.0 and 1.0, not {raw!r}"
        )
    return value


class PushKind(StrEnum):
    """What a push between the reviewed head and the new head changes.

    The two benign kinds are claimed only on evidence: `MERGE_ONLY` when
    every commit of the range merges the base branch, `DOCS_TESTS` when
    no commit of the range changes anything but docs and tests. Anything
    else -- including any range the evidence cannot rule on -- is `CODE`,
    the kind that makes a running review cancellable when it is early."""

    MERGE_ONLY = "merge of the base branch"
    DOCS_TESTS = "docs or tests only"
    CODE = "code"


@dataclass(frozen=True)
class PushClass:
    """The range's kind and its changed paths, as the comparison listed
    them. `paths` is the aggregate of the range -- a base merge's own
    paths included -- because the overlap check asks whether the push
    touches a file the review is still reading, and a base merge does
    change the tree the review reads."""

    kind: PushKind
    paths: tuple[str, ...]


def classify_push(
    commits: Sequence[Mapping[str, object]],
    paths: Sequence[str],
    *,
    base_tip: str | None,
    truncated: bool = False,
) -> PushClass:
    """The push's kind from the range's commits and changed paths.

    `commits` is GitHub's comparison listing, each entry carrying
    `sha` and `parents`. A merge commit (`parents` longer than one) is a
    base merge only when `base_tip` is known and its second parent is
    that tip -- `merge_base(base, new)`, the newest base commit the new
    head carries. Two base merges in one range misclassify the older one
    as code: the conservative direction, a cancel-eligible push. A cut
    commit list is unprovable either way and reads as code.

    An empty, untruncated range changes nothing the review reads and is
    benign by the same rule as a merge-only push."""
    if truncated:
        return PushClass(PushKind.CODE, tuple(paths))
    if not commits:
        return PushClass(PushKind.MERGE_ONLY, tuple(paths))
    if all(_is_base_merge(commit, base_tip) for commit in commits):
        return PushClass(PushKind.MERGE_ONLY, tuple(paths))
    if all(risk_tier(path) in (TESTS, DOCS) for path in paths):
        return PushClass(PushKind.DOCS_TESTS, tuple(paths))
    return PushClass(PushKind.CODE, tuple(paths))


def _is_base_merge(commit: Mapping[str, object], base_tip: str | None) -> bool:
    """True only for a merge commit whose second parent is `base_tip`.

    A regular commit (one parent) is never a base merge: it is a commit
    of the pull request itself, and its paths decide the kind. A merge
    whose base side cannot be identified -- `base_tip` unknown -- is not
    a provable base merge either, so it reads as code."""
    parents = commit.get("parents")
    if not isinstance(parents, list) or len(parents) <= 1:
        return False
    if base_tip is None:
        return False
    second = parents[1]
    sha = second.get("sha") if isinstance(second, Mapping) else None
    return isinstance(sha, str) and sha == base_tip


@dataclass(frozen=True)
class Progress:
    """The running review's progress, read back from its events file.

    Every field defaults to the value that reads as "nothing settled
    yet", because a review whose events were lost -- or that has settled
    nothing -- is early."""

    lenses_done: int = 0
    lenses_total: int = 0
    calls: int = 0
    committed_usd: Decimal = Decimal(0)
    settled_usd: Decimal = Decimal(0)
    reservation_usd: Decimal = Decimal(0)
    reading: frozenset[str] = frozenset()
    held_usd: Decimal = Decimal(0)
    """Reservations kept because the request was written and never
    answered (D93). A served call with no usage is not in this figure.
    A progress record that omits the field reads as held $0, so its
    settled figure is the bill."""
    source: str = ""
    """The operator funding source the review was pinned to (D94).
    Empty when the record names none, including every record from
    before the field existed."""

    @property
    def billed_usd(self) -> Decimal:
        """Known bills: settled spend minus holds. A served call with no
        usage is in `settled_usd` and not in `held_usd`, so it counts."""
        amount = self.settled_usd - self.held_usd
        return amount if amount > 0 else Decimal(0)


def read_progress(*paths: Path, max_bytes: int = PROGRESS_MAX_BYTES) -> Progress | None:
    """The newest progress the run's events files hold, or None when none
    of them holds a progress event.

    The events files are the child's own JSONL telemetry. A line that
    does not parse, or a read that fails, contributes nothing rather
    than failing the decision: a lost read reads as zero settled lenses
    and zero spend -- early on both measures -- which cancels, the
    degradation D79 records (`test_missing_progress_reads_as_early`);
    the telemetry cannot distinguish a record not yet written from a
    read that failed, so both surface as the zero reading. Rotation
    puts the older events in `<file>.1`; the older file is read first so
    a lens settled before a rotation is still counted. The count of
    settled lenses is the record's own `lenses_done` field -- the one
    source of truth for that number, already deduplicated against
    continuations by the writer -- not a recount over lens names."""
    records: list[Mapping[str, object]] = []
    for path in paths:
        text = _tail(path, max_bytes)
        if text is None:
            continue
        for line in text.splitlines():
            fields = _progress_fields(line)
            if fields is None:
                continue
            records.append(fields)
    if not records:
        return None
    return _merge_progress(records)


def _merge_progress(records: list[Mapping[str, object]]) -> Progress:
    """The field-for-field newest-wins merge every progress reader
    performs: each record carries the cumulative fields, and a field a
    record omits or carries unusably keeps the previous record's value."""
    done = 0
    total = 0
    calls = 0
    committed = Decimal(0)
    settled = Decimal(0)
    reservation = Decimal(0)
    reading: frozenset[str] = frozenset()
    held = Decimal(0)
    source = ""
    for fields in records:
        done = _int(fields.get(FIELD_LENSES_DONE), done)
        total = _int(fields.get(FIELD_LENSES_TOTAL), total)
        calls = _int(fields.get(FIELD_CALLS), calls)
        committed = _decimal(fields.get(FIELD_COMMITTED_USD), committed)
        settled = _decimal(fields.get(FIELD_SETTLED_USD), settled)
        reservation = _decimal(fields.get(FIELD_RESERVATION_USD), reservation)
        reading = _reading(fields, reading)
        held = _decimal(fields.get(FIELD_HELD_USD), held)
        source = _funding_source(fields, source)
    return Progress(
        done, total, calls, committed, settled, reservation, reading, held, source
    )


def _funding_source(fields: Mapping[str, object], previous: str) -> str:
    """The source name a progress record carries.

    A record that omits the field keeps the previous name. A blank
    field clears it. A value that is not a source name keeps the
    previous one, so a corrupt line cannot rename the review."""
    if FIELD_SOURCE not in fields:
        return previous
    parsed = accepted_source_name(fields[FIELD_SOURCE])
    if parsed is None:
        return previous
    return parsed


def _is_run_start(line: str) -> bool:
    """True when one events line is a run's own first event: `seq` is the
    sink's per-run counter and restarts at 1 every run, so the last
    ``seq: 1`` line delimits where the events file's last run begins --
    what makes an append-only file's runs tellable apart."""
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return False
    seq = data.get("seq") if isinstance(data, dict) else None
    return isinstance(seq, int) and not isinstance(seq, bool) and seq == 1


def last_run_progress(
    *paths: Path, max_bytes: int = PROGRESS_MAX_BYTES
) -> tuple[Progress, str] | None:
    """The progress figure of the events files' **last run**, with the
    attempt-scoped key that identifies it, or None when that run has no
    progress figure of its own.

    The events file is append-only across the runs one head's directory
    accumulates (the telemetry sink opens `O_APPEND` and nothing clears
    the directory), and `seq` restarts per run, so the last ``seq: 1``
    line delimits the last run's span. The figure is merged from the
    progress records inside that span only -- the same field-for-field
    merge `read_progress` performs, over the same bounded tail -- so a
    record left by an **earlier** run is never returned as this run's
    figure: a run that died before its first progress record has no
    figure, and the caller records nothing rather than re-counting the
    stale tail (r2 review of #773, M-R2-1). The key hashes the run's
    start line with the span's progress records; appends never modify
    existing lines, so the pair is stable for one dead run forever, and
    distinct across runs -- the start line's monotonic `start_s` differs
    per run -- which is what makes a once-per-attempt backfill
    idempotent in the ledger itself."""
    texts: list[str] = []
    for path in paths:
        text = _tail(path, max_bytes)
        if text is not None:
            texts.append(text)
    lines = [line for text in texts for line in text.splitlines() if line.strip()]
    starts = [i for i, line in enumerate(lines) if _is_run_start(line)]
    if not starts:
        return None
    span = lines[starts[-1] :]
    records = [
        fields for line in span if (fields := _progress_fields(line)) is not None
    ]
    if not records:
        return None
    evidence = "\n".join(
        (span[0], *(line for line in span if _progress_fields(line) is not None))
    )
    hasher = hashlib.sha256()
    hasher.update(evidence.encode("utf-8"))
    return _merge_progress(records), hasher.hexdigest()


def cap_reading(reading: Sequence[str]) -> str:
    """The reading set as one progress record carries it: a JSON array
    (paths can contain spaces, which a space-join mangled into
    fragments -- round-2 review of #747, R2-F12), capped at
    `READING_CHARS`, so a pull request with a very large diff cannot
    balloon the events file. A truncation can cut the JSON mid-escape;
    the reader then falls back to the legacy space split, whose
    fragments match no pushed path -- the same shorter-reading-set
    direction, which keeps a push rather than cancels, never the
    reverse."""
    text = json.dumps(sorted(reading))
    if len(text) > READING_CHARS:
        return text[:READING_CHARS]
    return text


def _tail(path: Path, max_bytes: int) -> str | None:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read(max_bytes)
    except OSError:
        return None
    return data.decode("utf-8", errors="replace")


def _progress_fields(line: str) -> Mapping[str, object] | None:
    if not line.strip():
        return None
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    # Both progress steps carry the same cumulative fields; the step only
    # says what moved, and the reader takes the newest record's values.
    # The sink writes the fields at the top level of the line
    # (`telemetry.Event.as_json`), never nested.
    if data.get("phase") != PROGRESS_PHASE:
        return None
    return data


def _int(raw: object, current: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return current
    return raw


def _decimal(raw: object, current: Decimal) -> Decimal:
    if not isinstance(raw, str):
        return current
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return current
    return value if value >= 0 else current


def _reading(fields: Mapping[str, object], current: frozenset[str]) -> frozenset[str]:
    """The newest record's reading set: a JSON array (the writer's own
    form), or the legacy space-joined form of a record written before
    the encoding -- and of a cap-truncated value, whose fragments match
    no pushed path and so keep a push, never cancel one. An absent
    field leaves the previous set; an empty one is a real value -- the
    review reported nothing left reading -- and resets."""
    raw = fields.get(FIELD_READING)
    if not isinstance(raw, str):
        return current
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        decoded = None
    if isinstance(decoded, list) and all(isinstance(item, str) for item in decoded):
        return frozenset(item for item in decoded if item)
    return frozenset(part for part in raw.split(" ") if part)


@dataclass(frozen=True)
class Decision:
    """The keep-or-cancel decision, with the numbers it was made from,
    so telemetry can show why. `reason` is controller text: it names the
    kind and the fractions, and carries no PR-written content."""

    cancel: bool
    reason: str
    lens_fraction: float
    spend_fraction: float


def decide(
    push: PushClass | None,
    progress: Progress | None,
    threshold: float,
    *,
    posting: bool = False,
) -> Decision:
    """Keep the running review, or cancel it for the new head.

    The order is the owner's: a benign push -- a merge of the base
    branch, docs and tests only, or no overlap with the files the review
    is still reading -- keeps the review however late it lands. A code
    push cancels a review that is still early, and early means under
    `threshold` on BOTH measures -- the fraction of lenses settled and
    the fraction of budget spent -- because finishing is the default and
    cancelling the narrow exception: the spend measure alone cannot tell
    an early review from a cheap one (a review whose every lens has
    settled can sit far under its derived worst-case reservation), so
    either measure alone would cancel completed work the issue exists to
    protect (round-1 review of #747, F1). Past the threshold on either
    measure, the review is kept and the delta review follows it. A
    review that is already posting is never cancelled: its spend is
    fully spent and its comment is about to go out. A push that could
    not be classified (`push` None -- a fetch that failed, no
    credentials to fetch with) keeps the review too: the benign kinds
    are claimed on evidence, and so is the cancel branch, and with no
    evidence either way the owner's default stands. The fractions are
    still computed from whatever progress exists, so the recorded
    decision shows what was known when it was made."""
    lens_fraction = _fraction(
        progress.lenses_done if progress else 0,
        progress.lenses_total if progress else 0,
    )
    spend_fraction = _spend_fraction(progress)
    if posting:
        return Decision(False, "the review was already posting its comment", 1.0, 1.0)
    if push is None:
        return Decision(
            False,
            "the push could not be classified; the review was kept and "
            "the follow-up will review the new head",
            lens_fraction,
            spend_fraction,
        )
    reading = progress.reading if progress else frozenset()
    if push.kind is PushKind.MERGE_ONLY:
        return Decision(
            False, f"the push was a {push.kind.value}", lens_fraction, spend_fraction
        )
    if push.kind is PushKind.DOCS_TESTS:
        return Decision(
            False, f"the push was {push.kind.value}", lens_fraction, spend_fraction
        )
    if reading and not (set(push.paths) & reading):
        return Decision(
            False,
            "the push touched no file the review was still reading",
            lens_fraction,
            spend_fraction,
        )
    early = lens_fraction < threshold and spend_fraction < threshold
    if early:
        return Decision(
            True,
            f"the review was early on both measures: {lens_fraction:.0%} of "
            f"its lenses and {spend_fraction:.0%} of its budget spent, each "
            f"under the {threshold:.0%} threshold, and the push changed code "
            "under review",
            lens_fraction,
            spend_fraction,
        )
    return Decision(
        False,
        "the review was past the early threshold; a delta review follows it",
        lens_fraction,
        spend_fraction,
    )


def _fraction(done: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return done / total


def _spend_fraction(progress: Progress | None) -> float:
    if progress is None or progress.reservation_usd <= 0:
        return 0.0
    return float(min(progress.settled_usd / progress.reservation_usd, Decimal(1)))


# ------------------------------------------------------------- the fetch


def classify_delivery(
    github: GitHubReader, running: PrEvent, new_event: PrEvent
) -> PushClass:
    """Fetch and classify the range between the running review's head and
    the new one, from live GitHub reads.

    The argument order matches the classifier protocol it adapts --
    `(running, new)` both here and in `PushClassifier` -- so a direct
    caller cannot transpose two same-typed heads (round-3 review of
    #747, R3-F8).

    Three reads: the pull request (for its base ref), the comparison of
    the two heads (commits and changed paths), and the comparison of the
    base ref against the new head (its merge base is the newest base
    commit the new head carries, which is what identifies a base merge's
    second parent). Any boundary failure -- a 404, a rate limit, a
    transport error -- propagates: the caller keeps the running review
    and records the gap, it does not guess a kind.

    A comparison whose merge base is not the reviewed head means the
    histories diverged -- a force-push, most likely -- and no rule about
    commits "between" the heads holds; that reads as code."""
    pull = github.get_pull(running.repo, running.pr_number)
    base = pull.get("base") if isinstance(pull, dict) else None
    ref = base.get("ref") if isinstance(base, dict) else None
    if not isinstance(ref, str) or not ref:
        raise BoundaryError("the pull request has no base ref")
    compare = github.get_compare(running.repo, running.head_sha, new_event.head_sha)
    commits, truncated = _commits(compare)
    paths, files_complete = _paths(compare)
    if _diverged(compare, running.head_sha):
        # No rule about commits "between" the heads holds once the
        # histories diverge, and the base-side read would classify
        # nothing useful; the code kind is the honest answer.
        return PushClass(PushKind.CODE, paths)
    base_tip = _merge_base(github.get_compare(running.repo, ref, new_event.head_sha))
    return classify_push(
        commits, paths, base_tip=base_tip, truncated=truncated or not files_complete
    )


def _commits(compare: Json) -> tuple[tuple[Mapping[str, object], ...], bool]:
    commits = compare.get("commits")
    if not isinstance(commits, list):
        raise BoundaryError("the comparison has no commits array")
    total = compare.get("total_commits")
    truncated = (
        not isinstance(total, bool) and isinstance(total, int) and total > len(commits)
    )
    shaped = [commit for commit in commits if isinstance(commit, dict)]
    if len(shaped) != len(commits):
        # A commit entry GitHub's own shape does not hold is unprovable.
        return tuple(shaped), True
    return tuple(shaped), truncated


_COMPARE_FILES_CAP = 300
"""GitHub's comparison response caps its `files` array; a list at the cap
may be cut, and a cut list cannot prove what the range's commits
changed -- a docs-or-tests kind claimed from a partial list is a benign
kind claimed without full evidence."""


def _paths(compare: Json) -> tuple[tuple[str, ...], bool]:
    """The comparison's changed paths, and whether the list is complete.

    A missing or non-array `files` raises: a comparison reply without a
    files array is not a reply this reader can trust, and an absent array
    read as empty would claim docs-or-tests vacuously -- a benign kind
    with no path evidence, the shape the classification forbids (round-1
    review of #747, F17). An entry that is not an object, or that names
    no path, makes the list incomplete; so does a list at the cap."""
    files = compare.get("files")
    if not isinstance(files, list):
        raise BoundaryError("the comparison has no files array")
    paths: list[str] = []
    complete = len(files) < _COMPARE_FILES_CAP
    for item in files:
        name = item.get("filename") if isinstance(item, dict) else None
        if isinstance(name, str) and name:
            paths.append(name)
        else:
            complete = False
    return tuple(paths), complete


def _diverged(compare: Json, running_sha: str) -> bool:
    """True unless the comparison proves its own base: a merge base that
    is missing, malformed, or not the reviewed head all read as diverged
    -- a force-push or a garbled reply must not have its commit list
    trusted as the range's, the same fail-closed rule every other
    unusable shape in this module follows (round-2 review of #747,
    R2-F5). Mutant: the missing-sha case read as not-diverged, which
    would classify a garbled reply's commits as the range's."""
    base = compare.get("merge_base_commit")
    sha = base.get("sha") if isinstance(base, dict) else None
    return not (isinstance(sha, str) and sha == running_sha)


def _merge_base(compare: Json) -> str | None:
    base = compare.get("merge_base_commit")
    sha = base.get("sha") if isinstance(base, dict) else None
    return sha if isinstance(sha, str) and sha else None
