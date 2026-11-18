# SPDX-License-Identifier: MIT
"""The review queue: one job per repository, PR and head SHA.

A second delivery of the same commit is a no-op. A head supersedes an
in-flight review only when its ``updated_at`` is later than the head this
PR already accepted. An older redelivery, or a SHA already superseded,
does not cancel the newer review. The file is the dedupe set:
it is rewritten with ``os.replace`` and an fsync, mode 0600, so a crash
does not drop a commit that was already accepted. A job left ``running``
when the process stopped is loaded back as ``queued`` so that one review
is tried again. A job left ``posting`` is loaded as ``post_pending``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from atlas_reviewer.domain import InvalidEventError, PrEvent
from atlas_reviewer.ledger import make_private_dirs


class Enqueue(StrEnum):
    QUEUED = "queued"
    DUPLICATE = "duplicate"
    STALE = "stale"
    FULL = "full"
    KEPT = "kept"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUPERSEDED = "superseded"
    DONE = "done"
    FAILED = "failed"
    POST_PENDING = "post_pending"
    POSTING = "posting"


_ACTIVE = frozenset(
    {JobState.QUEUED, JobState.RUNNING, JobState.POST_PENDING, JobState.POSTING}
)
_RELOAD = {
    JobState.RUNNING: JobState.QUEUED,
    JobState.POSTING: JobState.POST_PENDING,
}


class QueueError(ValueError):
    """The queue file cannot be used. Starting would forget a dedupe key."""


@dataclass
class Job:
    event: PrEvent
    state: JobState
    superseded: bool = False
    attempts: int = 0
    retry_at: float = 0.0
    cancel: threading.Event = field(default_factory=threading.Event)

    def key(self) -> tuple[str, int, str]:
        return (self.event.repo, self.event.pr_number, self.event.head_sha)

    def as_dict(self) -> dict[str, object]:
        return {
            "repo": self.event.repo,
            "pr": self.event.pr_number,
            "sha": self.event.head_sha,
            "state": self.state.value,
            "superseded": self.superseded,
            "attempts": self.attempts,
            "retry_at": self.retry_at,
            "delta_from": self.event.delta_from,
        }


# ``MAX_REMEMBERED`` is a hard cap on jobs that are still in progress
# (``queued``, ``running``, ``post_pending``, ``posting``). When that many
# belong to pull requests that are not already in the queue, ``enqueue``
# returns ``FULL`` and the HTTP handler answers 503, so the file cannot
# grow by accepting more active work. A newer head of a pull request that
# already has an active job takes that slot. Replacing a job that is still
# ``running`` or ``posting`` can leave the count at the cap plus those
# superseded jobs, and that extra is at most the worker concurrency.
# Terminal jobs are trimmed to make room. A ``FAILED`` job is
# not remembered as a duplicate: GitHub does not redeliver a delivery we
# already acknowledged, so the only way to review that commit again is to
# accept the same SHA when it is delivered again.
#
# ``MAX_SEEN`` is a soft cap. It drops the oldest key that is not a PR's
# current head, and it keeps every current head, so the set can grow by
# one key per pull request past 20,000. Dropping a current head would let
# a replay of that commit start a second review. A key is about 80 bytes.
# At 30,000 keys one enqueue holds the queue lock for about 338 ms while
# it rewrites the file, which is why the cap exists and why the rewrite
# stays on this path instead of keeping an unbounded history. A dropped
# historical key can be reviewed again when its ``updated_at`` is later
# than that PR's current head. A review that was already posted still will
# not be posted twice, because the GitHub marker is checked before a create.
# Neither cap is a review budget. ``_heads`` keeps one record per pull
# request that has been queued. It is not trimmed with ``MAX_SEEN``, so it
# grows by one entry per pull request rather than with every delivery.
MAX_REMEMBERED = 2_000
MAX_SEEN = 20_000
# After a failed queue save the worker waits this long before claiming
# again. Without it a full disk turns the rollback into a tight loop.
_SAVE_BACKOFF_S = 1.0


class Board:
    def __init__(
        self,
        path: Path,
        *,
        max_remembered: int = MAX_REMEMBERED,
        max_seen: int = MAX_SEEN,
    ) -> None:
        self._path = path
        self._cv = threading.Condition()
        self._jobs: list[Job] = []
        self._seen_order: list[tuple[str, int, str]] = []
        self._seen: set[tuple[str, int, str]] = set()
        self._heads: dict[tuple[str, int], tuple[str, datetime | None]] = {}
        # A head the keep side of the keep-or-cancel decision (#702) held
        # back while an earlier review kept running: `(repo, pr) ->
        # (sha, updated_at)`. It is queued for review when that review
        # settles, so it never holds an active slot while it waits.
        self._pending: dict[tuple[str, int], tuple[str, datetime | None]] = {}
        self._max_remembered = max_remembered
        self._max_seen = max_seen
        self._saves_ok = True
        self._save_retry_at = 0.0
        if path.exists():
            self._jobs, seen, self._heads, self._pending = _load(path)
            for key in seen:
                self._remember(key)

    def enqueue(
        self,
        event: PrEvent,
        *,
        at: datetime | None = None,
        superseded: list[Job] | None = None,
        delta_from: str = "",
    ) -> Enqueue:
        """``at`` is the pull request's ``updated_at`` on this delivery.
        A different head cancels the current review only when ``at`` is
        later than the head already accepted for that PR.

        ``delta_from`` names the head the new job reviews the delta
        against (#702): the previously reviewed head, when the caller
        queues a follow-up review for a head that was held back. A
        queued job of the same pull request that this enqueue supersedes
        passes its own ``delta_from`` on when the caller names none, so a
        push that lands while a follow-up review is queued does not
        detach the follow-up from the head it builds on."""
        with self._cv:
            key = (event.repo, event.pr_number, event.head_sha)
            if key in self._seen:
                return Enqueue.DUPLICATE
            if (
                self._pending.get((event.repo, event.pr_number), ("",))[0]
                == event.head_sha
            ):
                # The head a kept review is holding back is already
                # accepted as this pull request's follow-up; a
                # redelivery of it adds nothing.
                return Enqueue.DUPLICATE
            failed_job: Job | None = None
            for job in self._jobs:
                if job.key() != key:
                    continue
                if job.state is JobState.SUPERSEDED or job.superseded:
                    return Enqueue.STALE
                if job.state is JobState.FAILED:
                    failed_job = job
                    break
                return Enqueue.DUPLICATE
            if (
                failed_job is None
                and not self._retry_of_failed_head(event, at)
                and not self._newer_than_current(event, at)
            ):
                return Enqueue.STALE
            active = sum(1 for job in self._jobs if job.state in _ACTIVE)
            replaces = any(
                job.event.repo == event.repo
                and job.event.pr_number == event.pr_number
                and job.state in _ACTIVE
                for job in self._jobs
            )
            # A newer head of a PR already in the queue takes that slot.
            # Refusing it would leave the old review running. A job that
            # is still ``running`` or ``posting`` stays active until it
            # notices the cancel, so the count can reach
            # ``max_remembered`` plus those superseded jobs. That extra
            # is at most the worker concurrency.
            if active >= self._max_remembered and not replaces:
                return Enqueue.FULL
            inherited = delta_from or self._queued_delta_from(event)
            settled = self._install(event, at, failed_job, inherited)
            if superseded is not None:
                superseded.extend(settled)
            self._cv.notify()
            return Enqueue.QUEUED

    def _queued_delta_from(self, event: PrEvent) -> str:
        """The ``delta_from`` of the first active queued or pending job of
        this pull request, or "" when there is none."""
        for job in self._jobs:
            if (
                job.event.repo == event.repo
                and job.event.pr_number == event.pr_number
                and job.state in {JobState.QUEUED, JobState.POST_PENDING}
                and job.event.delta_from
            ):
                return job.event.delta_from
        return ""

    def keep_head(
        self,
        event: PrEvent,
        *,
        at: datetime | None = None,
        superseded: list[Job] | None = None,
    ) -> Enqueue:
        """Hold a pushed head back while an earlier review of this pull
        request keeps running (#702, D79).

        The head is recorded as the pull request's pending follow-up: it
        is queued for review -- as a delta review of the commits between
        the finished review's head and this one, when that review
        settles successfully -- when the running review settles. The
        running review itself is not touched, so it posts its comment at
        the head it reviewed. A queued or post-pending job of the same
        pull request is still superseded here, exactly as ``enqueue``
        would: a review that has not started is cancelled rather than
        kept.

        A redelivery of the pending head is a duplicate, and an older
        delivery is stale, against the pending head as against an
        installed one. When no running or posting review remains by the
        time this runs -- the decision raced a review that settled first
        -- the head is installed as an ordinary review, without a delta
        base: the follow-up then reviews the new head in full, which is
        correct, only not delta-shaped."""
        with self._cv:
            key = (event.repo, event.pr_number, event.head_sha)
            if key in self._seen:
                return Enqueue.DUPLICATE
            for job in self._jobs:
                if job.key() == key:
                    return (
                        Enqueue.STALE
                        if job.state is JobState.SUPERSEDED or job.superseded
                        else Enqueue.DUPLICATE
                    )
            if not self._newer_than_current(event, at):
                return Enqueue.STALE
            if not any(
                job.event.repo == event.repo
                and job.event.pr_number == event.pr_number
                and job.state in {JobState.RUNNING, JobState.POSTING}
                and not job.superseded
                for job in self._jobs
            ):
                return Enqueue.QUEUED
            previous_head = self._heads.get((event.repo, event.pr_number))
            previous_pending = self._pending.get((event.repo, event.pr_number))
            touched: list[tuple[Job, JobState, bool, bool]] = []
            settled: list[Job] = []
            for job in self._jobs:
                if (
                    job.event.repo != event.repo
                    or job.event.pr_number != event.pr_number
                ):
                    continue
                if job.state not in {JobState.QUEUED, JobState.POST_PENDING}:
                    continue
                touched.append((job, job.state, job.superseded, job.cancel.is_set()))
                job.superseded = True
                job.cancel.set()
                settled.append(job)
                job.state = JobState.SUPERSEDED
            self._pending[(event.repo, event.pr_number)] = (event.head_sha, at)
            self._heads[(event.repo, event.pr_number)] = (event.head_sha, at)
            try:
                self._save()
            except Exception:
                if previous_pending is None:
                    self._pending.pop((event.repo, event.pr_number), None)
                else:
                    self._pending[(event.repo, event.pr_number)] = previous_pending
                if previous_head is None:
                    self._heads.pop((event.repo, event.pr_number), None)
                else:
                    self._heads[(event.repo, event.pr_number)] = previous_head
                for job, state, was_superseded, cancelled in touched:
                    job.state = state
                    job.superseded = was_superseded
                    if cancelled:
                        job.cancel.set()
                    else:
                        job.cancel.clear()
                raise
            if superseded is not None:
                superseded.extend(settled)
            self._cv.notify()
            return Enqueue.KEPT

    def take_pending(self, finished: PrEvent, *, succeeded: bool) -> PrEvent | None:
        """Queue the pull request's pending head, if any, for review.

        Called when a review settles successfully or fails: a kept head
        waits for exactly that. A settled success queues the pending
        head as a delta review building on the head that just finished;
        a failure queues it as an ordinary review, because the failed
        review posted nothing for the delta to build on. The pending
        head is installed only while it is still the pull request's
        current head -- a later push that was itself held back replaced
        it in ``_pending`` and ``_heads``, and the newest one wins. None
        of this supersedes anything: the finished job is terminal, so
        the pending head takes its slot without a supersede."""
        with self._cv:
            head_key = (finished.repo, finished.pr_number)
            pending = self._pending.get(head_key)
            if pending is None:
                return None
            sha, at = pending
            current = self._heads.get(head_key)
            if current is None or current[0] != sha:
                # A newer head replaced this one while the review ran.
                self._pending.pop(head_key, None)
                return None
            key = (finished.repo, finished.pr_number, sha)
            if key in self._seen or any(job.key() == key for job in self._jobs):
                self._pending.pop(head_key, None)
                return None
            event = PrEvent(
                finished.repo,
                finished.pr_number,
                sha,
                delta_from=finished.head_sha if succeeded else "",
            )
            previous_head = self._heads.get(head_key)
            self._pending.pop(head_key, None)
            self._jobs.append(Job(event, JobState.QUEUED))
            try:
                self._save()
            except Exception:
                self._jobs.pop()
                self._pending[head_key] = pending
                self._heads[head_key] = previous_head or (sha, at)
                raise
            self._cv.notify()
            return event

    def _install(
        self,
        event: PrEvent,
        at: datetime | None,
        failed_job: Job | None,
        delta_from: str = "",
    ) -> tuple[Job, ...]:
        """Swap in ``event`` and save. A failed save puts the memory back."""
        head_key = (event.repo, event.pr_number)
        previous_head = self._heads.get(head_key)
        if failed_job is not None:
            self._jobs.remove(failed_job)
        touched: list[tuple[Job, JobState, bool, bool]] = []
        # A queued or pending job is stored SUPERSEDED here and never
        # returns to the worker, so the caller has to remove its run
        # directory. A running or posting job is only flagged; the
        # worker settles that one.
        settled: list[Job] = []
        for job in self._jobs:
            if job.event.repo != event.repo or job.event.pr_number != event.pr_number:
                continue
            if job.state not in _ACTIVE:
                continue
            touched.append((job, job.state, job.superseded, job.cancel.is_set()))
            job.superseded = True
            job.cancel.set()
            if job.state in {JobState.QUEUED, JobState.POST_PENDING}:
                settled.append(job)
                job.state = JobState.SUPERSEDED
        installed = replace(event, delta_from=delta_from or event.delta_from)
        self._jobs.append(Job(installed, JobState.QUEUED))
        self._heads[head_key] = (event.head_sha, at)
        try:
            self._save()
        except Exception:
            self._jobs.pop()
            if failed_job is not None:
                self._jobs.append(failed_job)
            for job, state, superseded, cancelled in touched:
                job.state = state
                job.superseded = superseded
                if cancelled:
                    job.cancel.set()
                else:
                    job.cancel.clear()
            if previous_head is None:
                self._heads.pop(head_key, None)
            else:
                self._heads[head_key] = previous_head
            raise
        return tuple(settled)

    def _retry_of_failed_head(self, event: PrEvent, at: datetime | None) -> bool:
        """The current head's only record was a failure that has already
        been trimmed. A redelivery of that same SHA is a new attempt.
        ``at`` is unused: the delivery may carry the same timestamp."""
        del at
        current = self._heads.get((event.repo, event.pr_number))
        if current is None or current[0] != event.head_sha:
            return False
        key = (event.repo, event.pr_number, event.head_sha)
        return key not in self._seen and all(job.key() != key for job in self._jobs)

    def _newer_than_current(self, event: PrEvent, at: datetime | None) -> bool:
        current = self._heads.get((event.repo, event.pr_number))
        if current is None:
            return True
        _sha, current_at = current
        if at is None:
            return False
        if current_at is None:
            return True
        if at > current_at:
            return True
        # Two pushes in one second share a timestamp. The different SHA
        # is the newer delivery; dropping it would leave the old head.
        return at == current_at and event.head_sha != _sha

    def claim(self) -> Job | None:
        with self._cv:
            return self._claim(JobState.QUEUED, JobState.RUNNING)

    def claim_post(
        self, now: float, *, stop: threading.Event | None = None
    ) -> Job | None:
        with self._cv:
            if stop is not None and stop.is_set():
                return None
            if time.monotonic() < self._save_retry_at:
                return None
            for job in self._jobs:
                if (
                    job.state is JobState.POST_PENDING
                    and not job.superseded
                    and job.retry_at <= now
                ):
                    job.state = JobState.POSTING
                    try:
                        self._save()
                    except Exception:
                        job.state = JobState.POST_PENDING
                        raise
                    return job
            return None

    def cancel_active(self) -> None:
        with self._cv:
            for job in self._jobs:
                if job.state in {JobState.RUNNING, JobState.POSTING}:
                    job.cancel.set()

    def wait_for_work(
        self,
        timeout: float,
        stop: threading.Event,
        now: float,
        *,
        posts: bool = True,
    ) -> None:
        with self._cv:
            delay = self._delay(now, posts=posts)
            if stop.is_set() or delay == 0:
                return
            # A failed save names its own wait. Capping it at the poll
            # interval retries the claim every 0.2 s, which is the loop
            # the backoff exists to stop.
            remaining = self._save_retry_at - time.monotonic()
            if remaining > 0:
                self._cv.wait(remaining)
                return
            self._cv.wait(timeout if delay is None else min(timeout, delay))

    def still_current(self, job: Job) -> bool:
        with self._cv:
            return (
                job.state in {JobState.RUNNING, JobState.POSTING} and not job.superseded
            )

    def head_change_candidate(
        self, event: PrEvent, *, at: datetime | None = None
    ) -> Job | None:
        """The review a keep-or-cancel decision would be made about
        (#702): the pull request's running or posting job, when this
        delivery is a newer head for it. None when nothing is running,
        when the delivery is a duplicate or stale against the accepted
        heads, or when the job was already superseded -- a delivery in
        any of those shapes takes the ordinary enqueue path, which is
        the cancel policy's whole path."""
        with self._cv:
            key = (event.repo, event.pr_number, event.head_sha)
            if key in self._seen:
                return None
            if any(job.key() == key for job in self._jobs):
                return None
            if not self._newer_than_current(event, at):
                return None
            for job in self._jobs:
                if (
                    job.event.repo == event.repo
                    and job.event.pr_number == event.pr_number
                    and job.state in {JobState.RUNNING, JobState.POSTING}
                    and not job.superseded
                ):
                    return job
            return None

    def pending_head(self, repo: str, pr_number: int) -> str:
        """The head currently held back for this pull request, or ""."""
        with self._cv:
            pending = self._pending.get((repo, pr_number))
            return pending[0] if pending else ""

    def begin_post(self, job: Job) -> bool:
        """True only when this job may be sent. A running job becomes
        POSTING under the lock, so a supersede that lands before this
        returns is not sent. A post GitHub has already accepted cannot
        be recalled."""
        with self._cv:
            if job.superseded or job.cancel.is_set():
                return False
            if job.state not in {JobState.RUNNING, JobState.POSTING}:
                return False
            if job.state is JobState.RUNNING:
                job.state = JobState.POSTING
                try:
                    self._save()
                except Exception:
                    job.state = JobState.RUNNING
                    raise
            return True

    def finish(self, job: Job, state: JobState) -> JobState:
        """The state actually stored. A job that was superseded is stored
        as superseded even when the caller asked for a success."""
        with self._cv:
            if job.superseded and state is not JobState.SUPERSEDED:
                state = JobState.SUPERSEDED
            previous = job.state
            job.state = state
            try:
                self._save()
            except Exception:
                job.state = previous
                raise
            self._cv.notify_all()
            return state

    def release_claim(self, job: Job) -> JobState | None:
        """``stop()`` landed after this job was claimed and before it ran.
        Put it back to ``queued`` so a later pass can claim it. Returns
        the state stored, or None when this job was not running. A
        superseded job is stored as superseded, and the caller removes
        its run directory."""
        with self._cv:
            if job.state is not JobState.RUNNING:
                return None
            # A newer head already replaced this one. Putting it back to
            # queued would leave a job claim() never takes, and it would
            # hold an active slot until the process is wiped.
            target = JobState.SUPERSEDED if job.superseded else JobState.QUEUED
            job.state = target
            was_set = job.cancel.is_set()
            if target is JobState.QUEUED:
                job.cancel.clear()
            try:
                self._save()
            except Exception:
                job.state = JobState.RUNNING
                if was_set:
                    job.cancel.set()
                elif target is JobState.QUEUED:
                    job.cancel.clear()
                raise
            return target

    def pause_post(self, job: Job) -> JobState | None:
        """Stop landed after the post was claimed and before it was sent.
        Returns the state stored, or None when this job was not posting.
        A pending job keeps its draft. A superseded job is stored as
        superseded, and the caller removes its run directory. Leaving it
        pending would hold an active slot that ``claim_post`` never takes."""
        with self._cv:
            if job.state is not JobState.POSTING:
                return None
            target = JobState.SUPERSEDED if job.superseded else JobState.POST_PENDING
            previous = job.state
            job.state = target
            was_set = job.cancel.is_set()
            if target is JobState.POST_PENDING:
                job.cancel.clear()
            try:
                self._save()
            except Exception:
                job.state = previous
                if was_set:
                    job.cancel.set()
                elif target is JobState.POST_PENDING:
                    job.cancel.clear()
                raise
            return target

    def wake(self) -> None:
        with self._cv:
            self._cv.notify_all()

    def states(self) -> tuple[tuple[str, JobState], ...]:
        with self._cv:
            return tuple((job.event.head_sha, job.state) for job in self._jobs)

    def _claim(self, source: JobState, dest: JobState) -> Job | None:
        if time.monotonic() < self._save_retry_at:
            return None
        for job in self._jobs:
            if job.state is source and not job.superseded:
                job.state = dest
                try:
                    self._save()
                except Exception as exc:
                    job.state = source
                    exc.event = job.event  # type: ignore[attr-defined]
                    raise
                return job
        return None

    def saves_ok(self) -> bool:
        """False after a queue save failed, until a later save works.
        ``/health`` uses this so a full disk is not reported as healthy."""
        return self._saves_ok

    def _delay(self, now: float, *, posts: bool = True) -> float | None:
        save_wait = self._save_retry_at - time.monotonic()
        if save_wait > 0:
            return save_wait
        return self._work_delay(now, posts=posts)

    def _work_delay(self, now: float, *, posts: bool = True) -> float | None:
        if any(
            job.state is JobState.QUEUED and not job.superseded for job in self._jobs
        ):
            return 0.0
        if not posts:
            return None
        waiting = [
            job.retry_at - now
            for job in self._jobs
            if job.state is JobState.POST_PENDING and not job.superseded
        ]
        if not waiting:
            return None
        return max(0.0, min(waiting))

    def _save(self) -> None:
        self._trim()
        try:
            _store(
                self._path,
                [job.as_dict() for job in self._jobs],
                [_key_text(key) for key in self._seen_order],
                [_head_record(key, sha, at) for key, (sha, at) in self._heads.items()],
                [
                    _head_record(key, sha, at)
                    for key, (sha, at) in self._pending.items()
                ],
            )
        except Exception:
            self._saves_ok = False
            self._save_retry_at = time.monotonic() + _SAVE_BACKOFF_S
            raise
        self._saves_ok = True
        self._save_retry_at = 0.0

    def _trim(self) -> None:
        terminal = [
            job
            for job in self._jobs
            if job.state in {JobState.DONE, JobState.FAILED, JobState.SUPERSEDED}
        ]
        overflow = len(self._jobs) - self._max_remembered
        for job in terminal[: max(0, overflow)]:
            # A failure is not a duplicate. Remembering it would block the
            # only retry GitHub can still deliver.
            if job.state is not JobState.FAILED:
                self._remember(job.key())
            self._jobs.remove(job)
        while len(self._seen_order) > self._max_seen:
            dropped = self._drop_oldest_seen()
            if not dropped:
                break

    def _drop_oldest_seen(self) -> bool:
        """Drop the oldest key that is not a PR's current head. A current
        head stays, so a replay of the commit already accepted for that
        PR remains a duplicate. Returns false when every remembered key
        is a current head."""
        for index, key in enumerate(self._seen_order):
            current = self._heads.get((key[0], key[1]))
            if current is not None and current[0] == key[2]:
                continue
            self._seen.discard(self._seen_order.pop(index))
            return True
        return False

    def _remember(self, key: tuple[str, int, str]) -> None:
        if key in self._seen:
            return
        self._seen.add(key)
        self._seen_order.append(key)


def _store(
    path: Path,
    jobs: list[dict[str, object]],
    seen: list[str],
    heads: list[dict[str, object]],
    pending: list[dict[str, object]],
) -> None:
    make_private_dirs(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            {"jobs": jobs, "seen": seen, "heads": heads, "pending": pending}, handle
        )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _load(
    path: Path,
) -> tuple[
    list[Job],
    list[tuple[str, int, str]],
    dict[tuple[str, int], tuple[str, datetime | None]],
    dict[tuple[str, int], tuple[str, datetime | None]],
]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise QueueError(f"cannot read the review queue {path}") from exc
    jobs = raw.get("jobs") if isinstance(raw, dict) else None
    if not isinstance(jobs, list):
        raise QueueError(f"review queue {path} has no jobs list")
    loaded: list[Job] = []
    for item in jobs:
        job = _job(item, path)
        job.state = _RELOAD.get(job.state, job.state)
        if job.superseded and job.state in {JobState.QUEUED, JobState.POST_PENDING}:
            job.state = JobState.SUPERSEDED
        if job.superseded:
            job.cancel.set()
        loaded.append(job)
    seen = _seen(raw.get("seen") if isinstance(raw, dict) else None, path)
    heads = _heads(raw.get("heads") if isinstance(raw, dict) else None, loaded, path)
    pending_raw = raw.get("pending") if isinstance(raw, dict) else None
    pending = {} if pending_raw is None else _heads(pending_raw, loaded, path)
    return loaded, seen, heads, pending


def _job(item: object, path: Path) -> Job:
    if not isinstance(item, dict):
        raise QueueError(f"review queue {path} holds a non-object job")
    repo, pr, sha, state_raw = (
        item.get("repo"),
        item.get("pr"),
        item.get("sha"),
        item.get("state"),
    )
    if (
        not isinstance(repo, str)
        or isinstance(pr, bool)
        or not isinstance(pr, int)
        or not isinstance(sha, str)
        or not isinstance(state_raw, str)
    ):
        raise QueueError(f"review queue {path} holds a job that cannot be loaded")
    try:
        state = JobState(state_raw)
        event = PrEvent(repo, pr, sha, delta_from=item.get("delta_from", "") or "")
    except (InvalidEventError, ValueError) as exc:
        raise QueueError(
            f"review queue {path} holds a job that cannot be loaded"
        ) from exc
    superseded = item.get("superseded")
    if not isinstance(superseded, bool):
        raise QueueError(f"review queue {path} holds a job with no superseded flag")
    attempts = item.get("attempts", 0)
    retry_at = item.get("retry_at", 0)
    if (
        isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or isinstance(retry_at, bool)
        or not isinstance(retry_at, (int, float))
    ):
        raise QueueError(f"review queue {path} holds a job with a bad retry record")
    return Job(event, state, superseded, attempts, float(retry_at))


def _seen(raw: object, path: Path) -> list[tuple[str, int, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise QueueError(f"review queue {path} holds a seen list that is not a list")
    keys: list[tuple[str, int, str]] = []
    for item in raw:
        key = _parse_key(item)
        if key is None:
            raise QueueError(
                f"review queue {path} holds a seen key that cannot be read"
            )
        keys.append(key)
    return keys


def _key_text(key: tuple[str, int, str]) -> str:
    return f"{key[0]}#{key[1]}#{key[2]}"


def _parse_key(item: object) -> tuple[str, int, str] | None:
    if not isinstance(item, str):
        return None
    repo, sep, rest = item.partition("#")
    pr, sep2, sha = rest.partition("#")
    if not sep or not sep2 or not pr.isdigit():
        return None
    try:
        event = PrEvent(repo, int(pr), sha)
    except InvalidEventError:
        return None
    return event.repo, event.pr_number, event.head_sha


def _head_record(
    key: tuple[str, int], sha: str, at: datetime | None
) -> dict[str, object]:
    return {
        "repo": key[0],
        "pr": key[1],
        "sha": sha,
        "at": None if at is None else at.isoformat(),
    }


def _heads(
    raw: object, jobs: list[Job], path: Path
) -> dict[tuple[str, int], tuple[str, datetime | None]]:
    if raw is None:
        return _inferred_heads(jobs)
    if not isinstance(raw, list):
        raise QueueError(f"review queue {path} holds a heads list that is not a list")
    heads: dict[tuple[str, int], tuple[str, datetime | None]] = {}
    for item in raw:
        parsed = _head(item, path)
        heads[(parsed[0], parsed[1])] = (parsed[2], parsed[3])
    return heads


def _head(item: object, path: Path) -> tuple[str, int, str, datetime | None]:
    if not isinstance(item, dict):
        raise QueueError(f"review queue {path} holds a head that is not an object")
    try:
        event = PrEvent(
            repo=item.get("repo", ""),
            pr_number=item.get("pr", 0),
            head_sha=item.get("sha", ""),
        )
    except InvalidEventError as exc:
        raise QueueError(
            f"review queue {path} holds a head that cannot be read"
        ) from exc
    raw_at = item.get("at")
    if raw_at is None:
        return event.repo, event.pr_number, event.head_sha, None
    if not isinstance(raw_at, str):
        raise QueueError(f"review queue {path} holds a head time that is not text")
    try:
        parsed = datetime.fromisoformat(raw_at)
    except ValueError as exc:
        raise QueueError(
            f"review queue {path} holds a head time that is not a time"
        ) from exc
    if parsed.tzinfo is None:
        raise QueueError(f"review queue {path} holds a head time with no timezone")
    return event.repo, event.pr_number, event.head_sha, parsed


def _inferred_heads(
    jobs: list[Job],
) -> dict[tuple[str, int], tuple[str, datetime | None]]:
    heads: dict[tuple[str, int], tuple[str, datetime | None]] = {}
    for job in jobs:
        if job.state is JobState.SUPERSEDED or job.superseded:
            continue
        heads[(job.event.repo, job.event.pr_number)] = (job.event.head_sha, None)
    return heads
