# SPDX-License-Identifier: MIT
"""The review queue: one job per repository, PR and head SHA.

A second delivery of the same commit is a no-op. A newer head SHA for the
same PR marks the older job superseded and sets its cancel event, whether
that job is still queued or already running. The file is the dedupe set:
it is rewritten with ``os.replace`` and an fsync, mode 0600, so a crash
does not drop a commit that was already accepted. A job left ``running``
when the process stopped is loaded back as ``queued`` so that one review
is tried again. A job left ``posting`` is loaded as ``post_pending``.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from atlas_reviewer.domain import InvalidEventError, PrEvent
from atlas_reviewer.ledger import make_private_dirs


class Enqueue(StrEnum):
    QUEUED = "queued"
    DUPLICATE = "duplicate"
    STALE = "stale"


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
        }


# Terminal jobs older than this are dropped from the queue file. Their
# keys stay in `seen`, so a replay is still a duplicate. The cap is a
# bound on the file, not a review budget.
MAX_REMEMBERED = 2_000


class Board:
    def __init__(self, path: Path, *, max_remembered: int = MAX_REMEMBERED) -> None:
        self._path = path
        self._cv = threading.Condition()
        self._jobs: list[Job] = []
        self._seen: set[tuple[str, int, str]] = set()
        self._max_remembered = max_remembered
        if path.exists():
            self._jobs, self._seen = _load(path)

    def enqueue(self, event: PrEvent) -> Enqueue:
        with self._cv:
            key = (event.repo, event.pr_number, event.head_sha)
            if key in self._seen:
                return Enqueue.DUPLICATE
            for job in self._jobs:
                if job.key() == key:
                    if job.state is JobState.SUPERSEDED or job.superseded:
                        return Enqueue.STALE
                    return Enqueue.DUPLICATE
            for job in self._jobs:
                if (
                    job.event.repo != event.repo
                    or job.event.pr_number != event.pr_number
                ):
                    continue
                if job.state not in _ACTIVE:
                    continue
                job.superseded = True
                job.cancel.set()
                if job.state in {JobState.QUEUED, JobState.POST_PENDING}:
                    job.state = JobState.SUPERSEDED
            self._jobs.append(Job(event, JobState.QUEUED))
            self._save()
            self._cv.notify()
            return Enqueue.QUEUED

    def claim(self) -> Job | None:
        with self._cv:
            return self._claim(JobState.QUEUED, JobState.RUNNING)

    def claim_post(self, now: float) -> Job | None:
        with self._cv:
            for job in self._jobs:
                if (
                    job.state is JobState.POST_PENDING
                    and not job.superseded
                    and job.retry_at <= now
                ):
                    job.state = JobState.POSTING
                    self._save()
                    return job
            return None

    def cancel_active(self) -> None:
        with self._cv:
            for job in self._jobs:
                if job.state in {JobState.RUNNING, JobState.POSTING}:
                    job.cancel.set()

    def wait_for_work(self, timeout: float, stop: threading.Event, now: float) -> None:
        with self._cv:
            delay = self._delay(now)
            if stop.is_set() or delay == 0:
                return
            self._cv.wait(timeout if delay is None else min(timeout, delay))

    def still_current(self, job: Job) -> bool:
        with self._cv:
            return (
                job.state in {JobState.RUNNING, JobState.POSTING} and not job.superseded
            )

    def finish(self, job: Job, state: JobState) -> None:
        with self._cv:
            if job.superseded and state is not JobState.SUPERSEDED:
                state = JobState.SUPERSEDED
            job.state = state
            self._save()
            self._cv.notify_all()

    def wake(self) -> None:
        with self._cv:
            self._cv.notify_all()

    def states(self) -> tuple[tuple[str, JobState], ...]:
        with self._cv:
            return tuple((job.event.head_sha, job.state) for job in self._jobs)

    def _claim(self, source: JobState, dest: JobState) -> Job | None:
        for job in self._jobs:
            if job.state is source and not job.superseded:
                job.state = dest
                self._save()
                return job
        return None

    def _delay(self, now: float) -> float | None:
        if any(
            job.state is JobState.QUEUED and not job.superseded for job in self._jobs
        ):
            return 0.0
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
        _store(
            self._path,
            [job.as_dict() for job in self._jobs],
            [_key_text(key) for key in self._seen],
        )

    def _trim(self) -> None:
        terminal = [
            job
            for job in self._jobs
            if job.state in {JobState.DONE, JobState.FAILED, JobState.SUPERSEDED}
        ]
        overflow = len(self._jobs) - self._max_remembered
        for job in terminal[: max(0, overflow)]:
            self._seen.add(job.key())
            self._jobs.remove(job)
        if len(self._seen) > self._max_remembered:
            self._seen = set(list(self._seen)[-self._max_remembered :])


def _store(path: Path, jobs: list[dict[str, object]], seen: list[str]) -> None:
    make_private_dirs(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"jobs": jobs, "seen": seen}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _load(path: Path) -> tuple[list[Job], set[tuple[str, int, str]]]:
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
        if job.superseded:
            job.cancel.set()
        loaded.append(job)
    return loaded, _seen(raw.get("seen") if isinstance(raw, dict) else None, path)


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
        event = PrEvent(repo=repo, pr_number=pr, head_sha=sha)
        state = JobState(state_raw)
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


def _seen(raw: object, path: Path) -> set[tuple[str, int, str]]:
    if raw is None:
        return set()
    if not isinstance(raw, list):
        raise QueueError(f"review queue {path} holds a seen list that is not a list")
    keys: set[tuple[str, int, str]] = set()
    for item in raw:
        key = _parse_key(item)
        if key is None:
            raise QueueError(
                f"review queue {path} holds a seen key that cannot be read"
            )
        keys.add(key)
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
