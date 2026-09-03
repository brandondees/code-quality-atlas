# SPDX-License-Identifier: MIT
# tests/test_vendor_skills.py
"""Regression tests for tooling/vendor-skills.sh's marker bookkeeping (issue
#112), --with-lens-coverage-hook (issue #357/Q23, #398), and marker-line
trust boundary, --dry-run, and provenance/UX gaps (issue #377)."""
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


def license_file(target):
    return target / ".claude" / "skills" / "LICENSE-CC-BY-4.0"


def test_vendor_writes_license_file_matching_source(tmp_path):
    """Issue #1157 (second-brain-config): a target repo's vendored skills
    carried an attribution notice that only *linked* to the license at the
    pinned commit, with no local copy — so the notice's own promise ("the
    license text matches what was actually vendored") depended on a live
    fetch from GitHub rather than anything actually shipped alongside the
    skills. Vendor the real license text so a target repo's copy is
    self-contained."""
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target)

    vendored = license_file(target)
    assert vendored.is_file()
    assert vendored.read_bytes() == (REPO_ROOT / "LICENSE-CC-BY-4.0").read_bytes()


def test_collapsed_vendor_also_writes_license_file(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target, "--collapsed")

    vendored = license_file(target)
    assert vendored.is_file()
    assert vendored.read_bytes() == (REPO_ROOT / "LICENSE-CC-BY-4.0").read_bytes()


def test_attribution_notice_references_the_vendored_license_file(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target)
    notice = notice_text(target)
    assert "LICENSE-CC-BY-4.0" in notice
    # The link to the pinned-commit source stays too, as a cross-check.
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10, check=True)
    sha = result.stdout.strip()
    assert f"blob/{sha}/LICENSE-CC-BY-4.0" in notice


def run_vendor_raw(target, *extra_args):
    # check=False: callers inspect result.returncode themselves (both
    # success and expected-failure cases), matching run_vendor's pattern.
    return subprocess.run(
        [str(SCRIPT), str(target), *extra_args],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=30, check=False,
    )


def test_vendor_skips_preexisting_non_tool_managed_directory(tmp_path):
    """Regression for #175: vendor_one used to `rm -rf` the destination
    directory for every skill name unconditionally, with no check for
    whether the target repo already had unrelated content there before this
    tool ever ran. A target repo's own pre-existing, hand-authored skill
    directory sharing a name with one of the suite's skills (e.g.
    checking-restraint) must survive a first vendoring run untouched, not be
    silently destroyed."""
    target = tmp_path / "target-repo"
    skills_dir = target / ".claude" / "skills"
    colliding = skills_dir / "checking-restraint"
    colliding.mkdir(parents=True)
    (colliding / "SKILL.md").write_text("# hand-authored, not vendored\n")
    (colliding / "my-private-notes.txt").write_text("do not delete\n")

    result = run_vendor_raw(target)
    assert result.returncode != 0, (
        "a run that skips a collision must exit non-zero so it's visible, "
        f"not silently succeed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "checking-restraint" in result.stderr
    assert "skipping" in result.stderr.lower() or "skipped" in result.stderr.lower()

    # The pre-existing content must be completely untouched.
    assert (colliding / "SKILL.md").read_text() == "# hand-authored, not vendored\n"
    assert (colliding / "my-private-notes.txt").read_text() == "do not delete\n"

    # Every other (non-colliding) skill must still have been vendored normally.
    other_skill_dirs = [
        p for p in skills_dir.iterdir()
        if p.is_dir() and p.name not in ("checking-restraint",) and (p / "SKILL.md").exists()
    ]
    assert len(other_skill_dirs) > 1

    # The marker must not claim ownership of the directory this run skipped,
    # so a later --prune can never be misled into treating it as tool-owned.
    assert "checking-restraint" not in marker_names(target)


def test_vendor_force_overwrites_preexisting_directory(tmp_path):
    """--force is the explicit escape hatch for #175's collision guard: with
    it, a colliding directory is overwritten (the pre-#175 behavior), the run
    succeeds, and the marker does claim the name going forward."""
    target = tmp_path / "target-repo"
    skills_dir = target / ".claude" / "skills"
    colliding = skills_dir / "checking-restraint"
    colliding.mkdir(parents=True)
    (colliding / "SKILL.md").write_text("# hand-authored, not vendored\n")

    run_vendor(target, "--force")

    assert (colliding / "SKILL.md").read_text() != "# hand-authored, not vendored\n"
    assert "checking-restraint" in marker_names(target)


def test_vendor_does_not_skip_directory_it_already_owns(tmp_path):
    """A second, ordinary re-run (refresh) must not treat a name this tool
    already vendored on a prior run as a collision — only genuinely
    non-tool-managed pre-existing content should trigger the #175 guard."""
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target)
    first_names = marker_names(target)
    assert "checking-restraint" in first_names

    result = run_vendor_raw(target)
    assert result.returncode == 0, (
        f"a plain refresh of tool-owned content must not fail: {result.stderr!r}"
    )
    assert "skipping" not in result.stderr.lower()


