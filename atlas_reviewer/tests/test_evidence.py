# SPDX-License-Identifier: MIT
import pytest

from atlas_reviewer.archive import ArchiveMember, ArchiveRead
from atlas_reviewer.domain import Conclusion, Missing, SourceKey, SourceKind
from atlas_reviewer.evidence import (
    LOG_TAIL_CHARS,
    artifact_contents_item,
    issue_refs,
    job_log_item,
    parse_artifacts,
    parse_check_runs,
    parse_jobs,
    parse_pull,
    parse_workflow_runs,
    tool_evidence,
)
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import ToolAbsent, ToolRan, ToolSpec

from .helpers import HEAD, NOW, fake_token

R = Redactor()
RUN = {
    "id": 5,
    "name": "ci",
    "head_sha": HEAD,
    "status": "completed",
    "conclusion": "failure",
    "path": "ci.yml",
}


@pytest.mark.parametrize(
    "items",
    [
        [1],
        [{"name": "x", "head_sha": HEAD, "status": "completed", "id": True}],
        [{"name": 3, "head_sha": HEAD, "status": "completed", "id": 1}],
    ],
)
def test_malformed_github_shapes_are_boundary_errors(items):
    with pytest.raises(BoundaryError):
        parse_check_runs(items, NOW, R)


def test_check_run_records_provenance_tool_and_pending_state():
    items = [
        {
            "id": 9,
            "name": "gate",
            "head_sha": HEAD,
            "status": "queued",
            "app": "?",
            "output": None,
        }
    ]
    (item,) = parse_check_runs(items, NOW, R)
    assert item.provenance.source_id == "check_run:9"
    assert item.tool.name == "unknown-app"
    assert item.conclusion is Conclusion.PENDING
    assert item.fetched_at == NOW


def test_unrecognised_conclusion_is_unreported():
    run = {**RUN, "conclusion": "something-new"}
    (wf,) = parse_workflow_runs([run], NOW, R)
    assert wf.item.conclusion is Conclusion.UNREPORTED
    assert wf.item.tool.version == f"ci.yml@{HEAD[:12]}"


def test_expired_artifact_has_no_verdict():
    art = {
        "id": 1,
        "name": "cov",
        "expired": True,
        "size_in_bytes": True,
        "workflow_run": {"id": 5, "head_sha": HEAD},
    }
    (ref,) = parse_artifacts([art], NOW, R)
    assert ref.item.conclusion is Conclusion.UNREPORTED
    assert ref.item.provenance.key.kind is SourceKind.ARTIFACT
    assert ref.expired is True
    assert ref.size_in_bytes is None


def _job(**overrides):
    (wf,) = parse_workflow_runs([RUN], NOW, R)
    job = {
        "id": 77,
        "name": "test",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "failure",
        **overrides,
    }
    return parse_jobs([job], wf, NOW, R)[0]


def test_job_carries_its_run_name_sha_and_provenance():
    job = _job()
    assert job.item.provenance.key == SourceKey(SourceKind.JOB, "ci / test")
    assert job.item.provenance.source_id == "job:77"
    assert job.item.conclusion is Conclusion.FAILURE
    with pytest.raises(BoundaryError):
        _job(head_sha=None)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.github.com/repos/o/r/check-runs/9001", 9001),
        ("https://api.github.com/repos/o/r/check-runs/9001/annotations", None),
        ("https://api.github.com/repos/o/r/check-suites/9001", None),
        (None, None),
        (42, None),
    ],
)
def test_job_check_run_link_comes_only_from_the_documented_url(url, expected):
    assert _job(check_run_url=url).check_run_id == expected


def test_job_without_check_run_url_has_no_check_run_link():
    assert _job().check_run_id is None


def test_job_log_tail_keeps_the_end_and_is_redacted():
    text = "x" * (LOG_TAIL_CHARS * 2) + "\npassword=supersecretvalue\nFAILED test_a"
    item = job_log_item(_job(), text.encode(), NOW, R)
    assert item.detail.text.endswith("FAILED test_a")
    assert "supersecretvalue" not in item.detail.text
    assert item.provenance.source_id == "job_log:77"
    assert item.provenance.key.kind is SourceKind.WORKFLOW_LOG
    assert job_log_item(_job(), b"short", NOW, R).detail.text == "short"


