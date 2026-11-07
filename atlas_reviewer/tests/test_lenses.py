# SPDX-License-Identifier: MIT

from atlas_reviewer.lenses import (
    BASELINE,
    GENERAL,
    LENS_BUDGET_CHARS,
    MAX_LENSES,
    MIN_TRUNCATED_CHARS,
    ROUTES,
    LensChoice,
    LensLibrary,
    LensStatus,
    plan_lenses,
    rank_lenses,
)


def names(ranked):
    return [c.name for c in ranked]


def test_every_lens_a_route_names_exists_in_the_skill_bundle():
    known = LensLibrary().names()
    named = {n for r in (*ROUTES, BASELINE, GENERAL) for n in r.lenses}
    assert named <= known, sorted(named - known)
    assert all(LensLibrary().body(n) for n in named)


def test_auth_paths_rank_the_security_lens_first():
    ranked = rank_lenses(["src/auth/login.py"], "add login throttling")
    assert names(ranked)[0] == "sweeping-for-security"
    assert "auth or untrusted input" in ranked[0].why


def test_text_signals_select_lenses_when_paths_say_nothing():
    ranked = rank_lenses(["lib/x.py"], "this refactor splits the module")
    assert "reviewing-module-design" in names(ranked)[:3]


def test_a_tests_only_change_leads_with_test_quality():
    ranked = rank_lenses(["tests/test_a.py", "tests/test_b.py"], "more tests")
    assert names(ranked)[:2] == [
        "reviewing-test-quality",
        "checking-idioms-and-consistency",
    ]


def test_a_mixed_change_is_not_tests_only():
    ranked = rank_lenses(["tests/test_a.py", "src/a.py"], "")
    assert not any("tests only" in c.why for c in ranked)


def test_tests_only_and_docs_only_changes_skip_the_general_change_fallback():
    for paths in (["tests/test_a.py"], ["README.md"]):
        ranked = rank_lenses(paths, "")
        assert not any("general change" in c.why for c in ranked)


def test_a_docs_only_change_selects_process_hygiene():
    ranked = rank_lenses(["README.md", "docs/guide.md"], "")
    assert (
        "docs only"
        in {c.name: c.why for c in ranked}["reviewing-pr-and-process-hygiene"]
    )


def test_unmatched_changes_still_get_the_baseline_lenses():
    ranked = rank_lenses(["lib/x.py"], "")
    assert set(names(ranked)) == set(BASELINE.lenses) | set(GENERAL.lenses)


def test_no_paths_and_no_text_is_still_a_baseline_review():
    ranked = rank_lenses([], "")
    assert set(names(ranked)) == set(BASELINE.lenses) | set(GENERAL.lenses)


def test_ranking_is_deterministic():
    args = (["src/auth/login.py", "web/app.tsx"], "fix a crash")
    assert rank_lenses(*args) == rank_lenses(*args)


class StubLibrary(LensLibrary):
    def __init__(self, bodies):
        self._bodies = bodies

    def body(self, name):
        return self._bodies.get(name)


def choice(name):
    return LensChoice(name, 1, ("route",))


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
    ranked = rank_lenses(["src/auth/login.py", "web/app.tsx"], "fix a crash")
    plan = plan_lenses(LensLibrary(), ranked)
    assert sum(len(lens.text) for lens in plan.loaded) <= LENS_BUDGET_CHARS + 200
    assert len(plan.loaded) >= 3
