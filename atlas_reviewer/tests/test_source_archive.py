# SPDX-License-Identifier: MIT
"""A source tarball's unpacked size is bounded before any runner sees it
(D39): members and declared bytes are counted from the headers alone."""

import gzip
import tarfile

import pytest

from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.source_archive import (
    MAX_MEMBERS,
    MAX_UNPACKED_BYTES,
    Unpacked,
    UnpackLimits,
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
    "limits", [{"max_bytes": 0}, {"max_members": -1}, {"max_bytes": True}]
)
def test_limits_must_be_positive_integers(limits):
    with pytest.raises(ValueError, match="positive integers"):
        UnpackLimits(**limits)


def two_members(first_size, second_size):
    """One tar stream split across two gzip members, as `cat a.gz b.gz`
    makes: a small file, then a big one carrying its data."""
    small = tarfile.TarInfo("src/small")
    small.size = first_size
    big = tarfile.TarInfo("src/big")
    big.size = second_size
    first = small.tobuf() + b"\0" * first_size
    return gzip.compress(first) + gzip.compress(big.tobuf() + b"\0" * second_size)


def test_a_file_in_a_later_gzip_member_is_still_counted():
    data = two_members(512, 4 * 1024 * 1024)
    assert len(data) < 16 * 1024
    with pytest.raises(BoundaryError, match="at least 4194816"):
        measure(data, UnpackLimits(max_bytes=1024 * 1024))


def test_members_in_every_gzip_member_are_counted():
    data = two_members(512, 512)
    assert measure(data) == Unpacked(2, 1024)


def test_a_header_in_a_later_member_is_refused_before_its_data_is_read():
    first = tarfile.TarInfo("a")
    big = tarfile.TarInfo("b")
    big.size = MAX_UNPACKED_BYTES + 1
    data = gzip.compress(first.tobuf()) + gzip.compress(big.tobuf())
    with pytest.raises(BoundaryError, match="unpacks to over 268435456 bytes"):
        measure(data)
