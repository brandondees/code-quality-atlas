# SPDX-License-Identifier: MIT
"""A source tarball's unpacked size is bounded before any runner sees it
(D39): members and declared bytes are counted from the headers alone."""

import gzip
import io
import subprocess
import tarfile
import time
import tracemalloc
from pathlib import Path

import pytest

from atlas_reviewer import source_archive
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.source_archive import (
    MAX_MEMBERS,
    MAX_METADATA_BYTES,
    MAX_METADATA_TOTAL_BYTES,
    MAX_PATH_BYTES,
    MAX_PATH_COMPONENTS,
    MAX_PATH_DEPTH,
    MAX_TRAILING_ZERO_BYTES,
    MAX_UNPACKED_BYTES,
    Unpacked,
    UnpackLimits,
    measure,
)

from .helpers import source_tarball


def declared_only(size, name="big"):
    """A gzip tar whose one header declares `size` bytes it never carries."""
    info = tarfile.TarInfo(name)
    info.size = size
    return gzip.compress(info.tobuf())


def test_members_and_declared_bytes_are_counted():
    data = source_tarball({"a.py": b"x" * 10, "b/c.py": b"y" * 5})
    assert measure(data) == Unpacked(4, 15)


def test_the_working_defaults_are_256_mib_and_50000_members():
    assert (MAX_UNPACKED_BYTES, MAX_MEMBERS) == (256 * 1024 * 1024, 50_000)


def test_a_header_past_the_byte_cap_is_refused_before_its_data_is_read():
    with pytest.raises(BoundaryError, match="unpacks to over 268435456 bytes"):
        measure(declared_only(MAX_UNPACKED_BYTES + 1))


def test_an_archive_exactly_at_the_byte_cap_is_accepted():
    data = source_tarball({"a": b"\0" * 1024})
    assert measure(data, UnpackLimits(max_bytes=1024)).total_bytes == 1024


def test_a_small_archive_of_zeros_that_unpacks_past_the_cap_is_refused():
    data = source_tarball({"zeros": b"\0" * (4 * 1024 * 1024)})
    assert len(data) < 16 * 1024
    with pytest.raises(BoundaryError, match="at least 4194304"):
        measure(data, UnpackLimits(max_bytes=1024 * 1024))


def test_more_members_than_the_cap_are_refused():
    data = source_tarball({f"f{i}": b"" for i in range(4)})
    with pytest.raises(BoundaryError, match="over 3 members"):
        measure(data, UnpackLimits(max_members=3))


@pytest.mark.parametrize(
    "data", [b"", b"not gzip", gzip.compress(b"gzip but not a tar" * 100)]
)
def test_an_unreadable_archive_is_refused(data):
    with pytest.raises(BoundaryError, match="not a readable gzip tar"):
        measure(data)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_bytes": 0},
        {"max_members": -1},
        {"max_bytes": True},
        {"max_metadata_bytes": 0},
        {"max_metadata_total_bytes": 0},
        {"max_path_bytes": 0},
        {"max_path_depth": 0},
        {"max_path_components": 0},
    ],
)
def test_limits_must_be_positive_integers(limits):
    with pytest.raises(ValueError, match="positive integers"):
        UnpackLimits(**limits)


END = b"\0" * 1024
BIG = 300 * 1024 * 1024
MIB = 1024 * 1024


def header(name, size=0, kind=tarfile.REGTYPE):
    info = tarfile.TarInfo(name)
    info.size, info.type = size, kind
    return info.tobuf(tarfile.GNU_FORMAT)


def padded(data):
    return data + b"\0" * (-len(data) % 512)


def with_checksum(block):
    """`block` with its checksum recomputed, as tar writes it."""
    block = bytearray(block)
    block[148:156] = b" " * 8
    block[148:156] = b"%06o\0 " % sum(block)
    return bytes(block)


def with_field(block, start, stop, value):
    block = bytearray(block)
    block[start:stop] = value.ljust(stop - start, b"\0")
    return with_checksum(block)


SMALL = header("small", 3) + padded(b"abc")


def hiding(middle):
    """A small file, then `middle`, then a header declaring 300 MiB. GNU tar
    reads past a `middle` that tarfile would take as the end of the archive."""
    return gzip.compress(SMALL + middle + header("big", BIG) + END)


