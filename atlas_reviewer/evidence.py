# SPDX-License-Identifier: MIT
"""Map raw GitHub JSON, downloaded bytes and runner results into
`EvidenceItem`s. Pure.

This is the validation boundary for GitHub response shapes: a field that is
missing or mistyped raises `BoundaryError` here instead of leaking a
`KeyError` into the controller. Every free-text field, log line and
artifact excerpt is redacted on the way in.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
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
from atlas_reviewer.redact import RedactedText, Redactor
from atlas_reviewer.runner import ToolAbsent, ToolResult

DETAIL_CHARS = 2_000
LOG_TAIL_CHARS = 6_000
ARTIFACT_EXCERPT_CHARS = 4_000
_TIMEOUT_EXITS = frozenset({124, 137})
_CLOSING_REF = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b")
_MAX_ISSUE_REFS = 3


def _field[T](data: Any, key: str, kind: type[T]) -> T:
    value = data.get(key) if isinstance(data, Mapping) else None
    if not isinstance(value, kind) or isinstance(value, bool) is not (kind is bool):
        raise BoundaryError(
            f"GitHub response field {key!r} missing or not {kind.__name__}"
        )
    return value


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
    head_sha: str
    head_ref: str
    title: RedactedText
    body: RedactedText
    issue_refs: tuple[int, ...]


def parse_pull(data: Json, redactor: Redactor) -> PullInfo:
    head = _field(data, "head", dict)
    body = _optional_str(data, "body")
    return PullInfo(
        head_sha=_field(head, "sha", str),
        head_ref=_field(head, "ref", str),
        title=redactor(_field(data, "title", str), 300),
        body=redactor(body, DETAIL_CHARS),
        issue_refs=issue_refs(body),
    )


def issue_refs(body: str) -> tuple[int, ...]:
    refs = dict.fromkeys(int(m.group(1)) for m in _CLOSING_REF.finditer(body))
    return tuple(refs)[:_MAX_ISSUE_REFS]


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
            SourceKey(SourceKind.CHECK_RUN, _field(run, "name", str)),
            f"check_run:{_field(run, 'id', int)}",
        ),
        tool=ToolInfo(
            slug if isinstance(slug, str) else "unknown-app", UNREPORTED_VERSION
        ),
        fetched_at=fetched_at,
        conclusion=_conclusion(
            _field(run, "status", str), _optional_str(run, "conclusion")
        ),
        detail=redactor(text, DETAIL_CHARS),
    )


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


def _workflow_tool(run: Json, head_sha: str) -> ToolInfo:
    path = _optional_str(run, "path") or "unknown-workflow"
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
            SourceKey(SourceKind.WORKFLOW_RUN, _field(run, "name", str)),
            f"workflow_run:{run_id}",
        ),
        tool=_workflow_tool(run, head_sha),
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
    item = EvidenceItem(
        head_sha=_field(job, "head_sha", str),
        provenance=Provenance(
            SourceKey(SourceKind.JOB, f"{run_name} / {_field(job, 'name', str)}"),
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
        detail=redactor(_tail(raw.decode("utf-8", errors="replace"))),
    )


def _tail(text: str) -> str:
    if len(text) <= LOG_TAIL_CHARS:
        return text
    tail = text[-LOG_TAIL_CHARS:]
    return tail[tail.find("\n") + 1 :]


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
            SourceKey(SourceKind.ARTIFACT, _field(artifact, "name", str)),
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
        return Missing(key, f"not available in the runner image ({result.detail})")
    return EvidenceItem(
        head_sha=head_sha,
        provenance=Provenance(key, f"runner:{runner_name}:{result.tool.name}"),
        tool=ToolInfo(result.tool.name, result.version),
        fetched_at=fetched_at,
        conclusion=_tool_conclusion(result.exit_code),
        detail=redactor(f"exit={result.exit_code}\n{result.output}", DETAIL_CHARS),
    )
