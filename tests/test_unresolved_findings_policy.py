# SPDX-License-Identifier: MIT
# tests/test_unresolved_findings_policy.py
"""Issue #526: an open Major+ finding could evaporate when its PR merged.
REVIEW.md now carries an `unresolved_findings` setting (note | require-followup
| file-followup | block, default note) and commands/atlas-review-pr.md step 5
says what each value does. Both files restate the same four values and the
follow-up issue marker, so this guards them against drifting apart the way
the ACK/round protocol once did (test_review_protocol_markers_sync.py)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_MODES = ["note", "require-followup", "file-followup", "block"]
_MARKER = "<!-- atlas-followup pr:<number> -->"
_SITES = ["REVIEW.md", "templates/REVIEW.md", "commands/atlas-review-pr.md"]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_review_md_declares_the_setting_with_advisory_default():
    text = _read("templates/REVIEW.md")
    assert "## Unresolved findings at merge" in text
    assert (
        "unresolved_findings: note        # note | require-followup | "
        "file-followup | block" in text
    )
    assert "unresolved_threshold: Major" in text
    assert "`note` *(default, advisory)*" in text


def test_every_site_names_every_mode_and_the_followup_marker():
    for rel in _SITES:
        text = _read(rel)
        for mode in _MODES:
            assert f"`{mode}`" in text, f"{rel} is missing mode `{mode}`"
        assert _MARKER in text, f"{rel} is missing the follow-up issue marker"


def test_block_mode_is_named_as_the_one_override_of_blocker_only_state():
    # The "GitHub review state vs. severity" section deliberately reserves
    # REQUEST_CHANGES for Blockers; `block` must say it overrides that rather
    # than silently contradict it.
    # Whitespace-normalized, like test_review_protocol_markers_sync.py's
    # wrap-tolerant tokens, so a cosmetic re-wrap doesn't fail this.
    text = " ".join(_read("templates/REVIEW.md").split())
    assert "that is the one override of this rule." in text


def test_block_mode_says_it_cannot_gate_a_self_authored_pr():
    # PR #533 round-1: GitHub forbids REQUEST_CHANGES on your own PR, so the
    # own-PR COMMENT substitute makes `block` no stronger than `note` there.
    # Both the policy and the command must say so rather than leave it to be
    # inferred.
    for rel in ["templates/REVIEW.md", "commands/atlas-review-pr.md"]:
        text = " ".join(_read(rel).split())
        assert "gates nothing beyond" in text, rel
