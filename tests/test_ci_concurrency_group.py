# SPDX-License-Identifier: MIT
# tests/test_ci_concurrency_group.py
"""D78's corrected concurrency rationale (round 1 of #746) rests on the
group expression carrying the event name (`ci-<event_name>-<ref>`): a
`schedule` event resolves to the default branch's ref, so a ref-only group
would put the weekly scheduled pip-audit (#379) in the same group as main
pushes -- and a concurrency group holds at most one running and one pending
run, with a newer run cancelling an older *pending* one regardless of
`cancel-in-progress` (observed live in this repo: push run 44087837195 was
cancelled at 2026-11-17T23:41:36Z, the instant run 44181631062 queued). So
a ref-only group means any mid-week push can silently supersede a pending
audit -- exactly what the corrected D78 promises against.

Round-2 review of #746 found that reverting the group to the round-0
ref-only form (mutant M4) passed the entire `tests/` suite, leaving that
promise with zero CI signal. This is that guard, in the repo's established
`test_ci_*` shape. It also pins `cancel-in-progress` to exactly the PR-only
expression (whitespace-normalized exact match, per round 3 of #746 -- the
round-2 substring check let the inverted split `!= 'pull_request'` pass as
mutant M7), so the split (PR runs cancel; push/schedule never cancel in
progress) can't silently flip either way: a bare `true` would let a push
kill an in-progress audit, a bare `false` would stop superseding PR runs,
and any inverted or OR'd variant fails the exact match.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _concurrency() -> dict:
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    conc = workflow.get("concurrency")
    assert (
        isinstance(conc, dict) and "group" in conc and "cancel-in-progress" in conc
    ), (
        f"{CI_YML}'s concurrency block is missing or reshaped ({conc!r}) -- "
        "update this guard either way."
    )
    return conc


def test_concurrency_group_carries_the_event_name():
    group = _concurrency()["group"]
    assert isinstance(group, str) and "${{" in group, (
        f"concurrency.group is {group!r} -- expected a GitHub Actions "
        "expression, not a literal group name."
    )
    assert "github.event_name" in group, (
        f"concurrency.group ({group!r}) no longer includes "
        "github.event_name -- push(main) and schedule would share a group "
        "again (both resolve to the default branch's ref), and a newer run "
        "cancels an older *pending* one regardless of cancel-in-progress, "
        "reopening the pending-audit supersession D78's corrected "
        "concurrency rationale promises against."
    )
    assert "github.ref" in group, (
        f"concurrency.group ({group!r}) no longer includes github.ref -- "
        "different refs would collide in one group."
    )


def test_cancel_in_progress_stays_pull_request_only():
    cip = _concurrency()["cancel-in-progress"]
    # Exact-expression pin, whitespace-normalized (round 3 of #746): the
    # round-2 substring check let the inverted split
    # `${{ github.event_name != 'pull_request' }}` pass (mutant M7), and it
    # is the semantically worst survivor -- push runs would cancel an
    # in-progress scheduled pip-audit, and PR runs would stop superseding.
    normalized = "".join(cip.split()) if isinstance(cip, str) else cip
    assert normalized == "${{github.event_name=='pull_request'}}", (
        f"concurrency.cancel-in-progress is {cip!r} -- expected exactly the "
        "PR-only expression `${{ github.event_name == 'pull_request' }}` "
        "(whitespace-insensitive). An inverted or OR'd variant cancels "
        "in-progress scheduled pip-audits (#379) and stops superseding PR "
        "runs; a bare true or false does one of those two one-sided."
    )
