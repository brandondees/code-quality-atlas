# SPDX-License-Identifier: MIT
"""The repo-narrowed admission config: parsing the base-ref ``REVIEW.md``
lines and the narrowing of an already-admitted delivery."""

import json

from atlas_reviewer.service_admit import (
    BASE_BRANCH_REASON,
    NO_NARROWING,
    SKIP_EVENT_REASON,
    narrow,
    parse_repo_admission,
)


def _payload(
    action="opened",
    *,
    labels=(),
    base_ref="main",
):
    pull = {
        "number": 7,
        "head": {"sha": "a" * 40},
        "base": {"ref": base_ref, "repo": {"full_name": "o/r"}},
        "labels": [{"name": label} for label in labels],
    }
    return {"action": action, "pull_request": pull}


def _lines(**keys):
    text = ""
    for key, value in keys.items():
        text += f"review_{key}: {value}\n"
    return text


def test_no_text_and_no_lines_read_as_no_narrowing():
    for text in (None, "", "\n", "# only a comment\n", "prose, not config\n"):
        assert parse_repo_admission(text) == NO_NARROWING
        assert parse_repo_admission(text).notes == ()


def test_every_key_parses_its_comma_separated_entries():
    admission = parse_repo_admission(
        _lines(
            base_include="main, release*",
            base_exclude="draft/*",
            skip_events="opened, synchronize",
        )
    )
    assert admission.base_include == ("main", "release*")
    assert admission.base_exclude == ("draft/*",)
    assert admission.skip_events == frozenset({"opened", "synchronize"})
    assert admission.notes == ()


def test_a_comment_after_the_value_is_not_part_of_it():
    admission = parse_repo_admission("review_base_include: main # trunk only\n")
    assert admission.base_include == ("main",)
    assert admission.notes == ()


def test_a_bare_key_is_unusable_and_named():
    admission = parse_repo_admission("review_base_include:\n")
    assert admission.base_include == ()
    assert len(admission.notes) == 1
    assert "review_base_include" in admission.notes[0]
    assert "ignored" in admission.notes[0]


def test_an_entry_outside_its_key_grammar_is_unusable_and_named():
    # A skip event that is not one of the three accepted actions.
    unusable_event = parse_repo_admission("review_skip_events: closed\n")
    assert unusable_event.skip_events == frozenset()
    assert unusable_event.notes
    # A base-branch entry with a glob the grammar does not carry.
    assert parse_repo_admission("review_base_include: feat*x\n").base_include == ()
    # An empty entry, an over-long branch name, and a control character.
    assert parse_repo_admission("review_base_exclude: a,,b\n").base_exclude == ()
    over = "x" * 65
    assert parse_repo_admission(f"review_base_include: {over}\n").base_include == ()
    assert parse_repo_admission("review_base_exclude: bad\x01name\n").base_exclude == ()


def test_a_key_that_appears_twice_is_unusable_and_named():
    admission = parse_repo_admission(
        "review_base_include: one\ndocumentation only\nreview_base_include: two\n"
    )
    assert admission.base_include == ()
    assert len(admission.notes) == 1
    assert "review_base_include" in admission.notes[0]


def test_more_entries_than_the_cap_is_unusable():
    entries = ", ".join(f"branch-{i}" for i in range(33))
    admission = parse_repo_admission(f"review_base_include: {entries}\n")
    assert admission.base_include == ()
    assert "review_base_include" in admission.notes[0]
    at_cap = ", ".join(f"branch-{i}" for i in range(32))
    assert parse_repo_admission(f"review_base_include: {at_cap}\n") != NO_NARROWING


def test_every_unusable_key_is_named_once_and_a_repeat_adds_no_note():
    text = (
        "review_base_include: bad\x01\n"
        "review_base_exclude: bad\x01\n"
        "review_skip_events: closed\n"
        "review_base_include: also-bad!\n"
        "review_skip_events: opened extra\n"
    )
    notes = parse_repo_admission(text).notes
    assert len(notes) == 3
    assert all("ignored" in note for note in notes)


def test_one_bad_line_leaves_the_other_keys_parsed():
    admission = parse_repo_admission(
        "review_skip_events: opened\nreview_base_exclude: not a branch!\n"
    )
    assert admission.skip_events == frozenset({"opened"})
    assert admission.base_exclude == ()
    assert len(admission.notes) == 1


