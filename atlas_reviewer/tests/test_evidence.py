# SPDX-License-Identifier: MIT
import io
import zipfile

import pytest

from atlas_reviewer.domain import Conclusion, Missing, SourceKind
from atlas_reviewer.evidence import (
    LOG_TAIL_CHARS,
    issue_refs,
    log_item,
    parse_artifacts,
    parse_check_runs,
    parse_pull,
    parse_workflow_runs,
    tool_evidence,
)
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import ToolAbsent, ToolRan, ToolSpec

from .helpers import HEAD, NOW

R = Redactor()
RUN = {
    "id": 5,
    "name": "ci",
    "head_sha": HEAD,
    "status": "completed",
    "conclusion": "failure",
    "path": "ci.yml",
}


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("job/1.txt", text)
        zf.writestr("job/", "")
    return buf.getvalue()


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"check_runs": "nope"},
        {"check_runs": [1]},
        {
            "check_runs": [
                {"name": "x", "head_sha": HEAD, "status": "completed", "id": True}
            ]
        },
        {"check_runs": [{"name": 3, "head_sha": HEAD, "status": "completed", "id": 1}]},
    ],
)
def test_malformed_github_shapes_are_boundary_errors(data):
    with pytest.raises(BoundaryError):
        parse_check_runs(data, NOW, R)


def test_check_run_records_provenance_tool_and_pending_state():
    data = {
        "check_runs": [
            {
                "id": 9,
                "name": "gate",
                "head_sha": HEAD,
                "status": "queued",
                "app": "?",
                "output": None,
            }
        ]
    }
    (item,) = parse_check_runs(data, NOW, R)
    assert item.provenance.source_id == "check_run:9"
    assert item.tool.name == "unknown-app"
    assert item.conclusion is Conclusion.PENDING
    assert item.fetched_at == NOW


def test_unrecognised_conclusion_is_unreported():
    run = {**RUN, "conclusion": "something-new"}
    (wf,) = parse_workflow_runs({"workflow_runs": [run]}, NOW, R)
    assert wf.item.conclusion is Conclusion.UNREPORTED
    assert wf.item.tool.version == f"ci.yml@{HEAD[:12]}"


def test_expired_artifact_has_no_verdict():
    art = {
        "id": 1,
        "name": "cov",
        "expired": True,
        "workflow_run": {"id": 5, "head_sha": HEAD},
    }
    (item,) = parse_artifacts({"artifacts": [art]}, NOW, R)
    assert item.conclusion is Conclusion.UNREPORTED
    assert item.provenance.key.kind is SourceKind.ARTIFACT


def test_log_tail_keeps_the_end_and_is_redacted():
    (wf,) = parse_workflow_runs({"workflow_runs": [RUN]}, NOW, R)
    text = "x" * (LOG_TAIL_CHARS * 2) + "\npassword=supersecretvalue\nFAILED test_a"
    item = log_item(wf, _zip(text), NOW, R)
    assert item.detail.text.endswith("FAILED test_a")
    assert "supersecretvalue" not in item.detail.text
    assert item.provenance.source_id == "workflow_log:5"


def test_corrupt_log_archive_is_a_boundary_error():
    (wf,) = parse_workflow_runs({"workflow_runs": [RUN]}, NOW, R)
    with pytest.raises(BoundaryError):
        log_item(wf, b"not a zip", NOW, R)


def test_pull_parsing_extracts_closing_issue_refs_only():
    pull = {"title": "t", "body": None, "head": {"sha": HEAD, "ref": "b"}}
    assert parse_pull(pull, R).issue_refs == ()
    assert issue_refs("Fixes #7, closes #8 and mentions #9; resolved #7 #1") == (7, 8)


@pytest.mark.parametrize(
    "exit_code,conclusion",
    [
        (0, Conclusion.SUCCESS),
        (1, Conclusion.FAILURE),
        (124, Conclusion.TIMED_OUT),
        (None, Conclusion.UNREPORTED),
    ],
)
def test_tool_exit_codes_map_to_conclusions(exit_code, conclusion):
    spec = ToolSpec("ruff", "v", "r")
    item = tool_evidence(
        ToolRan(spec, "ruff 1", exit_code, "out"), HEAD, "cqa-rev-x", NOW, R
    )
    assert item.conclusion is conclusion
    assert item.tool.version == "ruff 1"


def test_absent_tool_is_missing():
    result = tool_evidence(
        ToolAbsent(ToolSpec("ruff", "v", "r"), "exit 127"), HEAD, "cqa-rev-x", NOW, R
    )
    assert isinstance(result, Missing)
    assert "exit 127" in result.reason
