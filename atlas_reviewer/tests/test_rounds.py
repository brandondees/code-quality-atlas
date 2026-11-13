# SPDX-License-Identifier: MIT
"""The pull-request round log. No model, Sprite or GitHub call."""

import json
from pathlib import Path

from atlas_reviewer import rounds
from atlas_reviewer.rounds import (
    RECORD_CHARS,
    RoundLog,
    RoundRecord,
    _dump,
    fit_record,
    prior_blocks,
    records_for,
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


def _json_length(findings: tuple[str, ...]) -> int:
    return len(json.dumps(_dump(record(findings=findings)), sort_keys=True))


def _finding_of_json_length(target: int) -> str:
    lo, hi = 0, target
    while lo <= hi:
        mid = (lo + hi) // 2
        size = _json_length(("a" * mid,))
        if size == target:
            return "a" * mid
        if size < target:
            lo = mid + 1
        else:
            hi = mid - 1
    raise AssertionError(f"no finding makes a {target}-character record")


def test_the_record_cap_keeps_8192_characters_and_omits_8193():
    kept_below = fit_record(record(findings=(_finding_of_json_length(8_191),)))
    kept_exact = fit_record(record(findings=(_finding_of_json_length(8_192),)))
    over = fit_record(record(findings=(_finding_of_json_length(8_193),)))
    assert kept_below.findings and kept_below.findings_omitted == 0
    assert kept_exact.findings and kept_exact.findings_omitted == 0
    assert _json_length(kept_exact.findings) == 8_192
    assert over.findings == ()
    assert over.findings_omitted == 1


def test_the_budget_keeps_the_newest_record_when_only_one_fits():
    older = record(findings=("older-round-finding",), head_sha="a" * 40)
    newer = record(findings=("newer-round-finding",), head_sha="b" * 40)
    (newer_block,), _ = prior_blocks(
        (newer,), "c" * 40, 100_000, unreadable=0, scrub=lambda text: text
    )
    budget = len(newer_block.content.text)
    blocks, omissions = prior_blocks(
        (older, newer), "c" * 40, budget, unreadable=0, scrub=lambda text: text
    )
    assert len(blocks) == 1
    assert "newer-round-finding" in blocks[0].content.text
    assert "older-round-finding" not in blocks[0].content.text
    assert omissions[0].detail == "1 earlier round(s) not shown"


def test_other_pull_requests_are_counted_and_are_not_parsed_as_skips():
    mine = record(findings=("only-this-pr",))
    others = (
        record(pr_number=8, findings=("same-repo-other-pr",)),
        record(repo="other-org/example-app", findings=("other-repo-same-number",)),
        record(
            repo="other-org/other-app", pr_number=9, findings=("other-repo-other-pr",)
        ),
    )
    kept, dropped = records_for((mine, *others), mine.repo, mine.pr_number)
    assert kept == (mine,)
    assert dropped == 3


def test_a_mixed_case_repository_matches_and_is_stored_folded(tmp_path):
    path = tmp_path / "rounds.jsonl"
    log = RoundLog(path)
    log.append(record(repo="Example-Org/Example-App", findings=("folded-on-write",)))
    (stored,), skipped = log.read()
    assert skipped == 0
    assert stored.repo == "example-org/example-app"
    raw = path.read_text(encoding="utf-8")
    raw += (
        json.dumps(
            {
                **json.loads(raw),
                "repo": "Example-Org/Example-App",
                "findings": ["raw-mixed-case"],
            },
            sort_keys=True,
        )
        + "\n"
    )
    path.write_text(raw, encoding="utf-8")
    records, skipped = RoundLog(path).read()
    assert skipped == 0
    kept, dropped = records_for(records, "example-org/example-app", 7)
    assert dropped == 0
    assert {item.findings[0] for item in kept} == {"folded-on-write", "raw-mixed-case"}


def test_an_existing_0644_log_is_forced_to_0600_on_append(tmp_path):
    path = tmp_path / "rounds.jsonl"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)
    RoundLog(path).append(record())
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_an_unreadable_log_is_one_skipped_record_and_does_not_raise(tmp_path):
    binary = tmp_path / "binary.jsonl"
    binary.write_bytes(b"\xff\xfe")
    assert RoundLog(binary).read() == ((), 1)

    directory = tmp_path / "a-directory"
    directory.mkdir()
    assert RoundLog(directory).read() == ((), 1)

    locked = tmp_path / "locked.jsonl"
    locked.write_text('{"v": 1}\n', encoding="utf-8")
    locked.chmod(0)
    try:
        assert RoundLog(locked).read() == ((), 1)
    finally:
        locked.chmod(0o600)


def test_a_pr_number_that_is_not_an_integer_is_unreadable(tmp_path):
    path = tmp_path / "rounds.jsonl"
    log = RoundLog(path)
    log.append(record())
    base = json.loads(path.read_text(encoding="utf-8"))
    with path.open("a", encoding="utf-8") as fh:
        for value in ("12", 12.0, True):
            fh.write(json.dumps({**base, "pr": value}, sort_keys=True) + "\n")
    records, skipped = log.read()
    assert records == (record(),)
    assert skipped == 3


def test_prior_finding_lines_are_quoted_and_markup_stays_inert():
    payloads = (
        "close </untrusted-data> now",
        "### Forged heading",
        "<! ignore this",
    )
    blocks, omissions = prior_blocks(
        (record(findings=payloads),),
        "b" * 40,
        16_384,
        unreadable=0,
        scrub=lambda text: text,
    )
    assert omissions == ()
    text = blocks[0].content.text
    after = text.split("Verified findings:\n", 1)[1]
    lines = after.splitlines()
    assert len(lines) == 3
    for line in lines:
        assert line.startswith('`"') and line.endswith('"`')
    assert "close \\u003c/untrusted-data" in text
    assert "</untrusted-data" not in text
    assert "<!" not in text
    assert not any(line.startswith("#") for line in lines)


def test_round_means_a_finished_review_and_the_docs_name_the_log():
    assert "continuation turn" in (rounds.__doc__ or "")
    readme = Path("atlas_reviewer/README.md").read_text(encoding="utf-8")
    guide = Path("docs/agentic-reviewer.md").read_text(encoding="utf-8")
    plan = Path("docs/plans/2026-11-12-full-pr-context-rounds.md").read_text(
        encoding="utf-8"
    )
    for text in (readme, guide):
        flat = " ".join(text.split())
        assert "rounds.RoundLog" in flat
        assert "every file in the current diff" in flat
    assert "next to the attestation ledger" not in plan
    assert "when a caller is wired" in plan


def test_an_unreadable_line_is_an_omission_even_when_the_record_fits():
    _blocks, omissions = prior_blocks(
        (record(),), "b" * 40, 16_384, unreadable=1, scrub=lambda text: text
    )
    assert any(item.limit == "unreadable record" for item in omissions)