def test_vendor_all_collisions_leaves_marker_names_empty_without_crashing(tmp_path):
    """Regression for a follow-up gap in #175's own fix: when EVERY current-run
    skill name collides with pre-existing, non-tool-managed content and there
    is no prior marker (OLD_NAMES empty too — e.g. a target's first-ever
    vendoring attempt), marker_names ends up genuinely empty. The marker-write
    loop must handle that without unbound-variable trouble under `set -u` (the
    script targets bash 3.2, where `"${arr[@]}"` on a zero-element array
    raises 'unbound variable' unlike bash >=4.4) — mirror the guard already
    used for OLD_NAMES/SKIPPED_COLLISIONS elsewhere in main(). Uses --collapsed
    so only the 4 entrypoint names need to collide, not all 37."""
    target = tmp_path / "target-repo"
    skills_dir = target / ".claude" / "skills"
    for name in (
        "reviewing-a-change", "auditing-a-repository",
        "reviewing-a-decision", "reviewing-an-artifact",
    ):
        d = skills_dir / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"mine: {name}\n")

    result = run_vendor_raw(target, "--collapsed")
    assert result.returncode == 1, (
        f"all-collide run must still exit non-zero (visible), not crash: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "unbound variable" not in result.stderr
    assert "Vendored 0 skill(s)" in result.stdout

    marker = skills_dir / ".atlas-vendored"
    assert marker.exists()
    assert marker_names(target) == set()

    # Every pre-existing directory must still be completely untouched.
    for name in (
        "reviewing-a-change", "auditing-a-repository",
        "reviewing-a-decision", "reviewing-an-artifact",
    ):
        assert (skills_dir / name / "SKILL.md").read_text() == f"mine: {name}\n"


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
# (main()'s --prune branch). #377 moved the `${dest_root:?}` guard out of the
# `rm -rf` call itself and into this separate `target=` assignment (so the
# same resolved target can also be checked by confirm_child_of_dest_root
# before deletion) — kept as a module-level constant, cross-checked against
# the live script by test_prune_guard_expression_matches_script below, so a
# future edit to the real guard's syntax fails loudly here instead of leaving
# this test silently exercising an expression the script no longer has.
_PRUNE_TARGET_GUARD_LINE = '      target="${dest_root:?}/$old"'


def test_prune_guard_expression_matches_script():
    """Guards against this test file drifting from the real prune loop: if
    someone edits the guard in tooling/vendor-skills.sh without updating the
    hand-typed expression below, this fails and says so explicitly."""
    script_text = SCRIPT.read_text()
    assert _PRUNE_TARGET_GUARD_LINE in script_text, (
        "tooling/vendor-skills.sh's prune-loop target guard no longer matches "
        f"the expression this test exercises ({_PRUNE_TARGET_GUARD_LINE!r}); "
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
{_PRUNE_TARGET_GUARD_LINE.strip()}
rm -rf "$target"
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


# --- #377: the marker's trust boundary, --dry-run, and provenance/UX gaps ---

def test_prune_rejects_path_traversal_marker_line(tmp_path):
    """Regression for #377's reproduction: the marker is a generated,
    do-not-hand-edit file a reviewer skims rather than reads closely. A
    planted (or malformed) line like "../../src" must never reach OLD_NAMES
    -- and therefore never reach the --prune `rm -rf` -- even though nothing
    about the marker's own format previously stopped it. Plants a real
    victim directory one level above the target repo, exactly mirroring the
    issue's own reproduction (a marker line of "../../src" deleting
    <target>/../src)."""
    target = tmp_path / "target-repo"
    target.mkdir()

    run_vendor(target)

    marker = target / ".claude" / "skills" / ".atlas-vendored"
    victim = tmp_path / "src"
    victim.mkdir()
    (victim / "important.txt").write_text("must survive\n")

    with marker.open("a") as f:
        f.write("../../src\n")

    result = run_vendor_raw(target, "--prune")
    assert result.returncode == 0, result.stderr
    assert "ignoring malformed marker line" in result.stderr
    assert "../../src" in result.stderr

    # The victim, one level above the target repo, must be completely
    # untouched.
    assert victim.is_dir()
    assert (victim / "important.txt").read_text() == "must survive\n"

    # The malformed line must not survive the marker rewrite either.
    assert "../../src" not in marker.read_text()


def test_refresh_without_prune_also_rejects_a_traversal_marker_line(tmp_path):
    """Same as above but without --prune: the malformed line must be dropped
    (and warned about) on an ordinary refresh too, not only when --prune is
    passed -- OLD_NAMES feeds vendor_one's collision check as well as the
    prune loop, so an unvalidated entry there could also mislead that check."""
    target = tmp_path / "target-repo"
    target.mkdir()
    run_vendor(target)

    marker = target / ".claude" / "skills" / ".atlas-vendored"
    with marker.open("a") as f:
        f.write("/etc/passwd\n")

    result = run_vendor_raw(target)
    assert result.returncode == 0, result.stderr
    assert "ignoring malformed marker line" in result.stderr
    assert "/etc/passwd" in result.stderr
    assert "/etc/passwd" not in marker.read_text()


def test_forged_marker_name_does_not_bypass_the_collision_check_on_refresh(tmp_path):
    """Regression for a Major finding from Copilot and CodeRabbit on this
    PR: is_bare_skill_name only rules out a malformed *shape* (a traversal
    segment, an absolute path). A well-formed but falsely claimed marker
    line -- a real skill name the marker lists as previously vendored, for
    a directory this tool never actually touched -- previously still
    satisfied vendor_one's #175 collision check (`contains "$name"
    "${OLD_NAMES[@]}"` alone) and got silently `rm -rf`'d and overwritten
    without --force. Plants exactly that: a hand-authored
    "checking-restraint" directory (no generated-marker comment in its
    SKILL.md, i.e. never actually vendored) alongside a marker that falsely
    claims it was."""
    target = tmp_path / "target-repo"
    skills_dir = target / ".claude" / "skills"
    colliding = skills_dir / "checking-restraint"
    colliding.mkdir(parents=True)
    (colliding / "SKILL.md").write_text("# hand-authored, never vendored by this tool\n")
    (colliding / "my-private-notes.txt").write_text("do not delete\n")
    marker = skills_dir / ".atlas-vendored"
    marker.write_text(
        "# code-quality-atlas vendored skills — do not hand-edit; regenerate with tooling/vendor-skills.sh\n"
        "# format=1\n"
        "checking-restraint\n"
    )

    result = run_vendor_raw(target)
    assert result.returncode != 0, (
        "a forged marker claim must not let this run silently succeed while "
        f"overwriting non-owned content: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "checking-restraint" in result.stderr
    assert "skipping" in result.stderr.lower() or "skipped" in result.stderr.lower()

    # The critical assertion: the hand-authored content must be completely
    # untouched, exactly like the #175 regression this mirrors.
    assert (colliding / "SKILL.md").read_text() == "# hand-authored, never vendored by this tool\n"
    assert (colliding / "my-private-notes.txt").read_text() == "do not delete\n"


def test_forged_stale_marker_name_does_not_authorize_prune_deletion(tmp_path):
    """Same forgery, on the --prune path instead of the collision path: a
    marker line naming a real skill the current run doesn't vendor (so it's
    "stale") for a directory this tool never actually touched must not let
    --prune delete it. confirm_child_of_dest_root alone doesn't catch this
    -- the forged name's path is a perfectly legitimate child of dest_root;
    it's real ownership evidence (is_tool_vendored_skill_dir) that's needed
    here, the same fix as the collision-check regression above."""
    target = tmp_path / "target-repo"
    skills_dir = target / ".claude" / "skills"
    victim = skills_dir / "not-actually-vendored"
    victim.mkdir(parents=True)
    (victim / "SKILL.md").write_text("# hand-authored, never vendored by this tool\n")
    marker = skills_dir / ".atlas-vendored"
    marker.write_text(
        "# code-quality-atlas vendored skills — do not hand-edit; regenerate with tooling/vendor-skills.sh\n"
        "# format=1\n"
        "not-actually-vendored\n"
    )

    result = run_vendor_raw(target, "--prune")
    assert result.returncode == 0, result.stderr
    assert "not-actually-vendored" in result.stderr
    assert "does not look like something this tool vendored" in result.stderr

    # The critical assertion: survives untouched, and stays recorded in the
    # marker rather than being silently dropped now that it wasn't deleted.
    assert victim.is_dir()
    assert (victim / "SKILL.md").read_text() == "# hand-authored, never vendored by this tool\n"
    assert "not-actually-vendored" in marker_names(target)


def test_dry_run_creates_nothing(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()

    result = run_vendor_raw(target, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert not (target / ".claude").exists()
    assert "(dry-run) would vendor" in result.stdout


def test_dry_run_does_not_modify_an_existing_vendored_target(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()
    run_vendor(target)

    marker = target / ".claude" / "skills" / ".atlas-vendored"
    before_marker = marker.read_text()
    before_mtime = marker.stat().st_mtime_ns
    skill_md = target / ".claude" / "skills" / "checking-restraint" / "SKILL.md"
    before_skill = skill_md.read_text()

    result = run_vendor_raw(target, "--dry-run")
    assert result.returncode == 0, result.stderr

    assert marker.read_text() == before_marker
    assert marker.stat().st_mtime_ns == before_mtime
    assert skill_md.read_text() == before_skill


def test_dry_run_prune_reports_without_deleting(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()
    run_vendor(target)
    run_vendor(target, "--collapsed")  # leaves standalone names orphaned in the marker

    collapsed_dir = target / ".claude" / "skills"
    assert (collapsed_dir / "checking-restraint").is_dir()

    result = run_vendor_raw(target, "--collapsed", "--dry-run", "--prune")
    assert result.returncode == 0, result.stderr
    assert "(dry-run) would prune stale: checking-restraint" in result.stdout
    assert (collapsed_dir / "checking-restraint").is_dir()  # untouched


def test_refresh_without_prune_notes_stale_names(tmp_path):
    """#377 UX gap: a refresh with no --prune previously re-listed withdrawn
    lenses in the marker forever with no indication anything was stale or
    that --prune would remove them."""
    target = tmp_path / "target-repo"
    target.mkdir()
    run_vendor(target)
    run_vendor(target, "--collapsed")

    result = run_vendor_raw(target, "--collapsed")
    assert result.returncode == 0, result.stderr
    assert "checking-restraint" in result.stdout
    assert "re-run with --prune to remove them" in result.stdout


def test_marker_has_format_header(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()
    run_vendor(target)
    marker = target / ".claude" / "skills" / ".atlas-vendored"
    assert "# format=1" in marker.read_text().splitlines()


def test_marker_format_mismatch_warns(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()
    run_vendor(target)
    marker = target / ".claude" / "skills" / ".atlas-vendored"
    marker.write_text(marker.read_text().replace("# format=1", "# format=99"))

    result = run_vendor_raw(target)
    assert result.returncode == 0, result.stderr
    assert "format=99" in result.stderr
    assert "format=1" in result.stderr


def test_warns_when_target_is_not_a_git_worktree(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()
    result = run_vendor_raw(target)
    assert result.returncode == 0, result.stderr
    assert "does not look like a git working tree" in result.stderr


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(path), check=True)


def test_warns_when_target_has_uncommitted_skills_changes(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()
    _init_git_repo(target)

    run_vendor(target)
    subprocess.run(["git", "add", "-A"], cwd=str(target), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(target), check=True)

    # Append rather than replace: keeps the trailing generated-marker
    # comment intact, so this exercises only the git-dirty warning, not the
    # #377-review ownership check (is_tool_vendored_skill_dir) that a
    # wholesale rewrite would also -- correctly -- trip as a collision.
    skill_md = target / ".claude" / "skills" / "checking-restraint" / "SKILL.md"
    skill_md.write_text(skill_md.read_text() + "\n<!-- dirty edit for this test -->\n")

    result = run_vendor_raw(target)
    assert result.returncode == 0, result.stderr
    assert "uncommitted changes" in result.stderr


def test_no_warning_for_a_clean_git_target(tmp_path):
    target = tmp_path / "target-repo"
    target.mkdir()
    _init_git_repo(target)

    run_vendor(target)
    subprocess.run(["git", "add", "-A"], cwd=str(target), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(target), check=True)

    result = run_vendor_raw(target)
    assert result.returncode == 0, result.stderr
    assert "does not look like a git working tree" not in result.stderr
    assert "uncommitted changes" not in result.stderr


def test_is_bare_skill_name_accepts_only_the_manifest_name_shape():
    """Direct unit test of the trust-boundary predicate itself (#377):
    exactly what feeds OLD_NAMES, which in turn feeds the --prune `rm -rf`
    and vendor_one's collision check."""
    bash_script = f"""
set -euo pipefail
{_source_functions_only()}
for name in "checking-restraint" "auditing-config-and-build-hygiene" "a" "a1-2" "a-b-c-9"; do
  is_bare_skill_name "$name" || {{ printf 'REJECTED:%s\\n' "$name"; exit 1; }}
done
for bad in "../../victim" "/etc/passwd" "UPPER" "with space" "trailing/slash" "dot.name" ".."; do
  if is_bare_skill_name "$bad"; then
    printf 'ACCEPTED:%s\\n' "$bad"
    exit 1
  fi
done
printf 'OK\\n'
"""
    result = subprocess.run(
        ["bash", "-c", bash_script],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == "OK"


def test_is_bare_skill_name_rejects_empty_string():
    # A bare empty argument, exercised separately from the loop above since
    # an empty string in a bash for-loop word list is easy to get wrong.
    bash_script = f"""
set -euo pipefail
{_source_functions_only()}
is_bare_skill_name ""
"""
    result = subprocess.run(
        ["bash", "-c", bash_script],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode != 0


def test_confirm_child_of_dest_root_rejects_a_mismatched_parent(tmp_path):
    """Direct unit test of the defense-in-depth check (#377): unreachable
    through main()'s own flow today (is_bare_skill_name already rules out
    anything that could mismatch), which is exactly why it needs its own
    test rather than only integration coverage through main(). Tests the
    function in isolation -- it never calls rm itself (main()'s prune loop
    does, only after this check passes), so there's no rm call to mock or
    assert against here; the real proof is the returncode and message below,
    plus the integration-level test_prune_rejects_path_traversal_marker_line,
    which does exercise a real rm call (atlas review round-1 finding on this
    PR, dropping a vacuous MOCK_RM assertion this test previously carried)."""
    dest_root = tmp_path / "dest_root"
    dest_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    bash_script = f"""
set -euo pipefail
{_source_functions_only()}
confirm_child_of_dest_root "{outside}/victim" "{dest_root}"
"""
    result = subprocess.run(
        ["bash", "-c", bash_script],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode != 0
    assert "refusing to delete" in result.stderr


def test_confirm_child_of_dest_root_accepts_a_true_child(tmp_path):
    dest_root = tmp_path / "dest_root"
    dest_root.mkdir()

    bash_script = f"""
set -euo pipefail
{_source_functions_only()}
confirm_child_of_dest_root "{dest_root}/some-skill" "{dest_root}"
"""
    result = subprocess.run(
        ["bash", "-c", bash_script],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


# --- #398: the --with-lens-coverage-hook errexit-suspension / atomic-write regressions ---

def test_with_lens_coverage_hook_never_corrupts_a_settings_json_it_cannot_merge_into(tmp_path):
    """Regression for a Copilot-review finding on PR #398: a target's
    .claude/settings.json with a valid-but-unexpected .hooks shape (an
    object instead of an array under an event name -- itself a malformed
    Claude Code settings.json, but a plausible hand-authored mistake) made
    merge_settings_hook's jq error. vendor_lens_coverage_hook is called as
    `... || exit 1` in main(), and bash suspends errexit for the whole
    duration of a function invoked as the non-final part of an `||` list --
    so the jq failure did not stop execution, and the unguarded
    `... | jq . > "$settings_file"` truncated the target to an EMPTY file
    before ever reporting the error. Confirmed real data loss, not
    theoretical, before the fix (explicit checks + an atomic temp-file-then-
    mv write) landed."""
    target = tmp_path / "target-repo"
    settings_dir = target / ".claude"
    settings_dir.mkdir(parents=True)
    original = '{\n  "hooks": {\n    "PostToolUse": {"matcher": "Read", "hooks": []}\n  }\n}\n'
    (settings_dir / "settings.json").write_text(original)

    result = run_vendor_raw(target, "--with-lens-coverage-hook")
    assert result.returncode != 0, (
        "a merge that can't proceed must fail visibly, not silently succeed: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "settings.json" in result.stderr

    # The critical assertion: the pre-existing file must be byte-for-byte
    # untouched, not truncated/emptied/partially written.
    assert (settings_dir / "settings.json").read_text() == original

    # No stray temp file left behind from the aborted atomic write.
    leftovers = list(settings_dir.glob("settings.json.*"))
    assert leftovers == [], f"temp file(s) not cleaned up: {leftovers}"


def test_with_lens_coverage_hook_leaves_no_settings_json_when_script_install_fails(tmp_path):
    """Round-3 atlas review on PR #398: the fix above guarded the merge/
    write path but not vendor_lens_coverage_hook's mkdir/cp/chmod block
    above it, which sits in the same function called as `... || exit 1` in
    main() -- bash suspends errexit for a function's ENTIRE body when it's
    invoked as the non-final part of an `||` list, so a failed copy there
    hit the identical silent-false-success failure mode independently:
    confirmed by reproduction (an obstructed hook_dest made mkdir/cp/chmod
    fail loudly on stderr while the run still printed "Vendored
    lens-coverage hook -> ..." and exited 0, having written full
    PostToolUse/PreToolUse wiring into settings.json for two scripts that
    were never actually copied -- an installed-and-working claim for a
    gate that silently was not there at all).

    Fixed by calling vendor_lens_coverage_hook as a bare, untested statement
    (closing the whole errexit-suspension class at once, per the review's
    preferred fix over patching each site) plus an explicit guard around
    the copy block for a clear error message. This reproduces the exact
    obstruction shape from that review: hook_dest already exists as a
    plain file, so mkdir/cp/chmod all fail."""
    target = tmp_path / "target-repo"
    hook_dest = target / ".claude" / "hooks" / "lens-coverage"
    hook_dest.parent.mkdir(parents=True)
    hook_dest.write_text("not a directory\n")

    result = run_vendor_raw(target, "--collapsed", "--with-lens-coverage-hook")
    assert result.returncode != 0, (
        "a failed hook-script install must fail visibly, not report success "
        f"while leaving settings.json wired to scripts that don't exist: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "Vendored lens-coverage hook ->" not in result.stdout, (
        "must not claim success once the copy step failed"
    )

    # The critical assertion: no settings.json was ever written -- the
    # operator must never be told the gate is installed when it is absent.
    assert not (target / ".claude" / "settings.json").exists()
