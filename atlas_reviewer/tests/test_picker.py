# SPDX-License-Identifier: MIT

import json
import re
import time

import pytest

from atlas_reviewer.lenses import LensLibrary, LensStatus, plan_lenses
from atlas_reviewer.picker import (
    CRITICAL_TIER,
    FLOOR_TIER,
    PICKER_PATH,
    PR_HYGIENE,
    Depth,
    LensPreferences,
    PickerOutputError,
    body_states_verification,
    guideline_shapes,
    load_picker,
    parse_picks,
    picker_instructions,
    preferences_directive,
    select_agentic_lenses,
    select_lenses,
)
from atlas_reviewer.ports import BoundaryError, ByokRefusedError

from .helpers import StubLibrary, small_bundle

REAL = LensLibrary()


def picks(*names):
    return json.dumps({"lenses": list(names)})


def test_the_picker_is_this_repos_own_choosing_review_lenses_skill():
    assert PICKER_PATH.parts[-3:] == ("skills", "choosing-review-lenses", "SKILL.md")
    text = load_picker()
    assert text.startswith("---\nname: choosing-review-lenses\n")
    assert "## Routes" in text and "## Depth modes" in text


def test_instructions_name_the_operator_depth_and_the_guidelines_breadth():
    """D69: no depth but triage names a lens count. Review's instructions
    carry the guideline's breadth as a default, not a cap, its
    auto-includes, and the explicit no-fixed-cap sentence; comprehensive
    is uncapped by its own definition."""
    text = picker_instructions(Depth.REVIEW)
    assert "Depth mode: review, set by the operator." in text
    assert "its 3-8 default breadth is a starting recommendation, not a cap" in text
    assert "There is no fixed cap on how many lenses you name." in text
    assert "at most" not in text
    assert '{"lenses": ["<lens-name>", ...]}' in text
    comprehensive = picker_instructions(Depth.COMPREHENSIVE)
    assert "every relevant lens, uncapped" in comprehensive
    assert "at most" not in comprehensive
    triage = picker_instructions(Depth.TRIAGE)
    assert "Triage runs the critical tier only" in triage


def test_instructions_ask_for_the_guidelines_auto_includes():
    """#711 criterion 4, pinned at the instructions: the picker is asked to
    follow the guideline's auto-includes, and the summary agrees with the
    guideline it cites (round-1 F5) -- the decision route's second lens is
    named, the rename pair is attributed to the restructuring route
    rather than to an auto-include, and the enumeration claims to be a
    sample ("include"), not the whole set."""
    text = picker_instructions(Depth.REVIEW)
    assert "its auto-includes include" in text
    assert "name every lens the guideline says rides along" not in text
    assert (
        "for a decision-record or decisions-log change, "
        "reviewing-decision-lifecycle (the guideline adds "
        "auditing-decision-record-currency when the change touches an "
        "existing record rather than authoring a new one)" in text
    )
    assert "for a docs-only change, auditing-documentation-health" in text
    assert (
        "for a rename or restructuring, the guideline's restructuring "
        "route runs reviewing-module-design and "
        "reviewing-naming-and-readability, among others" in text
    )


def test_instructions_say_the_critical_tier_always_runs_and_never_spends_a_slot():
    """The 2026-11-13 trials: the picker spent 2-4 of its slots naming
    critical-tier lenses the controller adds anyway, and one model
    corrected an over-long list with a second JSON object, which the
    parser refused. The instructions still say the tier does not spend the
    slots and that one reply is one list (D58); D69 removes the slot
    economy the correction answered to."""
    text = picker_instructions(Depth.REVIEW)
    assert "always runs before your picks" in text
    assert "does not spend your" in text
    for name in CRITICAL_TIER:
        assert name in text
    assert "Do not correct yourself with a second list" in text


def test_the_last_json_object_in_a_reply_is_parsed():
    """The 2026-11-13 Sonnet #640 failure, verbatim in shape: a list of 9,
    then prose, then the corrected list of 8. The last object is the
    reply."""
    reply_text = (
        '{"lenses": ["a-b", "c-d", "e-f", "g-h", "i-j", "k-l", "m-n", "o-p", '
        '"q-r"]} Wait, I must limit to 8 names. Corrected: '
        '{"lenses": ["a-b", "c-d", "e-f", "g-h", "i-j", "k-l", "m-n", "o-p"]}'
    )
    assert parse_picks(reply_text) == (
        "a-b",
        "c-d",
        "e-f",
        "g-h",
        "i-j",
        "k-l",
        "m-n",
        "o-p",
    )


def test_a_bare_object_after_prose_is_parsed():
    assert parse_picks("Picking for this change:\n" + picks("checking-restraint")) == (
        "checking-restraint",
    )


def test_a_nested_object_does_not_win_over_its_parent():
    """The scanner skips a decoded object's own braces, so prose after a
    valid object cannot turn an interior fragment into the reply."""
    nested = '{"lenses": ["checking-restraint"], "note": {"why": "small"}} extra'
    assert parse_picks(nested) == ("checking-restraint",)


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

    chosen = select_lenses(Depth.TRIAGE, never, REAL, scrub=str)
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert not chosen.used_call
    assert chosen.note.startswith("Lens selection: triage depth makes no picker call")


def test_no_call_left_falls_back_to_the_critical_tier():
    chosen = select_lenses(Depth.REVIEW, None, REAL, scrub=str)
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert not chosen.used_call
    assert "no model call is left for the lens picker" in chosen.note