def test_a_label_rule_cannot_narrow():
    """The label filters are deliberately absent: the PR author can set
    labels, so a skip rule on them would let an author opt their own PR
    out of review. A label line is not an admission key -- it narrows
    nothing, and naming unknown keys is the shared config parser's
    surface, not this slice's."""
    admission = parse_repo_admission(
        "review_required_labels: priority\nreview_skip_labels: wip\n"
    )
    assert admission == NO_NARROWING
    assert narrow(_payload(labels=("wip",)), admission) is None


def test_a_skip_event_removes_only_that_event():
    admission = parse_repo_admission("review_skip_events: synchronize\n")
    assert narrow(_payload("synchronize"), admission).reason == SKIP_EVENT_REASON
    assert narrow(_payload("opened"), admission) is None
    assert narrow(_payload("ready_for_review"), admission) is None


def test_base_include_limits_review_to_the_named_branches():
    admission = parse_repo_admission("review_base_include: main, release*\n")
    assert narrow(_payload(base_ref="main"), admission) is None
    assert narrow(_payload(base_ref="release-1"), admission) is None
    skipped = narrow(_payload(base_ref="feature/x"), admission)
    assert skipped is not None and skipped.reason == BASE_BRANCH_REASON


def test_a_base_ref_the_shape_does_not_carry_matches_no_include():
    admission = parse_repo_admission("review_base_include: main\n")
    payload = _payload()
    del payload["pull_request"]["base"]["ref"]
    assert narrow(payload, admission).reason == BASE_BRANCH_REASON


def test_base_exclude_wins_over_include():
    admission = parse_repo_admission(_lines(base_include="main", base_exclude="main"))
    assert narrow(_payload(base_ref="main"), admission).reason == BASE_BRANCH_REASON
    excluded_alone = parse_repo_admission(_lines(base_exclude="hotfix*"))
    skipped = narrow(_payload(base_ref="hotfix-2"), excluded_alone)
    assert skipped is not None and skipped.reason == BASE_BRANCH_REASON
    assert narrow(_payload(base_ref="main"), excluded_alone) is None


def test_the_checks_run_in_a_fixed_order_and_the_first_hit_wins():
    admission = parse_repo_admission(_lines(base_include="main", skip_events="opened"))
    first = narrow(_payload("opened", base_ref="feature/x"), admission)
    assert first is not None and first.reason == SKIP_EVENT_REASON
    second = narrow(_payload("synchronize", base_ref="feature/x"), admission)
    assert second is not None and second.reason == BASE_BRANCH_REASON


def test_narrowing_json_payload_round_trips_through_a_real_delivery_shape():
    """The narrowing reads the payload shapes GitHub actually sends; a
    delivery body decoded as JSON narrows without a KeyError."""
    body = json.dumps(
        {
            "action": "opened",
            "pull_request": {
                "number": 7,
                "draft": False,
                "head": {"sha": "a" * 40},
                "base": {"ref": "main", "repo": {"full_name": "o/r"}},
            },
            "repository": {"full_name": "o/r"},
        }
    )
    admission = parse_repo_admission("review_base_exclude: main\n")
    assert narrow(json.loads(body), admission).reason == BASE_BRANCH_REASON


def test_a_leading_byte_order_mark_is_not_prose():
    """A UTF-8 BOM before the first key line must not silence it: the
    line still parses, or a still-unusable one is still named, the
    distinguishability the unusable-line pattern promises."""
    bom = "﻿"
    parsed = parse_repo_admission(f"{bom}review_base_include: main\n")
    assert parsed.base_include == ("main",)
    assert parsed.notes == ()
    unusable = parse_repo_admission(f"{bom}review_base_include:\n")
    assert unusable.base_include == ()
    assert len(unusable.notes) == 1
    assert "review_base_include" in unusable.notes[0]


def test_the_default_branch_comes_from_the_repository_object():
    """The config's source branch is the repository's default branch,
    from the payload's repository object; a shape without one is empty
    and the reader recovers it with a lookup."""
    from atlas_reviewer.service_admit import default_branch

    payload = _payload()
    payload["repository"] = {"full_name": "o/r", "default_branch": "trunk"}
    assert default_branch(payload) == "trunk"
    del payload["repository"]["default_branch"]
    assert default_branch(payload) == ""
    assert default_branch({}) == ""
