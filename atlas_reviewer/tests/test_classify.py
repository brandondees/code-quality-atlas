# SPDX-License-Identifier: MIT

import pytest

from atlas_reviewer.classify import (
    REASON_EXPECTED_ABSENT,
    REASON_ONLY_OTHER_SHAS,
    classify,
    not_rerun_failures,
    tally,
)
from atlas_reviewer.domain import (
    Conclusion,
    Matched,
    Missing,
    Outcome,
    SourceKey,
    SourceKind,
    Stale,
    outcome,
)

from .helpers import HEAD, OLD, item


def test_evidence_for_another_sha_is_stale_and_unknown():
    (evidence, missing) = classify(HEAD, [item(sha=OLD)])
    assert isinstance(evidence, Stale)
    assert outcome(evidence) is Outcome.UNKNOWN
    assert missing == Missing(
        SourceKey(SourceKind.CHECK_RUN, "gate"), REASON_ONLY_OTHER_SHAS
    )


def test_source_seen_on_both_shas_is_matched_not_missing():
    evidence = classify(HEAD, [item(sha=OLD), item(sha=HEAD)])
    assert [type(e) for e in evidence] == [Matched, Stale]
    assert outcome(evidence[0]) is Outcome.PASS


def test_expected_but_absent_is_missing_and_never_a_pass():
    key = SourceKey(SourceKind.CHECK_RUN, "security-scan")
    (missing,) = classify(HEAD, [], expected=[key])
    assert missing == Missing(key, REASON_EXPECTED_ABSENT)
    assert outcome(missing) is Outcome.UNKNOWN


def test_fetch_failures_count_as_coverage_not_duplicated_as_missing():
    key = SourceKey(SourceKind.CHECK_RUN, "gate")
    failure = Missing(key, "could not fetch: 500")
    assert classify(HEAD, [], expected=[key], failures=[failure]) == (failure,)


@pytest.mark.parametrize(
    "conclusion,expected",
    [
        (Conclusion.SUCCESS, Outcome.PASS),
        (Conclusion.FAILURE, Outcome.FAIL),
        (Conclusion.TIMED_OUT, Outcome.FAIL),
        (Conclusion.ACTION_REQUIRED, Outcome.FAIL),
        (Conclusion.PRESENT, Outcome.INFO),
        (Conclusion.NEUTRAL, Outcome.UNKNOWN),
        (Conclusion.SKIPPED, Outcome.UNKNOWN),
        (Conclusion.CANCELLED, Outcome.UNKNOWN),
        (Conclusion.PENDING, Outcome.UNKNOWN),
        (Conclusion.UNREPORTED, Outcome.UNKNOWN),
    ],
)
def test_only_success_at_the_head_sha_is_a_pass(conclusion, expected):
    assert outcome(Matched(item(conclusion=conclusion), HEAD)) is expected


def test_tally_separates_head_unknowns_from_stale():
    evidence = classify(
        HEAD,
        [
            item("a"),
            item("b", conclusion=Conclusion.FAILURE),
            item("c", conclusion=Conclusion.PENDING),
            item("d", sha=OLD),
            item("e", kind=SourceKind.ARTIFACT, conclusion=Conclusion.PRESENT),
        ],
    )
    t = tally(evidence)
    assert (t.passed, t.failed, t.unknown, t.stale, t.present) == (1, 1, 2, 1, 1)


def test_tally_counts_unread_views_apart_from_checks_without_a_result():
    failures = [
        Missing(SourceKey(SourceKind.ARTIFACT, "coverage (skipped entry 0)"), "x"),
        Missing(SourceKey(SourceKind.WORKFLOW_LOG, "ci / test"), "could not fetch"),
        Missing(SourceKey(SourceKind.CHECK_RUN, "lint"), "could not fetch"),
    ]
    t = tally(classify(HEAD, [item("a")], failures=failures))
    assert (t.passed, t.unknown, t.unread) == (1, 1, 2)


def test_a_failure_at_another_commit_without_a_head_result_is_singled_out():
    evidence = classify(
        HEAD,
        [
            item("lint", OLD, conclusion=Conclusion.FAILURE),
            item("tests", OLD, conclusion=Conclusion.TIMED_OUT),
            item("tests", HEAD),
            item("docs", OLD),
        ],
    )
    (lint,) = not_rerun_failures(evidence)
    assert (lint.item.provenance.key.name, lint.item.head_sha) == ("lint", OLD)
    assert outcome(lint) is Outcome.UNKNOWN
