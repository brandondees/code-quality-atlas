# SPDX-License-Identifier: MIT
"""The pull-request round log. No model, Sprite or GitHub call."""

import json

from atlas_reviewer.rounds import (
    RECORD_CHARS,
    RoundLog,
    RoundRecord,
    fit_record,
    prior_blocks,
)


def record(**kw) -> RoundRecord:
    base = {
        "repo": "example-org/example-app",
        "pr_number": 7,
        "head_sha": "a" * 40,
        "lens": "tracing-correctness-and-invariants",
        "event": "COMMENT",
        "findings": ("L1 major calc.py:2 totals drift",),
        "context_partial": False,
    }
    base.update(kw)
    return RoundRecord(**base)


def test_a_round_is_stored_0600_and_a_torn_line_is_counted(tmp_path):
    path = tmp_path / "state" / "rounds.jsonl"
    log = RoundLog(path)
    log.append(record())
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    records, skipped = log.read()
    assert records == (record(),)
    assert skipped == 1


def test_a_record_over_the_cap_keeps_no_finding_prefix(tmp_path):
    huge = "y" * (RECORD_CHARS + 50)
    stored = fit_record(record(findings=(huge,)))
    assert stored.findings == ()
    assert stored.findings_omitted == 1
    assert huge not in json.dumps(stored.findings)
    blocks, omissions = prior_blocks(
        (stored,), "b" * 40, 16_384, unreadable=0, scrub=lambda text: text
    )
    assert huge not in blocks[0].content.text
    assert "y" * 40 not in blocks[0].content.text
    assert omissions[0].source == "prior atlas reviews"
    assert "were not stored" in omissions[0].detail


def test_an_unreadable_line_is_an_omission_even_when_the_record_fits():
    _blocks, omissions = prior_blocks(
        (record(),), "b" * 40, 16_384, unreadable=1, scrub=lambda text: text
    )
    assert any(item.limit == "unreadable record" for item in omissions)
