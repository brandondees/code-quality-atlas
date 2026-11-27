# SPDX-License-Identifier: MIT
# tests/test_review_thread_resolution_scoping.py
"""#362: `mcp__github__resolve_review_thread` was granted to the unattended
reviewer with no ownership check -- `commands/atlas-review-pr.md`,
`REVIEW.md` / `templates/REVIEW.md`, and
`docs/runbooks/pr-review-automation.md` all instructed it to "resolve any
thread[s] the new push addressed" on its own judgment, with nothing scoping
that to threads the reviewer itself opened. Run from an unattended, scheduled
subagent (Model B), this let the agent close a *human* reviewer's still-open
thread -- and on a repo that gates merge on resolved conversations, clear
that gate -- purely because the agent judged the push had addressed it.

Fixed by scoping resolution to threads whose first comment's author is the
reviewer's own login (`mcp__github__get_me`, already called for the own-PR
fallback), reusing that identity rather than trusting a marker-free judgment
call. Nothing mechanically stops a future edit from quietly dropping that
scoping language back to the old, unscoped instruction -- these four files
have no shared source render step (unlike REVIEW.md/templates/REVIEW.md,
which test_review_template_sync.py keeps byte-identical) -- so this test
guards the prose shape directly: the vulnerable unscoped phrasing must not
reappear, and the ownership-check language must stay present in all four.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = {
    "atlas-review-pr command": ROOT / "commands" / "atlas-review-pr.md",
    "REVIEW.md": ROOT / "REVIEW.md",
    "templates/REVIEW.md": ROOT / "templates" / "REVIEW.md",
    "pr-review-automation runbook": ROOT
    / "docs"
    / "runbooks"
    / "pr-review-automation.md",
}

# The exact unscoped phrasings issue #362 quoted from each file, with
# whitespace normalized to a single space so a harmless Markdown re-wrap
# can't defeat the check. If any of these reappear, the ownership check
# has regressed.
VULNERABLE_PHRASES = (
    "resolve any threads the new push addressed",
    "resolve threads that later pushes addressed",
    (
        "if a prior thread was already addressed by a later push, resolve it "
        "with `resolve_review_thread` rather than re-raising it"
    ),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def test_no_file_still_carries_the_unscoped_resolve_instruction():
    for label, path in FILES.items():
        text = _normalize(_read(path))
        for phrase in VULNERABLE_PHRASES:
            assert phrase not in text, (
                f"{label} ({path}) still contains the unscoped resolve "
                f"instruction {phrase!r} -- this is the #362 regression: "
                'resolving a thread on "the push addressed it" alone, with '
                "no check that the reviewer itself opened the thread, lets "
                "the unattended reviewer close a human reviewer's open "
                "thread and clear a merge-blocking-conversations gate."
            )


def test_every_file_scopes_resolution_to_the_reviewer_s_own_threads():
    # "your own" alone is too weak a signal on its own: commands/atlas-review-pr.md
    # and the runbook both also say "your own PR" in unrelated own-PR-fallback
    # prose that predates this fix, so a check for "your own" plus "resolve"
    # somewhere in the file could pass even if the actual #362 scoping text
    # were reworded beyond recognition or dropped. Anchor it to the concrete
    # mechanism too (first-comment-author matching) so a file only passes when
    # both the scoping language *and* how it's enforced are still present.
    first_comment_re = re.compile(r"first[- ]comment", re.IGNORECASE)
    for label, path in FILES.items():
        text = _read(path)
        assert "your own" in text.lower(), (
            f"{label} ({path}) no longer scopes thread resolution to "
            '"your own" threads -- re-add the ownership check (#362): only '
            "resolve a thread whose first comment the reviewer itself "
            "posted, never a human reviewer's, another bot's, or the PR "
            "author's."
        )
        assert first_comment_re.search(text), (
            f'{label} ({path}) says "your own" but no longer names the '
            "first-comment-author mechanism that makes it an actual check "
            '(#362) -- "your own threads" with nothing tying it to a '
            "concrete comparison is unenforceable prose."
        )


def test_atlas_review_pr_names_the_ownership_check_mechanism():
    text = _read(ROOT / "commands" / "atlas-review-pr.md")
    assert "first comment" in text.lower(), (
        "atlas-review-pr.md's resolve step no longer names checking the "
        "thread's first comment author -- without a concrete mechanism "
        "(first comment's author login vs. mcp__github__get_me), \"your own "
        'threads" is unenforceable prose, not an actual check.'
    )
    assert "get_me" in text, (
        "atlas-review-pr.md's resolve step no longer ties the ownership "
        "check to mcp__github__get_me -- the reviewer needs its own login "
        "to compare a thread's first comment against."
    )
    assert "get_review_comments" in text, (
        "atlas-review-pr.md's resolve step no longer names how to read a "
        "thread's first comment author (mcp__github__pull_request_read's "
        "get_review_comments method) -- without it there is no way to "
        "actually determine thread ownership before resolving."
    )


def test_review_md_and_template_stay_in_sync_on_the_scoping_language():
    # test_review_template_sync.py already asserts full byte-equality; this
    # is a narrower, more targeted check that the specific #362 fix landed
    # in both, so this test fails on its own if only one copy is edited.
    review_md = _read(ROOT / "REVIEW.md")
    template = _read(ROOT / "templates" / "REVIEW.md")
    assert "your own" in review_md.lower()
    assert "your own" in template.lower()