@pytest.mark.parametrize(
    "outcome",
    [lambda: "not json", lambda: (_ for _ in ()).throw(BoundaryError("HTTP 529"))],
)
def test_a_failed_or_unusable_pick_runs_the_critical_tier_and_says_why(outcome):
    chosen = select_lenses(
        Depth.REVIEW, outcome, small_bundle("checking-restraint"), scrub=str
    )
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert chosen.used_call
    assert 'gave no usable lens list (reason, quoted: `"' in chosen.note
    assert all(c.why == "critical tier" for c in chosen.choices)


def test_a_good_pick_runs_after_the_critical_tier_and_is_attributed():
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint", "sweeping-for-security"),
        small_bundle("checking-restraint"),
        scrub=str,
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
    chosen = select_lenses(
        Depth.REVIEW, lambda: picks("checking-restraint"), library, scrub=str
    )
    names = [c.name for c in chosen.choices]
    assert names == [*CRITICAL_TIER, "checking-restraint"]
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    assert [u.name for u in plan.uses[: len(CRITICAL_TIER)]] == list(CRITICAL_TIER)


def test_names_past_the_breadth_are_not_run_and_body_less_names_take_no_slot():
    """A name with no body is NOT RUN with its reason and takes no slot;
    nothing is cut by count (D69)."""
    extras = [f"lens-{i}" for i in range(8)]
    library = small_bundle(*extras)
    chosen = select_lenses(
        Depth.REVIEW, lambda: picks("ghost", *extras), library, scrub=str
    )
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    by = {u.name: u for u in plan.uses}
    ran = [u.name for u in plan.uses if u.status is LensStatus.RUN]
    assert ran == [*CRITICAL_TIER, *extras]
    assert by["ghost"].reason == "no body.md in the bundle"
    assert (
        f"ranked {len(extras) + 1} lens name(s), {len(extras)} with a body"
        in chosen.note
    )


def test_more_than_eight_picks_survive_review_depth():
    """#711's headline criterion: a reply naming more than 8 lenses is not
    cut -- every named lens with a body is chosen, and the one-shot
    plan's character budget, not a lens count, decides what runs."""
    picks_beyond_the_old_cap = [f"lens-{i}" for i in range(12)]
    library = small_bundle(*picks_beyond_the_old_cap)
    chosen = select_lenses(
        Depth.REVIEW, lambda: picks(*picks_beyond_the_old_cap), library, scrub=str
    )
    names = [c.name for c in chosen.choices]
    assert names == [*CRITICAL_TIER, *picks_beyond_the_old_cap]
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    ran = [u.name for u in plan.uses if u.status is LensStatus.RUN]
    assert ran == [*CRITICAL_TIER, *picks_beyond_the_old_cap]
    assert not any("cap" in u.reason for u in plan.uses)


def test_more_than_eight_picks_survive_the_agentic_path():
    """D69 on the agentic path: every ranked lens with a body runs, no
    matter how many the picker names."""
    ranked = [f"lens-{i}" for i in range(12)]
    library = small_bundle(*ranked)
    selection, plan = select_agentic_lenses(
        Depth.REVIEW, lambda: picks(*ranked), library, scrub=str
    )
    names = [c.name for c in selection.choices]
    assert names == [*CRITICAL_TIER, *ranked]
    assert [u.name for u in plan.uses if u.status is LensStatus.RUN] == names


def test_a_pick_with_no_loadable_lens_runs_the_critical_tier():
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("no-such-lens"),
        small_bundle("checking-restraint"),
        scrub=str,
    )
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert chosen.used_call
    assert "none of the 1 lens name(s) the picker ranked has a body" in chosen.note


def test_the_critical_tier_lenses_all_exist_in_the_bundle():
    assert set(CRITICAL_TIER) <= LensLibrary().names()


def test_the_process_hygiene_lens_exists_in_the_bundle():
    assert LensLibrary().body(PR_HYGIENE) is not None


def test_a_body_stating_verification_results_adds_pr_hygiene_ahead_of_the_picks():
    """D58's policy rule: a PR body that states test counts, coverage or CI
    claims always gets the process-hygiene lens, ahead of the picks."""
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        small_bundle("checking-restraint"),
        scrub=str,
        pr_text="Tests: 2105 passed, coverage 96.78%; CI run 43493645208 green.",
    )
    names = [c.name for c in chosen.choices]
    assert names == [
        *CRITICAL_TIER,
        PR_HYGIENE,
        "checking-restraint",
    ]
    assert chosen.choices[len(CRITICAL_TIER)].why == (
        "the pull request body states verification results"
    )


def test_a_body_without_verification_results_adds_no_pr_hygiene():
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        small_bundle("checking-restraint"),
        scrub=str,
        pr_text="Adds a rounding helper to the totals module.",
    )
    assert PR_HYGIENE not in [c.name for c in chosen.choices]


def test_a_picker_ranked_pr_hygiene_is_not_duplicated():
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks(PR_HYGIENE, "checking-restraint"),
        small_bundle("checking-restraint", PR_HYGIENE),
        scrub=str,
        pr_text="All 12 tests passed.",
    )
    names = [c.name for c in chosen.choices]
    assert names.count(PR_HYGIENE) == 1
    assert names[len(CRITICAL_TIER)] == PR_HYGIENE


def test_a_ranked_pr_hygiene_survives_a_body_without_verification_results():
    """Review M3: a pr-hygiene lens the picker ranked must not vanish when
    the PR body states no verification results; it reaches the plan as an
    ordinary pick, so a NOT RUN line names it."""
    library = small_bundle("checking-restraint", PR_HYGIENE)
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks(PR_HYGIENE, "checking-restraint"),
        library,
        scrub=str,
        pr_text="Adds a rounding helper to the totals module.",
    )
    names = [c.name for c in chosen.choices]
    assert names.count(PR_HYGIENE) == 1
    assert names[-2:] == [PR_HYGIENE, "checking-restraint"]
    assert chosen.choices[-2].why == "picker rank 1"
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    by = {u.name: u for u in plan.uses}
    assert by[PR_HYGIENE].status is LensStatus.RUN
    assert by[PR_HYGIENE].why == "picker rank 1"


