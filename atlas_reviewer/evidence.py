# SPDX-License-Identifier: MIT
"""Map raw GitHub JSON and runner results into `EvidenceItem`s. Pure.

This is the validation boundary for GitHub response shapes: a field that is
missing or mistyped raises `BoundaryError` here instead of leaking a
`KeyError` into the controller. Every free-text field is redacted on the
way in.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
_LOG_MEMBER_CAP = 2_000_000
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


def _list(data: Any, key: str) -> list[Json]:
    items = _field(data, key, list)
    if not all(isinstance(i, Mapping) for i in items):
        raise BoundaryError(f"GitHub response field {key!r} holds a non-object entry")
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
    data: Json, fetched_at: datetime, redactor: Redactor
) -> tuple[EvidenceItem, ...]:
    return tuple(_check_run(r, fetched_at, redactor) for r in _list(data, "check_runs"))


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
    data: Json, fetched_at: datetime, redactor: Redactor
) -> tuple[WorkflowRun, ...]:
    return tuple(
        _workflow_run(r, fetched_at, redactor) for r in _list(data, "workflow_runs")
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


def parse_artifacts(
    data: Json, fetched_at: datetime, redactor: Redactor
) -> tuple[EvidenceItem, ...]:
    return tuple(_artifact(a, fetched_at, redactor) for a in _list(data, "artifacts"))


def _artifact(artifact: Json, fetched_at: datetime, redactor: Redactor) -> EvidenceItem:
    run = _field(artifact, "workflow_run", dict)
    artifact_id = _field(artifact, "id", int)
    expired = artifact.get("expired") is True
    detail = f"size_in_bytes={artifact.get('size_in_bytes', '?')} expired={expired} workflow_run={run.get('id', '?')}"
    return EvidenceItem(
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


def log_item(
    run: WorkflowRun, archive: bytes, fetched_at: datetime, redactor: Redactor
) -> EvidenceItem:
    source = run.item
    return EvidenceItem(
        head_sha=source.head_sha,
        provenance=Provenance(
            SourceKey(SourceKind.WORKFLOW_LOG, source.provenance.key.name),
            f"workflow_log:{run.run_id}",
        ),
        tool=source.tool,
        fetched_at=fetched_at,
        conclusion=source.conclusion,
        detail=redactor(_log_tail(archive)),
    )


def _log_tail(archive: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            parts = [_member(zf, info) for info in zf.infolist() if not info.is_dir()]
    except zipfile.BadZipFile as exc:
        raise BoundaryError(f"workflow log archive is not a zip: {exc}") from exc
    text = "\n".join(parts)
    tail = text[-LOG_TAIL_CHARS:]
    return tail[tail.find("\n") + 1 :] if len(text) > LOG_TAIL_CHARS else tail


def _member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    with zf.open(info) as fh:
        data = fh.read(_LOG_MEMBER_CAP)
    return f"--- {info.filename} ---\n" + data.decode("utf-8", errors="replace")


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
