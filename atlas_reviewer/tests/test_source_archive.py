# SPDX-License-Identifier: MIT
"""A source tarball's unpacked size is bounded before any runner sees it
(D39): members and declared bytes are counted from the headers alone."""

import gzip
import subprocess
import tarfile
from pathlib import Path

import pytest

from atlas_reviewer import source_archive
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.source_archive import (
    MAX_MEMBERS,
    MAX_METADATA_BYTES,
    MAX_TRAILING_ZERO_BYTES,
    MAX_UNPACKED_BYTES,
    Unpacked,
    UnpackLimits,
    _stream,
    measure,
)

from .helpers import source_tarball


def declared_only(size, name="src/big"):
    """A gzip tar whose one header declares `size` bytes it never carries."""
    info = tarfile.TarInfo(name)
    info.size = size
    return gzip.compress(info.tobuf())


def test_members_and_declared_bytes_are_counted():
    data = source_tarball({"a.py": b"x" * 10, "b/c.py": b"y" * 5})
    assert measure(data) == Unpacked(2, 15)


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
    ],
)
def test_limits_must_be_positive_integers(limits):
    with pytest.raises(ValueError, match="positive integers"):
        UnpackLimits(**limits)


END = b"\0" * 1024
BIG = 300 * 1024 * 1024


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


SMALL = header("src/small", 3) + padded(b"abc")


def hiding(middle):
    """A small file, then `middle`, then a header declaring 300 MiB. GNU tar
    reads past a `middle` that tarfile would take as the end of the archive."""
    return gzip.compress(SMALL + middle + header("src/big", BIG) + END)


def two_members(first_size, second_size):
    """One tar stream split across two gzip members, as `cat a.gz b.gz`
    makes: a small file, then a big one carrying its data."""
    first = header("src/small", first_size) + padded(b"\0" * first_size)
    second = header("src/big", second_size) + padded(b"\0" * second_size) + END
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


def _pax(name, fields):
    info = tarfile.TarInfo(name)
    info.pax_headers = fields
    return info.tobuf(tarfile.PAX_FORMAT)


@pytest.mark.parametrize(
    ("middle", "reason"),
    [
        (with_field(header("src/gap"), 124, 136, b"zzzzzzzzzzz"), "field does not parse"),
        (with_field(header("src/gap"), 136, 148, b"zzzzzzzzzzz"), "field does not parse"),
        (_pax("src/gap", {"size": "-1"}), "metadata entry does not parse"),
        (with_field(header("src/gap"), 124, 136, b"\xff" * 12), "negative size"),
        (header("././@LongLink", 512 * 1024 * 1024, tarfile.GNUTYPE_LONGNAME),
         "metadata entry declares 536870912 bytes"),
        (with_field(header("src/gap"), 148, 156, b"zzzzzz\0 ")[:148]
         + b"zzzzzz\0 " + with_field(header("src/gap"), 148, 156, b"")[156:],
         "header checksum failed"),
        (bytes(b ^ 1 if i == 0 else b for i, b in enumerate(header("src/gap"))),
         "header checksum failed"),
    ],
)  # fmt: skip
def test_a_header_gnu_tar_reads_past_cannot_hide_what_follows(middle, reason):
    data = hiding(middle)
    assert len(data) < 4096
    with pytest.raises(BoundaryError, match=reason):
        measure(data)


@pytest.mark.parametrize("size", ["abc", "-1", "1e3", ""])
@pytest.mark.parametrize("scope", ["member", "global"])
def test_a_pax_size_tarfile_would_read_as_zero_is_refused(size, scope):
    """tarfile reads an unparsable pax size as 0; a global header's size also
    skips tarfile's offset check. GNU tar would read either another way."""
    fields = {"size": size}
    pax = (
        _pax("src/gap", fields)
        if scope == "member"
        else tarfile.TarInfo.create_pax_global_header(fields) + header("src/gap")
    )
    with pytest.raises(BoundaryError, match="does not parse"):
        measure(gzip.compress(SMALL + pax + END))


def test_a_malformed_pax_sparse_map_is_refused():
    sparse = _pax("src/s", {"GNU.sparse.map": "0,x", "GNU.sparse.realsize": "1"})
    with pytest.raises(BoundaryError, match="not a readable gzip tar: ValueError"):
        measure(gzip.compress(SMALL + sparse + END))


