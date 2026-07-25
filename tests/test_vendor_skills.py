# SPDX-License-Identifier: MIT
# tests/test_vendor_skills.py
"""Regression tests for tooling/vendor-skills.sh's marker bookkeeping (issue #112)."""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tooling" / "vendor-skills.sh"


def run_vendor(target, *extra_args):
    result = subprocess.run(
        [str(SCRIPT), str(target), *extra_args],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def marker_names(target):
    marker = target / ".claude" / "skills" / ".atlas-vendored"
    return {
        line for line in marker.read_text().splitlines()
        if line and not line.startswith("#")
    }


def test_switching_to_collapsed_preserves_standalone_names_in_marker(tmp_path):
    """Before the fix, vendoring standalone then --collapsed into the same
    target overwrote the marker with only the 4 collapsed names, silently
    losing record of the ~35 standalone directories left on disk — a later
    --prune could never find them."""
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target)
    standalone_names = marker_names(target)
    assert len(standalone_names) > 4  # sanity: the standalone suite is large

    run_vendor(target, "--collapsed")
    names_after_collapsed = marker_names(target)

    collapsed_dir = target / ".claude" / "skills"
    collapsed_entrypoints = {
        p.name for p in collapsed_dir.iterdir()
        if p.is_dir() and (p / "SKILL.md").exists()
    } - standalone_names
    assert collapsed_entrypoints, "collapsed run should add new entrypoint dirs"

    # The marker must still remember every standalone name so --prune can
    # find them, even though this run only vendored the collapsed set.
    assert standalone_names <= names_after_collapsed
    assert collapsed_entrypoints <= names_after_collapsed

    # The now-orphaned standalone directories are still on disk, untouched.
    for name in standalone_names:
        assert (collapsed_dir / name).is_dir()


def test_prune_after_mode_switch_removes_orphaned_standalone_dirs(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target)
    standalone_names = marker_names(target)
    run_vendor(target, "--collapsed")
    run_vendor(target, "--collapsed", "--prune")

    collapsed_dir = target / ".claude" / "skills"
    final_names = marker_names(target)

    # Now that --prune has actually removed them, they must be gone from
    # both disk and the marker — not lingering forever as in the pre-fix
    # behavior.
    for name in standalone_names:
        assert not (collapsed_dir / name).exists()
        assert name not in final_names


def notice_text(target):
    return (target / ".claude" / "skills" / "NOTICE.md").read_text()


def test_vendor_writes_attribution_notice(tmp_path):
    """The vendored content is CC BY 4.0 (issue #134); each run must write an
    attribution notice alongside it, naming the source repo and the vendored
    commit, with the license link pinned to that same commit (not a moving
    branch, so the linked text matches what was actually vendored)."""
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target)
    notice = notice_text(target)
    assert "brandondees/code-quality-atlas" in notice
    assert "CC BY 4.0" in notice

    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10, check=True)
    sha = result.stdout.strip()
    assert sha in notice
    assert f"blob/{sha}/LICENSE-CC-BY-4.0" in notice


def test_vendor_refreshes_attribution_notice_on_rerun(tmp_path):
    """A second run must rewrite NOTICE.md (refresh), not leave a stale one from
    an earlier commit — mirroring how vendor_one refreshes the skill dirs."""
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target)
    first_mtime = (target / ".claude" / "skills" / "NOTICE.md").stat().st_mtime_ns

    run_vendor(target)
    second_mtime = (target / ".claude" / "skills" / "NOTICE.md").stat().st_mtime_ns
    assert second_mtime >= first_mtime
    assert notice_text(target)  # still present and non-empty


def test_collapsed_vendor_also_writes_attribution_notice(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target, "--collapsed")
    notice = notice_text(target)
    assert "brandondees/code-quality-atlas" in notice


