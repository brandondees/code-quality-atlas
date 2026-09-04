# SPDX-License-Identifier: MIT
# tests/test_pr_review_automation_runbook_accuracy.py
"""#363: `docs/runbooks/pr-review-automation.md` disagreed with the commands
it summarizes (standing authoring rule 2: a summary must agree with what it
summarizes).

1. The runbook's Model B write-up claimed "One subagent per PR needing one;
   run them concurrently" for the review-subagent spawn step. The command it
   summarizes, `commands/atlas-poll-and-review.md`, caps concurrency at 5
   review subagents in flight at once, batched in groups of 5 -- the runbook
   said the opposite (unbounded concurrency) to anyone building the routine
   from the inlined prompt alone (`/atlas-poll-and-review` does not resolve
   in routine sessions, so the runbook's inlined copy is what actually ships).
2. Setup §2 (the Model A poller routine) carried Trigger/Cadence/Model/
   Connectors/Prompt bullets but no Permissions bullet, unlike §1 and §4 --
   an operator following §2 alone had no explicit "leave unrestricted branch
   pushes off" instruction.
3. "Known boundaries" was entirely reliability framing (what can silently
   stop working); nothing named which identity the routines act as, what
   they can write, that a PR under review carries untrusted content, or the
   blast radius of the multi-repo sweep.

Following the same "prose drift tripwire" pattern as
tests/test_ack_round_identity_binding.py (#360) and
tests/test_review_thread_resolution_scoping.py (#362): these are
prompt-instruction/runbook files with no interpreter to run them against, so
this test guards the prose shape directly rather than exercising behavior.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = ROOT / "docs" / "runbooks" / "pr-review-automation.md"


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def test_runbook_states_the_real_concurrency_cap_not_unbounded_concurrency():
    text = _text()
    assert "run them concurrently" not in text, (
        "the old unbounded-concurrency claim is back -- it contradicts "
        "atlas-poll-and-review.md's 5-subagent cap"
    )
    assert re.search(r"[Cc]oncurrency\s+cap:?\s*at most 5", text), (
        "the runbook should state the same 5-subagent-in-flight cap "
        "atlas-poll-and-review.md enforces"
    )


def test_setup_section_2_carries_a_permissions_bullet():
    text = _text()
    match = re.search(r"### 2\. Poller routine.*?(?=\n### 3\.)", text, re.DOTALL)
    assert match, "Setup §2 (Poller routine) section not found"
    section = match.group(0)
    assert re.search(r"\*\*Permissions:\*\*", section), (
        "§2 is missing a Permissions bullet -- §1 and §4 both carry one"
    )
    assert "unrestricted branch pushes" in section.lower()


def test_runbook_names_trust_boundaries_not_just_reliability():
    text = _text()
    assert re.search(r"^## Accepted risks", text, re.MULTILINE), (
        "no trust-boundary section -- 'Known boundaries' alone is reliability "
        "framing and never names identity, write scope, or untrusted PR content"
    )
    section = text[text.index("## Accepted risks") :]
    for must_mention in ("identity", "untrusted", "blast radius"):
        assert must_mention in section.lower(), (
            f"Accepted-risks section doesn't mention {must_mention!r}"
        )
