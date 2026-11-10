# SPDX-License-Identifier: MIT
"""The read-only git tool bridge (D39), run for real: `LocalSprites` is a
`FakeSprites` that executes each exec's argv on this machine, so the
staging script, the git hardening and the output caps are exercised
against a fixture repository built here. No Sprite or GitHub call is made."""

import base64
import gzip
import io
import json
import subprocess
import tarfile

import pytest

from atlas_reviewer.bridge import (
    DEFAULT_LIMITS,
    SessionLimits,
    Status,
    ToolLimits,
    _grep_records,
    call_script,
    render,
    run_bridge,
)
from atlas_reviewer.bridge_args import Rev, validate
from atlas_reviewer.bridge_staging import (
    ATTRIBUTES,
    GIT_ENV,
    GIT_OPTIONS,
    SourceTrees,
    fetch_sources,
)
from atlas_reviewer.domain import CleanupStatus, RunnerStatus
from atlas_reviewer.fakes import ExecRule, FakeSprites, MemoryLedger
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.ports import BoundaryError, StreamTimeoutError
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import MAX_TARBALL_BYTES
from atlas_reviewer.source_archive import MAX_UNPACKED_BYTES
from atlas_reviewer.telemetry import Telemetry

from .helpers import (
    FIXTURE,
    HEAD,
    OLD,
    FakeClock,
    LocalSprites,
    fake_token,
    source_tarball,
)

OLD_TOKEN = fake_token("ghp_")
NEW_TOKEN = fake_token("ghs_")
BASE_FILES = {
    "calc.py": b"def total(xs):\n    return sum(xs)\n",
    "config/settings.py": f'API_TOKEN = "{OLD_TOKEN}"\n'.encode(),
    "docs/notes.md": b"rounding notes\n",
    "src/we:ird.txt": b"colon in the name\n",
}
HEAD_FILES = {
    **BASE_FILES,
    "calc.py": b"def total(xs):\n    return sum(round(x, 2) for x in xs)\n",
    "deploy/keys.py": f"key = {NEW_TOKEN}\n".encode(),
    ".gitattributes": b"* text=auto diff=evil filter=evil ident\n",
    "ident.txt": b"$Id: deadbeef $\n",
    "crlf.txt": b"a\r\nb\r\n",
    "bin.dat": b"total\0\x01\x02",
    "-n": b"total in a dash file\n",
    **{f"many/f{i:02d}.txt": b"x\n" for i in range(30)},
}


def tarball(files, top="example-org-example-app-abc1234"):
    return source_tarball(files, top)


def trees(default=None):
    return SourceTrees(
        tarball(BASE_FILES),
        tarball(HEAD_FILES),
        OLD,
        HEAD,
        None if default is None else tarball(default),
        None if default is None else "d" * 40,
    )


def bridge_run(tmp_path, body, sprites=None, source=None, **kw):
    sprites = sprites or LocalSprites()
    clock = FakeClock()
    telemetry = Telemetry(clock)
    report = run_bridge(
        sprites,
        MemoryLedger(),
        source or trees(),
        body,
        redactor=Redactor(),
        changed=frozenset({"calc.py", "deploy/keys.py"}),
        name="cqa-bridge-test",
        deadline_s=120,
        clock=clock,
        telemetry=telemetry,
        root=str(tmp_path / "bridge"),
        **kw,
    )
    return report, sprites, telemetry


def calls(tmp_path, *requests, **kw):
    """Each `(tool, args)` in order; returns the results and the bridge."""
    results, bridges = [], []

    def body(bridge):
        bridges.append(bridge)
        results.extend(bridge.call(tool, args) for tool, args in requests)
        return f"{len(results)} call(s)"

    report, sprites, telemetry = bridge_run(tmp_path, body, **kw)
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    return results, bridges[0], sprites, telemetry


def one(tmp_path, tool, args=None, **kw):
    (result,), *_ = calls(tmp_path, (tool, args or {}), **kw)
    return result


def test_staging_commits_base_and_head_and_the_diff_is_the_prs_change(tmp_path):
    result = one(tmp_path, "diff_stat")
    assert result.status is Status.OK
    stat = result.content.text
    assert "calc.py" in stat
    assert "deploy/keys.py" in stat
    assert "docs/notes.md" not in stat
    assert "config/settings.py" not in stat


