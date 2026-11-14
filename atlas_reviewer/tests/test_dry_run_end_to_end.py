# SPDX-License-Identifier: MIT
"""The shipped dry run, end to end: the real CLI entry, the shipped
sample-pr fixture, and a lens script per verdict class. Everything here is
offline and credential-free — `env={}` is the whole environment the CLI
gets — and the assertions pin the outcomes a reviewer can repeat: the
draft's event, the coverage gate, the exit code, and the safety hooks
that must have actually run."""

import io
import json
import subprocess
import sys
from pathlib import Path

from atlas_reviewer import cli
from atlas_reviewer.verdict import STATUS_PREFIX

from .helpers import FIXTURE

EVENT = str(FIXTURE / "event.json")
SCENARIOS = FIXTURE / "scenarios"


def run_dry_run(tmp_path, *extra):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "agentic-review",
            "--event",
            EVENT,
            "--dry-run",
            *extra,
        ],
        env={},
        out=out,
        err=err,
    )
    return code, out.getvalue(), err.getvalue()


def status_line(draft: str) -> dict:
    first = draft.splitlines()[0]
    assert first.startswith(STATUS_PREFIX)
    return json.loads(first.removeprefix(STATUS_PREFIX).removesuffix("-->"))


def scenario(name: str) -> str:
    return str(SCENARIOS / f"{name}.json")


def test_the_default_dry_run_requests_changes_for_a_verified_blocker(tmp_path):
    """The shipped scenario: one verified introduced Blocker with its quote
    verified against the fixture's head tree, complete coverage, exit 5."""
    events = tmp_path / "events.jsonl"
    code, _out, err = run_dry_run(
        tmp_path, "--events", str(events), "--out", str(tmp_path / "draft.md")
    )
    assert code == cli.EXIT_CHANGES_REQUESTED, err
    draft = (tmp_path / "draft.md").read_text(encoding="utf-8")
    status = status_line(draft)
    assert status["mode"] == "agentic"
    assert status["review_event"] == "REQUEST_CHANGES"
    assert status["proposed_event"] == "REQUEST_CHANGES"
    assert status["coverage_complete"] is True
    assert status["changed_files"] == 2
    assert status["unreviewed_files"] == 0
    assert status["verified_findings"] == 1
    assert "REVIEW INCOMPLETE" not in draft
    assert "**Review event: REQUEST_CHANGES.** Verdict: block." in draft
    assert (
        '- **L1-F1** [blocker, defect, route: eng, introduced] `"calc.py:4"` '
        "(tracing-correctness-and-invariants)" in draft
    )
    # The committed secrets the diff carries are controller findings, and
    # their values are scrubbed from everything the run wrote.
    assert "## Possible committed secrets (controller findings)" in draft
    assert 'possible committed secret (aws-key-id) in `"settings.ini:2"`' in draft
    assert "AKIAIOSFODNN7EXAMPLE" not in draft
    # The runner lifecycle ran for real: the cleanup was verified, not
    # skipped, and the egress policy was set and read back as deny-all.
    assert "Runner: completed; cleanup destroyed (verified absent)." in draft
    recorded = [json.loads(line) for line in events.read_text().splitlines()]
    read_back = [
        event
        for event in recorded
        if event["phase"] == "egress" and event["step"] == "read back"
    ]
    assert read_back and all(event["deny_all"] is True for event in read_back)


def test_an_approved_dry_run_exits_zero(tmp_path):
    code, out, err = run_dry_run(tmp_path, "--lens-script", scenario("approve"))
    assert code == cli.EXIT_OK, err
    status = status_line(out)
    assert status["review_event"] == "APPROVE"
    assert status["proposed_event"] == "APPROVE"
    assert status["coverage_complete"] is True
    assert status["verified_findings"] == 0
    assert "No verified findings." in out


