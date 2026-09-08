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
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "self-hosted-runners.md"

# Every private-repo name, host identifier, and PR/issue reference confirmed
# scrubbed from this file (and, separately, from its own session-log entry --
# see docs/session-log.md's 2026-09-08 "#394" entries) as of the fix. Extend
# this list if a future audit finds another one; never remove an entry just
# because it currently passes.
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
)


def test_doc_exists():
    assert DOC.is_file(), (
        f"{DOC} is missing -- has it been renamed or moved? Update this "
        "guard's path (and re-verify the rest of it still applies) either way."
    )


def test_no_known_private_strings_in_self_hosted_runners_doc():
    text = DOC.read_text(encoding="utf-8")
    hits = [s for s in _PRIVATE_STRINGS if s in text]
    assert not hits, (
        f"docs/self-hosted-runners.md contains {hits!r} -- one of the "
        "private-repo names/identifiers #394 scrubbed from this public "
        "repo's copy has reappeared, most likely from a verbatim re-copy "
        "of the private canonical this file is copied from (see this "
        "file's own header). Re-genericize before merging; do not "
        "silence this guard by removing an entry from the list above."
    )
