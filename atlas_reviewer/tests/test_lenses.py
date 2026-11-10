# SPDX-License-Identifier: MIT

import json

from atlas_reviewer.lenses import (
    LENS_BUDGET_CHARS,
    MAX_LENSES,
    LensChoice,
    LensLibrary,
    LensStatus,
    plan_lenses,
)
from atlas_reviewer.picker import CRITICAL_TIER, Depth, select_lenses


def test_review_breadth_is_the_top_of_the_manifests_3_to_8():
    assert MAX_LENSES == 8


def test_every_critical_tier_lens_has_a_body_in_the_bundle():
    assert all(LensLibrary().body(n) for n in CRITICAL_TIER)


class StubLibrary(LensLibrary):
    def __init__(self, bodies):
        self._bodies = bodies

    def body(self, name):
        return self._bodies.get(name)


def choice(name, why="picker rank 1"):
    return LensChoice(name, why)


def test_a_lens_larger_than_the_budget_left_is_skipped_whole_and_a_later_one_fits():
    lib = StubLibrary(
        {"a": "A" * 6_000 + "\n", "b": ("B" * 99 + "\n") * 100, "c": "C" * 5_000}
    )
    ranked = [choice("a"), choice("b", "picker rank 2"), choice("c", "picker rank 3")]
    plan = plan_lenses(lib, ranked, budget_chars=12_000)
    by = {u.name: u for u in plan.uses}
    assert [by[n].status for n in "abc"] == [
        LensStatus.RUN,
        LensStatus.NOT_RUN,
        LensStatus.RUN,
    ]
    assert by["b"].reason == (
        "did not fit the 12000-character lens budget whole "
        "(10000 characters, 5999 left)"
    )
    assert {lens.name: lens.text for lens in plan.loaded} == {
        "a": "A" * 6_000 + "\n",
        "c": "C" * 5_000,
    }
    assert plan.coverage() == (
        "run whole: a, c; NOT RUN: b (did not fit the 12000-character lens "
        "budget whole (10000 characters, 5999 left); picker rank 2)"
    )


def test_a_lens_that_fits_exactly_runs_and_one_character_over_does_not():
    lib = StubLibrary({"a": "A" * 100, "b": "B" * 101})
    exact = plan_lenses(lib, [choice("a")], budget_chars=100)
    over = plan_lenses(lib, [choice("b")], budget_chars=100)
    assert exact.uses[0].status is LensStatus.RUN
    assert over.uses[0].status is LensStatus.NOT_RUN and over.loaded == ()


def test_lenses_past_the_cap_are_not_run_even_when_budget_remains():
    lib = StubLibrary({f"l{i}": "x" * 10 for i in range(MAX_LENSES + 2)})
    plan = plan_lenses(lib, [choice(f"l{i}") for i in range(MAX_LENSES + 2)])
    assert len(plan.loaded) == MAX_LENSES
    assert all(u.status is LensStatus.NOT_RUN for u in plan.uses[MAX_LENSES:])
    assert all("below the cap of 8 lenses" == u.reason for u in plan.uses[MAX_LENSES:])


def test_a_lens_with_no_body_is_not_run_not_invented():
    plan = plan_lenses(StubLibrary({}), [choice("ghost")])
    assert plan.uses[0].status is LensStatus.NOT_RUN
    assert plan.uses[0].reason == "no body.md in the bundle"
    assert plan.loaded == ()
    assert plan.coverage() == "NOT RUN: ghost (no body.md in the bundle; picker rank 1)"


def test_nothing_selected_says_so():
    assert plan_lenses(StubLibrary({}), []).coverage() == "no lens selected"


def _bundle_plan(depth, reply=None):
    library = LensLibrary()
    run = None if reply is None else (lambda: json.dumps({"lenses": reply}))
    chosen = select_lenses(depth, run, lambda n: library.body(n) is not None)
    return plan_lenses(library, chosen.choices, depth.limit)


def test_every_real_lens_is_inlined_whole_or_not_at_all():
    library = LensLibrary()
    plan = plan_lenses(library, [choice(n) for n in sorted(library.names())])
    assert sum(len(lens.text) for lens in plan.loaded) <= LENS_BUDGET_CHARS
    for lens in plan.loaded:
        assert lens.text == library.body(lens.name)
    ran = {u.name for u in plan.uses if u.status is LensStatus.RUN}
    assert ran == {lens.name for lens in plan.loaded}


def test_a_thin_pick_cannot_drop_a_critical_lens_except_by_it_not_fitting():
    plan = _bundle_plan(Depth.REVIEW, ["checking-restraint"])
    by = {u.name: u for u in plan.uses}
    for name in CRITICAL_TIER:
        use = by[name]
        assert use.why.startswith("critical tier")
        if use.status is LensStatus.NOT_RUN:
            assert use.reason.startswith("did not fit the 60000-character")
            assert f"{name} (did not fit" in plan.coverage()
    assert [u.name for u in plan.uses[: len(CRITICAL_TIER)]] == list(CRITICAL_TIER)
