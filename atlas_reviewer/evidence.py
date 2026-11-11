# SPDX-License-Identifier: MIT
"""Map raw GitHub JSON, downloaded bytes and runner results into
`EvidenceItem`s. Pure.

This is the validation boundary for GitHub response shapes: a field that is
missing or mistyped raises `BoundaryError` here instead of leaking a
`KeyError` into the controller. Every free-text field, log line and
artifact excerpt is redacted on the way in: names, app slugs, workflow
paths and tool versions too, since a PR can choose them. Ids, SHAs and
statuses are kept as GitHub sent them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from graphlib import CycleError, TopologicalSorter
from typing import Any

from atlas_reviewer.archive import ArchiveRead
from atlas_reviewer.domain import (
    UNREPORTED_VERSION,
    Conclusion,
    EvidenceItem,
    Missing,
    Provenance,
    SourceKey,
    SourceKind,
    ToolInfo,
)
from atlas_reviewer.ports import BoundaryError, Json
from atlas_reviewer.redact import RedactedText, Redactor, tail
from atlas_reviewer.runner import ToolAbsent, ToolResult

DETAIL_CHARS = 2_000
BODY_CHARS = 16_384
NAME_CHARS = 300
LOG_TAIL_CHARS = 6_000
ARTIFACT_EXCERPT_CHARS = 4_000
_TIMEOUT_EXITS = frozenset({124, 137})
_CLOSING_REF = re.compile(
    r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d{1,9})\b"
)
_MAX_ISSUE_REFS = 3
_SHA = re.compile(r"[0-9a-f]{40}")


def _field[T](data: Any, key: str, kind: type[T]) -> T:
    value = data.get(key) if isinstance(data, Mapping) else None
    if not isinstance(value, kind) or isinstance(value, bool) is not (kind is bool):
        raise BoundaryError(
            f"GitHub response field {key!r} missing or not {kind.__name__}"
        )
    return value


def _text(redactor: Redactor, raw: str) -> str:
    return redactor(raw, NAME_CHARS).text


def _optional_str(data: Json, key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _objects(items: Sequence[Any], what: str) -> Sequence[Json]:
    if not all(isinstance(i, Mapping) for i in items):
        raise BoundaryError(f"GitHub {what} list holds a non-object entry")
    return items


def _conclusion(status: str, conclusion: str) -> Conclusion:
    if status != "completed":
        return Conclusion.PENDING
    try:
        return Conclusion(conclusion)
    except ValueError:
        return Conclusion.UNREPORTED


@dataclass(frozen=True)
class PullInfo:
    """Names (author, branches, labels, reviewers) are redacted like every
    other PR-chosen string."""

    head_sha: str
    head_ref: str
    title: RedactedText
    body: RedactedText
    issue_refs: tuple[int, ...]
    changed_files: int | None = None
    """GitHub's own count, to check the fetched diff against; None when the
    payload has no usable count, which leaves file coverage unknown."""
    author: str = ""
    base_ref: str = ""
    labels: tuple[str, ...] = ()
    reviewers: tuple[str, ...] = ()
    teams: tuple[str, ...] = ()
    draft: bool = False


def parse_pull(
    data: Json, redactor: Redactor, body_chars: int = BODY_CHARS
) -> PullInfo:
    head = _field(data, "head", dict)
    body = _optional_str(data, "body")
    changed = data.get("changed_files")
    return PullInfo(
        head_sha=_field(head, "sha", str),
        head_ref=_field(head, "ref", str),
        title=redactor(_field(data, "title", str), NAME_CHARS),
        body=redactor(body, body_chars),
        issue_refs=issue_refs(body),
        changed_files=(
            changed
            if isinstance(changed, int)
            and not isinstance(changed, bool)
            and changed >= 0
            else None
        ),
        author=_login(data.get("user"), redactor),
        base_ref=_text(redactor, _optional_str(_mapping(data, "base"), "ref")),
        labels=_names(data, "labels", "name", redactor),
        reviewers=_names(data, "requested_reviewers", "login", redactor),
        teams=_names(data, "requested_teams", "slug", redactor),
        draft=data.get("draft") is True,
    )


def _mapping(data: Json, key: str) -> Json:
    value = data.get(key)
    return value if isinstance(value, Mapping) else {}


def _login(user: Any, redactor: Redactor) -> str:
    """GitHub sends `user: null` for a deleted account."""
    login = user.get("login") if isinstance(user, Mapping) else None
    return _text(redactor, login) if isinstance(login, str) else "(unknown user)"


def _names(data: Json, key: str, field: str, redactor: Redactor) -> tuple[str, ...]:
    entries = data.get(key)
    values = (
        e.get(field) for e in (entries if isinstance(entries, list) else ())
        if isinstance(e, Mapping)
    )  # fmt: skip
    return tuple(_text(redactor, v) for v in values if isinstance(v, str))


def issue_refs(body: str) -> tuple[int, ...]:
    refs: dict[int, None] = {}
    for m in _CLOSING_REF.finditer(body):
        refs[int(m.group(1))] = None
        if len(refs) == _MAX_ISSUE_REFS:
            break
    return tuple(refs)


def parse_check_runs(
    items: Sequence[Any], fetched_at: datetime, redactor: Redactor
) -> tuple[EvidenceItem, ...]:
    return tuple(
        _check_run(r, fetched_at, redactor) for r in _objects(items, "check run")
    )


def _check_run(run: Json, fetched_at: datetime, redactor: Redactor) -> EvidenceItem:
    app = run.get("app")
    raw_output = run.get("output")
    output: Json = raw_output if isinstance(raw_output, Mapping) else {}
    slug = app.get("slug") if isinstance(app, Mapping) else None
    text = "\n".join(
        filter(None, (_optional_str(output, "title"), _optional_str(output, "summary")))
    )
    return EvidenceItem(
        head_sha=_field(run, "head_sha", str),
        provenance=Provenance(
            SourceKey(SourceKind.CHECK_RUN, _text(redactor, _field(run, "name", str))),
            f"check_run:{_field(run, 'id', int)}",
        ),
        tool=ToolInfo(
            _text(redactor, slug) if isinstance(slug, str) else "unknown-app",
            UNREPORTED_VERSION,
        ),
        fetched_at=fetched_at,
        conclusion=_conclusion(
            _field(run, "status", str), _optional_str(run, "conclusion")
        ),
        detail=redactor(text, DETAIL_CHARS),
    )


@dataclass(frozen=True)
class PrCommit:
    """One commit of the PR: its SHA, checked as a full 40-hex id because it
    labels evidence and telemetry, and its subject line (raw, PR-written):
    the message up to its first line terminator of any kind, since git keeps
    a bare `\\r` or U+2028 inside a subject. `parents` and `committed_at`
    (committer date as GitHub sends it, or empty) order the commits."""

    sha: str
    subject: str
    parents: tuple[str, ...] = ()
    committed_at: str = ""


def parse_commits(items: Sequence[Any]) -> tuple[PrCommit, ...]:
    """Oldest first in history, whatever order GitHub lists them in."""
    return in_history_order(parse_commit_entries(items))


def parse_commit_entries(items: Sequence[Any]) -> tuple[PrCommit, ...]:
    """The commits as listed, unordered: order only means something over the
    whole listing, so callers that parse entry by entry order once at the end
    with `in_history_order`."""
    return tuple(_commit(c) for c in _objects(items, "commit"))


def _commit(data: Json) -> PrCommit:
    sha = _field(data, "sha", str)
    if not _SHA.fullmatch(sha):
        raise BoundaryError("GitHub commit sha is not a full 40-hex id")
    commit = _mapping(data, "commit")
    lines = _optional_str(commit, "message").splitlines()
    return PrCommit(
        sha,
        lines[0] if lines else "",
        _parent_shas(data),
        _optional_str(_mapping(commit, "committer"), "date"),
    )


def _parent_shas(data: Json) -> tuple[str, ...]:
    parents = data.get("parents")
    shas = (
        p.get("sha") for p in (parents if isinstance(parents, list) else ())
        if isinstance(p, Mapping)
    )  # fmt: skip
    return tuple(s for s in shas if isinstance(s, str))


def in_history_order(commits: Sequence[PrCommit]) -> tuple[PrCommit, ...]:
    """Each commit after every parent listed with it; commits with no such
    order between them by committer date, then by listed position. A
    repeated SHA is kept once; a parent cycle, which git cannot produce,
    falls back to date order."""
    rank = {c.sha: (c.committed_at, i) for i, c in reversed(list(enumerate(commits)))}
    by_sha = {c.sha: c for c in reversed(commits)}
    graph = {sha: [p for p in c.parents if p in rank] for sha, c in by_sha.items()}
    try:
        order = _layered(TopologicalSorter(graph), rank)
    except CycleError:
        order = sorted(rank, key=rank.__getitem__)
    return tuple(by_sha[sha] for sha in order)


def _layered(
    sorter: TopologicalSorter[str], rank: Mapping[str, tuple[str, int]]
) -> list[str]:
    sorter.prepare()
    order: list[str] = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready(), key=rank.__getitem__)
        order.extend(ready)
        sorter.done(*ready)
    return order


@dataclass(frozen=True)
class Remark:
    """One review, review comment or conversation comment on the PR, raw.
    `at` is GitHub's own timestamp, which orders remarks; `context` is built
    by the controller from typed fields; `author` and `body` are PR text,
    redacted when the conversation block is built."""

    source_id: str
    at: str
    author: str
    context: str
    body: str


def parse_issue_comment(data: Json, head_sha: str) -> Remark:
    comment_id = _field(data, "id", int)
    return Remark(
        f"issue_comment:{comment_id}",
        _field(data, "created_at", str),
        _optional_login(data),
        "conversation comment",
        _optional_str(data, "body"),
    )


def parse_review(data: Json, head_sha: str) -> Remark:
    """A review's `submitted_at` is absent while it is pending."""
    review_id = _field(data, "id", int)
    state = _field(data, "state", str)
    return Remark(
        f"review:{review_id}",
        _optional_str(data, "submitted_at"),
        _optional_login(data),
        f"review, state {_quoted(state)}, {_commit_label(data, head_sha)}",
        _optional_str(data, "body"),
    )


