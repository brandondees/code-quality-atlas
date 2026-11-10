# SPDX-License-Identifier: MIT
"""The runner holds the unpack caps again by its own tar (D39), so an
archive the controller's check let through still cannot expand past them.
The controller check is bypassed here and the real shell runs each exec."""

import gzip
import subprocess
import tarfile

import pytest

from atlas_reviewer import bridge, runner
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
from atlas_reviewer.source_archive import UnpackLimits

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


def staging(tmp_path, head, body=None):
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
        unpack=LIMITS,
    )


@pytest.mark.parametrize(("head", "reason"), PAST_THE_CAPS)
def test_staging_refuses_a_tree_the_runner_would_expand_past_a_cap(
    tmp_path, unchecked, head, reason
):
    called = []
    report = staging(tmp_path, head, called.append)
    assert report.status is RunnerStatus.FAILED
    assert (
        f"bridge staging failed (exit 3): {REFUSED}{reason}; nothing it unpacked "
        "is kept"
    ) in report.note
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


def one_shot(tmp_path, archive):
    api = MappedSprites()
    api.root = str(tmp_path)
    return run_disposable(
        api,
        MemoryLedger(),
        RunnerJob(archive, (TRIVIAL_TOOL,), unpack=LIMITS),
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
    assert (
        f"source unpack failed (exit 3): {REFUSED}{reason}; nothing it unpacked is kept"
    ) in outcome.report.note
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
        f"{REFUSED}a file grew past 1048576 bytes while it was written; "
        "nothing it unpacked is kept"
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
    assert unpack_refusal(done.stdout.decode()) is None
    assert not (tmp_path / "out").exists()


def test_the_runner_limits_follow_the_controller_caps():
    script = unpack_script("a.tgz", "d")
    assert "head -c 268435457 " in script
    assert "head -n 50001 " in script
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