def two_members(first_size, second_size):
    """One tar stream split across two gzip members, as `cat a.gz b.gz`
    makes: a small file, then a big one carrying its data."""
    first = header("small", first_size) + padded(b"\0" * first_size)
    second = header("big", second_size) + padded(b"\0" * second_size) + END
    return gzip.compress(first) + gzip.compress(second)


def test_a_file_in_a_later_gzip_member_is_still_counted():
    data = two_members(512, 4 * 1024 * 1024)
    assert len(data) < 16 * 1024
    with pytest.raises(BoundaryError, match="at least 4194816"):
        measure(data, UnpackLimits(max_bytes=1024 * 1024))


def test_members_in_every_gzip_member_are_counted():
    data = two_members(512, 512)
    assert measure(data) == Unpacked(2, 1024)


def test_a_header_in_a_later_member_is_refused_once_its_size_is_seen():
    data = gzip.compress(header("a")) + gzip.compress(
        header("b", MAX_UNPACKED_BYTES + 1)
    )
    with pytest.raises(BoundaryError, match="unpacks to over 268435456 bytes"):
        measure(data)


def _pax(name, fields, size=0):
    info = tarfile.TarInfo(name)
    info.size, info.pax_headers = size, fields
    return info.tobuf(tarfile.PAX_FORMAT)


def pax_entry(payload, kind=tarfile.XHDTYPE):
    """A pax header carrying `payload` exactly as given."""
    return header("././@PaxHeader", len(payload), kind) + padded(payload)


def records(*pairs):
    """Pax records, each `<length> <key>=<value>\\n` with its own length."""
    out = b""
    for key, value in pairs:
        body = b" " + key + b"=" + value + b"\n"
        length = len(body)
        while len(str(length)) + len(body) != length:
            length = len(str(length)) + len(body)
        out += str(length).encode() + body
    return out


def global_header(fields):
    return tarfile.TarInfo.create_pax_global_header(fields)


@pytest.mark.parametrize(
    ("middle", "reason"),
    [
        (with_field(header("gap"), 124, 136, b"zzzzzzzzzzz"), "plain octal"),
        (with_field(header("gap"), 136, 148, b"zzzzzzzzzzz"), "plain octal"),
        (_pax("gap", {"size": "-1"}), "pax key 'size' is not accepted"),
        (with_field(header("gap"), 124, 136, b"\xff" * 12), "plain octal"),
        (header("././@LongLink", 512 * 1024 * 1024, tarfile.GNUTYPE_LONGNAME),
         "metadata entry declares 536870912 bytes"),
        (with_field(header("gap"), 148, 156, b"zzzzzz\0 ")[:148]
         + b"zzzzzz\0 " + with_field(header("gap"), 148, 156, b"")[156:],
         "header checksum failed"),
        (bytes(b ^ 1 if i == 0 else b for i, b in enumerate(header("gap"))),
         "header checksum failed"),
    ],
)  # fmt: skip
def test_a_header_gnu_tar_reads_past_cannot_hide_what_follows(middle, reason):
    data = hiding(middle)
    assert len(data) < 4096
    with pytest.raises(BoundaryError, match=reason):
        measure(data)


@pytest.mark.parametrize(
    ("start", "stop", "value"),
    [
        (124, 136, b"1_000"),
        (124, 136, b"0o1000"),
        (124, 136, b"+1000"),
        (124, 136, b"1000\0junk"),
        (136, 148, b"1_0"),
        (100, 108, b"0o7"),
        (108, 116, b"1_0"),
        (329, 337, b"1_0"),
    ],
)
def test_a_number_gnu_tar_rejects_is_refused(start, stop, value):
    """GNU tar rejects `1_000` as a size and reads the cover's data block as
    the next header, extracting `hidden`; Python's `int` reads 512."""
    cover = with_field(header("cover", 512), start, stop, value)
    data = gzip.compress(cover + header("hidden") + END)
    with pytest.raises(BoundaryError, match="does not parse as plain octal"):
        measure(data)


