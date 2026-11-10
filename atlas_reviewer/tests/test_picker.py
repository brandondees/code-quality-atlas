# SPDX-License-Identifier: MIT

import json
import re

import pytest

from atlas_reviewer.lenses import MAX_LENSES, LensLibrary, LensStatus, plan_lenses
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

from .helpers import StubLibrary, small_bundle

REAL = LensLibrary()


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
    assert parse_picks(reply) == ("sweeping-for-security", "checking-restraint")


def test_a_fenced_json_reply_is_accepted():
    reply = f"```json\n{picks('checking-restraint')}\n```"
    assert parse_picks(reply) == ("checking-restraint",)


def test_no_name_is_dropped_at_the_breadth():
    names = [f"lens-{i}" for i in range(12)]
    assert parse_picks(picks(*names)) == tuple(names)


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
        parse_picks(reply)


def test_triage_runs_the_critical_tier_without_a_call():
    def never():
        raise AssertionError("triage must not call the picker")

    chosen = select_lenses(Depth.TRIAGE, never, REAL)
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert not chosen.used_call
    assert chosen.note.startswith("Lens selection: triage depth makes no picker call")


def test_no_call_left_falls_back_to_the_critical_tier():
    chosen = select_lenses(Depth.REVIEW, None, REAL)
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert not chosen.used_call
    assert "no model call is left for the lens picker" in chosen.note


@pytest.mark.parametrize(
    "outcome",
    [lambda: "not json", lambda: (_ for _ in ()).throw(BoundaryError("HTTP 529"))],
)
def test_a_failed_or_unusable_pick_runs_the_critical_tier_and_says_why(outcome):
    chosen = select_lenses(Depth.REVIEW, outcome, small_bundle("checking-restraint"))
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert chosen.used_call
    assert 'gave no usable lens list (reason, quoted: `"' in chosen.note
    assert all(c.why == "critical tier" for c in chosen.choices)


def test_a_good_pick_runs_after_the_critical_tier_and_is_attributed():
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint", "sweeping-for-security"),
        small_bundle("checking-restraint"),
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
    assert "The critical tier is considered first" in chosen.note


def test_a_thin_pick_cannot_drop_the_critical_tier():
    """A valid but thin reply, e.g. one steered by injected PR text, adds
    lenses but never displaces the critical tier."""
    library = small_bundle("checking-restraint")
    chosen = select_lenses(Depth.REVIEW, lambda: picks("checking-restraint"), library)
    names = [c.name for c in chosen.choices]
    assert names == [*CRITICAL_TIER, "checking-restraint"]
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    assert [u.name for u in plan.uses[: len(CRITICAL_TIER)]] == list(CRITICAL_TIER)


def test_names_past_the_breadth_are_not_run_and_body_less_names_take_no_slot():
    extras = [f"lens-{i}" for i in range(MAX_LENSES)]
    library = small_bundle(*extras)
    chosen = select_lenses(Depth.REVIEW, lambda: picks("ghost", *extras), library)
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    by = {u.name: u for u in plan.uses}
    room = MAX_LENSES - len(CRITICAL_TIER)
    ran = [u.name for u in plan.uses if u.status is LensStatus.RUN]
    assert ran == [*CRITICAL_TIER, *extras[:room]]
    assert by["ghost"].reason == "no body.md in the bundle"
    for name in extras[room:]:
        assert by[name].status is LensStatus.NOT_RUN
        assert by[name].reason.startswith(f"below the cap of {MAX_LENSES} lenses")
        assert f"{name} (below the cap" in plan.coverage()
    assert (
        f"ranked {MAX_LENSES + 1} lens name(s), {MAX_LENSES} with a body" in chosen.note
    )


def test_a_pick_with_no_loadable_lens_runs_the_critical_tier():
    chosen = select_lenses(
        Depth.REVIEW, lambda: picks("no-such-lens"), small_bundle("checking-restraint")
    )
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert chosen.used_call
    assert "none of the 1 lens name(s) the picker ranked has a body" in chosen.note


def test_the_critical_tier_lenses_all_exist_in_the_bundle():
    assert set(CRITICAL_TIER) <= LensLibrary().names()


def never():
    raise AssertionError("the picker must not be called")


def test_the_picker_is_not_called_when_no_other_real_lens_can_fit_whole():
    """With the real bundle the critical tier leaves less room than the
    smallest other lens needs, so a pick could not change what runs."""
    for depth in (Depth.REVIEW, Depth.COMPREHENSIVE):
        chosen = select_lenses(depth, never, REAL)
        assert not chosen.used_call
        assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
        assert re.search(
            r"the critical tier leaves \d+ of the 60000-character lens budget and "
            r"the smallest other lens is \d+ characters, so no pick could add a "
            r"lens and the lens picker was not called",
            chosen.note,
        )


def _sized(other_chars):
    bodies = {n: "c" * 200 for n in CRITICAL_TIER}
    return StubLibrary({**bodies, "checking-restraint": "r" * other_chars})


def test_the_picker_is_called_when_another_lens_fits_exactly_in_what_is_left():
    chosen = select_lenses(
        Depth.REVIEW, lambda: picks("checking-restraint"), _sized(200), 1_000
    )
    assert chosen.used_call
    assert [c.name for c in chosen.choices][-1] == "checking-restraint"


def test_the_picker_is_skipped_when_every_other_lens_is_one_character_too_big():
    chosen = select_lenses(Depth.REVIEW, never, _sized(201), 1_000)
    assert not chosen.used_call
    assert "leaves 200 of the 1000-character lens budget" in chosen.note
    assert "the smallest other lens is 201 characters" in chosen.note


def test_the_picker_is_skipped_when_the_bundle_has_no_other_lens():
    chosen = select_lenses(Depth.REVIEW, never, small_bundle())
    assert not chosen.used_call
    assert "the bundle has no other lens" in chosen.note


OVERCLAIM = re.compile(r"critical tier (ran|runs|always runs)|ran first|runs first")


@pytest.mark.parametrize(
    ("depth", "run", "library"),
    [
        (Depth.TRIAGE, never, REAL),
        (Depth.REVIEW, None, REAL),
        (Depth.REVIEW, never, REAL),
        (Depth.REVIEW, lambda: "not json", small_bundle("checking-restraint")),
        (Depth.REVIEW, lambda: picks("ghost"), small_bundle("checking-restraint")),
        (
            Depth.REVIEW,
            lambda: picks("checking-restraint"),
            small_bundle("checking-restraint"),
        ),
    ],
)
def test_no_selection_note_claims_the_critical_tier_ran(depth, run, library):
    """Half the real critical tier is NOT RUN, so a note may say it was
    considered first and point at the Lenses line, never that it ran."""
    note = select_lenses(depth, run, library).note
    assert not OVERCLAIM.search(note), note
    assert "considered" in note
    assert "the lenses line says which" in note.lower()


def test_deeply_nested_json_falls_back_to_the_critical_tier():
    """json.loads raises RecursionError, not ValueError, on nesting past the
    C stack (9,998 arrays here, 19,996 characters). That must be an unusable
    pick and the critical tier, not an error escaping select_lenses."""
    nested = "[" * 10_000 + "]" * 10_000
    chosen = select_lenses(
        Depth.REVIEW, lambda: nested, small_bundle("checking-restraint")
    )
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert chosen.used_call
    assert "gave no usable lens list" in chosen.note
