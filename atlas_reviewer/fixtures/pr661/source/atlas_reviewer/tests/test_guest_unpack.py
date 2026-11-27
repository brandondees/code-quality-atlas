# SPDX-License-Identifier: MIT
"""The runner holds the unpack caps again by its own tar (D39), so an
archive the controller's check let through still cannot expand past them.
The controller check is bypassed here and the real shell runs each exec."""

import gzip
import io
import os
import shutil
import subprocess
import tarfile

import pytest

from atlas_reviewer import bridge, guest_unpack, runner
from atlas_reviewer.bridge import run_bridge
from atlas_reviewer.bridge_args import Rev
from atlas_reviewer.bridge_staging import SourceTrees, parse_staged, stage_script
from atlas_reviewer.domain import CleanupStatus, RunnerStatus
from atlas_reviewer.fakes import MemoryLedger
from atlas_reviewer.guest_unpack import (
    FILE_TOO_LARGE,
    REFUSED_TAG,
    file_size_blocks,
    unpack_refusal,
    unpack_script,
)
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import (
    SOURCE_ARCHIVE,
    TRIVIAL_TOOL,
    WORKDIR,
    RunnerJob,
    ToolRan,
    run_disposable,
)
from atlas_reviewer.source_archive import DEFAULT_UNPACK, UnpackLimits

from .helpers import HEAD, OLD, FakeClock, LocalSprites, source_tarball

MIB = 1024 * 1024
LIMITS = UnpackLimits(max_bytes=MIB, max_members=10)
REFUSED = "the runner refused to unpack the source archive: "


def header(name, size=0):
    info = tarfile.TarInfo(name)
    info.size = size
    return info.tobuf(tarfile.GNU_FORMAT)


def hidden_by_a_global_size():
    """Round 5's bypass: tarfile skipped the cover's data and counted 0
    bytes; GNU tar skips by the global `size=0` and writes the 4 MiB member
    hidden in it."""
    big = tarfile.TarInfo("src/big")
    big.pax_headers = {"size": str(4 * MIB)}
    hidden = big.tobuf(tarfile.PAX_FORMAT) + b"\0" * (4 * MIB)
    cover = header("src/cover", len(hidden))
    glob = tarfile.TarInfo.create_pax_global_header({"size": "0"})
    return gzip.compress(glob + cover + hidden + b"\0" * 1024)


PAST_THE_CAPS = [
    (source_tarball({"zeros": b"\0" * (4 * MIB)}), "its files hold over 1048576 bytes"),
    (hidden_by_a_global_size(), "its files hold over 1048576 bytes"),
    (source_tarball({f"f{i}": b"" for i in range(20)}), "it lists over 10 members"),
]


@pytest.fixture
def unchecked(monkeypatch):
    """Lets every archive past the controller's `measure`."""
    monkeypatch.setattr(bridge, "check_sizes", lambda trees, **_: None)
    monkeypatch.setattr(runner, "refused_archive", lambda data, limits: None)


def staging(tmp_path, head, body=None, limits=LIMITS):
    return run_bridge(
        LocalSprites(),
        MemoryLedger(),
        SourceTrees(source_tarball(), head, OLD, HEAD),
        body or (lambda bridge: "ran"),
        redactor=Redactor(),
        changed=frozenset(),
        name="cqa-unpack-test",
        deadline_s=120,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        unpack=limits,
    )


@pytest.mark.parametrize(("head", "reason"), PAST_THE_CAPS)
def test_staging_refuses_a_tree_the_runner_would_expand_past_a_cap(
    tmp_path, unchecked, head, reason
):
    called = []
    report = staging(tmp_path, head, called.append)
    assert report.status is RunnerStatus.FAILED
    assert f"bridge staging failed (exit 3): {REFUSED}{reason}" in report.note
    assert report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert called == []
    assert not (tmp_path / "bridge" / "trees" / "head").exists()


def test_staging_within_the_runner_limits_completes(tmp_path, unchecked):
    report = staging(tmp_path, source_tarball({"a.py": b"x" * 100}))
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert (tmp_path / "bridge" / "trees" / "head" / "a.py").read_bytes() == b"x" * 100


