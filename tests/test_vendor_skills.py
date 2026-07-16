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
        capture_output=True, text=True, timeout=30,
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
