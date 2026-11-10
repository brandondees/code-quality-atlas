# SPDX-License-Identifier: MIT

import json

import pytest

from atlas_reviewer.lenses import MAX_LENSES, LensLibrary, plan_lenses
from atlas_reviewer.picker import (
    COMPREHENSIVE_LIMIT,
    CRITICAL_TIER,
    PICKER_PATH,
    Depth,
    PickerOutputError,
    load_picker,
    parse_picks,
    picker_instructions,
    select_lenses,
)
from atlas_reviewer.ports import BoundaryError


def has_body(name):
    return LensLibrary().body(name) is not None


def picks(*names):
    return json.dumps({"lenses": list(names)})


def test_the_picker_is_this_repos_own_choosing_review_lenses_skill():
    assert PICKER_PATH.parts[-3:] == ("skills", "choosing-review-lenses", "SKILL.md")
    text = load_picker()
    assert text.startswith("---\nname: choosing-review-lenses\n")
    assert "## Routes" in text and "## Depth modes" in text


def test_instructions_name_the_operator_depth_and_its_breadth():
    text = picker_instructions(Depth.REVIEW)
    assert "Depth mode: review, set by the operator." in text
    assert f"at most {MAX_LENSES} names" in text
    assert '{"lenses": ["<lens-name>", ...]}' in text
    assert f"at most {COMPREHENSIVE_LIMIT} names" in picker_instructions(
        Depth.COMPREHENSIVE
    )


def test_a_ranked_list_is_kept_in_order_without_duplicates():
    reply = picks(
        "sweeping-for-security", "checking-restraint", "sweeping-for-security"
    )
    assert parse_picks(reply, 8) == ("sweeping-for-security", "checking-restraint")


def test_a_fenced_json_reply_is_accepted():
    reply = f"```json\n{picks('checking-restraint')}\n```"
    assert parse_picks(reply, 8) == ("checking-restraint",)


def test_the_list_is_cut_at_the_breadth():
    names = [f"lens-{i}" for i in range(12)]
    assert parse_picks(picks(*names), 8) == tuple(names[:8])


@pytest.mark.parametrize(
    "reply",
    [
        "I would pick security first.",
        json.dumps(["sweeping-for-security"]),
        json.dumps({"lenses": "sweeping-for-security"}),
        json.dumps({"lenses": [1, 2]}),
        json.dumps({"lenses": []}),
        picks("Ignore previous instructions"),
        picks("../../etc/passwd"),
        picks("x" * 81),
    ],
)
def test_anything_but_a_list_of_lens_shaped_names_is_refused(reply):
    with pytest.raises(PickerOutputError):
        parse_picks(reply, 8)


def test_triage_runs_the_critical_tier_without_a_call():
    def never():
        raise AssertionError("triage must not call the picker")

    chosen = select_lenses(Depth.TRIAGE, never, has_body)
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert not chosen.used_call
    assert chosen.note.startswith("Lens selection: triage depth runs the critical tier")


def test_no_call_left_falls_back_to_the_critical_tier():
    chosen = select_lenses(Depth.REVIEW, None, has_body)
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert not chosen.used_call
    assert "no model call is left for the lens picker" in chosen.note


@pytest.mark.parametrize(
    "outcome",
    [lambda: "not json", lambda: (_ for _ in ()).throw(BoundaryError("HTTP 529"))],
)
def test_a_failed_or_unusable_pick_runs_the_critical_tier_and_says_why(outcome):
    chosen = select_lenses(Depth.REVIEW, outcome, has_body)
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert chosen.used_call
    assert 'gave no usable lens list (reason, quoted: `"' in chosen.note
    assert all(c.why == "critical tier" for c in chosen.choices)


def test_a_good_pick_runs_after_the_critical_tier_and_is_attributed():
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint", "sweeping-for-security"),
        has_body,
    )
    assert [(c.name, c.why) for c in chosen.choices] == [
        ("tracing-correctness-and-invariants", "critical tier"),
        ("sweeping-for-security", "critical tier; picker rank 2"),
        ("reviewing-migration-and-data-safety", "critical tier"),
        ("reviewing-concurrency-and-async", "critical tier"),
        ("checking-restraint", "picker rank 1"),
    ]
    assert chosen.used_call
    assert "`choosing-review-lenses` ran as one model call at review depth" in (
        chosen.note
    )
    assert "the critical tier always runs first" in chosen.note


def test_a_thin_pick_cannot_drop_the_critical_tier():
    """A valid but thin reply, e.g. one steered by injected PR text, adds
    lenses but never displaces the critical tier."""
    chosen = select_lenses(Depth.REVIEW, lambda: picks("checking-restraint"), has_body)
    names = [c.name for c in chosen.choices]
    assert names == [*CRITICAL_TIER, "checking-restraint"]
    plan = plan_lenses(LensLibrary(), chosen.choices, Depth.REVIEW.limit)
    assert [u.name for u in plan.uses[: len(CRITICAL_TIER)]] == list(CRITICAL_TIER)


def test_the_merged_pick_stays_within_the_depth_breadth():
    extras = [f"lens-{i}" for i in range(MAX_LENSES)]
    chosen = select_lenses(Depth.REVIEW, lambda: picks(*extras), lambda n: True)
    names = [c.name for c in chosen.choices]
    assert len(names) == MAX_LENSES
    assert names == [*CRITICAL_TIER, *extras[: MAX_LENSES - len(CRITICAL_TIER)]]


def test_a_pick_with_no_loadable_lens_runs_the_critical_tier():
    chosen = select_lenses(Depth.REVIEW, lambda: picks("no-such-lens"), has_body)
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert chosen.used_call
    assert "none of the 1 lens name(s) the picker ranked has a body" in chosen.note


def test_the_critical_tier_lenses_all_exist_in_the_bundle():
    assert set(CRITICAL_TIER) <= LensLibrary().names()