class MappedSprites(LocalSprites):
    """Runs the one-shot path's execs here, its fixed runner paths mapped
    under `root`."""

    root = ""

    def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
        mapped = tuple(
            arg.replace(SOURCE_ARCHIVE, f"{self.root}/source.tar.gz").replace(
                WORKDIR, f"{self.root}/work"
            )
            for arg in argv
        )
        return super().exec(name, mapped, stdin, timeout_s, first_byte_s)


def one_shot(tmp_path, archive, limits=LIMITS):
    api = MappedSprites()
    api.root = str(tmp_path)
    return run_disposable(
        api,
        MemoryLedger(),
        RunnerJob(archive, (TRIVIAL_TOOL,), unpack=limits),
        name="cqa-unpack-test",
        deadline_s=600,
        clock=FakeClock(),
    )


@pytest.mark.parametrize(("archive", "reason"), PAST_THE_CAPS)
def test_the_one_shot_unpack_refuses_an_archive_past_a_cap(
    tmp_path, unchecked, archive, reason
):
    outcome = one_shot(tmp_path, archive)
    assert outcome.report.status is RunnerStatus.FAILED
    assert f"source unpack failed (exit 3): {REFUSED}{reason}" in outcome.report.note
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert outcome.results == ()
    assert not (tmp_path / "work").exists()


def test_the_one_shot_unpack_within_the_limits_runs_its_tools(tmp_path, unchecked):
    outcome = one_shot(tmp_path, source_tarball({"a.py": b"x", "b/c.py": b"y"}))
    assert outcome.report.status is RunnerStatus.COMPLETED, outcome.report.note
    (result,) = outcome.results
    assert isinstance(result, ToolRan)
    assert result.output.strip() == "2"
    assert not (tmp_path / "source.tar.gz").exists()


FAKE_TAR = """#!/bin/sh
case "$1" in
  -xOzf) printf abc ;;
  -tzf) echo src/a ;;
  -xzf) exec head -c {size} /dev/zero > "$4/big" ;;
esac
"""


def guard(tmp_path, size):
    """The guard with a `tar` that lists 3 bytes and then writes `size`:
    how a reader that disagrees with the listing would behave."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "tar").write_text(FAKE_TAR.format(size=size))
    (bin_dir / "tar").chmod(0o755)
    script = unpack_script(str(tmp_path / "a.tgz"), str(tmp_path / "out"), "", LIMITS)
    return subprocess.run(
        ["/bin/sh", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
    )


def test_a_file_written_past_the_cap_is_stopped_and_the_tree_removed(tmp_path):
    done = guard(tmp_path, 2 * MIB)
    assert done.returncode == FILE_TOO_LARGE
    assert unpack_refusal(done.stdout, LIMITS) == (
        f"{REFUSED}a file grew past 1048576 bytes while it was written"
    )
    assert not (tmp_path / "out").exists()


def test_a_file_of_exactly_the_cap_is_written_whole(tmp_path):
    """`ulimit -f` counts 512-byte blocks under dash, so the cap is exact."""
    done = guard(tmp_path, MIB)
    assert done.returncode == 0, done.stdout
    assert (tmp_path / "out" / "big").stat().st_size == MIB


def test_an_archive_tar_cannot_read_fails_without_a_tree(tmp_path):
    (tmp_path / "a.tgz").write_bytes(gzip.compress(b"not a tar" * 100))
    script = unpack_script(str(tmp_path / "a.tgz"), str(tmp_path / "out"))
    done = subprocess.run(["/bin/sh", "-c", script], capture_output=True, check=False)
    assert done.returncode == 2
    assert unpack_refusal(done.stdout.decode()) == (
        f"{REFUSED}tar could not read or list the archive"
    )
    assert not (tmp_path / "out").exists()


def test_the_runner_limits_follow_the_controller_caps():
    script = unpack_script("a.tgz", "d")
    assert "head -c 268435457 " in script
    assert "-v max=50000 -v depth=64 " in script
    assert "ulimit -f 524288 " in script


@pytest.mark.parametrize(
    ("size", "blocks"), [(1, 1), (512, 1), (513, 2), (256 * MIB, 524288)]
)
def test_the_file_size_limit_is_in_512_byte_blocks(size, blocks):
    assert file_size_blocks(size) == blocks


def test_staging_keeps_its_60_second_tar_timeout_on_every_pass():
    script = stage_script("/r", "/usr/bin/git", (Rev.BASE, Rev.HEAD))
    for command in ("tar -xOzf", "tar -tzf", "tar -xzf"):
        assert script.count(f"timeout -k 2 60 {command} ") == 2


def test_a_refusal_tag_on_an_exec_that_succeeded_is_not_a_refusal():
    text = (
        f"{REFUSED_TAG}:bytes\n"
        f"atlas-staged:base:{'a' * 40}\natlas-staged:head:{'b' * 40}"
    )
    commits = parse_staged(0, text, (Rev.BASE, Rev.HEAD))
    assert commits == {Rev.BASE: "a" * 40, Rev.HEAD: "b" * 40}


def test_output_without_a_tag_is_not_a_refusal():
    assert unpack_refusal("tar: Unexpected EOF in archive") is None


def deep_bomb(members=1_000, depth=64):
    """`members` regular files, each at its own `depth`-segment path, and no
    directory entries: unpacking creates `depth - 1` directories per file
    from about 170 bytes of archive each (round 6)."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz", format=tarfile.PAX_FORMAT) as tf:
        for i in range(members):
            path = "/".join(f"{i:x}-{j}" for j in range(depth))
            tf.addfile(tarfile.TarInfo(path))
    return out.getvalue()