def test_an_agentic_pick_of_pr_hygiene_survives_a_quiet_body_too():
    from atlas_reviewer.picker import select_agentic_lenses

    library = small_bundle("checking-restraint", PR_HYGIENE)
    selection, plan = select_agentic_lenses(
        Depth.REVIEW,
        lambda: picks(PR_HYGIENE, "checking-restraint"),
        library,
        scrub=str,
        pr_text="Adds a rounding helper to the totals module.",
    )
    names = [c.name for c in selection.choices]
    assert names.count(PR_HYGIENE) == 1
    assert {u.name for u in plan.loaded} >= {PR_HYGIENE, "checking-restraint"}


def test_hygiene_does_not_use_a_guideline_slot():
    """#711: the process-hygiene lens rides on top of the picks and never
    spends one of the guideline's slots. A pick whose guideline would have
    included hygiene -- here, twelve named picks with a body that states
    verification results -- still yields the full set of non-hygiene picks
    plus hygiene, every one of them running."""
    ranked = [f"lens-{i}" for i in range(12)]
    library = small_bundle(*ranked, PR_HYGIENE)
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks(*ranked),
        library,
        scrub=str,
        pr_text="Tests: 2105 passed, coverage 96.78%; CI run 43493645208 green.",
    )
    names = [c.name for c in chosen.choices]
    assert names == [*CRITICAL_TIER, PR_HYGIENE, *ranked]
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    ran = [u.name for u in plan.uses if u.status is LensStatus.RUN]
    assert ran == [*CRITICAL_TIER, PR_HYGIENE, *ranked]


def test_hygiene_does_not_use_a_guideline_slot_on_the_agentic_path():
    ranked = [f"lens-{i}" for i in range(12)]
    library = small_bundle(*ranked, PR_HYGIENE)
    selection, plan = select_agentic_lenses(
        Depth.REVIEW,
        lambda: picks(*ranked),
        library,
        scrub=str,
        pr_text="Tests: 2105 passed, coverage 96.78%; CI run 43493645208 green.",
    )
    names = [c.name for c in selection.choices]
    assert names == [*CRITICAL_TIER, PR_HYGIENE, *ranked]
    assert {u.name for u in plan.loaded} == set(names)


def test_the_picker_naming_hygiene_displaces_no_pick():
    """A guideline-following picker names hygiene among its auto-includes;
    the controller's own hygiene include and the ranked name are one lens,
    and every other pick survives beside it."""
    ranked = [f"lens-{i}" for i in range(12)]
    library = small_bundle(*ranked, PR_HYGIENE)
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks(PR_HYGIENE, *ranked),
        library,
        scrub=str,
        pr_text="Tests: 2105 passed, coverage 96.78%; CI run 43493645208 green.",
    )
    names = [c.name for c in chosen.choices]
    assert names.count(PR_HYGIENE) == 1
    assert names == [*CRITICAL_TIER, PR_HYGIENE, *ranked]


PREFERENCES = LensPreferences(
    include=("reviewing-threat-model",),
    exclude=("checking-restraint",),
)


def test_a_repo_preference_exclude_drops_a_ranked_pick_and_is_recorded():
    library = small_bundle(
        "checking-restraint", "reviewing-test-quality", "reviewing-threat-model"
    )
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint", "reviewing-test-quality"),
        library,
        scrub=str,
        preferences=PREFERENCES,
    )
    names = [c.name for c in chosen.choices]
    assert "checking-restraint" not in names
    assert names == [
        *CRITICAL_TIER,
        "reviewing-test-quality",
        "reviewing-threat-model",
    ]
    assert (
        "The reviewed repo's merge-base REVIEW.md overrides the guideline "
        "(include: reviewing-threat-model; exclude: checking-restraint): "
        "dropped from the picks: checking-restraint; "
        "added: reviewing-threat-model." in chosen.note
    )
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    ran = [u.name for u in plan.uses if u.status is LensStatus.RUN]
    assert "checking-restraint" not in ran
    assert "reviewing-threat-model" in ran


def test_a_repo_preference_include_runs_even_when_the_picker_missed_it():
    """The override is honored against the model, not only suggested to
    it: an include the picker never ranked still runs (and the one-shot
    note records it), closing the shape #640 died of."""
    library = small_bundle("reviewing-test-quality")
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("reviewing-test-quality"),
        library,
        scrub=str,
        preferences=PREFERENCES,
    )
    names = [c.name for c in chosen.choices]
    assert "reviewing-threat-model" in names
    assert chosen.choices[-1].why == (
        "included by the reviewed repo's merge-base REVIEW.md (D69)"
    )
    assert "added: reviewing-threat-model." in chosen.note


def test_a_repo_preference_include_is_honored_when_the_picker_falls_back():
    """The override is a repo directive, not a picker hint: a fallback
    (here, an unusable reply) still runs the included lens and records
    it."""
    library = small_bundle("reviewing-test-quality")
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: "not json",
        library,
        scrub=str,
        preferences=PREFERENCES,
    )
    names = [c.name for c in chosen.choices]
    assert names == [*CRITICAL_TIER, "reviewing-threat-model"]
    assert "added: reviewing-threat-model." in chosen.note
    assert "gave no usable lens list" in chosen.note


def test_a_repo_preference_include_is_honored_when_no_call_is_available():
    library = small_bundle("reviewing-test-quality")
    chosen = select_lenses(
        Depth.REVIEW,
        None,
        library,
        scrub=str,
        preferences=PREFERENCES,
    )
    names = [c.name for c in chosen.choices]
    assert names == [*CRITICAL_TIER, "reviewing-threat-model"]
    assert not chosen.used_call


