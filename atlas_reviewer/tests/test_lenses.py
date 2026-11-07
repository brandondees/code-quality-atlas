# SPDX-License-Identifier: MIT

from atlas_reviewer.lenses import (
    LENS_BUDGET_CHARS,
    MAX_LENSES,
    MIN_TRUNCATED_CHARS,
    LensChoice,
    LensLibrary,
    LensStatus,
    plan_lenses,
)
from atlas_reviewer.picker import CRITICAL_TIER


def test_review_breadth_is_the_top_of_the_manifests_3_to_8():
    assert MAX_LENSES == 8


def test_every_critical_tier_lens_has_a_body_in_the_bundle():
    assert all(LensLibrary().body(n) for n in CRITICAL_TIER)


class StubLibrary(LensLibrary):
    def __init__(self, bodies):
        self._bodies = bodies

    def body(self, name):
        return self._bodies.get(name)


def choice(name):
    return LensChoice(name, "picker rank 1")


def test_plan_includes_what_fits_truncates_one_and_omits_the_rest():
    lib = StubLibrary(
        {"a": "A" * 6_000 + "\n", "b": ("B" * 99 + "\n") * 100, "c": "C" * 5_000}
    )
    plan = plan_lenses(lib, [choice(n) for n in "abc"], budget_chars=12_000)
    by = {u.name: u for u in plan.uses}
    assert by["a"].status is LensStatus.INCLUDED
    assert by["b"].status is LensStatus.TRUNCATED
    assert 0 < by["b"].kept_chars < by["b"].total_chars
    assert by["c"].status is LensStatus.OMITTED
    assert "size budget" in by["c"].why
    loaded = {lens.name: lens.text for lens in plan.loaded}
    assert loaded["a"] == "A" * 6_000 + "\n"
    assert "lens body truncated by atlas_reviewer" in loaded["b"]
    assert "c" not in loaded
    assert plan.coverage().startswith("included: a; truncated: b (")


def test_a_sliver_of_budget_omits_instead_of_truncating():
    lib = StubLibrary({"a": "A" * 9_000, "b": "B" * 9_000})
    plan = plan_lenses(
        lib, [choice("a"), choice("b")], budget_chars=9_000 + MIN_TRUNCATED_CHARS - 1
    )
    assert [u.status for u in plan.uses] == [LensStatus.INCLUDED, LensStatus.OMITTED]


def test_lenses_past_the_cap_are_omitted_even_when_budget_remains():
    lib = StubLibrary({f"l{i}": "x" * 10 for i in range(MAX_LENSES + 2)})
    plan = plan_lenses(lib, [choice(f"l{i}") for i in range(MAX_LENSES + 2)])
    assert len(plan.loaded) == MAX_LENSES
    assert all("below the cap" in u.why for u in plan.uses[MAX_LENSES:])


def test_a_lens_with_no_body_is_omitted_not_invented():
    plan = plan_lenses(StubLibrary({}), [choice("ghost")])
    assert plan.uses[0].status is LensStatus.OMITTED
    assert plan.loaded == ()


def test_real_bundle_plan_stays_inside_the_budget():
    ranked = [choice(n) for n in sorted(LensLibrary().names())]
    plan = plan_lenses(LensLibrary(), ranked)
    assert sum(len(lens.text) for lens in plan.loaded) <= LENS_BUDGET_CHARS + 200
    assert len(plan.loaded) >= 3