def parse_review_comment(data: Json, head_sha: str) -> Remark:
    comment_id = _field(data, "id", int)
    path = _field(data, "path", str)
    return Remark(
        f"review_comment:{comment_id}",
        _field(data, "created_at", str),
        _optional_login(data),
        f"review comment on {_quoted(path)}{_line_label(data)}, "
        f"{_commit_label(data, head_sha)}{_thread_label(data)}",
        _optional_str(data, "body"),
    )


def _optional_login(data: Json) -> str:
    login = _mapping(data, "user").get("login")
    return login if isinstance(login, str) else "(unknown user)"


def _quoted(text: str) -> str:
    return json.dumps(text, ensure_ascii=True)


def _int_field(data: Json, key: str) -> int | None:
    value = data.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _line_label(data: Json) -> str:
    """`line` is null once the commented line is outdated; `original_line`
    is where it was."""
    line, original = _int_field(data, "line"), _int_field(data, "original_line")
    if line is not None:
        return f" line {line}"
    return "" if original is None else f" (outdated; was line {original})"


def _commit_label(data: Json, head_sha: str) -> str:
    commit = _optional_str(data, "commit_id")
    if commit == head_sha:
        return "at the reviewed head SHA"
    return (
        f"at commit {commit[:12]}" if _SHA.fullmatch(commit) else "commit not reported"
    )