def test_a_repo_preference_never_touches_the_critical_tier():
    """The critical tier is the controller's own floor, not the
    guideline's: an exclude naming a critical lens leaves the tier whole,
    and an include naming one adds no duplicate."""
    preferences = LensPreferences(
        include=("sweeping-for-security", "reviewing-threat-model"),
        exclude=("tracing-correctness-and-invariants",),
    )
    library = small_bundle("reviewing-test-quality", "reviewing-threat-model")
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("reviewing-test-quality"),
        library,
        scrub=str,
        preferences=preferences,
    )
    names = [c.name for c in chosen.choices]
    assert names[: len(CRITICAL_TIER)] == list(CRITICAL_TIER)
    assert names.count("sweeping-for-security") == 1
    assert "reviewing-threat-model" in names
    assert "dropped from the picks" not in chosen.note
    assert "added: reviewing-threat-model." in chosen.note
    assert chosen.choices[-1].why == (
        "included by the reviewed repo's merge-base REVIEW.md (D69)"
    )


def test_a_repo_preference_exclude_never_touches_the_manifest_floor_tier():
    """D69's 5:13 PM CT update: the protection set is the manifest's whole
    `tier: floor`, not the critical tier alone -- `hunting-silent-failures`
    is refused the way the critical four are, on the picks and in the
    record, so a repo preference cannot silently suppress a floor lens."""
    preferences = LensPreferences(exclude=("hunting-silent-failures",))
    library = small_bundle("reviewing-test-quality")
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("hunting-silent-failures", "reviewing-test-quality"),
        library,
        scrub=str,
        preferences=preferences,
    )
    names = [c.name for c in chosen.choices]
    assert names == [
        *CRITICAL_TIER,
        "hunting-silent-failures",
        "reviewing-test-quality",
    ]
    # The record must not claim a drop that did not happen.
    assert "dropped from the picks" not in chosen.note

    from atlas_reviewer.picker import _apply_preferences

    applied = _apply_preferences(
        ("hunting-silent-failures", "reviewing-test-quality"),
        (),
        preferences,
    )
    assert applied.kept == ("hunting-silent-failures", "reviewing-test-quality")
    assert applied.dropped == ()


def test_a_fallback_exclude_never_touches_the_floor_tier_either():
    """The fallback path's protection set is the floor tier too (D69's
    5:13 PM CT update), pinned directly: a fallback selection that names
    a floor lens keeps it whatever the exclude says."""
    from atlas_reviewer.lenses import LensChoice
    from atlas_reviewer.picker import LensSelection, _preferenced_fallback

    selection = LensSelection(
        (LensChoice("hunting-silent-failures", "picker rank 1"),), "note", True
    )
    out = _preferenced_fallback(
        selection, LensPreferences(exclude=("hunting-silent-failures",)), Depth.REVIEW
    )
    assert [c.name for c in out.choices] == ["hunting-silent-failures"]


def test_the_floor_tier_is_the_manifests_tier_floor_set():
    """The protection set is the manifest's, not a second hand-kept copy:
    a tier change in `skills/manifest.yaml` fails here instead of silently
    widening what a merge-base exclude may drop."""
    from tooling.manifest import load_manifest

    from .test_lenses import _REPO

    manifest = load_manifest(str(_REPO / "skills/manifest.yaml"))
    assert sorted(FLOOR_TIER) == sorted(
        s.name for s in manifest.skills if s.tier == "floor"
    )


def test_a_repo_preference_include_of_an_unbundled_lens_is_not_run_not_dropped():
    """A directive naming a lens that matches nothing is surfaced, never
    silently guessed away: the include reaches the plan and its NOT RUN
    line names it."""
    preferences = LensPreferences(include=("not-a-real-lens",))
    library = small_bundle("reviewing-test-quality")
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("reviewing-test-quality"),
        library,
        scrub=str,
        preferences=preferences,
    )
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    by = {u.name: u for u in plan.uses}
    assert by["not-a-real-lens"].status is LensStatus.NOT_RUN
    assert by["not-a-real-lens"].reason == "no body.md in the bundle"
    assert "added: not-a-real-lens." in chosen.note


def test_triage_is_not_widened_by_a_repo_preference():
    """A preference re-ranks within its depth mode's breadth and never
    widens the mode: triage's breadth is the critical tier alone, so an
    include changes nothing there."""
    library = small_bundle("reviewing-test-quality")

    def never():
        raise AssertionError("triage must not call the picker")

    chosen = select_lenses(
        Depth.TRIAGE, never, library, scrub=str, preferences=PREFERENCES
    )
    names = [c.name for c in chosen.choices]
    assert names == list(CRITICAL_TIER)
    assert chosen.note.startswith("Lens selection: triage depth makes no picker call")


def test_the_preference_directive_reaches_the_instructions():
    """The picker is told the override so it does not fight it; the names
    it carries are lens-shaped, validated at parse, so the trusted
    instructions cannot be injected into from REVIEW.md."""
    text = picker_instructions(Depth.REVIEW, PREFERENCES)
    assert (
        "The reviewed repo's merge-base REVIEW.md overrides the guideline: "
        "run reviewing-threat-model; do not run checking-restraint. The "
        "controller applies this override to your picks itself." in text
    )
    assert picker_instructions(Depth.REVIEW).endswith(
        "Do not correct yourself with a second list."
    )


def test_an_empty_preference_directive_adds_nothing():
    assert preferences_directive(None) == ""
    assert preferences_directive(LensPreferences()) == ""


# --- round 1 (F1): hygiene and the preference, and structural dedupe ----


