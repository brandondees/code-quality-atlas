# SPDX-License-Identifier: MIT
from datetime import datetime

import pytest

from atlas_reviewer.classify import (
    REASON_EXPECTED_ABSENT,
    REASON_ONLY_OTHER_SHAS,
    classify,
    tally,
)
from atlas_reviewer.domain import (
    Conclusion,
    EvidenceItem,
    InvalidEventError,
    Matched,
    Missing,
    Outcome,
    PrEvent,
    SourceKey,
    SourceKind,
    Stale,
    outcome,
)
from atlas_reviewer.redact import redact

from .helpers import HEAD, OLD, item


@pytest.mark.parametrize(
    "repo,number,sha",
    [
        ("not-a-repo", 1, HEAD),
        ("o/r", 0, HEAD),
        ("o/r", True, HEAD),
        ("o/r", "1", HEAD),
        ("o/r", 1, "abc123"),
        ("o/r", 1, HEAD.upper()),
    ],
)
def test_event_must_name_one_exact_commit(repo, number, sha):
    with pytest.raises(InvalidEventError):
        PrEvent(repo, number, sha)


def test_matched_and_stale_cannot_lie_about_their_sha():
    with pytest.raises(ValueError, match="Matched"):
        Matched(item(sha=OLD), HEAD)
    with pytest.raises(ValueError, match="Stale"):
        Stale(item(sha=HEAD), HEAD)


def test_evidence_requires_aware_fetch_time():
    good = item()
    with pytest.raises(ValueError, match="timezone"):
        EvidenceItem(
            good.head_sha,
            good.provenance,
            good.tool,
            datetime(2026, 1, 1),
            good.conclusion,
            redact(""),
        )


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
