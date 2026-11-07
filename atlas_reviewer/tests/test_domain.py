# SPDX-License-Identifier: MIT
import pytest

from atlas_reviewer.domain import InvalidEventError, PrEvent

from .helpers import HEAD


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