def test_a_verified_major_is_a_comment_with_a_verified_removed_line(tmp_path):
    """D55: a verified introduced Major or Minor is approve-with-changes
    (COMMENT), and a quote of a removed line verifies as `removed lines`."""
    code, out, err = run_dry_run(tmp_path, "--lens-script", scenario("comment"))
    assert code == cli.EXIT_OK, err
    status = status_line(out)
    assert status["review_event"] == "COMMENT"
    assert status["proposed_event"] == "COMMENT"
    assert status["coverage_complete"] is True
    assert status["verified_findings"] == 2
    assert "**Review event: COMMENT.** Verdict: approve with changes." in out
    assert "[major, defect, route: eng, introduced]" in out
    assert "[minor, defect, route: eng, introduced, removed lines]" in out


def test_a_coverage_gap_is_not_approvable_and_names_the_unread_file(tmp_path):
    code, out, err = run_dry_run(tmp_path, "--lens-script", scenario("gap"))
    assert code == cli.EXIT_INCOMPLETE, err
    status = status_line(out)
    assert status["coverage_complete"] is False
    assert status["unreviewed_files"] == 1
    assert status["review_event"] == "COMMENT"
    assert "REVIEW INCOMPLETE -- not approvable." in out
    assert '"settings.ini"' in out
    assert "1 changed file not read in full, highest risk first" in out


def test_a_dropped_finding_is_named_and_blocks_approval(tmp_path):
    code, out, err = run_dry_run(tmp_path, "--lens-script", scenario("drop"))
    assert code == cli.EXIT_INCOMPLETE, err
    status = status_line(out)
    assert status["coverage_complete"] is False
    assert status["review_event"] == "COMMENT"
    assert "## Dropped findings (left out of this review)" in out
    assert "raw severity 'severe'" in out


def test_a_scenario_file_outside_the_contract_is_refused_before_a_run(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text(
        json.dumps(
            {
                "findings": {
                    "lens": [
                        {
                            "location": "calc.py:1",
                            "evidence": "x",
                            "severity": "blocker",
                            "valence": "maybe",
                            "route": "eng",
                            "attribution": "introduced",
                            "finding": "f",
                            "fix": "x",
                        }
                    ]
                }
            }
        )
    )
    code, out, err = run_dry_run(tmp_path, "--lens-script", str(broken))
    assert code == cli.EXIT_USAGE
    assert "breaks the finding contract" in err
    assert out == ""


def test_a_missing_scenario_file_is_refused(tmp_path):
    code, out, err = run_dry_run(tmp_path, "--lens-script", str(tmp_path / "no.json"))
    assert code == cli.EXIT_USAGE
    assert "does not exist" in err
    assert out == ""


def test_a_lens_script_cannot_reach_a_live_run(tmp_path):
    """The flag is a dry-run fixture: a live run refuses it before anything
    else, so a canned reply can never stand in for a real model."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "agentic-review",
            "--event",
            EVENT,
            "--lens-script",
            scenario("approve"),
        ],
        env={},
        out=out,
        err=err,
    )
    assert code == cli.EXIT_USAGE
    assert "--lens-script is a dry-run fixture" in err.getvalue()
    assert out.getvalue() == ""


def test_the_shipped_command_runs_with_no_environment_at_all(tmp_path):
    """The exact command a reviewer runs, as a real process, with an empty
    environment: no credentials, no model key, no network configuration."""
    draft = tmp_path / "draft.md"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "atlas_reviewer",
            "--state-dir",
            str(tmp_path / "state"),
            "agentic-review",
            "--event",
            str(FIXTURE / "event.json"),
            "--dry-run",
            "--out",
            str(draft),
        ],
        env={},
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent.parent,
        check=False,
    )
    assert done.returncode == cli.EXIT_CHANGES_REQUESTED, done.stderr
    assert done.stdout.startswith(f"review draft written to {draft}\n")
    assert "review event: REQUEST_CHANGES" in done.stdout
    assert done.stderr == ""
    status = status_line(draft.read_text(encoding="utf-8"))
    assert status["review_event"] == "REQUEST_CHANGES"
    assert status["coverage_complete"] is True