def test_plain_octal_with_leading_spaces_or_no_terminator_is_accepted():
    spaced = with_field(header("a", 3), 124, 136, b" 3 ")
    full = with_field(header("b", 3), 124, 136, b"%012o" % 3)
    data = gzip.compress(spaced + padded(b"abc") + full + padded(b"abc") + END)
    assert measure(data) == Unpacked(2, 6)


def cover_hiding_a_member(fields):
    """The reviewer's bypass: tarfile skips the cover's data by its header
    size and then reports the global `size`; GNU tar skips by the global
    size and extracts the pax-sized member hidden in the cover's data."""
    hidden = _pax("big", {"size": str(4096)}) + padded(b"\0" * 4096)
    return gzip.compress(
        global_header(fields) + header("cover", len(hidden)) + hidden + END
    )


@pytest.mark.parametrize("size", ["0", "1", "1024", str(MAX_UNPACKED_BYTES)])
def test_a_global_pax_size_cannot_hide_a_member(size):
    with pytest.raises(BoundaryError, match="pax key 'size' is not accepted"):
        measure(cover_hiding_a_member({"comment": "c" * 40, "size": size}))


@pytest.mark.parametrize("key", ["size", "path", "mtime", "uid", "GNU.sparse.map"])
def test_a_global_header_may_hold_only_a_comment(key):
    with pytest.raises(BoundaryError, match=f"pax key '{key}' is not accepted"):
        measure(gzip.compress(global_header({key: "1"}) + SMALL + END))


@pytest.mark.parametrize(
    "key",
    ["size", "uid", "gid", "uname", "gname", "atime", "ctime", "comment",
     "hdrcharset", "GNU.sparse.map", "GNU.sparse.realsize", "SCHILY.xattr.user.a",
     "LIBARCHIVE.creationtime"],
)  # fmt: skip
def test_a_member_pax_key_outside_the_shared_set_is_refused(key):
    entry = pax_entry(records((key.encode(), b"3")))
    with pytest.raises(BoundaryError, match=f"pax key '{key}' is not accepted"):
        measure(gzip.compress(entry + SMALL + END))


def test_a_pax_size_that_agrees_with_the_header_is_still_refused():
    with pytest.raises(BoundaryError, match="pax key 'size' is not accepted"):
        measure(gzip.compress(_pax("a", {"size": "3"}, 3) + padded(b"abc") + END))


@pytest.mark.parametrize(
    "fields",
    [
        {"path": "p" * 300},
        {"linkpath": "t" * 300},
        {"mtime": "1700000000"},
        {"mtime": "1700000000.25"},
        {"path": "caf\u00e9"},
    ],
)
def test_the_pax_keys_both_readers_share_are_accepted(fields):
    data = gzip.compress(pax_entry(records(*_encoded(fields))) + SMALL + END)
    assert measure(data) == Unpacked(1, 3)


def _encoded(fields):
    return [(key.encode(), value.encode()) for key, value in fields.items()]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (records((b"path", b"a"), (b"path", b"b")), "pax key repeats"),
        (records((b"mtime", b"soon")), "pax mtime does not parse"),
        (b"abc", "pax record does not parse"),
        (b"8 path=a\n", "pax record does not parse"),
        (b"99 path=a\n", "pax record does not parse"),
        (b"10 path a\n", "pax record does not parse"),
        (b"9 path=ab", "pax record does not parse"),
        (b"8 =abcd\n", "pax record does not parse"),
        (b"0 path=a\n", "pax record does not parse"),
        (records((b"path", b"a")) + b"\0", "pax record does not parse"),
    ],
)
def test_a_pax_entry_must_be_well_formed_records(payload, reason):
    with pytest.raises(BoundaryError, match=reason):
        measure(gzip.compress(pax_entry(payload) + SMALL + END))


@pytest.mark.parametrize(
    "fields",
    [
        {"GNU.sparse.map": "0,x", "GNU.sparse.realsize": "1"},
        {"GNU.sparse.map": "0,0", "GNU.sparse.realsize": "0"},
    ],
)
def test_sparse_pax_keys_are_refused_malformed_or_not(fields):
    with pytest.raises(BoundaryError, match="pax key 'GNU.sparse"):
        measure(gzip.compress(SMALL + _pax("s", fields) + END))


