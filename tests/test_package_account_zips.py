# SPDX-License-Identifier: MIT
# tests/test_package_account_zips.py
"""Regression tests for tooling/package-account-zips.sh's CC BY attribution
(issue #161's Major finding: the account-zips distribution channel had no
equivalent of vendor-skills.sh's NOTICE.md)."""
import os
import subprocess
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tooling" / "package-account-zips.sh"


def run_package(out_dir, *extra_args):
    result = subprocess.run(
        [str(SCRIPT), "--out", str(out_dir), *extra_args],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result


def _current_sha():
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10, check=True)
    return result.stdout.strip()


def _read_from_zip(zip_path, member):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(member).decode("utf-8")


def test_every_per_skill_zip_contains_a_notice(tmp_path):
    """Every ZIP the claude.ai GUI accepts must carry its own attribution —
    each ZIP is uploaded and extracted independently, so a single notice
    somewhere else in the repo can't cover it."""
    out_dir = tmp_path / "zips"
    run_package(out_dir)

    zips = sorted(out_dir.glob("*.zip"))
    assert len(zips) > 30  # sanity: the standalone suite is large

    for zip_path in zips:
        name = zip_path.stem
        notice = _read_from_zip(zip_path, f"{name}/NOTICE.md")
        assert "brandondees/code-quality-atlas" in notice
        assert "CC BY 4.0" in notice


def test_notice_names_source_repo_commit_and_pinned_license_link(tmp_path):
    out_dir = tmp_path / "zips"
    run_package(out_dir)

    zip_path = out_dir / "checking-restraint.zip"
    notice = _read_from_zip(zip_path, "checking-restraint/NOTICE.md")

    sha = _current_sha()
    assert sha in notice
    assert f"blob/{sha}/LICENSE-CC-BY-4.0" in notice


def test_evals_are_excluded_but_skill_content_is_intact(tmp_path):
    """The staging rewrite (needed to add NOTICE.md) must not regress the
    existing evals/ exclusion or drop SKILL.md / reference/ content."""
    out_dir = tmp_path / "zips"
    run_package(out_dir)

    zip_path = out_dir / "checking-restraint.zip"
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

    assert any(n.endswith("SKILL.md") for n in names)
    assert any("/reference/" in n for n in names)
    assert not any("/evals/" in n for n in names)


def test_skill_with_no_reference_dir_still_packages(tmp_path):
    """choosing-review-lenses has no reference/ subdirectory — the staging
    step's `[ -d ... ] && cp -R ...` guard is the last statement in
    stage_skill(); without an explicit `return 0` a false test there returns
    non-zero from the function and set -e kills the whole run."""
    out_dir = tmp_path / "zips"
    run_package(out_dir)

    zip_path = out_dir / "choosing-review-lenses.zip"
    assert zip_path.exists()
    notice = _read_from_zip(zip_path, "choosing-review-lenses/NOTICE.md")
    assert "brandondees/code-quality-atlas" in notice


def test_collapsed_zips_also_carry_notice(tmp_path):
    out_dir = tmp_path / "zips"
    run_package(out_dir, "--collapsed")

    zip_path = out_dir / "reviewing-a-change.zip"
    assert zip_path.exists()
    notice = _read_from_zip(zip_path, "reviewing-a-change/NOTICE.md")
    assert "brandondees/code-quality-atlas" in notice


def test_unresolvable_sha_warns_on_stderr(tmp_path):
    """If `git rev-parse --short HEAD` fails (e.g. run from a source export
    with no .git), sha falls back to the literal 'unknown', which gets baked
    into every NOTICE.md's pinned license URL as a dead link. The script
    should warn on stderr so a packager notices before distributing —
    silently is not good enough for a change whose whole point is license
    compliance. repo_root() has its own git-unavailable fallback (walking up
    from the script's location), so packaging still succeeds; only the SHA
    resolution should degrade."""
    out_dir = tmp_path / "zips"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nexit 1\n")
    fake_git.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(
        [str(SCRIPT), "--out", str(out_dir), "--collapsed"],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "could not resolve a git commit SHA" in result.stderr

    notice = _read_from_zip(out_dir / "reviewing-a-change.zip", "reviewing-a-change/NOTICE.md")
    assert "blob/unknown/LICENSE-CC-BY-4.0" in notice


def test_bundle_zip_also_carries_per_skill_notices(tmp_path):
    """The --bundle archive isn't GUI-uploadable, but it still redistributes
    the same CC BY content and should carry the same per-skill notices."""
    out_dir = tmp_path / "zips"
    run_package(out_dir, "--collapsed", "--bundle-only")

    bundle = out_dir / "code-quality-atlas-skills.zip"
    assert bundle.exists()
    notice = _read_from_zip(bundle, "reviewing-a-change/NOTICE.md")
    assert "brandondees/code-quality-atlas" in notice