def test_a_repo_preference_include_of_hygiene_does_not_run_it_twice():
    """Round-1 F1: the controller-added hygiene choice is inside the
    covered set, so an include naming it adds no second choice and the
    plan loads the body once, not twice."""
    library = small_bundle("checking-restraint", PR_HYGIENE)
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        library,
        scrub=str,
        pr_text="All 12 tests passed.",
        preferences=LensPreferences(include=(PR_HYGIENE,)),
    )
    names = [c.name for c in chosen.choices]
    assert names.count(PR_HYGIENE) == 1
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    assert [lens.name for lens in plan.loaded].count(PR_HYGIENE) == 1
    assert "nothing needed changing" in chosen.note


def test_a_repo_preference_exclude_removes_the_controller_added_hygiene():
    """Round-1 F1: the controller-added hygiene lens is neither
    critical-tier nor a cap, so a repo exclude declines it -- it does not
    run, and the note says so. Kills the mutant that re-adds the
    controller-added choice in `_with_critical` whatever the exclude
    says."""
    library = small_bundle("checking-restraint", PR_HYGIENE)
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        library,
        scrub=str,
        pr_text="All 12 tests passed.",
        preferences=LensPreferences(exclude=(PR_HYGIENE,)),
    )
    names = [c.name for c in chosen.choices]
    assert PR_HYGIENE not in names
    assert f"dropped the controller-added {PR_HYGIENE} lens" in chosen.note
    plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
    assert PR_HYGIENE not in [lens.name for lens in plan.loaded]


def test_the_selection_never_carries_a_duplicate_name():
    """Round-1 F1, structurally: however hygiene, the ranked picks and a
    repo preference combine, no lens is chosen twice and no body loads
    twice."""
    library = small_bundle("checking-restraint", "reviewing-test-quality", PR_HYGIENE)
    verification = "Tests: 2105 passed, coverage 96.78%."
    cases: tuple[dict, ...] = (
        {},
        {"pr_text": verification},
        {"preferences": LensPreferences(include=(PR_HYGIENE,))},
        {
            "pr_text": verification,
            "preferences": LensPreferences(include=(PR_HYGIENE,)),
        },
        {
            "pr_text": verification,
            "preferences": LensPreferences(exclude=(PR_HYGIENE,)),
        },
        {
            "preferences": LensPreferences(
                include=("reviewing-test-quality",),
                exclude=("checking-restraint",),
            )
        },
        {
            "run": lambda: "not json",
            "pr_text": verification,
            "preferences": LensPreferences(include=("reviewing-test-quality",)),
        },
        {
            "run": lambda: picks(
                PR_HYGIENE, "checking-restraint", "reviewing-test-quality"
            ),
            "pr_text": verification,
        },
    )
    for case in cases:
        run = case.pop(
            "run", lambda: picks("checking-restraint", "reviewing-test-quality")
        )
        chosen = select_lenses(Depth.REVIEW, run, library, scrub=str, **case)
        names = [c.name for c in chosen.choices]
        assert len(names) == len(set(names)), (names, case)
        plan = plan_lenses(library, chosen.choices, Depth.REVIEW.limit)
        loaded = [lens.name for lens in plan.loaded]
        assert len(loaded) == len(set(loaded)), loaded


# --- round 1 (F2): exclude wins on every path ---------------------------


def test_exclude_wins_over_include_on_the_success_path():
    preferences = LensPreferences(
        include=("checking-restraint",), exclude=("checking-restraint",)
    )
    library = small_bundle("checking-restraint")
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        library,
        scrub=str,
        preferences=preferences,
    )
    names = [c.name for c in chosen.choices]
    assert "checking-restraint" not in names
    assert "dropped from the picks: checking-restraint" in chosen.note
    assert "added: checking-restraint" not in chosen.note


def test_exclude_wins_over_include_on_the_fallback_path():
    """Round-1 F2: the precedence is the repo's config, not the picker's
    luck -- a name in both lists does not run when the picker fell back
    either."""
    preferences = LensPreferences(
        include=("reviewing-test-quality",), exclude=("reviewing-test-quality",)
    )
    library = small_bundle("reviewing-test-quality")
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: "not json",
        library,
        scrub=str,
        preferences=preferences,
    )
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert "added: reviewing-test-quality" not in chosen.note
    assert "overrides the guideline" in chosen.note


def test_a_fallback_exclude_removes_the_controller_added_hygiene():
    """Round-1 F2, with something the fallback exclude can actually drop:
    the controller-added hygiene choice is excludable when the picker fell
    back, exactly as on the success path."""
    library = small_bundle("checking-restraint", PR_HYGIENE)
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: "not json",
        library,
        scrub=str,
        pr_text="All 12 tests passed.",
        preferences=LensPreferences(exclude=(PR_HYGIENE,)),
    )
    names = [c.name for c in chosen.choices]
    assert names == list(CRITICAL_TIER)
    assert f"dropped the controller-added {PR_HYGIENE} lens" in chosen.note


def test_a_fallback_hygiene_exclude_is_recorded_once():
    """Round-2 N3: a fallback has no picks, so the hygiene drop is
    recorded once, as the controller-added drop -- never also as a
    dropped pick, which would mislabel a controller-added choice and say
    the same thing twice."""
    library = small_bundle("checking-restraint", PR_HYGIENE)
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: "not json",
        library,
        scrub=str,
        pr_text="All 12 tests passed.",
        preferences=LensPreferences(exclude=(PR_HYGIENE,)),
    )
    note = chosen.note
    assert note.count(f"dropped the controller-added {PR_HYGIENE} lens") == 1
    assert "dropped from the picks" not in note


# --- round 1 (F4): the controller's shape facts -------------------------


