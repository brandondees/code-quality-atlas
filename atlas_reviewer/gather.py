# SPDX-License-Identifier: MIT
"""Gather CI evidence for one head SHA: check runs, workflow runs, jobs,
job logs and artifact contents. Controller-side; every byte is untrusted.

Workflow runs come from two listings: those at the head SHA, and those
under the head branch's name, of which only runs at one of this PR's own
commits are kept. A branch name is shared (a fork's `main`, a reused name,
the base repository's own pushes), so a run at any other commit is not
this PR's evidence; how many were set aside is noted. Runs at earlier
commits of the PR stay, labelled by their SHA, and only head-SHA evidence
can count as a current result (`classify`).

Downloads (job logs, artifact ZIPs) happen only for runs, jobs and
artifacts at the reviewed head SHA, each under a byte cap, within
per-review count caps. Anything a cap or a page limit leaves unread is
recorded twice: as an `Omission` (listed in the draft) and, where it could
have held evidence, as `Missing` (UNKNOWN, never a pass).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from atlas_reviewer.archive import ArchiveLimits, read_zip
from atlas_reviewer.domain import (
    Conclusion,
    EvidenceItem,
    Missing,
    Omission,
    PrEvent,
    SourceKey,
    SourceKind,
)
from atlas_reviewer.evidence import (
    ArtifactRef,
    Job,
    WorkflowRun,
    artifact_contents_item,
    contents_key,
    job_log_item,
    parse_artifacts,
    parse_check_runs,
    parse_commit_shas,
    parse_jobs,
    parse_workflow_runs,
)
from atlas_reviewer.groups import Link
from atlas_reviewer.ports import (
    BoundaryError,
    GitHubReader,
    Json,
    Listing,
    ResponseTooLargeError,
)
from atlas_reviewer.redact import Redactor

_FAILING = frozenset(
    {Conclusion.FAILURE, Conclusion.TIMED_OUT, Conclusion.ACTION_REQUIRED}
)


@dataclass(frozen=True)
class IngestConfig:
    max_runs: int = 5
    max_job_logs: int = 10
    max_log_bytes: int = 5 * 1024 * 1024
    max_artifacts: int = 5
    archive: ArchiveLimits = field(default_factory=ArchiveLimits)


@dataclass
class Collected:
    items: list[EvidenceItem] = field(default_factory=list)
    failures: list[Missing] = field(default_factory=list)
    omissions: list[Omission] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)

    def omit(
        self, source: str, limit: str, detail: str, key: SourceKey | None = None
    ) -> None:
        self.omissions.append(Omission(source, limit, detail))
        if key is not None:
            self.failures.append(Missing(key, f"not read: {limit} -- {detail}"))


@dataclass
class _Left:
    """Per-review download counts still unspent, shared by every run."""

    job_logs: int
    artifacts: int


@dataclass(frozen=True)
class _Ctx:
    event: PrEvent
    github: GitHubReader
    now: Callable[[], datetime]
    redactor: Redactor
    config: IngestConfig
    out: Collected
    left: _Left


def gather_ci(
    event: PrEvent,
    head_ref: str,
    github: GitHubReader,
    now: Callable[[], datetime],
    redactor: Redactor,
    config: IngestConfig,
    out: Collected,
) -> None:
    left = _Left(config.max_job_logs, config.max_artifacts)
    ctx = _Ctx(event, github, now, redactor, config, out, left)
    repo, sha = event.repo, event.head_sha
    checks = _listing(
        ctx,
        SourceKind.CHECK_RUN,
        "check runs",
        lambda: github.list_check_runs(repo, sha),
    )
    out.items.extend(
        _parse_each(
            ctx,
            SourceKind.CHECK_RUN,
            "check runs",
            checks,
            lambda e: parse_check_runs(e, now(), redactor),
        )
    )
    runs = _pr_runs(ctx, head_ref)
    out.items.extend(r.item for r in runs)
    at_head = [r for r in runs if r.item.head_sha == sha]
    for run in _capped(
        ctx,
        "workflow runs at the head SHA",
        at_head,
        config.max_runs,
        config.max_runs,
        lambda r: SourceKey(SourceKind.JOB, f"(jobs of {r.item.provenance.key.name})"),
    ):
        _gather_run(ctx, run)


def _runs(
    ctx: _Ctx, what: str, fetch: Callable[[], Listing]
) -> tuple[WorkflowRun, ...]:
    return _parse_each(
        ctx,
        SourceKind.WORKFLOW_RUN,
        what,
        _listing(ctx, SourceKind.WORKFLOW_RUN, what, fetch),
        lambda e: parse_workflow_runs(e, ctx.now(), ctx.redactor),
    )


def _pr_runs(ctx: _Ctx, head_ref: str) -> list[WorkflowRun]:
    repo, sha = ctx.event.repo, ctx.event.head_sha
    at_head = _runs(
        ctx,
        "head-SHA workflow runs",
        lambda: ctx.github.list_workflow_runs_at(repo, sha),
    )
    commits = {sha, *_pr_commits(ctx)}
    on_branch = _runs(
        ctx, "workflow runs", lambda: ctx.github.list_workflow_runs(repo, head_ref)
    )
    outside = [r for r in on_branch if r.item.head_sha not in commits]
    if outside:
        ctx.out.notes.append(
            f"{len(outside)} workflow run(s) listed under this PR's head branch "
            "name were at commits that are not in this PR and were not used."
        )
    runs: dict[int, WorkflowRun] = {}
    for run in (*at_head, *on_branch):
        if run.item.head_sha in commits:
            runs.setdefault(run.run_id, run)
    return list(runs.values())


def _pr_commits(ctx: _Ctx) -> tuple[str, ...]:
    """This PR's commit SHAs. A failed or cut-off listing leaves out the
    runs at commits it did not return, which only drops evidence from
    other commits; the failure itself is recorded."""
    what = "commits of this PR"
    return tuple(
        s
        for shas in _parse_each(
            ctx,
            SourceKind.WORKFLOW_RUN,
            what,
            _listing(
                ctx,
                SourceKind.WORKFLOW_RUN,
                what,
                lambda: ctx.github.list_pull_commits(
                    ctx.event.repo, ctx.event.pr_number
                ),
            ),
            lambda e: (parse_commit_shas(e),),
        )
        for s in shas
    )


def _attempt[T](out: Collected, key: SourceKey, fetch: Callable[[], T]) -> T | None:
    try:
        return fetch()
    except BoundaryError as exc:
        out.failures.append(Missing(key, f"could not fetch: {exc}"))
        return None


def _listing(
    ctx: _Ctx, kind: SourceKind, what: str, fetch: Callable[[], Listing]
) -> tuple[Json, ...]:
    listing = _attempt(ctx.out, SourceKey(kind, f"(all {what})"), fetch)
    if listing is None:
        return ()
    if listing.truncated:
        ctx.out.omit(
            what,
            f"page cap ({listing.pages_read} pages)",
            "further pages exist and were not read",
            SourceKey(kind, f"({what} beyond page {listing.pages_read})"),
        )
    return listing.items


def _parse_each[T](
    ctx: _Ctx,
    kind: SourceKind,
    what: str,
    entries: Sequence[Json],
    parse: Callable[[Sequence[Json]], tuple[T, ...]],
) -> tuple[T, ...]:
    """Parse entry by entry, so one malformed entry is UNKNOWN on its own
    rather than aborting the review and discarding the valid ones."""
    parsed: list[T] = []
    for i, entry in enumerate(entries):
        try:
            parsed.extend(parse([entry]))
        except BoundaryError as exc:
            key = SourceKey(kind, f"({what} entry {i})")
            ctx.out.failures.append(Missing(key, f"malformed: {exc}"))
    return tuple(parsed)


def _capped[T](
    ctx: _Ctx,
    what: str,
    found: Sequence[T],
    left: int,
    cap: int,
    key: Callable[[T], SourceKey],
) -> Sequence[T]:
    """The first `left` of `found`; each one past it is UNKNOWN."""
    skipped = found[max(left, 0) :]
    if skipped:
        limit = f"per-review cap of {cap}"
        ctx.out.omit(what, limit, f"{len(skipped)} of {len(found)} not ingested")
        ctx.out.failures.extend(Missing(key(s), f"not read: {limit}") for s in skipped)
    return found[: max(left, 0)]


def _gather_run(ctx: _Ctx, run: WorkflowRun) -> None:
    repo, name = ctx.event.repo, run.item.provenance.key.name
    jobs = _parse_each(
        ctx,
        SourceKind.JOB,
        f"jobs of {name}",
        _listing(
            ctx,
            SourceKind.JOB,
            f"jobs of {name}",
            lambda: ctx.github.list_run_jobs(repo, run.run_id),
        ),
        lambda e: parse_jobs(e, run, ctx.now(), ctx.redactor),
    )
    ctx.out.items.extend(j.item for j in jobs)
    ctx.out.links.extend(_job_links(run, jobs))
    _gather_job_logs(ctx, [j for j in jobs if j.item.head_sha == ctx.event.head_sha])
    artifacts = _parse_each(
        ctx,
        SourceKind.ARTIFACT,
        f"artifacts of {name}",
        _listing(
            ctx,
            SourceKind.ARTIFACT,
            f"artifacts of {name}",
            lambda: ctx.github.list_run_artifacts(repo, run.run_id),
        ),
        lambda e: parse_artifacts(e, ctx.now(), ctx.redactor),
    )
    ctx.out.items.extend(a.item for a in artifacts)
    _gather_artifacts(ctx, artifacts)


def _job_links(run: WorkflowRun, jobs: tuple[Job, ...]) -> list[Link]:
    run_id = run.item.provenance.source_id
    links = []
    for job in jobs:
        job_id = job.item.provenance.source_id
        links.append(Link(run_id, job_id))
        if job.check_run_id is not None:
            links.append(Link(job_id, f"check_run:{job.check_run_id}"))
    return links


def _gather_job_logs(ctx: _Ctx, jobs: list[Job]) -> None:
    ordered = sorted(jobs, key=lambda j: j.item.conclusion not in _FAILING)
    taken = _capped(
        ctx, "job logs", ordered, ctx.left.job_logs, ctx.config.max_job_logs, _log_key
    )
    ctx.left.job_logs -= len(taken)
    for job in taken:
        _gather_job_log(ctx, job)


def _log_key(job: Job) -> SourceKey:
    return SourceKey(SourceKind.WORKFLOW_LOG, job.item.provenance.key.name)


def _gather_job_log(ctx: _Ctx, job: Job) -> None:
    key = _log_key(job)
    limit = ctx.config.max_log_bytes
    try:
        raw = ctx.github.get_job_logs(ctx.event.repo, job.job_id, limit)
    except ResponseTooLargeError:
        ctx.out.omit(
            f"log of job:{job.job_id}",
            f"{limit}-byte download cap",
            "log too large",
            key,
        )
        return
    except BoundaryError as exc:
        ctx.out.failures.append(Missing(key, f"could not fetch: {exc}"))
        return
    log = job_log_item(job, raw, ctx.now(), ctx.redactor)
    ctx.out.items.append(log)
    ctx.out.links.append(Link(log.provenance.source_id, job.item.provenance.source_id))


def _gather_artifacts(ctx: _Ctx, artifacts: tuple[ArtifactRef, ...]) -> None:
    live = [
        a for a in artifacts if a.item.head_sha == ctx.event.head_sha and not a.expired
    ]
    taken = _capped(
        ctx,
        "artifact downloads",
        live,
        ctx.left.artifacts,
        ctx.config.max_artifacts,
        contents_key,
    )
    ctx.left.artifacts -= len(taken)
    for ref in taken:
        _gather_artifact(ctx, ref)


def _gather_artifact(ctx: _Ctx, ref: ArtifactRef) -> None:
    source, key = f"artifact:{ref.artifact_id}", contents_key(ref)
    limit = ctx.config.archive.max_compressed_bytes
    cap = f"{limit}-byte compressed cap"
    if ref.size_in_bytes is not None and ref.size_in_bytes > limit:
        ctx.out.omit(
            source, cap, f"listed at {ref.size_in_bytes} bytes; not downloaded", key
        )
        return
    try:
        raw = ctx.github.download_artifact(ctx.event.repo, ref.artifact_id, limit)
    except ResponseTooLargeError:
        ctx.out.omit(source, cap, "download exceeded the cap", key)
        return
    except BoundaryError as exc:
        ctx.out.failures.append(Missing(key, f"could not fetch: {exc}"))
        return
    read = read_zip(raw, ctx.config.archive)
    if read.rejected is not None:
        ctx.out.omit(source, "archive rejected", read.rejected, key)
        return
    name = ref.item.provenance.key.name
    for i, skipped in enumerate(read.skipped):
        entry = SourceKey(SourceKind.ARTIFACT, f"{name} (skipped entry {i})")
        ctx.out.omit(source, "archive entry skipped", skipped, entry)
    if not read.members and read.skipped:
        ctx.out.failures.append(Missing(key, "not read: every archive entry skipped"))
        return
    contents = artifact_contents_item(ref, read, ctx.now(), ctx.redactor)
    ctx.out.items.append(contents)
    ctx.out.links.append(Link(contents.provenance.source_id, source))
