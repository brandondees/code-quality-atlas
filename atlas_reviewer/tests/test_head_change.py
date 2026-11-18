# SPDX-License-Identifier: MIT
"""The keep-or-cancel decision for a push that lands mid-review (#702).

Each behavior is a test that fails when the behavior is reverted; the
mutant each test kills is named in its body. The decision is a pure
function over the range's classification, the running review's progress
and the configured threshold, so every rule is pinned without a GitHub
or model call; `classify_delivery`'s reads are pinned against a fake
reader, the way the poster's are against a recorder transport."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from atlas_reviewer.domain import PrEvent
from atlas_reviewer.head_change import (
    CANCEL_FRACTION_ENV,
    POLICY_ENV,
    READING_CHARS,
    Progress,
    PushClass,
    PushKind,
    cancel_fraction,
    classify_delivery,
    classify_push,
    decide,
    head_change_policy,
    read_progress,
)
from atlas_reviewer.ports import BoundaryError, NotFoundError

OLD = "a" * 40
NEW = "b" * 40
BASE = "c" * 40


def _merge(parent: str, second: str) -> dict[str, object]:
    return {"sha": NEW, "parents": [{"sha": parent}, {"sha": second}]}


def _commit(sha: str) -> dict[str, object]:
    return {"sha": sha, "parents": [{"sha": OLD}]}


# ------------------------------------------------------- the classification


def test_a_range_of_base_merges_is_merge_only():
    push = classify_push([_merge(OLD, BASE)], ["src/x.py"], base_tip=BASE)
    # Mutant: the base-tip comparison dropped, which reads every merge as
    # code and cancels reviews a merge of main should have kept.
    assert push.kind is PushKind.MERGE_ONLY


def test_a_feature_branch_merge_is_not_a_base_merge():
    other = "d" * 40
    push = classify_push([_merge(OLD, other)], ["src/x.py"], base_tip=BASE)
    # Mutant: every merge treated as a base merge, which would keep a
    # review through a push that merges new code in.
    assert push.kind is PushKind.CODE


def test_a_regular_commit_is_never_a_base_merge():
    push = classify_push([_commit(NEW)], ["src/x.py"], base_tip=BASE)
    assert push.kind is PushKind.CODE


def test_docs_and_tests_only_paths_are_their_own_kind():
    push = classify_push(
        [_commit(NEW)], ["docs/guide.md", "tests/test_x.py", "README.md"], base_tip=BASE
    )
    assert push.kind is PushKind.DOCS_TESTS


def test_one_code_path_makes_the_push_code():
    push = classify_push([_commit(NEW)], ["docs/guide.md", "src/x.py"], base_tip=BASE)
    assert push.kind is PushKind.CODE


def test_a_merge_whose_base_side_cannot_be_identified_reads_as_code():
    push = classify_push([_merge(OLD, BASE)], ["src/x.py"], base_tip=None)
    # Mutant: the unknown-tip merge claimed benign, keeping reviews
    # through pushes no evidence called benign.
    assert push.kind is PushKind.CODE


def test_a_cut_commit_list_reads_as_code():
    push = classify_push([_commit(NEW)], ["src/x.py"], base_tip=BASE, truncated=True)
    assert push.kind is PushKind.CODE


def test_an_empty_range_changes_nothing_the_review_reads():
    push = classify_push([], [], base_tip=BASE)
    assert push.kind is PushKind.MERGE_ONLY


def test_the_push_carries_its_changed_paths():
    push = classify_push([_commit(NEW)], ["src/x.py", "docs/a.md"], base_tip=BASE)
    assert push.paths == ("src/x.py", "docs/a.md")


# ------------------------------------------------------------- the decision


def _progress(
    done: int = 0,
    total: int = 4,
    calls: int = 0,
    settled: str = "0",
    reservation: str = "10",
    reading: tuple[str, ...] = (),
) -> Progress:
    return Progress(
        frozenset(f"lens{n}" for n in range(done)),
        total,
        calls,
        settled_usd=Decimal(settled),
        reservation_usd=Decimal(reservation),
        reading=frozenset(reading),
    )


def _code() -> PushClass:
    return PushClass(PushKind.CODE, ("src/x.py",))


def test_a_merge_of_the_base_branch_keeps_a_running_review():
    push = classify_push([_merge(OLD, BASE)], ["src/x.py"], base_tip=BASE)
    verdict = decide(push, _progress(done=0), 0.5)
    assert verdict.cancel is False


def test_a_docs_and_tests_push_keeps_a_running_review():
    push = classify_push([_commit(NEW)], ["docs/a.md"], base_tip=BASE)
    assert decide(push, None, 0.5).cancel is False


def test_a_code_push_that_touches_no_file_still_being_read_is_kept():
    push = PushClass(PushKind.CODE, ("src/other.py",))
    progress = _progress(done=1, reading=("src/x.py",))
    verdict = decide(push, progress, 0.5)
    # Mutant: the overlap check dropped, which cancels reviews whose
    # remaining files the push never touches.
    assert verdict.cancel is False
    assert "still reading" in verdict.reason


def test_an_early_code_push_cancels_the_running_review():
    verdict = decide(
        _code(), _progress(done=1, total=4, settled="1", reservation="10"), 0.5
    )
    # Mutant: the cancel branch dropped, which would keep every review
    # and never save the spend the issue exists to save.
    assert verdict.cancel is True
    assert "early" in verdict.reason


def test_a_review_past_the_threshold_is_kept_for_a_delta_review():
    verdict = decide(
        _code(),
        _progress(done=3, total=4, settled="8", reservation="10"),
        0.5,
    )
    assert verdict.cancel is False
    assert "delta" in verdict.reason


def test_missing_progress_reads_as_early():
    verdict = decide(_code(), None, 0.5)
    # Mutant: missing progress read as fully spent, which would keep a
    # review that has settled nothing.
    assert verdict.cancel is True


def test_either_fraction_under_the_threshold_cancels():
    # Every planned lens settled, but a tenth of the budget spent: the
    # spend measure alone puts most of the remaining spend on stale code.
    verdict = decide(
        _code(),
        _progress(done=4, total=4, settled="1", reservation="10"),
        0.5,
    )
    assert verdict.cancel is True


def test_the_threshold_is_configurable():
    progress = _progress(done=3, total=4, settled="6", reservation="10")
    # Mutant: the threshold hardcoded to one side, which would make the
    # setting a no-op in one direction.
    assert decide(_code(), progress, 0.7).cancel is True
    assert decide(_code(), progress, 0.5).cancel is False


def test_an_unclassifiable_push_keeps_the_review():
    verdict = decide(None, _progress(done=0, total=4), 0.5)
    assert verdict.cancel is False
    assert "classified" in verdict.reason


def test_a_posting_review_is_never_cancelled():
    verdict = decide(_code(), None, 0.5, posting=True)
    assert verdict.cancel is False
    assert verdict.lens_fraction == 1.0


def test_the_decision_carries_the_fractions_it_was_made_from():
    verdict = decide(
        _code(), _progress(done=1, total=4, settled="2", reservation="10"), 0.5
    )
    assert verdict.lens_fraction == 0.25
    assert verdict.spend_fraction == 0.2


# ------------------------------------------------------------ the progress


def _event(**fields: object) -> str:
    return json.dumps(
        {"seq": 1, "phase": "progress", "step": "lens settled", "status": "ok"} | fields
    )


def _write(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_progress_is_read_from_the_events_file(tmp_path):
    path = _write(
        tmp_path / "events.jsonl",
        json.dumps({"phase": "service", "step": "other", "fields": {}}),
        _event(
            lens="tracing",
            lenses_done=1,
            lenses_total=4,
            calls=2,
            committed_usd="0.40",
            settled_usd="0.30",
            reservation_usd="10",
            reading="src/x.py src/y.py",
        ),
        _event(
            lens="security",
            lenses_done=2,
            lenses_total=4,
            calls=5,
            committed_usd="1.00",
            settled_usd="0.80",
            reservation_usd="10",
            reading="src/x.py",
        ),
    )
    progress = read_progress(path)
    assert progress is not None
    assert progress.lenses_done == frozenset({"tracing", "security"})
    assert progress.lenses_total == 4
    assert progress.calls == 5
    assert progress.settled_usd == Decimal("0.80")
    assert progress.reservation_usd == Decimal(10)
    assert progress.reading == frozenset({"src/x.py"})


def test_the_rotated_file_is_read_before_the_current_one(tmp_path):
    older = _write(tmp_path / "events.jsonl.1", _event(lens="tracing", lenses_total=4))
    newer = _write(
        tmp_path / "events.jsonl",
        _event(lens="security", lenses_total=4, calls=9),
    )
    progress = read_progress(older, newer)
    assert progress is not None
    # Mutant: the current file read first, which would let a rotation
    # hide a lens settled before it.
    assert progress.lenses_done == frozenset({"tracing", "security"})
    assert progress.calls == 9


def test_a_garbled_or_missing_events_file_reads_as_no_progress(tmp_path):
    assert read_progress(tmp_path / "absent.jsonl") is None
    garbled = tmp_path / "events.jsonl"
    garbled.write_bytes(b"\xff\xfe not json\n")
    assert read_progress(garbled) is None


def test_progress_fields_that_cannot_be_read_contribute_nothing(tmp_path):
    path = _write(
        tmp_path / "events.jsonl",
        _event(lenses_total=-5, calls=True, settled_usd="not-a-number"),
        _event(lens="tracing", lenses_total=4),
    )
    progress = read_progress(path)
    assert progress is not None
    assert progress.calls == 0
    assert progress.settled_usd == Decimal(0)
    assert progress.lenses_total == 4


def test_a_reading_list_over_its_cap_is_truncated_not_failed(tmp_path):
    path = _write(
        tmp_path / "events.jsonl",
        _event(lens="tracing", lenses_total=1, reading="p " * 4_100),
    )
    progress = read_progress(path)
    assert progress is not None
    assert progress.reading
    assert sum(len(path) + 1 for path in progress.reading) - 1 <= READING_CHARS


# ------------------------------------------------------ the delivery reads


class _FakeGitHub:
    def __init__(self, *replies: object) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[str, str, str]] = []

    def get_pull(self, repo: str, number: int) -> object:
        self.calls.append(("get_pull", repo, str(number)))
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def get_compare(self, repo: str, base: str, head: str) -> object:
        self.calls.append(("get_compare", repo, f"{base}...{head}"))
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _pull() -> dict[str, object]:
    return {"base": {"ref": "main"}}


def _compare(
    commits: list[dict[str, object]], files: list[str], merge_base: str
) -> dict[str, object]:
    return {
        "commits": commits,
        "total_commits": len(commits),
        "merge_base_commit": {"sha": merge_base},
        "files": [{"filename": path} for path in files],
    }


def test_the_range_is_classified_from_three_reads():
    github = _FakeGitHub(
        _pull(),
        _compare([_merge(OLD, BASE)], ["src/x.py"], OLD),
        {"merge_base_commit": {"sha": BASE}},
    )
    push = classify_delivery(github, PrEvent("o/r", 7, NEW), PrEvent("o/r", 7, OLD))
    assert push.kind is PushKind.MERGE_ONLY
    assert github.calls == [
        ("get_pull", "o/r", "7"),
        ("get_compare", "o/r", f"{OLD}...{NEW}"),
        ("get_compare", "o/r", f"main...{NEW}"),
    ]


def test_a_diverged_history_reads_as_code_without_the_base_read():
    github = _FakeGitHub(
        _pull(),
        _compare([_commit(NEW)], ["src/x.py"], BASE),
    )
    push = classify_delivery(github, PrEvent("o/r", 7, NEW), PrEvent("o/r", 7, OLD))
    assert push.kind is PushKind.CODE
    assert len(github.calls) == 2


def test_a_pull_without_a_base_ref_is_a_boundary_error():
    github = _FakeGitHub({})
    with pytest.raises(BoundaryError):
        classify_delivery(github, PrEvent("o/r", 7, NEW), PrEvent("o/r", 7, OLD))


def test_a_failed_read_propagates_to_the_caller():
    github = _FakeGitHub(NotFoundError("gone"))
    with pytest.raises(NotFoundError):
        classify_delivery(github, PrEvent("o/r", 7, NEW), PrEvent("o/r", 7, OLD))


# --------------------------------------------------------- the environment


def test_the_policy_defaults_to_keep_and_refuses_an_unknown_value():
    assert head_change_policy({}) == "keep"
    assert head_change_policy({POLICY_ENV: "cancel"}) == "cancel"
    with pytest.raises(ValueError):
        head_change_policy({POLICY_ENV: "maybe"})


def test_the_cancel_fraction_defaults_to_half_and_is_bounded():
    assert cancel_fraction({}) == 0.5
    assert cancel_fraction({CANCEL_FRACTION_ENV: "0.25"}) == 0.25
    with pytest.raises(ValueError):
        cancel_fraction({CANCEL_FRACTION_ENV: "1.5"})
    with pytest.raises(ValueError):
        cancel_fraction({CANCEL_FRACTION_ENV: "half"})