def _thread_label(data: Json) -> str:
    parent = _int_field(data, "in_reply_to_id")
    return "" if parent is None else f", reply to review_comment:{parent}"


@dataclass(frozen=True)
class WorkflowRun:
    run_id: int
    item: EvidenceItem


def parse_workflow_runs(
    items: Sequence[Any], fetched_at: datetime, redactor: Redactor
) -> tuple[WorkflowRun, ...]:
    return tuple(
        _workflow_run(r, fetched_at, redactor) for r in _objects(items, "workflow run")
    )


def _workflow_tool(run: Json, head_sha: str, redactor: Redactor) -> ToolInfo:
    path = _text(redactor, _optional_str(run, "path")) or "unknown-workflow"
    return ToolInfo("github-actions", f"{path}@{head_sha[:12]}")


def _workflow_run(run: Json, fetched_at: datetime, redactor: Redactor) -> WorkflowRun:
    run_id = _field(run, "id", int)
    head_sha = _field(run, "head_sha", str)
    detail = (
        f"event={_optional_str(run, 'event')} attempt={run.get('run_attempt', '?')}"
    )
    item = EvidenceItem(
        head_sha=head_sha,
        provenance=Provenance(
            SourceKey(
                SourceKind.WORKFLOW_RUN, _text(redactor, _field(run, "name", str))
            ),
            f"workflow_run:{run_id}",
        ),
        tool=_workflow_tool(run, head_sha, redactor),
        fetched_at=fetched_at,
        conclusion=_conclusion(
            _field(run, "status", str), _optional_str(run, "conclusion")
        ),
        detail=redactor(detail, DETAIL_CHARS),
    )
    return WorkflowRun(run_id, item)


_CHECK_RUN_URL = re.compile(r"/check-runs/(\d+)$")


@dataclass(frozen=True)
class Job:
    job_id: int
    item: EvidenceItem
    check_run_id: int | None = None


def parse_jobs(
    items: Sequence[Any], run: WorkflowRun, fetched_at: datetime, redactor: Redactor
) -> tuple[Job, ...]:
    return tuple(_job(j, run, fetched_at, redactor) for j in _objects(items, "job"))


def _job(job: Json, run: WorkflowRun, fetched_at: datetime, redactor: Redactor) -> Job:
    job_id = _field(job, "id", int)
    run_name = run.item.provenance.key.name
    name = _text(redactor, _field(job, "name", str))
    item = EvidenceItem(
        head_sha=_field(job, "head_sha", str),
        provenance=Provenance(
            SourceKey(SourceKind.JOB, f"{run_name} / {name}"),
            f"job:{job_id}",
        ),
        tool=run.item.tool,
        fetched_at=fetched_at,
        conclusion=_conclusion(
            _field(job, "status", str), _optional_str(job, "conclusion")
        ),
        detail=redactor(f"workflow_run={run.run_id}", DETAIL_CHARS),
    )
    return Job(job_id, item, _check_run_id(job))