def test_a_header_summed_as_signed_bytes_is_accepted():
    block = bytearray(header("caf\xe9"))
    block[148:156] = b" " * 8
    signed = sum(b if b < 128 else b - 256 for b in block)
    assert signed != sum(block)
    block[148:156] = b"%06o\0 " % signed
    assert measure(gzip.compress(bytes(block) + END)) == Unpacked(1, 0)


def test_a_header_without_ustar_magic_is_refused():
    v7 = with_field(header("old"), 257, 265, b"")
    with pytest.raises(BoundaryError, match="not a ustar header"):
        measure(gzip.compress(v7 + END))


@pytest.mark.parametrize(
    "kind",
    [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.CONTTYPE,
     tarfile.GNUTYPE_SPARSE, tarfile.SOLARIS_XHDTYPE, b"V", b"Z", b"D", b"M"],
)  # fmt: skip
def test_a_member_type_git_archive_does_not_write_is_refused(kind):
    with pytest.raises(BoundaryError, match="member type .* is not accepted"):
        measure(gzip.compress(SMALL + header("odd", 0, kind) + END))


@pytest.mark.parametrize("kind", [tarfile.DIRTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_a_non_file_member_that_declares_data_is_refused(kind):
    member = header("x", 512, kind) + b"\0" * 512
    with pytest.raises(BoundaryError, match="non-file member declares data"):
        measure(gzip.compress(SMALL + member + END))


def long_name(size, name=b"n", kind=tarfile.GNUTYPE_LONGNAME):
    entry = header("././@LongLink", size, kind)
    return entry + padded(name * (size - 1) + b"\0")


def long_link(size):
    return long_name(size, kind=tarfile.GNUTYPE_LONGLINK)


def test_a_metadata_entry_over_the_cap_is_refused_before_it_is_read():
    with pytest.raises(BoundaryError, match="over the 1024-byte cap; not read"):
        measure(
            gzip.compress(long_name(2048) + header("a") + END),
            UnpackLimits(max_metadata_bytes=1024),
        )
    assert MAX_METADATA_BYTES == 1024 * 1024


def test_a_long_name_under_the_cap_is_read_and_counted_once():
    data = gzip.compress(long_name(300) + header("x", 3) + padded(b"abc") + END)
    assert measure(data) == Unpacked(1, 3)


def many_long_names(count, size=MIB):
    """`count` members, each preceded by a long-link entry of `size` bytes:
    metadata a path cap does not bound."""
    entry = long_link(size) + header("a")
    return gzip.compress(entry * count + END)


def test_metadata_past_the_archive_wide_total_is_refused_before_it_is_read():
    data = many_long_names(MAX_METADATA_TOTAL_BYTES // MIB + 1)
    assert len(data) < 64 * 1024
    with pytest.raises(BoundaryError, match="over 16777216 bytes in all; not read"):
        measure(data)
    assert MAX_METADATA_TOTAL_BYTES == 16 * MIB


def test_the_metadata_total_is_a_limit():
    with pytest.raises(BoundaryError, match="over 4096 bytes in all"):
        measure(many_long_names(5, 1024), UnpackLimits(max_metadata_total_bytes=4096))
    assert measure(
        many_long_names(4, 1024), UnpackLimits(max_metadata_total_bytes=4096)
    )


def test_metadata_under_the_total_is_read_one_entry_at_a_time():
    """Fifteen 1 MiB names are accepted while holding about one in memory:
    nothing is kept per member, as tarfile's member list would."""
    data = many_long_names(15)
    tracemalloc.start()
    try:
        assert measure(data) == Unpacked(15, 0)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 6 * MIB


def test_many_global_keys_are_refused_at_the_first_one_not_allowed():
    keys = {"comment": "c" * 40} | {f"k{i}": "v" for i in range(10_000)}
    data = gzip.compress(global_header(keys) * 100 + SMALL + END)
    with pytest.raises(BoundaryError, match="pax key 'k0' is not accepted"):
        measure(data)


def test_a_global_comment_per_member_keeps_nothing_between_members():
    entry = global_header({"comment": "c" * 40}) + SMALL
    assert measure(gzip.compress(entry * 100 + END)) == Unpacked(100, 300)


def test_a_pax_entry_of_tiny_records_is_refused_at_its_second_record():
    """Tarfile parsed every record of every entry (about 0.13 s each for a
    1 MiB entry of tiny ones); measure stops once an entry holds a record it
    may not, so 1,500 such entries cost one."""
    tiny = records(*[(b"mtime", b"1")] * (MIB // 11))
    assert MIB - 1024 < len(tiny) <= MAX_METADATA_BYTES
    data = gzip.compress(pax_entry(tiny) + SMALL) * 1_500 + gzip.compress(END)
    started = time.process_time()
    with pytest.raises(BoundaryError, match="pax key repeats"):
        measure(data)
    assert time.process_time() - started < 1.0


def test_metadata_of_one_kind_repeated_before_a_member_is_refused():
    with pytest.raises(BoundaryError, match="repeats before its member"):
        measure(gzip.compress(long_name(2) * 2 + header("a") + END))


def test_one_metadata_entry_of_each_kind_before_a_member_is_accepted():
    entries = (
        global_header({"comment": "c"})
        + pax_entry(records((b"mtime", b"1")))
        + long_name(4)
        + header("././@LongLink", 3, tarfile.GNUTYPE_LONGLINK)
        + padded(b"to\0")
    )
    assert measure(gzip.compress(entries + header("a") + END)) == Unpacked(1, 0)


def test_a_metadata_entry_with_no_member_after_it_is_refused():
    with pytest.raises(BoundaryError, match="has no member after it"):
        measure(gzip.compress(SMALL + pax_entry(records((b"path", b"a"))) + END))


@pytest.mark.parametrize(
    ("tail", "reason"),
    [
        (b"", "without an end-of-archive block"),
        (b"\0" * 512 + header("big", BIG) + END, "data follows the end-of-archive"),
        (END + b"x", "data follows the end-of-archive"),
        (
            END + b"\0" * (MAX_TRAILING_ZERO_BYTES + 1),
            "data follows the end-of-archive",
        ),
        (b"\0" * 100, "without an end-of-archive block"),
        (header("short", 4096) + b"\0" * 512, "ends inside an entry's data"),
        (long_name(2048)[:1024], "ends inside an entry's data"),
    ],
)
def test_only_zero_padding_may_follow_the_last_member(tail, reason):
    with pytest.raises(BoundaryError, match=reason):
        measure(gzip.compress(SMALL + tail))


def test_end_padding_to_a_record_is_accepted():
    assert measure(gzip.compress(SMALL + END + b"\0" * 9216)) == Unpacked(1, 3)


def test_an_archive_with_no_members_is_refused():
    with pytest.raises(BoundaryError, match="holds no members"):
        measure(gzip.compress(END))


@pytest.mark.parametrize("error", [MemoryError, ValueError, OSError, RecursionError])
def test_any_reader_failure_is_a_refusal(monkeypatch, error):
    def fail(buf):
        raise error

    monkeypatch.setattr(source_archive, "_checksum_failed", fail)
    with pytest.raises(
        BoundaryError, match=f"not a readable gzip tar: {error.__name__}"
    ):
        measure(source_tarball())


def test_pax_names_as_pythons_tarfile_writes_them_are_accepted():
    data = source_tarball({"caf\u00e9.py": b"x", "d/" + "n" * 200 + ".py": b"yz"})
    assert measure(data) == Unpacked(4, 3)


REPO = Path(__file__).resolve().parents[2]


def git_archive(repo):
    return subprocess.run(
        ["git", "archive", "--format=tar.gz", "--prefix=src/", "HEAD"],
        cwd=repo, capture_output=True, check=True,
    ).stdout  # fmt: skip


def test_git_archive_of_this_repository_is_accepted():
    """`git archive` is what GitHub serves tarballs from: a pax global header
    with the commit id, directories, files, symlinks, record padding."""
    measured = measure(git_archive(REPO))
    assert measured.members > 500
    assert measured.total_bytes > 1024 * 1024


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo, capture_output=True, check=True,
    )  # fmt: skip


def test_git_archive_of_ordinary_repository_features_is_accepted(tmp_path):
    """Long paths and link targets (pax `path` and `linkpath`), unicode
    names, empty and executable files, symlinks, a submodule and an
    `export-subst` file, as `git archive` writes them."""
    deep = tmp_path / ("d" * 120) / ("e" * 120)
    deep.mkdir(parents=True)
    (deep / ("f" * 120 + ".txt")).write_text("deep\n")
    (tmp_path / "caf\u00e9 \u65e5\u672c.md").write_text("unicode\n")
    (tmp_path / "empty").write_bytes(b"")
    (tmp_path / "run.sh").write_text("#!/bin/sh\n")
    (tmp_path / "run.sh").chmod(0o755)
    (tmp_path / "link").symlink_to("run.sh")
    (tmp_path / "far").symlink_to(str(deep.relative_to(tmp_path)))
    (tmp_path / "version.txt").write_text("$Format:%H$\n")
    (tmp_path / ".gitattributes").write_text("version.txt export-subst\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "update-index", "--add", "--cacheinfo", f"160000,{'a' * 40},sub")
    git(tmp_path, "commit", "-q", "-m", "features")
    archive = git_archive(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        expected = len(tar.getmembers())
    assert measure(archive).members == expected


# --- paths: unpacking must not create a directory the walk did not count ---

DIR = tarfile.DIRTYPE


def tree(*entries, limits=None):
    """measure of an archive of `(name, kind)` entries, or bare file names."""
    blocks = b"".join(
        header(*entry) if isinstance(entry, tuple) else header(entry)
        for entry in entries
    )
    return measure(gzip.compress(blocks + END), limits or UnpackLimits())


def dirs(*names):
    return [(name, 0, DIR) for name in names]


def deep_bomb(members, depth):
    """`members` files at their own `depth`-segment paths and no directory
    entries: unpacking creates `depth - 1` directories for each."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz", format=tarfile.PAX_FORMAT) as tf:
        for i in range(members):
            path = "/".join(f"{i:x}-{j}" for j in range(depth))
            tf.addfile(tarfile.TarInfo(path))
    return out.getvalue()


def test_the_path_working_defaults():
    assert (MAX_PATH_BYTES, MAX_PATH_DEPTH, MAX_PATH_COMPONENTS) == (
        4096,
        64,
        1_000_000,
    )


def test_deep_paths_with_no_directory_entries_are_refused():
    """Round 6: a 1,310-byte archive made 100,101 directories and 410 MB, and
    the plain ustar prefix reaches about 6 million for 0.34 MiB."""
    data = deep_bomb(1_000, 64)
    assert len(data) < 256 * 1024
    with pytest.raises(BoundaryError, match="parent directory is not an earlier entry"):
        measure(data)


def test_a_ustar_prefix_path_with_no_directory_entries_is_refused():
    one = "a" * 60 + "/" + "b" * 60 + "/f"
    block = tarfile.TarInfo(one).tobuf(tarfile.USTAR_FORMAT)
    assert block[345:500].strip(b"\0")  # the long part went into the prefix
    with pytest.raises(BoundaryError, match="parent directory is not an earlier entry"):
        measure(gzip.compress(block + END))


def test_a_ustar_prefix_path_whose_directories_are_listed_is_accepted():
    top, mid = "a" * 60, "b" * 60
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz", format=tarfile.USTAR_FORMAT) as tf:
        for path in (top, f"{top}/{mid}"):
            info = tarfile.TarInfo(path)
            info.type = DIR
            tf.addfile(info)
        tf.addfile(tarfile.TarInfo(f"{top}/{mid}/f"))
    assert measure(out.getvalue()) == Unpacked(3, 0)


def test_a_member_whose_directory_comes_after_it_is_refused():
    with pytest.raises(BoundaryError, match="not an earlier entry"):
        tree("a/f", ("a", 0, DIR))


def test_members_under_listed_directories_are_accepted():
    entries = [*dirs("top", "top/a", "top/a/b"), "top/a/b/f", "top/g", "h"]
    assert tree(*entries) == Unpacked(6, 0)


def test_a_trailing_slash_on_a_directory_name_is_accepted():
    assert tree(*dirs("top/", "top/a/"), "top/a/f").members == 3


@pytest.mark.parametrize("kind", [tarfile.REGTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_a_file_or_link_is_not_a_parent_directory(kind):
    with pytest.raises(BoundaryError, match="not an earlier entry"):
        tree(("a", 0, kind), "a/f")


@pytest.mark.parametrize("name", ["a//b", "./a", "a/./b", "a/../b", "../a", "/abs"])
def test_a_path_with_an_empty_dot_or_dotdot_segment_is_refused(name):
    with pytest.raises(BoundaryError, match="empty, '.' or '..' segment"):
        tree(*dirs("a", "a/b"), name)


def test_a_file_named_with_a_trailing_slash_is_refused():
    with pytest.raises(BoundaryError, match="ends in a slash"):
        tree("a/")


def test_a_path_over_the_byte_cap_is_refused_before_its_parents_are_looked_up():
    name = "a" * (MAX_PATH_BYTES + 1)
    with pytest.raises(BoundaryError, match="empty or over 4096 bytes"):
        tree(name)
    assert tree("a" * MAX_PATH_BYTES) == Unpacked(1, 0)


def test_a_pax_path_over_the_byte_cap_is_refused():
    entry = pax_entry(records((b"path", b"a" * (MAX_PATH_BYTES + 1))))
    with pytest.raises(BoundaryError, match="empty or over 4096 bytes"):
        measure(gzip.compress(entry + header("x") + END))


def test_the_depth_cap_is_a_limit():
    limits = UnpackLimits(max_path_depth=3)
    ok = [*dirs("a", "a/b"), "a/b/c"]
    assert tree(*ok, limits=limits).members == 3
    with pytest.raises(BoundaryError, match="over 3 segments deep"):
        tree(*dirs("a", "a/b", "a/b/c"), "a/b/c/d", limits=limits)


def test_the_total_component_cap_is_a_limit():
    limits = UnpackLimits(max_path_components=8)
    assert tree(*dirs("a", "a/b"), "a/b/c", "x", limits=limits).members == 4
    with pytest.raises(BoundaryError, match="over 8 segments in all"):
        tree(*dirs("a", "a/b"), "a/b/c", "a/b/d", "a/b/e", limits=limits)


def test_a_pax_path_names_the_member_not_its_header():
    """GNU tar and Python both take the pax `path` over the header's name."""
    decoy = header("top/x/y/z") + b""
    top = tree(*dirs("top"))  # the walk accepts a listed parent
    assert top.members == 1
    entry = pax_entry(records((b"path", b"top/f")))
    data = gzip.compress(header("top", 0, DIR) + entry + decoy + END)
    assert measure(data) == Unpacked(2, 0)
    bad = pax_entry(records((b"path", b"top/x/y/z")))
    with pytest.raises(BoundaryError, match="not an earlier entry"):
        measure(gzip.compress(header("top", 0, DIR) + bad + header("top/f") + END))


def test_a_gnu_long_name_names_the_member():
    long = "d" * 120
    entries = header(long, 0, DIR) + header(f"{long}/f")
    assert measure(gzip.compress(entries + END)) == Unpacked(2, 0)
    with pytest.raises(BoundaryError, match="not an earlier entry"):
        measure(gzip.compress(header(long) + header(f"{long}/x/f") + END))


def test_a_member_named_by_two_metadata_entries_is_refused():
    entries = (
        header("top", 0, DIR)
        + pax_entry(records((b"path", b"top/a")))
        + long_name(8, b"top/b")
        + header("top/c")
    )
    with pytest.raises(BoundaryError, match="more than one metadata entry"):
        measure(gzip.compress(entries + END))


def test_a_pax_path_that_does_not_name_a_member_is_forgotten_after_it():
    entries = header("top", 0, DIR) + pax_entry(records((b"path", b"top/a")))
    entries += header("top/a") + header("top/b")
    assert measure(gzip.compress(entries + END)) == Unpacked(3, 0)


def test_an_old_gnu_header_with_a_prefix_is_refused():
    block = with_field(header("f"), 345, 500, b"pre")
    with pytest.raises(BoundaryError, match="old GNU header carries a prefix"):
        measure(gzip.compress(block + END))


def test_directory_entries_are_kept_as_digests_not_names():
    names = [f"{'d' * 90}{i:05d}" for i in range(5_000)]
    data = gzip.compress(
        b"".join(header(n, 0, DIR) + header(f"{n}/f") for n in names) + END
    )
    tracemalloc.start()
    try:
        assert measure(data).members == 10_000
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 2 * MIB
