# SPDX-License-Identifier: MIT
# tests/test_ack_round_identity_binding.py
"""#360: ACK/round detection across `commands/atlas-review-pr.md`,
`commands/atlas-poll-and-review.md`, `commands/atlas-rebase-stale.md`, and
`docs/runbooks/pr-review-automation.md` treated *any* issue comment carrying
the ack marker/phrase, or *any* review opening with a `## Round N` heading /
carrying the round marker, as authoritative -- regardless of who posted it.
Three related gaps, one root cause (none of the detection logic authenticates
who posted a signal, or distinguishes "couldn't tell" from "definitely
absent"):

1. No reviewer-identity binding (Major, spoofing/DoS): a PR author or other
   collaborator could post a fabricated ACK or a fake high `## Round N`
   review to suppress the real ACK or inflate the round count.
2. The ACK "post it as a lock" pattern wasn't atomic (Major, race
   condition): "check for no ack, then post one" is a read-then-write race
   over a non-transactional API -- two sessions acting as the same reviewer
   identity (an event-triggered routine and a poller sweep both watching the
   same PR, an explicitly supported combination per the runbook) could each
   read "no ack" before either write lands, and both post.
3. A review with neither readable signal was silently treated as "no
   round," not "unreadable" (Major, false round-1 restart / coverage blind
   spot): indistinguishable from a review that genuinely predates any round.

Fixed by: (1) establishing "your own login" via `mcp__github__get_me` once
per session and filtering every ack/round candidate to
`author.login == that login`; (2) replacing the naive check-then-post ACK
with an actual GitHub-enforced mutex -- `pull_request_review_write` method
`create` with no `event` opens a pending review, and GitHub allows only one
pending review per identity per PR at a time, so a concurrent `create`
fails outright instead of racing; the lock is released with `delete_pending`
regardless of outcome; (3) a third `unknown` round state, distinct from both
"round 1" and any specific N, for when reviews from the expected identity
exist but none parses a heading or marker -- each site refuses to guess and
either stops (the reviewer itself) or skips escalation and flags it (the
pollers) rather than silently defaulting to round 1 or "no round review."

These are prompt-instruction files with no interpreter to run them against,
so -- following the same pattern as
tests/test_review_thread_resolution_scoping.py (#362) -- this test guards
the prose shape directly rather than exercising behavior.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = {
    "atlas-review-pr command": ROOT / "commands" / "atlas-review-pr.md",
    "atlas-poll-and-review command": ROOT / "commands" / "atlas-poll-and-review.md",
    "atlas-rebase-stale command": ROOT / "commands" / "atlas-rebase-stale.md",
    "pr-review-automation runbook": ROOT / "docs" / "runbooks" / "pr-review-automation.md",
}

# Only the two ack-posting surfaces (plus the runbook's prose describing
# both) need the pending-review lock -- atlas-rebase-stale.md never posts an
# ack, only pokes and re-requests review, so it has nothing to lock.
ACK_POSTING_FILES = {
    "atlas-review-pr command": ROOT / "commands" / "atlas-review-pr.md",
    "atlas-poll-and-review command": ROOT / "commands" / "atlas-poll-and-review.md",
    "pr-review-automation runbook": ROOT / "docs" / "runbooks" / "pr-review-automation.md",
}

# The three independently-scheduled surfaces that actually run the
# stuck-lock recovery pass (PR #402's own review round) --
# atlas-review-pr.md never runs it itself (a dead session can't clean up
# after itself); it only references where recovery lives.
RECOVERY_FILES = {
    "atlas-poll-and-review command": ROOT / "commands" / "atlas-poll-and-review.md",
    "atlas-rebase-stale command": ROOT / "commands" / "atlas-rebase-stale.md",
    "pr-review-automation runbook": ROOT / "docs" / "runbooks" / "pr-review-automation.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_file_cites_issue_360():
    for label, path in FILES.items():
        text = _read(path)
        assert "#360" in text, (
            f"{label} ({path}) no longer cites issue #360 anywhere -- this "
            "is the drift tripwire for the identity-binding/lock/tri-state "
            "fix; if the citation is gone, check whether the fix itself "
            "(get_me filtering, the pending-review lock, or the `unknown` "
            "round state) was quietly edited away with it."
        )


def test_every_file_calls_get_me_for_ack_round_detection():
    for label, path in FILES.items():
        text = _read(path)
        assert "get_me" in text, (
            f"{label} ({path}) no longer calls mcp__github__get_me -- "
            "without an established identity, ack/round detection has "
            "nothing to filter candidate comments/reviews by (#360, gap 1)."
        )


def test_every_file_handles_an_unknown_round_state():
    for label, path in FILES.items():
        text = _read(path)
        assert re.search(r"unknown", text, re.IGNORECASE), (
            f"{label} ({path}) no longer names an \"unknown\" round state -- "
            "re-add the tri-state handling (#360, gap 3): a review/comment "
            "from the expected identity that carries neither a parseable "
            "heading nor marker must not be silently folded into \"no round "
            "review\" / \"round 1\"."
        )


def test_ack_posting_surfaces_use_the_pending_review_lock():
    for label, path in ACK_POSTING_FILES.items():
        text = _read(path)
        assert "delete_pending" in text, (
            f"{label} ({path}) no longer releases a pending-review lock -- "
            "re-add the atomic ACK lock (#360, gap 2): create a pending "
            "review (method create, no event) before checking for/posting "
            "the ack, and always delete_pending afterward. Without the "
            "release half, a stuck lock would permanently block future ACK "
            "attempts, which is exactly the kind of gap this pattern must "
            "not silently reintroduce."
        )
        assert "pull_request_review_write" in text, (
            f"{label} ({path}) mentions delete_pending but not "
            "pull_request_review_write -- the lock must be the documented "
            "GitHub-enforced one-pending-review-per-identity mechanism, not "
            "some other primitive."
        )


def test_atlas_rebase_stale_allowed_tools_includes_get_me():
    text = _read(ROOT / "commands" / "atlas-rebase-stale.md")
    match = re.search(r"^allowed-tools:\s*(.+)$", text, re.MULTILINE)
    assert match, "atlas-rebase-stale.md has no allowed-tools frontmatter line"
    assert "mcp__github__get_me" in match.group(1), (
        "atlas-rebase-stale.md's allowed-tools line no longer grants "
        "mcp__github__get_me -- without it, step 3's identity-filtered "
        "coverage check (#360, gap 1) has no way to actually call get_me."
    )


def test_identity_filtering_is_tied_to_round_or_ack_not_just_present():
    # A bare "get_me" mention could be the pre-existing own-PR-fallback or
    # #362 resolve-scoping use, unrelated to round/ack detection. Anchor to
    # language that actually ties identity to round/ack signals specifically.
    round_ack_identity_re = re.compile(
        r"(author\.login|own login).{0,200}(round|ack)"
        r"|(round|ack).{0,200}(author\.login|own login)",
        re.IGNORECASE | re.DOTALL,
    )
    for label, path in FILES.items():
        text = _read(path)
        assert round_ack_identity_re.search(text), (
            f"{label} ({path}) has get_me and \"unknown\" language but "
            "nothing ties an author's login to round/ack detection "
            "specifically -- the identity check must scope round/ack "
            "candidates, not just exist somewhere else in the file (#360, "
            "gap 1)."
        )


def test_pollers_recover_a_stuck_ack_lock():
    # PR #402's own review round: a session that dies between the lock's
    # create and delete_pending orphans it forever, since every future
    # create under the same identity then fails and the protocol's own
    # instruction was "stand down" -- with none of the system's backstops
    # (they share the reviewer's identity) able to route around it. Fixed
    # by having the independently-scheduled pollers detect and clear a
    # stale (30+ minute old) pending review under their own identity.
    for label, path in RECOVERY_FILES.items():
        text = _read(path)
        # "stuck", "get_reviews", and "delete_pending" alone are too weak an
        # anchor for atlas-poll-and-review.md specifically: all three already
        # existed there before this recovery pass, for unrelated reasons (the
        # ACK lock's own create/delete_pending, and get_reviews used
        # elsewhere for identity filtering). Anchor to the staleness
        # threshold instead, which is new and specific to this mechanism.
        assert "30 minutes" in text, (
            f"{label} ({path}) no longer names the stuck-lock staleness "
            "threshold (30 minutes) -- without a concrete recovery pass "
            "(detect a PENDING review under your own identity older than "
            "the threshold, clear it with delete_pending), a session dying "
            "between the ACK lock's create and delete_pending permanently "
            "and silently stops the affected PR from ever being ack'd or "
            "reviewed again (PR #402 review)."
        )
        assert "get_reviews" in text, (
            f"{label} ({path}) mentions the staleness threshold but not "
            "get_reviews -- the recovery pass needs a concrete way to find "
            "its own orphaned pending review (pull_request_read's "
            "get_reviews method, which returns the authenticated user's own "
            "PENDING review even though it's otherwise invisible to anyone "
            "else)."
        )
        assert "delete_pending" in text, (
            f"{label} ({path}) mentions stuck-lock detection but not the "
            "delete_pending call that actually clears it -- detection "
            "without release doesn't fix anything."
        )


def test_create_failure_distinguishes_contention_from_a_real_error():
    # A second, smaller PR #402 finding: every create failure was folded
    # into "someone else has the lock," silently swallowing permission
    # errors, rate limits, and other real failures under the same "stand
    # down" branch as ordinary lock contention.
    for label, path in ACK_POSTING_FILES.items():
        text = _read(path)
        assert re.search(r"real\s+(failure|error)", text, re.IGNORECASE), (
            f"{label} ({path}) no longer distinguishes a real create "
            "failure (permissions, rate limit, a transient API error) from "
            "ordinary lock contention (\"a pending review already "
            "exists\") -- re-add the distinction so a genuine failure gets "
            "surfaced instead of silently read as \"someone else has it.\""
        )