def _check_run_id(job: Json) -> int | None:
    """The job's own check run, from the documented `check_run_url` field.
    Nothing is inferred from names or from id equality."""
    url = job.get("check_run_url")
    match = _CHECK_RUN_URL.search(url) if isinstance(url, str) else None
    return int(match.group(1)) if match else None


def job_log_item(
    job: Job, raw: bytes, fetched_at: datetime, redactor: Redactor
) -> EvidenceItem:
    source = job.item
    return EvidenceItem(
        head_sha=source.head_sha,
        provenance=Provenance(
            SourceKey(SourceKind.WORKFLOW_LOG, source.provenance.key.name),
            f"job_log:{job.job_id}",
        ),
        tool=source.tool,
        fetched_at=fetched_at,
        conclusion=source.conclusion,
        detail=tail(redactor(raw.decode("utf-8", errors="replace")), LOG_TAIL_CHARS),
    )


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: int
    size_in_bytes: int | None
    expired: bool
    item: EvidenceItem


def parse_artifacts(
    items: Sequence[Any], fetched_at: datetime, redactor: Redactor
) -> tuple[ArtifactRef, ...]:
    return tuple(
        _artifact(a, fetched_at, redactor) for a in _objects(items, "artifact")
    )


def _artifact(artifact: Json, fetched_at: datetime, redactor: Redactor) -> ArtifactRef:
    run = _field(artifact, "workflow_run", dict)
    artifact_id = _field(artifact, "id", int)
    expired = artifact.get("expired") is True
    raw_size = artifact.get("size_in_bytes")
    size = (
        raw_size
        if isinstance(raw_size, int) and not isinstance(raw_size, bool)
        else None
    )
    detail = f"size_in_bytes={size if size is not None else '?'} expired={expired} workflow_run={run.get('id', '?')}"
    item = EvidenceItem(
        head_sha=_field(run, "head_sha", str),
        provenance=Provenance(
            SourceKey(
                SourceKind.ARTIFACT, _text(redactor, _field(artifact, "name", str))
            ),
            f"artifact:{artifact_id}",
        ),
        tool=ToolInfo("github-actions-artifact", UNREPORTED_VERSION),
        fetched_at=fetched_at,
        conclusion=Conclusion.UNREPORTED if expired else Conclusion.PRESENT,
        detail=redactor(detail, DETAIL_CHARS),
    )
    return ArtifactRef(artifact_id, size, expired, item)


def contents_key(ref: ArtifactRef) -> SourceKey:
    return SourceKey(SourceKind.ARTIFACT, f"{ref.item.provenance.key.name} (contents)")


def artifact_contents_item(
    ref: ArtifactRef, read: ArchiveRead, fetched_at: datetime, redactor: Redactor
) -> EvidenceItem:
    excerpt = "\n".join(f"--- {m.name} ---\n{m.text}" for m in read.members)
    return EvidenceItem(
        head_sha=ref.item.head_sha,
        provenance=Provenance(contents_key(ref), f"artifact:{ref.artifact_id}:zip"),
        tool=ref.item.tool,
        fetched_at=fetched_at,
        conclusion=Conclusion.PRESENT,
        detail=redactor(
            excerpt or "(no readable text entries)", ARTIFACT_EXCERPT_CHARS
        ),
    )


def _tool_conclusion(exit_code: int | None) -> Conclusion:
    if exit_code is None:
        return Conclusion.UNREPORTED
    if exit_code == 0:
        return Conclusion.SUCCESS
    return Conclusion.TIMED_OUT if exit_code in _TIMEOUT_EXITS else Conclusion.FAILURE


def tool_evidence(
    result: ToolResult,
    head_sha: str,
    runner_name: str,
    fetched_at: datetime,
    redactor: Redactor,
) -> EvidenceItem | Missing:
    key = SourceKey(SourceKind.RUNNER_TOOL, result.tool.name)
    if isinstance(result, ToolAbsent):
        detail = _text(redactor, result.detail)
        return Missing(key, f"not available in the runner image ({detail})")
    return EvidenceItem(
        head_sha=head_sha,
        provenance=Provenance(key, f"runner:{runner_name}:{result.tool.name}"),
        tool=ToolInfo(result.tool.name, _text(redactor, result.version)),
        fetched_at=fetched_at,
        conclusion=_tool_conclusion(result.exit_code),
        detail=redactor(f"exit={result.exit_code}\n{result.output}", DETAIL_CHARS),
    )
