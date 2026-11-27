# SPDX-License-Identifier: MIT
# tests/test_package_account_zips.py
"""Regression tests for tooling/package-account-zips.sh's CC BY attribution
(issue #161's Major finding: the account-zips distribution channel had no
equivalent of vendor-skills.sh's NOTICE.md)."""

import os
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tooling" / "package-account-zips.sh"


def run_package(out_dir, *extra_args):
    result = subprocess.run(
        [str(SCRIPT), "--out", str(out_dir), *extra_args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _current_sha():
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return result.stdout.strip()


def _read_from_zip(zip_path, member):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(member).decode("utf-8")


def _expected_standalone_skill_names():
    return {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}


def test_every_per_skill_zip_contains_a_notice(tmp_path):
    """Every ZIP the claude.ai GUI accepts must carry its own attribution —
    each ZIP is uploaded and extracted independently, so a single notice
    somewhere else in the repo can't cover it."""
    out_dir = tmp_path / "zips"
    run_package(out_dir)

    zips = sorted(out_dir.glob("*.zip"))
    zip_names = {z.stem for z in zips}
    expected = _expected_standalone_skill_names()
    assert zip_names == expected, (
        "one ZIP per skills/*/SKILL.md directory, no more, no fewer — a "
        "threshold check here would miss a narrowed packaging glob "
        f"(missing: {expected - zip_names}, extra: {zip_names - expected})"
    )

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


def test_every_per_skill_zip_vendors_the_license_text(tmp_path):
    """Issue #351: unlike vendor-skills.sh (fixed for #1157), this channel's
    write_attribution() used to ship only a NOTICE.md linking back to
    LICENSE-CC-BY-4.0 on GitHub, never the license text itself. That's worse
    here than it was for #1157: an uploaded zip is extracted into a claude.ai
    account skill with no ongoing relationship to this git repo at all, so a
    dead or unreachable link would be the *only* copy of the license terms
    that skill will ever have. Every zip must carry its own verbatim copy."""
    out_dir = tmp_path / "zips"
    run_package(out_dir)

    source_license = (ROOT / "LICENSE-CC-BY-4.0").read_bytes()

    zips = sorted(out_dir.glob("*.zip"))
    zip_names = {z.stem for z in zips}
    expected = _expected_standalone_skill_names()
    assert zip_names == expected, (
        "one ZIP per skills/*/SKILL.md directory, no more, no fewer — a "
        "threshold check here would miss a narrowed packaging glob "
        f"(missing: {expected - zip_names}, extra: {zip_names - expected})"
    )

    for zip_path in zips:
        name = zip_path.stem
        with zipfile.ZipFile(zip_path) as zf:
            vendored = zf.read(f"{name}/LICENSE-CC-BY-4.0")
        assert vendored == source_license


def test_notice_references_the_vendored_license_file(tmp_path):
    out_dir = tmp_path / "zips"
    run_package(out_dir)

    zip_path = out_dir / "checking-restraint.zip"
    notice = _read_from_zip(zip_path, "checking-restraint/NOTICE.md")
    # The vendored file is named explicitly, not just linked.
    assert "vendored alongside" in notice
    assert "`LICENSE-CC-BY-4.0`" in notice


def test_collapsed_zips_also_vendor_the_license_text(tmp_path):
    out_dir = tmp_path / "zips"
    run_package(out_dir, "--collapsed")

    source_license = (ROOT / "LICENSE-CC-BY-4.0").read_bytes()
    zip_path = out_dir / "reviewing-a-change.zip"
    with zipfile.ZipFile(zip_path) as zf:
        vendored = zf.read("reviewing-a-change/LICENSE-CC-BY-4.0")
    assert vendored == source_license


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
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "could not resolve a git commit SHA" in result.stderr

    notice = _read_from_zip(
        out_dir / "reviewing-a-change.zip", "reviewing-a-change/NOTICE.md"
    )
    assert "blob/unknown/LICENSE-CC-BY-4.0" in notice


@pytest.mark.parametrize("flag", ["--bundle", "--bundle-only"])
def test_removed_bundle_flags_name_the_replacement(tmp_path, flag):
    """--bundle/--bundle-only were removed (#449, no real consumer -- the
    claude.ai GUI rejects a multi-skill ZIP outright). A caller who still
    remembers either flag should be pointed at the actual replacement
    (vendor-skills.sh), not left with a bare "unknown argument"."""
    result = subprocess.run(
        [str(SCRIPT), "--out", str(tmp_path), flag],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert flag in result.stderr
    assert "was removed" in result.stderr
    assert "tooling/vendor-skills.sh" in result.stderr