def test_a_well_formed_sparse_file_is_refused():
    sparse = _pax("src/s", {"GNU.sparse.map": "0,0", "GNU.sparse.realsize": "0"})
    with pytest.raises(BoundaryError, match="sparse files are not accepted"):
        measure(gzip.compress(SMALL + sparse + END))


def test_a_header_summed_as_signed_bytes_is_accepted():
    block = bytearray(header("src/caf\xe9"))
    block[148:156] = b" " * 8
    signed = sum(b if b < 128 else b - 256 for b in block)
    assert signed != sum(block)
    block[148:156] = b"%06o\0 " % signed
    assert measure(gzip.compress(bytes(block) + END)) == Unpacked(1, 0)


@pytest.mark.parametrize(
    "kind",
    [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.CONTTYPE,
     tarfile.GNUTYPE_SPARSE, tarfile.SOLARIS_XHDTYPE, b"V", b"Z"],
)  # fmt: skip
def test_a_member_type_git_archive_does_not_write_is_refused(kind):
    with pytest.raises(BoundaryError, match="member type .* is not accepted"):
        measure(gzip.compress(SMALL + header("src/odd", 0, kind) + END))


@pytest.mark.parametrize("kind", [tarfile.DIRTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_a_non_file_member_that_declares_data_is_refused(kind):
    member = header("src/x", 512, kind) + b"\0" * 512
    with pytest.raises(BoundaryError, match="non-file member declares data"):
        measure(gzip.compress(SMALL + member + END))


def test_a_metadata_entry_over_the_cap_is_refused_before_it_is_read():
    name = header("././@LongLink", 2048, tarfile.GNUTYPE_LONGNAME) + padded(b"a" * 2048)
    with pytest.raises(BoundaryError, match="over the 1024-byte cap; not read"):
        measure(
            gzip.compress(name + header("src/a") + END),
            UnpackLimits(max_metadata_bytes=1024),
        )
    assert MAX_METADATA_BYTES == 1024 * 1024


def test_a_long_name_under_the_cap_is_read_and_counted_once():
    long = "src/" + "n" * 300
    name = header("././@LongLink", len(long) + 1, tarfile.GNUTYPE_LONGNAME)
    data = gzip.compress(
        name + padded(long.encode() + b"\0") + header("x", 3) + padded(b"abc") + END
    )
    assert measure(data) == Unpacked(1, 3)


def test_metadata_nested_deeper_than_git_archive_writes_is_refused():
    link = header("././@LongLink", 2, tarfile.GNUTYPE_LONGNAME) + padded(b"a\0")
    with pytest.raises(BoundaryError, match="nested too deep"):
        measure(gzip.compress(link * 4 + header("src/a") + END))


def test_a_metadata_entry_with_no_member_after_it_is_refused():
    pax = _pax("src/gap", {"path": "src/real"})[:-512]
    with pytest.raises(BoundaryError, match="has no member after it"):
        measure(gzip.compress(SMALL + pax + END))


@pytest.mark.parametrize(
    ("tail", "reason"),
    [
        (b"", "without an end-of-archive block"),
        (b"\0" * 512 + header("src/big", BIG) + END, "data follows the end-of-archive"),
        (END + b"x", "data follows the end-of-archive"),
        (
            END + b"\0" * (MAX_TRAILING_ZERO_BYTES + 1),
            "data follows the end-of-archive",
        ),
        (b"\0" * 100, "without an end-of-archive block"),
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


def test_a_header_read_without_a_stream_is_an_error():
    closed = tarfile.TarFile.__new__(tarfile.TarFile)
    closed.fileobj = None
    with pytest.raises(tarfile.StreamError, match="closed"):
        _stream(closed)


def test_pax_names_as_pythons_tarfile_writes_them_are_accepted():
    data = source_tarball({"caf\u00e9.py": b"x", "d/" + "n" * 200 + ".py": b"yz"})
    assert measure(data) == Unpacked(2, 3)


REPO = Path(__file__).resolve().parents[2]


def test_git_archive_of_this_repository_is_accepted():
    """`git archive` is what GitHub serves tarballs from: a pax global header
    with the commit id, directories, files, symlinks, record padding."""
    archive = subprocess.run(
        ["git", "archive", "--format=tar.gz", "--prefix=src/", "HEAD"],
        cwd=REPO, capture_output=True, check=True,
    ).stdout  # fmt: skip
    measured = measure(archive)
    assert measured.members > 500
    assert measured.total_bytes > 1024 * 1024