def test_a_private_key_straddling_the_log_tail_cut_is_still_redacted():
    body = "\n".join(["K" * 63] * (LOG_TAIL_CHARS // 64))
    key = f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----"
    text = "x" * LOG_TAIL_CHARS + "\n" + key + "\nFAILED test_a"
    item = job_log_item(_job(), text.encode(), NOW, R)
    assert "KKKK" not in item.detail.text
    assert item.detail.text.endswith("[REDACTED:private-key]\nFAILED test_a")
    assert item.detail.truncated_from is not None


def test_artifact_contents_are_redacted_excerpts_with_provenance():
    art = {"id": 4, "name": "cov", "workflow_run": {"id": 5, "head_sha": HEAD}}
    (ref,) = parse_artifacts([art], NOW, R)
    read = ArchiveRead((ArchiveMember("a.txt", "token=abcdefghijkl"),))
    item = artifact_contents_item(ref, read, NOW, R)
    assert item.provenance.key.name == "cov (contents)"
    assert item.provenance.source_id == "artifact:4:zip"
    assert item.head_sha == HEAD
    assert "abcdefghijkl" not in item.detail.text
    empty = artifact_contents_item(ref, ArchiveRead(), NOW, R)
    assert empty.detail.text == "(no readable text entries)"


def test_pull_parsing_extracts_closing_issue_refs_only():
    pull = {"title": "t", "body": None, "head": {"sha": HEAD, "ref": "b"}}
    assert parse_pull(pull, R).issue_refs == ()
    assert issue_refs("Fixes #7, closes #8 and mentions #9; resolved #7 #1") == (7, 8)


@pytest.mark.parametrize(
    ("value", "parsed"), [(3, 3), (0, 0), (-1, None), (True, None), ("3", None)]
)
def test_pull_parsing_keeps_only_a_usable_changed_file_count(value, parsed):
    pull = {"title": "t", "head": {"sha": HEAD, "ref": "b"}, "changed_files": value}
    assert parse_pull(pull, R).changed_files == parsed
    del pull["changed_files"]
    assert parse_pull(pull, R).changed_files is None


def test_an_oversized_issue_ref_is_skipped_and_parsing_stops_at_three():
    assert issue_refs("Fixes #" + "9" * 5000 + " fixes #4") == (4,)
    assert issue_refs("fixes #1 fixes #1 fixes #2 fixes #3 fixes #4") == (1, 2, 3)


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
    spec = ToolSpec("ruff", "ruff", "v", "r")
    item = tool_evidence(
        ToolRan(spec, "ruff 1", exit_code, "out"), HEAD, "cqa-rev-x", NOW, R
    )
    assert item.conclusion is conclusion
    assert item.tool.version == "ruff 1"


def test_absent_tool_is_missing():
    result = tool_evidence(
        ToolAbsent(ToolSpec("ruff", "ruff", "v", "r"), "exit 127"),
        HEAD,
        "cqa-rev-x",
        NOW,
        R,
    )
    assert isinstance(result, Missing)
    assert "exit 127" in result.reason


def test_tool_reported_versions_and_absence_details_are_redacted():
    secret = "opaque-" + fake_token("", 24)
    spec = ToolSpec("ruff", "ruff", "v", "r")
    redactor = Redactor((secret,))
    ran = tool_evidence(
        ToolRan(spec, f"ruff 1 {secret}", 0, ""), HEAD, "cqa-rev-x", NOW, redactor
    )
    absent = tool_evidence(
        ToolAbsent(spec, f"exit 127 {secret}"), HEAD, "cqa-rev-x", NOW, redactor
    )
    assert ran.tool.version.startswith("ruff 1 [REDACTED")
    assert isinstance(absent, Missing)
    assert secret not in absent.reason
    assert "exit 127 [REDACTED" in absent.reason