def test_staged_commits_are_full_ids_and_head_descends_from_base(tmp_path):
    _, bridge, _, telemetry = calls(tmp_path)
    commits = bridge.staged.commits
    assert set(commits) == {Rev.BASE, Rev.HEAD}
    assert all(len(c) == 40 for c in commits.values())
    parent = subprocess.run(
        [
            "git",
            f"--git-dir={tmp_path}/bridge/repo.git",
            "rev-parse",
            f"{commits[Rev.HEAD]}^",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
    )
    assert parent.stdout.strip() == commits[Rev.BASE]
    (staged,) = [e for e in telemetry.events if e.step == "staged"]
    assert staged.fields["git"] in ("/usr/bin/git", "/bin/git")
    assert staged.fields["git_version"].startswith("git version")


def test_diff_file_pages_by_byte_offset_until_the_whole_diff_is_read(tmp_path):
    limits = {**DEFAULT_LIMITS, "diff_file": ToolLimits(40, 10)}
    whole = one(tmp_path / "a", "diff_file", {"path": "calc.py"}).content.text
    pages, offset = [], 0
    while offset is not None:
        page = one(
            tmp_path / "b",
            "diff_file",
            {"path": "calc.py", "offset": offset},
            limits=limits,
        )
        pages.append(page.content.text)
        assert page.truncated is (page.next_offset is not None)
        assert ("next page at offset" in render(page)) is page.truncated
        offset = page.next_offset
    assert "".join(pages) == whole
    assert len(pages) > 1
    assert "+    return sum(round(x, 2) for x in xs)" in whole


@pytest.mark.parametrize("cap", [37, 38, 39, 40])
def test_diff_pages_split_only_between_whole_utf8_characters(tmp_path, cap):
    text = "naïve café — 日本語 🙂 " * 4
    head = {**HEAD_FILES, "docs/notes.md": f"{text}\n".encode()}
    source = SourceTrees(tarball(BASE_FILES), tarball(head), OLD, HEAD)
    limits = {**DEFAULT_LIMITS, "diff_file": ToolLimits(cap, 10)}
    pages, offset = [], 0
    while offset is not None:
        page = one(
            tmp_path / str(offset), "diff_file",
            {"path": "docs/notes.md", "offset": offset}, source=source, limits=limits,
        )  # fmt: skip
        assert "\ufffd" not in page.content.text
        assert page.shown_bytes <= cap
        pages.append(page.content.text)
        offset = page.next_offset
    assert f"+{text}" in "".join(pages)


def test_a_page_asked_for_mid_character_starts_at_the_next_whole_one(tmp_path):
    head = {**HEAD_FILES, "docs/notes.md": "日本\n".encode()}
    source = SourceTrees(tarball(BASE_FILES), tarball(head), OLD, HEAD)
    whole = one(tmp_path / "w", "diff_file", {"path": "docs/notes.md"}, source=source)
    at = whole.content.text.encode().index("日".encode()) + 1
    page = one(
        tmp_path / "p", "diff_file", {"path": "docs/notes.md", "offset": at},
        source=source,
    )  # fmt: skip
    assert page.content.text.startswith("本\n")


def test_next_offset_counts_the_bytes_skipped_to_a_character_boundary(tmp_path):
    limits = {**DEFAULT_LIMITS, "diff_file": ToolLimits(5, 10)}
    head = {**HEAD_FILES, "docs/notes.md": "日本語\n".encode()}
    source = SourceTrees(tarball(BASE_FILES), tarball(head), OLD, HEAD)
    whole = one(tmp_path / "w", "diff_file", {"path": "docs/notes.md"}, source=source)
    raw = whole.content.text.encode()
    at = raw.index("日".encode()) + 1
    args = {"path": "docs/notes.md", "offset": at}
    page = one(tmp_path / "p", "diff_file", args, source=source, limits=limits)
    assert (page.content.text, page.next_offset) == ("本", at + 2 + 3)
    assert raw[page.next_offset :].startswith("語".encode())


COMMIT = "c" * 40


@pytest.mark.parametrize(
    "text",
    [
        f"{'d' * 40}:a.py\x001\x00hit\n",
        "a.py\x001\x00hit\n",
        f"{COMMIT}a.py\x001\x00hit\n",
    ],
)
def test_a_grep_record_not_prefixed_with_the_staged_commit_is_not_taken(text):
    assert _grep_records(text, COMMIT) == ([], False)


def test_a_grep_record_prefixed_with_the_staged_commit_is_taken():
    text = f"{COMMIT}:a.py\x001\x00hit\n"
    assert _grep_records(text, COMMIT) == ([("a.py", "1", "hit")], True)


def test_a_byte_cap_inside_a_character_keeps_only_whole_ones(tmp_path):
    limits = {**DEFAULT_LIMITS, "read_file": ToolLimits(4, 10, 400)}
    head = {**HEAD_FILES, "u.txt": "aé日\n".encode()}
    source = SourceTrees(tarball(BASE_FILES), tarball(head), OLD, HEAD)
    result = one(tmp_path, "read_file", {"path": "u.txt"}, source=source, limits=limits)
    assert (result.content.text, result.shown_bytes, result.truncated) == (
        "aé",
        3,
        True,
    )


RENAMED_BASE = {"old/name.py": b"".join(b"line %d\n" % i for i in range(20))}
RENAMED_HEAD = {
    "new/name.py": RENAMED_BASE["old/name.py"] + f"key = {NEW_TOKEN}\n".encode()
}


@pytest.mark.parametrize("path", ["new/name.py", "old/name.py"])
def test_a_renamed_file_diffs_as_a_rename_from_either_side(tmp_path, path):
    source = SourceTrees(tarball(RENAMED_BASE), tarball(RENAMED_HEAD), OLD, HEAD)
    result = one(tmp_path, "diff_file", {"path": path}, source=source)
    assert result.status is Status.OK
    assert "rename from old/name.py\nrename to new/name.py\n" in result.content.text
    assert "new file mode" not in result.content.text
    assert "deleted file mode" not in result.content.text
    assert {(s.path, s.line) for s in result.secrets} == {("new/name.py", 21)}


def test_renames_are_listed_once_per_bridge(tmp_path):
    source = SourceTrees(tarball(RENAMED_BASE), tarball(RENAMED_HEAD), OLD, HEAD)
    _, _, sprites, _ = calls(
        tmp_path,
        ("diff_file", {"path": "new/name.py"}),
        ("diff_file", {"path": "old/name.py"}),
        source=source,
    )
    listings = [
        s for s in sprites.calls if s[0] == "exec" and "--diff-filter=R" in s[2]
    ]
    assert len(listings) == 1


def test_a_rename_listing_that_fails_makes_diff_file_unavailable(tmp_path):
    sprites = _answer("__ATLAS_BRIDGE__ 128 0 0 0 0\n\n")
    (diff, stat), *_ = calls(
        tmp_path, ("diff_file", {"path": "a"}), ("diff_stat", {}), sprites=sprites
    )
    assert diff.status is Status.UNAVAILABLE
    assert "renames could not be listed in full (exit 128)" in diff.error.text
    assert stat.status is Status.FAILED


def test_a_cut_rename_listing_makes_diff_file_unavailable(tmp_path):
    sprites = _answer("__ATLAS_BRIDGE__ 0 0 9 0 0\n\n")
    (diff,), *_ = calls(tmp_path, ("diff_file", {"path": "a"}), sprites=sprites)
    assert diff.status is Status.UNAVAILABLE
    assert "renames could not be listed in full" in diff.error.text


def test_list_files_reads_a_revision_under_a_prefix(tmp_path):
    head, base, docs = calls(
        tmp_path,
        ("list_files", {}),
        ("list_files", {"rev": "BASE"}),
        ("list_files", {"prefix": "docs"}),
    )[0]
    assert "deploy/keys.py" in head.content.text.splitlines()
    assert "deploy/keys.py" not in base.content.text.splitlines()
    assert docs.content.text.splitlines() == ["docs/notes.md"]
    assert '"src/we:ird.txt"' not in head.content.text
    assert "src/we:ird.txt" in head.content.text


def test_every_name_list_files_shows_plainly_reads_back_and_the_rest_are_marked(
    tmp_path,
):
    files = {
        "odd/é.txt": b"accented\n",
        "odd/a\nb.txt": b"newline\n",
        "odd/-dash": b"dash\n",
        "odd/tab\there": b"tab\n",
        "odd/we:ird.txt": b"colon\n",
    }
    source = SourceTrees(tarball(BASE_FILES), tarball(files), OLD, HEAD)
    listing = one(tmp_path, "list_files", {"prefix": "odd"}, source=source)
    lines = listing.content.text.split("\n")
    assert sorted(lines) == sorted(
        [
            "odd/é.txt",
            "odd/we:ird.txt",
            (
                '"odd/a\\nb.txt" (not readable by read_file: path contains a control '
                "character)"
            ),
            (
                '"odd/tab\\there" (not readable by read_file: path contains a control '
                "character)"
            ),
            "odd/-dash",
        ]
    )
    plain = [line for line in lines if "(not readable" not in line]
    reads, *_ = calls(
        tmp_path / "r",
        *(("read_file", {"path": p}) for p in plain),
        source=source,
    )
    assert [r.content.text for r in reads] == [files[p].decode() for p in plain]


def test_a_top_level_dash_name_is_listed_as_not_readable(tmp_path):
    listing = one(tmp_path, "list_files")
    assert (
        "\"-n\" (not readable by read_file: path may not start with '-' or '/')"
        in listing.content.text.split("\n")
    )


def test_a_name_that_is_not_utf8_is_marked_not_readable(tmp_path):
    """The raw byte goes in the ustar name, as `git archive` writes it; pax
    would add `hdrcharset`, which the source archive check refuses."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.USTAR_FORMAT,
                      encoding="utf-8", errors="surrogateescape") as tf:  # fmt: skip
        for directory in ("top", "top/odd"):
            info = tarfile.TarInfo(directory)
            info.type, info.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(info)
        info = tarfile.TarInfo("top/odd/\udcff.txt")
        info.size = 2
        tf.addfile(info, io.BytesIO(b"x\n"))
    source = SourceTrees(tarball(BASE_FILES), buf.getvalue(), OLD, HEAD)
    listing = one(tmp_path, "list_files", {"prefix": "odd"}, source=source)
    assert listing.content.text == (
        '"odd/\\ufffd.txt" (not readable by read_file: path is not valid UTF-8)'
    )


def test_list_files_past_its_line_cap_is_cut_and_says_so(tmp_path):
    limits = {**DEFAULT_LIMITS, "list_files": ToolLimits(32 * 1024, 10, 10)}
    result = one(tmp_path, "list_files", {"prefix": "many"}, limits=limits)
    assert len(result.content.text.splitlines()) == 10
    assert (result.truncated, result.total_lines) == (True, 30)
    assert "output cut: " in render(result)


def test_read_file_returns_the_requested_lines_of_a_revision(tmp_path):
    head, base, second = calls(
        tmp_path,
        ("read_file", {"path": "calc.py"}),
        ("read_file", {"path": "calc.py", "rev": "BASE"}),
        ("read_file", {"path": "calc.py", "start": 2, "end": 2}),
    )[0]
    assert head.content.text == HEAD_FILES["calc.py"].decode()
    assert base.content.text == BASE_FILES["calc.py"].decode()
    assert second.content.text == "    return sum(round(x, 2) for x in xs)\n"


def test_in_tree_attributes_change_nothing_that_is_staged_or_read(tmp_path):
    ident, crlf, diff = calls(
        tmp_path,
        ("read_file", {"path": "ident.txt"}),
        ("read_file", {"path": "crlf.txt"}),
        ("diff_file", {"path": "calc.py"}),
    )[0]
    assert ident.content.text == "$Id: deadbeef $\n"
    assert crlf.content.text == "a\r\nb\r\n"
    assert (diff.status, diff.error) == (Status.OK, None)


def test_a_missing_path_is_a_failed_call_with_gits_error(tmp_path):
    result = one(tmp_path, "read_file", {"path": "nope.py"})
    assert result.status is Status.FAILED
    assert "does not exist" in result.error.text
    assert result.content.text == ""


def test_grep_is_fixed_string_by_default_literal_in_prefix_and_skips_binaries(tmp_path):
    fixed, regex, globbed, dash, none = calls(
        tmp_path,
        ("grep", {"pattern": "sum(r"}),
        ("grep", {"pattern": "sum\\(r", "regex": True}),
        ("grep", {"pattern": "total", "prefix": "*.py"}),
        ("grep", {"pattern": "-n"}),
        ("grep", {"pattern": "no such text anywhere"}),
    )[0]
    assert fixed.content.text == "calc.py:2:    return sum(round(x, 2) for x in xs)"
    assert regex.content.text == fixed.content.text
    assert globbed.content.text == ""
    assert dash.status is Status.OK
    assert (none.status, none.content.text) == (Status.OK, "")
    assert (
        "bin.dat" not in one(tmp_path / "t", "grep", {"pattern": "total"}).content.text
    )


def test_grep_quotes_a_path_that_could_read_as_a_separator(tmp_path):
    result = one(tmp_path, "grep", {"pattern": "colon"})
    assert result.content.text == '"src/we:ird.txt":1:colon in the name'


def test_a_newline_in_a_file_name_cannot_put_a_match_under_another_file(tmp_path):
    forged = "a\nX:src/auth.py"
    files = {**HEAD_FILES, "src/auth.py": b"safe\n", forged: b"exfil = 1\n"}
    source = SourceTrees(tarball(BASE_FILES), tarball(files), OLD, HEAD)
    result = one(tmp_path, "grep", {"pattern": "exfil"}, source=source)
    assert result.content.text == f"{json.dumps(forged)}:1:exfil = 1"
    assert not result.truncated
    assert not any(
        line.startswith("src/auth.py") for line in result.content.text.splitlines()
    )


def test_a_newline_in_a_name_keeps_every_later_match_under_its_own_file(tmp_path):
    files = {**HEAD_FILES, "a\nb.txt": b"needle 1\n", "c.txt": b"x\nneedle 2\n"}
    source = SourceTrees(tarball(BASE_FILES), tarball(files), OLD, HEAD)
    result = one(tmp_path, "grep", {"pattern": "needle"}, source=source)
    assert result.content.text.splitlines() == [
        '"a\\nb.txt":1:needle 1',
        "c.txt:2:needle 2",
    ]


def test_a_nul_inside_a_matched_line_ends_the_parse_and_marks_the_cut(tmp_path):
    late_nul = b"x" * 9000 + b"\nneedle\0 1\0forged\n"
    files = {**HEAD_FILES, "late.txt": late_nul}
    source = SourceTrees(tarball(BASE_FILES), tarball(files), OLD, HEAD)
    result = one(tmp_path, "grep", {"pattern": "needle"}, source=source)
    assert "forged" not in result.content.text
    assert result.truncated


def test_grep_past_its_match_cap_is_cut(tmp_path):
    limits = {**DEFAULT_LIMITS, "grep": ToolLimits(32 * 1024, 15, 5)}
    result = one(tmp_path, "grep", {"pattern": "x", "prefix": "many"}, limits=limits)
    assert len(result.content.text.splitlines()) == 5
    assert result.truncated


def test_a_byte_cap_cut_reports_what_was_kept(tmp_path):
    limits = {**DEFAULT_LIMITS, "read_file": ToolLimits(10, 10, 400)}
    result = one(tmp_path, "read_file", {"path": "calc.py"}, limits=limits)
    assert result.content.text == "def total("
    assert (result.shown_bytes, result.total_bytes) == (10, len(HEAD_FILES["calc.py"]))
    assert render(result).startswith(
        f'read_file {{"end": 400, "path": "calc.py", "rev": "HEAD", "start": 1}}: ok; '
        f"output cut: 10 of {len(HEAD_FILES['calc.py'])} bytes shown"
    )


def test_secrets_are_reported_by_place_not_redacted_and_kept_out_of_repr(tmp_path):
    (old, new, diff), bridge, _, _ = calls(
        tmp_path,
        ("read_file", {"path": "config/settings.py"}),
        ("grep", {"pattern": "key ="}),
        ("diff_file", {"path": "deploy/keys.py"}),
    )
    assert OLD_TOKEN in old.content.text
    assert {(s.path, s.line, s.preexisting) for s in old.secrets} == {
        ("config/settings.py", 1, True)
    }
    assert {(s.path, s.line, s.preexisting) for s in new.secrets} == {
        ("deploy/keys.py", 1, False)
    }
    assert ("deploy/keys.py", 1, False) in {
        (s.path, s.line, s.preexisting) for s in diff.secrets
    }
    assert OLD_TOKEN not in repr(old)
    assert NEW_TOKEN not in repr(bridge)
    assert {OLD_TOKEN, NEW_TOKEN} <= set(bridge.flagged())
    assert "possible committed secret(s) reported to the controller" in render(old)


def test_a_secret_at_base_is_preexisting_even_in_a_changed_file(tmp_path):
    source = trees()
    base = tarball({**BASE_FILES, "calc.py": f"t = {NEW_TOKEN}\n".encode()})
    source = SourceTrees(base, source.head, OLD, HEAD)
    diff = one(tmp_path, "diff_file", {"path": "calc.py"}, source=source)
    (secret,) = diff.secrets
    assert (secret.path, secret.line, secret.preexisting) == ("calc.py", 1, True)


def test_the_default_branch_is_its_own_root_commit_and_readable(tmp_path):
    source = trees(default={"calc.py": b"default branch\n"})
    (read, stat), bridge, _, _ = calls(
        tmp_path,
        ("read_file", {"path": "calc.py", "rev": "DEFAULT"}),
        ("diff_stat", {}),
        source=source,
    )
    assert read.content.text == "default branch\n"
    assert "deploy/keys.py" in stat.content.text
    assert set(bridge.staged.commits) == {Rev.BASE, Rev.HEAD, Rev.DEFAULT}


@pytest.mark.parametrize(
    "tool,args,reason",
    [
        ("shell", {}, "unknown-tool: the tools are diff_stat, diff_file,"),
        (None, {}, "unknown-tool: "),
        ("diff_stat", ["x"], "bad-arguments: arguments must be an object"),
        ("diff_stat", {"rev": "HEAD"}, 'unknown-argument: `"rev"`'),
        ("read_file", {}, "missing-argument: path"),
        (
            "read_file",
            {"path": "../etc/passwd"},
            "invalid-argument: path has an empty, '.' or '..' segment",
        ),
        ("read_file", {"path": "a/./b"}, "segment"),
        ("read_file", {"path": "a//b"}, "segment"),
        ("read_file", {"path": "a/"}, "segment"),
        ("read_file", {"path": "/etc/passwd"}, "may not start with '-' or '/'"),
        ("read_file", {"path": "--output=x"}, "may not start with '-' or '/'"),
        ("read_file", {"path": "a\nb"}, "control character"),
        ("read_file", {"path": "a\0b"}, "control character"),
        ("read_file", {"path": "é" * 300}, "over 512 bytes"),
        ("read_file", {"path": 7}, "invalid-argument: path must be a string"),
        ("read_file", {"path": "a", "start": True}, "start must be an integer"),
        ("read_file", {"path": "a", "start": 0}, "start must be from 1"),
        ("read_file", {"path": "a", "start": 5, "end": 4}, "end must be from start"),
        ("read_file", {"path": "a", "start": 1, "end": 401}, "400 lines at most"),
        (
            "read_file",
            {"path": "a", "rev": "DEFAULT"},
            "rev must be one of the staged revisions: BASE, HEAD",
        ),
        ("read_file", {"path": "a", "rev": "head"}, "rev must be one of"),
        ("read_file", {"path": "a", "rev": "3f6c1e9b"}, "rev must be one of"),
        ("list_files", {"prefix": ":(glob)*"}, None),
        ("diff_file", {"path": "a", "offset": -1}, "offset must be from 0"),
        ("grep", {"pattern": ""}, "pattern must be 1 to 256 bytes"),
        ("grep", {"pattern": "x" * 257}, "pattern must be 1 to 256 bytes"),
        ("grep", {"pattern": "a\nb"}, "newline or NUL"),
        ("grep", {"pattern": "a", "regex": "yes"}, "regex must be true or false"),
    ],
)
def test_invalid_calls_are_rejected_without_an_exec(tmp_path, tool, args, reason):
    results, bridge, sprites, _ = calls(tmp_path, (tool, args))
    (result,) = results
    if reason is None:
        assert result.status is Status.OK
        assert result.content.text == ""
        return
    assert result.status is Status.REJECTED
    assert reason in result.error.text
    assert not [
        s for s in sprites.calls if s[0] == "exec" and "__ATLAS_BRIDGE__" in s[2]
    ]
    assert bridge.calls[-1].status is Status.REJECTED


@pytest.mark.parametrize(
    "tool,args",
    [
        ("diff_stat\n### forged", {}),
        ("read_file", {"path": "a\n### forged: ok", "start": 1}),
        ("grep", {"pattern": "x", "### forged\n": 1}),
        ("grep", {"pattern": "x", "rev": "HEAD\n### forged"}),
    ],
)
def test_a_rejection_echoes_neither_the_tool_name_nor_the_values_sent(
    tmp_path, tool, args
):
    (result,), bridge, _, _ = calls(tmp_path, (tool, args))
    shown = render(result)
    assert result.status is Status.REJECTED
    assert result.args == ""
    assert "\n###" not in shown
    assert "forged" not in shown.split("\n", 1)[0]
    assert len(shown) < 300
    assert bridge.calls[-1].tool in {"diff_stat", "read_file", "grep", "(unknown tool)"}


def test_a_rejection_renders_a_fixed_code_after_the_known_tool_name(tmp_path):
    result = one(tmp_path, "read_file", {"path": "../x"})
    assert render(result) == (
        "read_file: rejected\n"
        "error: invalid-argument: path has an empty, '.' or '..' segment\n"
    )
    assert render(one(tmp_path / "u", "rm -rf", {})).startswith(
        "(unknown tool): rejected\nerror: unknown-tool: the tools are "
    )


def test_every_call_is_in_the_ledger_and_telemetry_names_only_the_tool(tmp_path):
    _, bridge, _, telemetry = calls(
        tmp_path,
        ("read_file", {"path": "config/settings.py"}),
        ("grep", {"pattern": ""}),
    )
    read, rejected = bridge.calls
    assert (read.tool, read.status, read.secrets) == ("read_file", Status.OK, 2)
    assert read.shown_bytes == read.total_bytes > 0
    assert rejected.status is Status.REJECTED
    steps = [e.step for e in telemetry.events if e.phase == "exec"]
    assert "bridge read_file" in steps
    assert not any("settings" in str(e.fields) for e in telemetry.events)


def test_every_git_call_is_hardened_and_quoted(tmp_path):
    _, bridge, _, _ = calls(tmp_path)
    script = call_script(
        bridge.staged,
        validate("grep", {"pattern": "'; rm -rf / #"}, bridge.staged.revs),
        DEFAULT_LIMITS["grep"],
    )
    for option in GIT_OPTIONS[1::2]:
        assert f"-c {option}" in script
    for variable in GIT_ENV:
        assert variable in script
    assert "-e ''\"'\"'; rm -rf / #'" in script
    assert "timeout -k 2 15" in script
    assert "ulimit -f" in script
    attributes = (tmp_path / "bridge" / "repo.git" / "info" / "attributes").read_text()
    assert attributes == REVIEWED_ATTRIBUTES + "\n"


# Written out, not imported: a test that compares against the constants it
# checks cannot notice one of them dropped.
REVIEWED_ATTRIBUTES = "* -text !eol -filter -ident !diff !working-tree-encoding"
REVIEWED_ENV = (
    "GIT_CONFIG_NOSYSTEM=1",
    "GIT_CONFIG_GLOBAL=/dev/null",
    "GIT_NO_REPLACE_OBJECTS=1",
    "GIT_LITERAL_PATHSPECS=1",
    "GIT_ATTR_NOSYSTEM=1",
    "GIT_TERMINAL_PROMPT=0",
    "GIT_OPTIONAL_LOCKS=0",
    "GIT_PAGER=cat",
)
REVIEWED_OPTIONS = (
    "core.hooksPath=/dev/null",
    "core.fsmonitor=",
    "core.pager=cat",
    "protocol.allow=never",
    "color.ui=never",
    "core.quotePath=true",
    "core.autocrlf=false",
    "core.safecrlf=false",
)


def test_the_hardening_is_exactly_the_reviewed_set():
    assert ATTRIBUTES == REVIEWED_ATTRIBUTES
    assert GIT_ENV == REVIEWED_ENV
    assert GIT_OPTIONS == tuple(x for o in REVIEWED_OPTIONS for x in ("-c", o))


def test_staging_and_every_tool_run_with_the_reviewed_hardening(tmp_path):
    _, _, sprites, _ = calls(tmp_path, ("diff_stat", {}))
    scripts = [s[2] for s in sprites.calls if s[0] == "exec" and "repo.git" in s[2]]
    assert len(scripts) >= 2
    for script in scripts:
        assert f"export {' '.join(REVIEWED_ENV)}" in script
        assert all(f"-c {o}" in script for o in REVIEWED_OPTIONS)


def test_a_shell_metacharacter_pattern_is_searched_for_not_run(tmp_path):
    result = one(tmp_path, "grep", {"pattern": "$(touch pwned)"})
    assert (result.status, result.content.text) == (Status.OK, "")
    assert not (tmp_path / "bridge" / "pwned").exists()


# ----------------------------------------------------- rule-driven fakes


def _answer(stdout, code=0):
    return FakeSprites(
        rules=(
            ExecRule("--version", "atlas-git:/usr/bin/git\ngit version 2.43.0", 0),
            ExecRule(
                "atlas-staged",
                f"atlas-staged:base:{'a' * 40}\natlas-staged:head:{'b' * 40}",
                0,
            ),
            ExecRule("__ATLAS_BRIDGE__", stdout, code),
        )
    )


@pytest.mark.parametrize(
    "status_code,status",
    [
        (124, Status.TIMED_OUT),
        (137, Status.TIMED_OUT),
        (153, Status.TOO_LARGE),
        (128, Status.FAILED),
        (0, Status.OK),
    ],
)
def test_the_in_runner_exit_status_maps_to_a_result_status(
    tmp_path, status_code, status
):
    sprites = _answer(f"__ATLAS_BRIDGE__ {status_code} 0 0 0 0\n\n")
    (result,), *_ = calls(tmp_path, ("diff_stat", {}), sprites=sprites)
    assert result.status is status


def test_a_stalled_exec_is_timed_out_and_a_lost_one_unavailable(tmp_path):
    errors = [StreamTimeoutError("no output for 25s"), BoundaryError("exec 502")]

    class Stalls(FakeSprites):
        def _answer(self, script, stdin):
            if "__ATLAS_BRIDGE__" in script:
                raise errors.pop(0)
            return super()._answer(script, stdin)

    sprites = Stalls(rules=_answer("").rules)
    (timed, lost), *_ = calls(
        tmp_path, ("diff_stat", {}), ("diff_stat", {}), sprites=sprites
    )
    assert (timed.status, lost.status) == (Status.TIMED_OUT, Status.UNAVAILABLE)
    assert "exec 502" in lost.error.text


@pytest.mark.parametrize(
    "stdout",
    [
        "no header at all",
        "__ATLAS_BRIDGE__ 0 0 1 1 1\n!!notbase64!!\n",
        "__ATLAS_BRIDGE__ 0 1 1\n\n",
        "__ATLAS_BRIDGE__ 0 0 1 1 1\nabc\n",
    ],
)
def test_an_unparseable_reply_is_unavailable_not_empty(tmp_path, stdout):
    (result,), *_ = calls(tmp_path, ("diff_stat", {}), sprites=_answer(stdout))
    assert result.status is Status.UNAVAILABLE
    assert "no bridge reply" in result.error.text


@pytest.mark.parametrize(
    "stdout,error",
    [
        (
            "__ATLAS_BRIDGE__ 0 0 5 1 5\n\n",
            "the runner's encoded output held 0 of 5 bytes",
        ),
        (
            f"__ATLAS_BRIDGE__ 0 0 9 1 9\n{base64.b64encode(b'abc').decode()}\n",
            "the runner's encoded output held 3 of 9 bytes",
        ),
        ("__ATLAS_BRIDGE__ 0 2 0 0 0\n\n", "could not cut the output (exit 2)"),
    ],
)
def test_output_lost_after_git_succeeded_is_an_error_not_an_empty_ok(
    tmp_path, stdout, error
):
    (result,), *_ = calls(tmp_path, ("diff_stat", {}), sprites=_answer(stdout))
    assert result.status is Status.FAILED
    assert error in result.error.text
    assert result.content.text == ""


def test_stderr_is_redacted_runtime_text(tmp_path):
    err = base64.b64encode(f"fatal: token {OLD_TOKEN}".encode()).decode()
    sprites = _answer(f"__ATLAS_BRIDGE__ 128 0 0 0 0\n\n{err}")
    (result,), *_ = calls(tmp_path, ("diff_stat", {}), sprites=sprites)
    assert OLD_TOKEN not in result.error.text
    assert "fatal: token" in result.error.text


@pytest.mark.parametrize(
    "reply,code",
    [
        ("atlas-git:none", 1),
        ("atlas-git:/tmp/work/git\ngit version 9", 0),
        ("atlas-git:/usr/bin/git\natlas-git:/tmp/git", 0),
    ],
)
def test_staging_refuses_a_missing_or_untrusted_git(tmp_path, reply, code):
    sprites = FakeSprites(rules=(ExecRule("--version", reply, code),))
    report, sprites, _ = bridge_run(tmp_path, lambda b: "unreached", sprites=sprites)
    assert report.status is RunnerStatus.FAILED
    assert "no trusted git in the runner" in report.note
    assert report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert not [c for c in sprites.calls if c[0] == "exec" and "cat >" in c[2]]


def test_staging_that_does_not_report_every_commit_fails_the_run(tmp_path):
    sprites = FakeSprites(
        rules=(
            ExecRule("--version", "atlas-git:/usr/bin/git\ngit version 2", 0),
            ExecRule("atlas-staged", f"atlas-staged:base:{'a' * 40}", 0),
        )
    )
    report, _, _ = bridge_run(tmp_path, lambda b: "unreached", sprites=sprites)
    assert report.status is RunnerStatus.FAILED
    assert "bridge staging failed" in report.note


def test_an_oversized_tree_is_refused_before_a_runner_exists(tmp_path):
    big = SourceTrees(b"x" * (MAX_TARBALL_BYTES + 1), b"", OLD, HEAD)
    report, sprites, telemetry = bridge_run(tmp_path, lambda b: "unreached", source=big)
    assert (report.status, report.cleanup) == (
        RunnerStatus.FAILED,
        CleanupStatus.NOT_CREATED,
    )
    assert "BASE is" in report.note
    assert sprites.calls == []
    assert any(e.step == "size check" for e in telemetry.events)


def test_a_tree_that_would_unpack_past_the_cap_is_refused_before_a_runner(tmp_path):
    bomb = tarfile.TarInfo("top/big")
    bomb.size = MAX_UNPACKED_BYTES + 1
    source = SourceTrees(tarball(BASE_FILES), gzip.compress(bomb.tobuf()), OLD, HEAD)
    report, sprites, _ = bridge_run(tmp_path, lambda b: "unreached", source=source)
    assert (report.status, report.cleanup) == (
        RunnerStatus.FAILED,
        CleanupStatus.NOT_CREATED,
    )
    assert "HEAD is refused: source archive unpacks to over" in report.note
    assert sprites.calls == []


def test_limits_must_be_positive_integers():
    for bad in ({"max_bytes": 0, "timeout_s": 1}, {"max_bytes": 1, "timeout_s": True}):
        with pytest.raises(ValueError, match="positive integers"):
            ToolLimits(**bad)


def test_sources_are_the_merge_base_and_head_tarballs():
    gh = FixtureGitHub(FIXTURE)
    source = fetch_sources(gh, "example-org/example-app", "main", HEAD)
    merge_base = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d"
    assert (source.base_sha, source.head_sha) == (merge_base, HEAD)
    assert [c for c in gh.calls if c[0] in ("get_compare", "get_tarball")] == [
        ("get_compare", "example-org/example-app", f"main...{HEAD}"),
        ("get_tarball", "example-org/example-app", merge_base),
        ("get_tarball", "example-org/example-app", HEAD),
    ]


@pytest.mark.parametrize(
    "reply", [{}, {"merge_base_commit": None}, {"merge_base_commit": {"sha": "abc"}}]
)
def test_a_compare_reply_without_a_full_merge_base_is_refused(reply):
    class Odd(FixtureGitHub):
        def get_compare(self, repo, base, head):
            return reply

    with pytest.raises(BoundaryError, match="merge_base_commit"):
        fetch_sources(Odd(FIXTURE), "o/r", "main", HEAD)


def test_fetched_sources_over_the_cap_are_refused():
    with pytest.raises(BoundaryError, match="upload cap"):
        fetch_sources(FixtureGitHub(FIXTURE), "o/r", "main", HEAD, max_bytes=10)


def test_a_session_refuses_calls_past_its_call_limit_without_running_them(tmp_path):
    results, bridge, sprites, _ = calls(
        tmp_path,
        ("diff_stat", {}),
        ("shell", {}),
        ("diff_stat", {}),
        session_limits=SessionLimits(max_calls=2),
    )
    assert [r.status for r in results] == [
        Status.OK,
        Status.REJECTED,
        Status.OVER_SESSION_LIMIT,
    ]
    assert render(results[2]) == (
        "diff_stat: session limit reached\n"
        "error: session-limit: all 2 calls of this session made\n"
    )
    bridge_execs = [
        s for s in sprites.calls if s[0] == "exec" and "__ATLAS_BRIDGE__" in s[2]
    ]
    assert len(bridge_execs) == 1
    assert len(bridge.calls) == 3


def test_a_session_shows_no_more_output_than_it_has_left(tmp_path):
    size = len(HEAD_FILES["calc.py"])
    results, bridge, _, _ = calls(
        tmp_path,
        ("read_file", {"path": "calc.py"}),
        ("read_file", {"path": "calc.py"}),
        ("read_file", {"path": "calc.py"}),
        session_limits=SessionLimits(max_output_bytes=size + 10),
    )
    first, second, third = results
    assert (first.shown_bytes, first.truncated) == (size, False)
    assert (second.shown_bytes, second.truncated) == (10, True)
    assert third.status is Status.OVER_SESSION_LIMIT
    assert f"all {size + 10} output bytes of this session shown" in third.error.text
    assert sum(c.shown_bytes for c in bridge.calls) == size + 10


@pytest.mark.parametrize("limits", [{"max_calls": 0}, {"max_output_bytes": True}])
def test_session_limits_must_be_positive_integers(limits):
    with pytest.raises(ValueError, match="positive integers"):
        SessionLimits(**limits)


def test_the_session_defaults_are_64_calls_and_1_mib_of_output():
    assert SessionLimits() == SessionLimits(64, 1024 * 1024)