def test_the_decisions_log_shape_is_a_controller_fact_in_the_instructions():
    shapes = guideline_shapes(("docs/open-questions.md",), scrub=str)
    assert len(shapes) == 1
    assert "reviewing-decision-lifecycle" in shapes[0]
    assert "auditing-decision-record-currency" in shapes[0]
    text = picker_instructions(Depth.REVIEW, shapes=shapes)
    assert "The controller read the changed paths itself:" in text
    assert shapes[0] in text
    assert picker_instructions(Depth.REVIEW).endswith(
        "Do not correct yourself with a second list."
    )


def test_an_adr_directory_shape_is_detected():
    shapes = guideline_shapes(
        ("docs/adr/0007-store-money-as-minor-units.md",), scrub=str
    )
    assert "reviewing-decision-lifecycle" in shapes[0]


def test_the_rename_shape_names_the_restructuring_route_lenses():
    diff = (
        "diff --git a/old_calc.py b/new_calc.py\n"
        "similarity index 100%\n"
        "rename from old_calc.py\n"
        "rename to new_calc.py\n"
    )
    shapes = guideline_shapes(("new_calc.py",), scrub=str, diff=diff)
    assert len(shapes) == 1
    assert "the guideline's restructuring route runs" in shapes[0]
    assert "reviewing-module-design" in shapes[0]
    assert "reviewing-naming-and-readability, among others" in shapes[0]
    assert '"old_calc.py"` to `"new_calc.py"' in shapes[0]


def test_a_rename_record_inside_diff_content_is_not_a_shape():
    """A content line never starts with `rename`, so a PR body or an added
    line cannot state a shape into the controller's facts."""
    diff = (
        "diff --git a/calc.py b/calc.py\n"
        "--- a/calc.py\n"
        "+++ b/calc.py\n"
        "@@ -1 +1 @@\n"
        "+rename from docs/open-questions.md\n"
    )
    assert guideline_shapes(("calc.py",), scrub=str, diff=diff) == ()


def test_a_docs_only_shape_names_documentation_health():
    assert guideline_shapes(("README.md", "docs/guide.md"), scrub=str) == (
        (
            "every changed path is documentation: the guideline "
            "auto-includes auditing-documentation-health"
        ),
    )


def test_a_docs_only_diff_with_code_is_not_docs_only():
    assert guideline_shapes(("README.md", "calc.py"), scrub=str) == ()


def test_a_pure_decision_record_diff_states_no_docs_only_shape():
    """The guideline's own rule: a spec/ADR/RFC under docs/** is a design
    doc first, so the docs-only row's auto-include is not stated for a
    diff that is only decision records."""
    shapes = guideline_shapes(
        ("docs/adr/0007-store-money-as-minor-units.md",), scrub=str
    )
    assert len(shapes) == 1
    assert "auditing-documentation-health" not in shapes[0]


def test_shape_paths_are_quoted_as_data():
    def scrub(text):
        return text.replace("sek|ret", "[REDACTED]")

    shapes = guideline_shapes(("sek|ret/adr-0007.md",), scrub=scrub)
    assert "sek|ret" not in shapes[0]
    assert '`"[REDACTED]/adr-0007.md"`' in shapes[0]


def test_the_selection_note_carries_the_shape_facts():
    shapes = guideline_shapes(("docs/open-questions.md",), scrub=str)
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        small_bundle("checking-restraint"),
        scrub=str,
        shapes=shapes,
    )
    assert "The controller's shape facts from the changed paths:" in chosen.note
    assert shapes[0] in chosen.note


def test_the_fallback_note_carries_the_shape_facts():
    """The request stays auditable even when the picker left it out: the
    fallback note still names the shapes the instructions asked for."""
    shapes = guideline_shapes(("docs/open-questions.md",), scrub=str)
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: "not json",
        small_bundle(),
        scrub=str,
        shapes=shapes,
    )
    assert shapes[0] in chosen.note
    assert "only the critical tier was considered" in chosen.note


# --- round 1 (F6): an override that changed nothing is still recorded ---


def test_a_preference_that_changes_nothing_is_still_recorded():
    """Round-1 F6: an operator reading the draft can tell "applied and
    already satisfied" from "ignored"."""
    library = small_bundle("reviewing-test-quality")
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("reviewing-test-quality"),
        library,
        scrub=str,
        preferences=LensPreferences(include=("reviewing-test-quality",)),
    )
    assert (
        "The reviewed repo's merge-base REVIEW.md overrides the guideline "
        "(include: reviewing-test-quality; exclude: none): nothing needed "
        "changing." in chosen.note
    )


# --- round 1 (F7): the fallback note's "only" ---------------------------


def test_the_fallback_note_drops_only_when_the_preference_changes_the_set():
    """Round-1 F7: "only the critical tier was considered" stays true only
    while the preference has added nothing and dropped nothing."""
    library = small_bundle("reviewing-test-quality")
    plain = select_lenses(Depth.REVIEW, lambda: "not json", library, scrub=str)
    assert "only the critical tier was considered" in plain.note
    changed = select_lenses(
        Depth.REVIEW,
        lambda: "not json",
        library,
        scrub=str,
        preferences=LensPreferences(include=("reviewing-test-quality",)),
    )
    assert "only the critical tier was considered" not in changed.note
    assert "the critical tier was considered" in changed.note
    assert "added: reviewing-test-quality" in changed.note


def test_the_fallback_paths_add_pr_hygiene_when_the_body_states_results():
    for run in (None, lambda: "not json"):
        chosen = select_lenses(
            Depth.REVIEW,
            run,
            small_bundle("checking-restraint"),
            scrub=str,
            pr_text="Coverage is 94%.",
        )
        names = [c.name for c in chosen.choices]
        assert names == [*CRITICAL_TIER, PR_HYGIENE]