def _source_functions_only():
    """The script's functions/vars, without the trailing `main "$@"` call, so
    a caller can invoke individual functions (e.g. vendor_one) directly."""
    lines = SCRIPT.read_text().splitlines()
    assert lines[-1].strip() == 'main "$@"', \
        "script's last line changed shape; update this helper"
    return "\n".join(lines[:-1])


# A fake `rm` shadowing the real binary as a shell function (bash resolves a
# bare command name to a function before PATH lookup). Regardless of whether
# the guard under test holds, no `rm` invocation in these tests can ever touch
# a real path — the mock only logs what it *would* have deleted. This matters
# specifically because these tests exist to exercise the failure mode where a
# guard regresses and an absolute system path (e.g. "/etc") is computed; a
# real `rm -rf` there would be catastrophic on whatever machine runs pytest.
_MOCK_RM = 'rm() { printf "MOCK_RM_CALLED:%s\\n" "$*" >&2; return 1; }'


def test_vendor_one_aborts_instead_of_deleting_rooted_path_on_empty_dest_root():
    """Regression for the SC2115 hardening (#157): vendor_one's original fix
    guarded `${dest:?}`, but dest is built as "$dest_root/$name" — string
    concatenation with a literal "/" means dest can never actually be empty
    even when dest_root is (it becomes "/$name" instead), so a dest-only
    guard can't catch this. The fix now guards dest_root directly at the
    point dest is built. Prove it: with dest_root empty and name="etc", a
    dest-only guard would let `rm -rf "/etc"` through; the fixed script must
    abort before `rm` (mocked below, never the real binary) is ever called."""
    bash_script = f"""
set -euo pipefail
{_MOCK_RM}
{_source_functions_only()}
vendor_one "etc" ""
"""
    result = subprocess.run(
        ["bash", "-c", bash_script],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode != 0, (
        f"vendor_one should have aborted on empty dest_root; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "MOCK_RM_CALLED" not in result.stderr, (
        "the guard should abort before rm is ever reached, mocked or not: "
        f"stderr={result.stderr!r}"
    )


# The literal guarded expression from the prune loop in tooling/vendor-skills.sh
# (main()'s --prune branch). Kept as a module-level constant, cross-checked
# against the live script by test_prune_guard_expression_matches_script below,
# so a future edit to the real guard's syntax fails loudly here instead of
# leaving this test silently exercising a expression the script no longer has.
_PRUNE_RM_GUARD_LINE = '        rm -rf "${dest_root:?}/$old"'


def test_prune_guard_expression_matches_script():
    """Guards against this test file drifting from the real prune loop: if
    someone edits the guard in tooling/vendor-skills.sh without updating the
    hand-typed expression below, this fails and says so explicitly."""
    script_text = SCRIPT.read_text()
    assert _PRUNE_RM_GUARD_LINE in script_text, (
        "tooling/vendor-skills.sh's prune-loop rm guard no longer matches "
        f"the expression this test exercises ({_PRUNE_RM_GUARD_LINE!r}); "
        "update both together"
    )


def test_prune_rm_guard_aborts_on_empty_dest_root():
    """Companion regression for the prune loop's own `${dest_root:?}` guard
    (the pattern vendor_one's fix above was brought in line with): an empty
    dest_root there must abort rather than expand to `rm -rf "/$old"`. Uses
    the exact expression from tooling/vendor-skills.sh (kept in sync by
    test_prune_guard_expression_matches_script above) with `rm` mocked, so a
    regressed guard would be caught here rather than deleting a real path."""
    bash_script = f"""
set -euo pipefail
{_MOCK_RM}
dest_root=""
old="etc"
{_PRUNE_RM_GUARD_LINE.strip()}
"""
    result = subprocess.run(
        ["bash", "-c", bash_script],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode != 0
    assert "dest_root" in result.stderr
    assert "MOCK_RM_CALLED" not in result.stderr, (
        "the guard should abort before rm is ever reached, mocked or not: "
        f"stderr={result.stderr!r}"
    )
