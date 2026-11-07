# SPDX-License-Identifier: MIT
import pytest

from atlas_reviewer.diffs import (
    BOUNDARY,
    CONFIG,
    CUT_MARKER,
    DOCS,
    MAX_FIT_ROUNDS,
    SECURITY,
    SOURCE,
    SUPPLY_CHAIN,
    TESTS,
    UNPARSED_PATH,
    describe_by_risk,
    diff_paths,
    fit_diff,
    risk_tier,
    select_diff,
    split_files,
)


def file_diff(path: str, body: str = "x" * 20) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n+{body}\n"


DIFF = file_diff("a.py") + file_diff("b/c.py") + file_diff("d.md")


def paths(files):
    return [f.path for f in files]


def test_paths_are_the_new_side_in_order_including_renames():
    renamed = "diff --git a/old name.py b/new name.py\nsimilarity index 100%\n"
    assert diff_paths(DIFF + renamed) == ("a.py", "b/c.py", "d.md", "new name.py")


QUOTED = (
    'diff --git "a/tab\\there.py" "b/tab\\there.py"\n+x\n'
    'diff --git "a/caf\\303\\251.md" "b/caf\\303\\251.md"\n+y\n'
    'diff --git a/old.py "b/say \\"hi\\" \\\\ back.py"\n+z\n'
)


def test_quoted_git_headers_are_parsed_and_unescaped():
    expected = ("tab\there.py", "caf\u00e9.md", 'say "hi" \\ back.py')
    assert diff_paths(QUOTED) == expected
    files = split_files(QUOTED)
    assert tuple(paths(files)) == expected
    assert "".join(f.text for f in files) == QUOTED


def test_splitting_keeps_every_character_in_diff_order():
    files = split_files(DIFF)
    assert paths(files) == ["a.py", "b/c.py", "d.md"]
    assert "".join(f.text for f in files) == DIFF


def test_text_before_the_first_header_is_kept_as_a_pseudo_file():
    files = split_files("stray preamble\n" + DIFF)
    assert files[0].path == UNPARSED_PATH
    assert files[0].text == "stray preamble\n"
    assert split_files("not a diff")[0].text == "not a diff"
    assert split_files("") == ()


@pytest.mark.parametrize(
    "path,tier",
    [
        ("atlas_reviewer/github_auth.py", SECURITY),
        ("atlas_reviewer/redact.py", SECURITY),
        ("src/secrets_store.py", SECURITY),
        ("atlas_reviewer/runner.py", BOUNDARY),
        ("atlas_reviewer/http.py", BOUNDARY),
        ("atlas_reviewer/sprites_api.py", BOUNDARY),
        ("atlas_reviewer/openrouter.py", BOUNDARY),
        ("atlas_reviewer/draft.py", SOURCE),
        (".github/workflows/ci.yml", SUPPLY_CHAIN),
        ("requirements.txt", SUPPLY_CHAIN),
        ("pyproject.toml", SUPPLY_CHAIN),
        (".github/ISSUE_TEMPLATE/bug.yml", CONFIG),
        ("config/settings.yaml", CONFIG),
        ("atlas_reviewer/tests/test_redact.py", TESTS),
        ("atlas_reviewer/fixtures/sample-pr/runner-script.json", TESTS),
        ("docs/security.md", DOCS),
        ("skills/reviewing-ai-authored-code/examples.md", DOCS),
    ],
)
def test_risk_tiers_put_tests_and_docs_last_whatever_their_names(path, tier):
    assert risk_tier(path) is tier


def test_selection_puts_the_riskiest_files_first_and_leaves_docs_unseen():
    diff = (
        file_diff("README.md", "d" * 300)
        + file_diff("tests/test_auth.py", "t" * 300)
        + file_diff("app/auth.py", "a" * 300)
        + file_diff("app/http.py", "h" * 300)
    )
    one = len(file_diff("app/auth.py", "a" * 300))
    sel = select_diff(diff, max_parts=2, part_chars=one)
    assert [paths(p.files) for p in sel.parts] == [["app/auth.py"], ["app/http.py"]]
    assert paths(sel.unseen) == ["tests/test_auth.py", "README.md"]
    assert not sel.complete


def test_first_fit_lets_a_small_file_fill_a_gap_in_an_earlier_part():
    big, small = "b" * 500, "s" * 10
    diff = (
        file_diff("app/auth.py", big)
        + file_diff("app/x.py", big)
        + file_diff("z.md", small)
    )
    budget = len(file_diff("app/auth.py", big)) + len(file_diff("z.md", small))
    sel = select_diff(diff, max_parts=2, part_chars=budget)
    assert [paths(p.files) for p in sel.parts] == [
        ["app/auth.py", "z.md"],
        ["app/x.py"],
    ]
    assert sel.complete


def test_a_file_larger_than_one_call_is_cut_into_a_part_of_its_own():
    diff = file_diff("app/runner.py", "line\n" * 400) + file_diff("a.py")
    sel = select_diff(diff, max_parts=3, part_chars=500)
    (cut,) = sel.cut
    assert cut.path == "app/runner.py"
    assert cut.text.endswith(CUT_MARKER)
    assert len(cut.text) <= 500
    assert cut.shown_chars == len(cut.text) - len(CUT_MARKER)
    assert cut.full_chars > 2_000
    assert paths(sel.full) == ["a.py"]
    assert not sel.complete


