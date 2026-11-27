# SPDX-License-Identifier: MIT
# tests/test_no_private_repo_names_in_runner_docs.py
"""docs/self-hosted-runners.md is copied verbatim into every repo on a
private, personal runner fleet (see that file's own header), and this repo
is the only public one carrying a copy. #394's fix scrubbed personal
machine/account identifiers; a follow-up pass then found the file still
named five other private repos plus a host container ID throughout, and
genericized those too -- but flagged, in the file's own text, that a future
verbatim re-copy from the private canonical could silently reintroduce any
of them, with "no guard against that beyond this note" (round-1 review
finding on that PR, CodeRabbit).

This is that guard. It doesn't (and can't) validate that the file's content
is otherwise correct against the canonical -- only that the specific
strings already confirmed private never reappear here. A new private-repo
name introduced by some future canonical re-copy wouldn't be caught until
someone adds it below; this catches regression of the *known* names, not
every possible future leak.

Originally scoped to `docs/self-hosted-runners.md` alone -- widened
(2026-09-15, #394 follow-up) to scan the whole tracked tree after an audit
found the same strings surviving in `ci.yml`, `test_vendor_skills.py`, and
`session-log.md`, none of which the narrower guard covered.

Recorded anchor snapshots are the one further exemption (2026-11-27, the
parity fixtures under `atlas_reviewer/fixtures/pr640/` and `pr661/`):
frozen, provenance-documented snapshots of specific commits that are
already public in this repo's own git history -- both anchor heads are
fetchable from origin by SHA, so the strings they carry add no exposure
the history does not already have -- and whose content must not be
re-genericized, because a snapshot that differs from the anchor it
records would falsify the eval the fixture exists for (the history
bundle must carry the anchor's own commits and their bytes; quote and
liveness checks grade the anchor's own tree). The trees ship as the
tarball bytes GitHub serves, so no loose anchor file is scanned; what
the scan still flags inside a snapshot is the compressed `history.bundle`,
whose git objects carry the anchor era's own copies of these strings.
The rebuild source is the public anchor (``gh api`` reads plus ``git
bundle`` of public commits), never the private canonical, so the
regression this guard exists to catch -- a fresh verbatim re-copy --
cannot come through this path. The exemption is scoped to those two
snapshot directories; a new fixture needs its own entry here, deliberate
each time.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "self-hosted-runners.md"
THIS_FILE = Path(__file__).resolve()

# Every private-repo name, host identifier, and PR/issue reference confirmed
# scrubbed from this repo (and, separately, from docs/session-log.md's
# 2026-09-08 "#394" entries) as of the fix. Extend this list if a future
# audit finds another one; never remove an entry just because it currently
# passes.
_PRIVATE_STRINGS = (
    "calendar-proxy",
    "second-brain-config",
    "bazzite-config",
    "git_archive_sync",
    "software-factory",
    "cuddly-palm-tree",
    "9cbf0d01cf92",
    "libsql",
    "calproxy",
    "runner-2604",
    "actions-runner-mbp",
    "/home/dees",
)

# The recorded anchor snapshots' tracked paths (see this file's docstring):
# frozen public-history content, exempt from the scan, each added
# deliberately.
_RECORDED_SNAPSHOTS = (
    "atlas_reviewer/fixtures/pr640/",
    "atlas_reviewer/fixtures/pr661/",
)


def _tracked_files():
    # `-z` (NUL-separated) avoids git's default quote-escaping of paths with
    # non-ASCII or otherwise "unusual" bytes -- a quoted path wouldn't
    # resolve to the real file below, silently scanning zero bytes of it.
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [ROOT / p for p in out.decode("utf-8").split("\0") if p]


def test_doc_exists():
    assert DOC.is_file(), (
        f"{DOC} is missing -- has it been renamed or moved? Update this "
        "guard's path (and re-verify the rest of it still applies) either way."
    )


def test_no_known_private_strings_in_tracked_tree():
    private_bytes = [s.encode("utf-8") for s in _PRIVATE_STRINGS]
    offenders = {}
    for path in _tracked_files():
        if path.resolve() == THIS_FILE or not path.is_file():
            # This file's own _PRIVATE_STRINGS list is the one legitimate
            # place these strings appear in the tree.
            continue
        relative_path = path.relative_to(ROOT).as_posix()
        if relative_path.startswith(_RECORDED_SNAPSHOTS):
            # A recorded anchor snapshot is frozen public-history content
            # (see this file's docstring); it is exempt, not genericized.
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue  # unreadable (e.g. broken symlink) -- nothing to scan
        hits = sorted(
            {
                s
                for s, b in zip(_PRIVATE_STRINGS, private_bytes)
                if b in data or s in relative_path
            }
        )
        if hits:
            offenders[relative_path] = hits
    assert not offenders, (
        f"{offenders!r} -- one of the private-repo names/identifiers #394 "
        "scrubbed from this public repo has reappeared, most likely from a "
        "verbatim re-copy of a private canonical source (see "
        "docs/self-hosted-runners.md's own header for the pattern this "
        "guard was originally written against). Re-genericize before "
        "merging; do not silence this guard by removing an entry from the "
        "list above."
    )