BOMB = deep_bomb()
IMPLIED = "its paths nest over 64 deep or imply over 50000 directories"


def test_the_bomb_is_small_and_names_more_directories_than_the_cap():
    assert len(BOMB) < 256 * 1024
    assert 1_000 * 63 > DEFAULT_UNPACK.max_members


def test_staging_refuses_the_implied_directory_bomb_with_measure_bypassed(
    tmp_path, unchecked
):
    report = staging(tmp_path, BOMB, limits=DEFAULT_UNPACK)
    assert report.status is RunnerStatus.FAILED
    assert f"bridge staging failed (exit 3): {REFUSED}{IMPLIED}" in report.note
    assert not (tmp_path / "bridge" / "trees" / "head").exists()


def test_the_one_shot_unpack_refuses_the_implied_directory_bomb(tmp_path, unchecked):
    outcome = one_shot(tmp_path, BOMB, DEFAULT_UNPACK)
    assert outcome.report.status is RunnerStatus.FAILED
    assert f"source unpack failed (exit 3): {REFUSED}{IMPLIED}" in outcome.report.note
    assert not (tmp_path / "work").exists()


def tar_of(tmp_path, *names):
    """A gzip tar of empty files and directories (names ending in `/`)."""
    path = tmp_path / "a.tgz"
    with tarfile.open(path, "w:gz") as tf:
        for name in names:
            info = tarfile.TarInfo(name)
            if name.endswith("/"):
                info.type, info.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(info)
    return str(path)


def run_script(tmp_path, limits, *names, env=None):
    archive = tar_of(tmp_path, *names)
    script = unpack_script(archive, str(tmp_path / "out"), "", limits)
    return subprocess.run(
        ["/bin/sh", "-c", script], capture_output=True, text=True, env=env, check=False
    )


@pytest.mark.parametrize(
    ("limits", "names"),
    [
        (UnpackLimits(max_members=10), [f"{'d/' * 11}f"]),
        (
            UnpackLimits(max_members=10),
            [f"{c}/{c}/{c}/f" for c in "abcd"],
        ),
        (UnpackLimits(max_path_depth=3), ["a/b/c/d"]),
        (UnpackLimits(max_path_depth=3), ["a/", "a/b/", "a/b/c/", "a/b/c/d/"]),
    ],
)
def test_the_runner_pass_refuses_implied_directories_and_deep_paths(
    tmp_path, limits, names
):
    done = run_script(tmp_path, limits, *names)
    assert done.returncode == 3
    assert unpack_refusal(done.stdout, limits).startswith(f"{REFUSED}its paths nest")
    assert not (tmp_path / "out").exists()


def test_a_listing_that_names_every_directory_passes_the_runner_pass(tmp_path):
    names = ["top/", "top/a/", "top/a/b/", "top/a/b/f", "top/a/g", "top/h"]
    done = run_script(tmp_path, UnpackLimits(max_members=6, max_path_depth=4), *names)
    assert done.returncode == 0, done.stdout
    assert (tmp_path / "out" / "top" / "a" / "b" / "f").is_file()