def test_every_file_is_accounted_for_exactly_once():
    diff = "".join(file_diff(f"f{i}.py", "y" * (50 * i)) for i in range(12))
    sel = select_diff(diff, max_parts=3, part_chars=400)
    accounted = paths(sel.full) + paths(sel.cut) + paths(sel.unseen)
    assert sorted(accounted) == sorted(diff_paths(diff))
    assert len(sel.parts) <= 3
    assert all(p.chars <= 400 for p in sel.parts)
    assert sel.total_files == 12 and sel.total_chars == len(diff)


def test_an_empty_diff_has_no_parts_and_is_complete():
    sel = select_diff("", 3, 1_000)
    assert sel.parts == () and sel.complete


def test_unseen_files_are_described_grouped_by_risk_with_a_count_of_the_rest():
    files = split_files(
        file_diff("docs/a.md") + file_diff("app/auth.py") + file_diff("tests/test_x.py")
    )
    assert describe_by_risk(files, 10) == (
        "[security, auth, secrets and redaction] app/auth.py; "
        "[tests and fixtures] tests/test_x.py; [docs] docs/a.md"
    )
    assert describe_by_risk(files, 1) == (
        "[security, auth, secrets and redaction] app/auth.py; and 2 more"
    )


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/release.yml",
        ".github/actions/setup/action.yml",
        "tools/action.yaml",
        ".gitlab-ci.yml",
        ".circleci/config.yml",
        ".github/dependabot.yml",
        "requirements.txt",
        "requirements-dev.in",
        "docs/requirements.txt",
        "tests/requirements.txt",
        "constraints.txt",
        "pyproject.toml",
        "setup.py",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "package.json",
        "web/package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "go.mod",
        "go.sum",
        "Cargo.lock",
        "Gemfile",
        "fixtures/app.gemspec",
        "Dockerfile",
        "docker/Dockerfile.ci",
        "Makefile",
        "tests/conftest.py",
    ],
)
def test_ci_dependency_and_build_files_rank_high_whatever_their_directory(path):
    """Pilot 3, ranking finding: workflows and lockfiles ranked below
    ordinary code, and a `tests/` or `docs/` directory demoted them."""
    tier = risk_tier(path)
    assert tier is SUPPLY_CHAIN
    assert tier.rank < BOUNDARY.rank < SOURCE.rank


def test_ci_and_lockfiles_are_reviewed_before_ordinary_code_when_budget_is_short():
    diff = (
        file_diff("app/views.py", "v" * 500)
        + file_diff("uv.lock", "l" * 300)
        + file_diff(".github/workflows/ci.yml", "w" * 300)
    )
    sel = select_diff(diff, 1, 900)
    assert paths(sel.parts[0].files) == ["uv.lock", ".github/workflows/ci.yml"]
    assert paths(sel.unseen) == ["app/views.py"]


# --- fitting parts to the measured prompt -----------------------------------

BIG = "".join(file_diff(f"src/m{i}.py", "x" * 900) for i in range(10))


def largest(sel):
    return max(p.chars for p in sel.parts)


def test_a_selection_that_fits_is_returned_after_one_measurement():
    seen = []
    sel = fit_diff(BIG, 2, 50_000, lambda s: seen.append(s) or -1, 1_000)
    assert len(seen) == 1
    assert sel.part_chars == 50_000 and sel.complete


def test_parts_shrink_until_the_whole_prompt_fits():
    overhead, room = 700, 3_000
    sel = fit_diff(BIG, 3, 50_000, lambda s: largest(s) + overhead - room, 1_000)
    assert largest(sel) + overhead <= room
    assert sel.part_chars < 50_000
    assert not sel.complete


def test_fitting_stops_at_the_minimum_part_size():
    sel = fit_diff(BIG, 1, 5_000, lambda s: 10**6, 1_000)
    assert sel.part_chars == 1_000


def test_fitting_gives_up_after_a_bounded_number_of_rounds():
    seen = []
    fit_diff(BIG, 1, 50_000, lambda s: seen.append(s) or 1, 1_000)
    assert len(seen) == MAX_FIT_ROUNDS


def test_an_empty_diff_shrinks_by_the_overflow_alone():
    sel = fit_diff("", 1, 5_000, lambda s: 100 if s.part_chars == 5_000 else -1, 1_000)
    assert sel.part_chars == 4_900


def test_multibyte_parts_shrink_by_characters_not_bytes():
    wide = "".join(file_diff(f"src/m{i}.py", "\u6f22" * 900) for i in range(10))
    room = 9_000
    sel = fit_diff(
        wide,
        3,
        50_000,
        lambda s: max(len(p.text.encode()) for p in s.parts) - room,
        1_000,
    )
    assert max(len(p.text.encode()) for p in sel.parts) <= room
    assert max(len(p.text.encode()) for p in sel.parts) > room - 3 * 1_000