@pytest.mark.parametrize(
    ("text", "states"),
    [
        ("2105 passed, 96.78% coverage", True),
        ("CI run 43493645208 passed", True),
        ("All checks are green.", True),
        ("3 tests failed", True),
        ("96.78% coverage across the suite", True),
        ("Fixes the CI flake.", False),
        ("Fixes the flaky CI test that was failing on main.", False),
        ("CI was red on main due to a flake; this fixes it.", False),
        ("Adds a rounding helper.", False),
        ("Follows the existing module design.", False),
        ("CI" + ",9," * 20_000, False),
    ],
)
def test_verification_detection(text, states):
    assert body_states_verification(text) is states


def test_verification_detection_is_bounded_on_a_crafted_body():
    """The digit-run patterns must not backtrack quadratically on untrusted
    text: a body at GitHub's 65,536-character cap of digit-comma repeats
    scans in well under a second."""
    body = "9," * 40_000
    start = time.monotonic()
    assert body_states_verification(body) is False
    assert time.monotonic() - start < 1.0


def never():
    raise AssertionError("the picker must not be called")


def test_agentic_selection_calls_the_picker_when_the_one_shot_budget_would_not():
    """The real bundle leaves no room for a one-shot pick. The agentic
    path still calls the picker and keeps every ranked lens that has a body,
    including a repo-shaped one."""
    calls = []

    def run():
        calls.append("called")
        return picks("checking-restraint", "auditing-documentation-health")

    selection, plan = select_agentic_lenses(Depth.REVIEW, run, REAL, scrub=str)
    assert calls == ["called"]
    assert selection.used_call
    assert "one-shot character budget does not apply" in selection.note
    ran = [use.name for use in plan.uses if use.status is LensStatus.RUN]
    assert set(CRITICAL_TIER) <= set(ran)
    assert "checking-restraint" in ran
    assert "auditing-documentation-health" in ran


def test_the_picker_is_not_called_when_no_other_real_lens_can_fit_whole():
    """With the real bundle the critical tier leaves less room than the
    smallest other lens needs, so a pick could not change what runs."""
    for depth in (Depth.REVIEW, Depth.COMPREHENSIVE):
        chosen = select_lenses(depth, never, REAL, scrub=str)
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
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        _sized(200),
        1_000,
        scrub=str,
    )
    assert chosen.used_call
    assert [c.name for c in chosen.choices][-1] == "checking-restraint"


def test_the_picker_is_skipped_when_every_other_lens_is_one_character_too_big():
    chosen = select_lenses(Depth.REVIEW, never, _sized(201), 1_000, scrub=str)
    assert not chosen.used_call
    assert "leaves 200 of the 1000-character lens budget" in chosen.note
    assert "the smallest other lens is 201 characters" in chosen.note


def test_the_picker_is_skipped_when_the_bundle_has_no_other_lens():
    chosen = select_lenses(Depth.REVIEW, never, small_bundle(), scrub=str)
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
    note = select_lenses(depth, run, library, scrub=str).note
    assert not OVERCLAIM.search(note), note
    assert "considered" in note
    assert "the lenses line says which" in note.lower()


def test_deeply_nested_json_falls_back_to_the_critical_tier():
    """json.loads raises RecursionError, not ValueError, on nesting past the
    C stack (9,998 arrays here, 19,996 characters). That must be an unusable
    pick and the critical tier, not an error escaping select_lenses."""
    nested = "[" * 10_000 + "]" * 10_000
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: nested,
        small_bundle("checking-restraint"),
        scrub=str,
    )
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)
    assert chosen.used_call
    assert "gave no usable lens list" in chosen.note


MARKUP_VALUES = ("sek|retAA", "sek\\retAA", "sek`retAA")


def _scrub(value):
    def scrub(text):
        return text.replace(value, "[REDACTED:possible-committed-secret]")

    return scrub


def test_a_byok_refusal_is_not_turned_into_a_fallback_pick():
    def fail():
        raise ByokRefusedError("refusing the review: usage.is_byok is true")

    with pytest.raises(ByokRefusedError, match="usage.is_byok is true"):
        select_lenses(Depth.REVIEW, fail, small_bundle("checking-restraint"), scrub=str)


@pytest.mark.parametrize("value", MARKUP_VALUES)
def test_a_picker_error_is_scrubbed_before_it_is_quoted(value):
    def fail():
        raise BoundaryError(value)

    chosen = select_lenses(
        Depth.REVIEW, fail, small_bundle("checking-restraint"), scrub=_scrub(value)
    )
    note = chosen.note
    assert value not in note
    assert value.replace("\\", "\\\\").replace("|", "\\|") not in note
    assert value.replace("`", "\\u0060") not in note
    assert "[REDACTED:possible-committed-secret]" in note


def test_the_shape_auto_includes_detect_the_guidelines_mandates():
    from atlas_reviewer.picker import (
        DECISION_CURRENCY_LENS,
        DECISION_LENS,
        DOCS_HEALTH_LENS,
        MODULE_DESIGN_LENS,
        NAMING_LENS,
        shape_auto_includes,
    )

    edited = (
        "diff --git a/docs/open-questions.md b/docs/open-questions.md\n"
        "--- a/docs/open-questions.md\n"
        "+++ b/docs/open-questions.md\n"
        "@@ -1,2 +1,3 @@\n"
        " old line\n"
        "+new line\n"
    )
    assert shape_auto_includes(("docs/open-questions.md",), diff=edited) == (
        DECISION_LENS,
        DECISION_CURRENCY_LENS,
    )
    authored = (
        "diff --git a/docs/rfc/007-new.md b/docs/rfc/007-new.md\n"
        "--- /dev/null\n"
        "+++ b/docs/rfc/007-new.md\n"
        "@@ -0,0 +1,2 @@\n"
        "+a new record\n"
    )
    assert shape_auto_includes(("docs/rfc/007-new.md",), diff=authored) == (
        DECISION_LENS,
    )
    assert shape_auto_includes(("README.md", "docs/other.md")) == (DOCS_HEALTH_LENS,)
    renamed = "diff --git a/a.py b/b.py\nrename from a.py\nrename to b.py\n"
    assert shape_auto_includes(("b.py",), diff=renamed) == (
        MODULE_DESIGN_LENS,
        NAMING_LENS,
    )
    assert shape_auto_includes(("calc.py",)) == ()