def test_the_runner_pass_counts_a_member_cap_over_the_listing(tmp_path):
    limits = UnpackLimits(max_members=2)
    done = run_script(tmp_path, limits, "a", "b", "c")
    assert done.returncode == 3
    assert unpack_refusal(done.stdout, limits).endswith("it lists over 2 members")


def test_a_listing_pass_that_does_not_print_ok_extracts_nothing(tmp_path):
    """tar lists the archive and exits 0, and awk exits 0 having printed
    nothing. The `members`/`dirs` case does not match, so only the check
    that the listing pass answered `ok` stops the unpack."""
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("tar", "gzip", "head", "wc", "cat", "rm", "mkdir", "timeout"):
        os.symlink(shutil.which(name), tools / name)
    awk = tools / "awk"
    awk.write_text("#!/bin/sh\ncat >/dev/null\n")
    awk.chmod(0o755)
    done = run_script(tmp_path, LIMITS, "a", env={"PATH": f"{tools}:/usr/bin:/bin"})
    assert done.returncode == 2
    assert unpack_refusal(done.stdout) == (
        f"{REFUSED}tar could not read or list the archive"
    )
    assert not (tmp_path / "out").exists()


def test_a_runner_without_awk_cannot_check_the_listing_and_extracts_nothing(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("tar", "gzip", "head", "wc", "cat", "rm", "mkdir", "timeout", "sh"):
        os.symlink(shutil.which(name), tools / name)
    done = run_script(tmp_path, LIMITS, "a", env={"PATH": str(tools)})
    assert done.returncode == 2
    assert unpack_refusal(done.stdout) == (
        f"{REFUSED}tar could not read or list the archive"
    )
    assert not (tmp_path / "out").exists()


SLEEPING_TAR = """#!/bin/sh
case "$1" in
  -xOzf) {xo} ;;
  -tzf) {t} ;;
  -xzf) {x} ;;
esac
"""


def hung_tar(tmp_path, xo="printf abc", t="echo a", x="mkdir -p $4; touch $4/a"):
    """`tar` answering each pass with the given shell, under a 1-second
    `timeout`, as the real one runs under 60."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "tar").write_text(SLEEPING_TAR.format(xo=xo, t=t, x=x))
    (bin_dir / "tar").chmod(0o755)
    script = unpack_script(str(tmp_path / "a.tgz"), str(tmp_path / "out"), "", LIMITS)
    return subprocess.run(
        ["/bin/sh", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
    )


@pytest.fixture
def one_second_timeout(monkeypatch):
    monkeypatch.setattr(guest_unpack, "_TIMEOUT", "timeout -k 1 1 ")


@pytest.mark.parametrize(
    ("hang", "code"),
    [({"xo": "sleep 30"}, 4), ({"t": "sleep 30"}, 4), ({"x": "sleep 30"}, 124)],
)
def test_a_tar_that_hangs_is_stopped_and_named_on_every_pass(
    tmp_path, one_second_timeout, hang, code
):
    done = hung_tar(tmp_path, **hang)
    assert done.returncode == code
    assert unpack_refusal(done.stdout) == (
        f"{REFUSED}tar did not finish within 60 seconds"
    )
    assert not (tmp_path / "out").exists()


def test_a_tar_that_ignores_term_is_killed_after_the_grace(
    tmp_path, one_second_timeout
):
    done = hung_tar(tmp_path, t="trap '' TERM; sleep 30")
    assert done.returncode == 4
    assert f"{REFUSED}tar did not finish" in unpack_refusal(done.stdout)


def test_the_one_shot_unpack_runs_every_tar_pass_under_the_staging_timeout(
    tmp_path, unchecked
):
    api = MappedSprites()
    api.root = str(tmp_path)
    run_disposable(
        api,
        MemoryLedger(),
        RunnerJob(source_tarball(), (TRIVIAL_TOOL,), unpack=LIMITS),
        name="cqa-unpack-test",
        deadline_s=600,
        clock=FakeClock(),
    )
    (script,) = [a[-1] for a in api.argv_seen if "tar -xzf" in a[-1]]
    for command in ("tar -xOzf", "tar -tzf", "tar -xzf"):
        assert script.count(f"timeout -k 2 60 {command} ") == 1


def test_the_one_shot_and_staging_share_one_timeout():
    assert (guest_unpack.EXTRACT_TIMEOUT_S, guest_unpack.KILL_AFTER_S) == (60, 2)
