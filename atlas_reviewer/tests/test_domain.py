# SPDX-License-Identifier: MIT
from datetime import datetime

import pytest

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
    evidence_key,
    outcome,
)
from atlas_reviewer.redact import redact

from .helpers import HEAD, OLD, item


@pytest.mark.parametrize(
    ("repo", "pr_number", "head_sha", "message"),
    [
        (None, 1, HEAD, "repo must be owner/name"),
        (["o/r"], 1, HEAD, "repo must be owner/name"),
        ("o/r", 1, None, "head_sha must be"),
        ("o/r", 1, 123, "head_sha must be"),
        ("o/r", True, HEAD, "pr_number must be an integer"),
        ("o/r", 0, HEAD, "pr_number must be positive"),
    ],
)
def test_an_event_field_of_the_wrong_type_is_an_invalid_event(
    repo, pr_number, head_sha, message
):
    with pytest.raises(InvalidEventError, match=message):
        PrEvent(repo, pr_number, head_sha)


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


@pytest.mark.parametrize(
    "conclusion,expected",
    [
        (Conclusion.SUCCESS, Outcome.PASS),
        (Conclusion.FAILURE, Outcome.FAIL),
        (Conclusion.ACTION_REQUIRED, Outcome.FAIL),
        (Conclusion.PENDING, Outcome.UNKNOWN),
        (Conclusion.PRESENT, Outcome.INFO),
    ],
)
def test_only_matched_evidence_has_a_verdict(conclusion, expected):
    assert outcome(Matched(item(conclusion=conclusion), HEAD)) is expected
    assert outcome(Stale(item(sha=OLD, conclusion=conclusion), HEAD)) is (
        Outcome.UNKNOWN
    )


def test_every_kind_of_evidence_has_a_key():
    key = SourceKey(SourceKind.CHECK_RUN, "gate")
    assert evidence_key(Matched(item(), HEAD)) == key
    assert evidence_key(Stale(item(sha=OLD), HEAD)) == key
    assert evidence_key(Missing(key, "absent")) == key