def test_a_rename_change_auto_includes_the_restructuring_route_lenses():
    """The protocol's step-2 auto-includes are enforced by the controller,
    not left to the picker's ranking: a rename pulls in
    reviewing-module-design and reviewing-naming-and-readability however
    the picker ranks -- or omits -- them, riding additively after the
    picks."""
    selection, plan = select_agentic_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        small_bundle(
            "checking-restraint",
            "reviewing-module-design",
            "reviewing-naming-and-readability",
        ),
        scrub=str,
        shapes=("the diff renames a.py to b.py: the guideline's route runs them",),
        auto_includes=("reviewing-module-design", "reviewing-naming-and-readability"),
    )
    names = [c.name for c in selection.choices]
    assert names[: len(CRITICAL_TIER)] == list(CRITICAL_TIER)
    assert ("reviewing-module-design", "auto-included: the diff renames files") in [
        (c.name, c.why) for c in selection.choices
    ]
    assert "reviewing-naming-and-readability" in names
    assert "checking-restraint" in names
    assert [u.name for u in plan.uses if u.status is LensStatus.RUN] == names
    assert "Auto-included on the shape facts: reviewing-module-design, " in (
        selection.note
    )


def test_the_auto_includes_run_ahead_of_the_picks_in_the_one_shot_budget():
    """The one-shot plan spends its character budget in the choices' order,
    so an auto-include placed behind the picks could be budgeted out and
    the guideline's always-ride-along rule would be hollow. They sit
    between the critical tier and the picks."""
    chosen = select_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        small_bundle("checking-restraint"),
        scrub=str,
        auto_includes=("reviewing-module-design", "reviewing-naming-and-readability"),
    )
    names = [c.name for c in chosen.choices]
    assert names.index("reviewing-module-design") < names.index("checking-restraint")


def test_the_auto_includes_ride_a_fallback_selection():
    """A picker that fell back -- no usable reply -- does not lift the
    guideline's own mandate: the controller's shapes still add their
    lenses on the fallback paths."""
    selection, plan = select_agentic_lenses(
        Depth.REVIEW,
        None,
        small_bundle(
            "checking-restraint",
            "reviewing-module-design",
            "reviewing-naming-and-readability",
        ),
        scrub=str,
        auto_includes=("reviewing-module-design", "reviewing-naming-and-readability"),
    )
    names = [c.name for c in selection.choices]
    assert "reviewing-module-design" in names
    assert "reviewing-naming-and-readability" in names
    assert [u.name for u in plan.uses if u.status is LensStatus.RUN] == names


def test_a_repo_preference_exclude_drops_a_shape_auto_include():
    """A repo preference's exclude wins over the controller-added
    auto-include the way it wins over the controller-added hygiene lens
    (D69): the auto-include is neither floor-tier nor a cap."""
    preferences = LensPreferences(
        include=(), exclude=("reviewing-naming-and-readability",)
    )
    selection, _ = select_agentic_lenses(
        Depth.REVIEW,
        lambda: picks("checking-restraint"),
        small_bundle("checking-restraint"),
        scrub=str,
        preferences=preferences,
        auto_includes=("reviewing-module-design", "reviewing-naming-and-readability"),
    )
    names = [c.name for c in selection.choices]
    assert "reviewing-module-design" in names
    assert "reviewing-naming-and-readability" not in names
    assert "Auto-included on the shape facts: reviewing-module-design." in (
        selection.note
    )


def test_triage_is_not_widened_by_the_auto_includes():
    chosen = select_lenses(
        Depth.TRIAGE,
        None,
        REAL,
        scrub=str,
        auto_includes=("reviewing-module-design",),
    )
    assert [c.name for c in chosen.choices] == list(CRITICAL_TIER)


def test_the_auto_included_lenses_exist_in_the_bundle():
    """An auto-include the bundle carries no body for is NOT RUN, so a
    renamed or dropped lens would silently hollow the enforcement: the
    five names the shapes mandate must exist in the real bundle."""
    from atlas_reviewer.picker import (
        DECISION_CURRENCY_LENS,
        DECISION_LENS,
        DOCS_HEALTH_LENS,
        MODULE_DESIGN_LENS,
        NAMING_LENS,
    )

    for name in (
        DECISION_LENS,
        DECISION_CURRENCY_LENS,
        DOCS_HEALTH_LENS,
        MODULE_DESIGN_LENS,
        NAMING_LENS,
    ):
        assert LensLibrary().body(name) is not None, name


def test_an_auto_include_the_picker_also_named_is_not_planned_twice():
    """The picker naming a mandated lens must not turn the controller's
    own copy into a second choice: a repeated name is NOT RUN with
    "already chosen earlier in this plan", and a NOT RUN lens blocks
    coverage. The shape's copy dedupes against the covered set."""
    selection, plan = select_agentic_lenses(
        Depth.REVIEW,
        lambda: picks("reviewing-module-design"),
        small_bundle("reviewing-module-design", "reviewing-naming-and-readability"),
        scrub=str,
        auto_includes=("reviewing-module-design", "reviewing-naming-and-readability"),
    )
    names = [c.name for c in selection.choices]
    assert names.count("reviewing-module-design") == 1
    assert [u.name for u in plan.uses if u.status is LensStatus.RUN] == names
