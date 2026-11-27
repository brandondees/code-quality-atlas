# SPDX-License-Identifier: MIT
"""The merge/verify call's pieces (the plan's step 7): the turn's
blocks, the reply's parse, and the controller's reconciliation, where
every disposition the reply proposes is checked against the findings
the controller holds before anything is composed. Pure."""

import json

import pytest

from atlas_reviewer.findings import MintedFinding
from atlas_reviewer.lens_contract import (
    Attribution,
    ContractError,
    Finding,
    LineRange,
    Route,
    Severity,
    Valence,
)
from atlas_reviewer.prompt import UntrustedBlock
from atlas_reviewer.synthesis import (
    MERGE_TARGET_PREFIX,
    MergeReply,
    findings_block,
    merge_system,
    merge_turn,
    parse_merge_reply,
    reconcile,
)


def a_finding(**kw) -> Finding:
    base = {
        "location": LineRange("calc.py", 2, 2),
        "severity": Severity.MINOR,
        "valence": Valence.DEFECT,
        "route": Route.ENG,
        "attribution": Attribution.INTRODUCED,
        "finding": "rounds each item before summing, so totals drift",
        "fix": "sum first, then round once",
        "evidence": "return sum(round(x, 2) for x in xs)",
    }
    return Finding(**{**base, **kw})


def minted(identifier: str, lens: str, **kw) -> MintedFinding:
    verified = kw.pop("_verified", True)
    finding = kw.pop("finding", None) or a_finding(**kw)
    return MintedFinding(identifier, lens, finding, verified, "head")


def reply(clusters=(), dispositions=()) -> str:
    return json.dumps({"clusters": list(clusters), "dispositions": list(dispositions)})


def test_the_system_prompt_carries_the_instructions_and_the_fence_rule():
    system = merge_system("f00dfeed")
    assert "coordinator" in system
    assert 'id="f00dfeed"' in system


def test_the_turn_opens_with_the_controller_subject_and_fences_every_block():
    from atlas_reviewer.domain import PrEvent
    from atlas_reviewer.prompt import RepoText

    event = PrEvent("example-org/example-app", 7, "a" * 40)
    turn = merge_turn(
        event,
        UntrustedBlock("findings", RepoText("L1-F1 [minor] calc.py:2")),
        UntrustedBlock("prior-rounds", RepoText("round at abc1234: COMMENT")),
        (UntrustedBlock("conversation", RepoText("the body")),),
        "f00dfeed",
    )
    assert turn.startswith(
        MERGE_TARGET_PREFIX + f"example-org/example-app#7 at {'a' * 40}"
    )
    assert 'id="f00dfeed"' in turn
    assert (
        turn.index("findings") < turn.index("prior-rounds") < turn.index("conversation")
    )


def test_the_findings_block_names_each_finding_id_severity_and_standing():
    block = findings_block(
        [
            minted("L1-F1", "tracing"),
            minted("L2-F1", "naming", _verified=False),
        ]
    )
    text = block.content.text
    assert "L1-F1 [minor defect introduced] calc.py:2 (lens tracing, verified):" in text
    assert "L2-F1" in text and "NOT verified" in text
    assert "evidence: return sum(round(x, 2) for x in xs)" in text


def test_a_reply_with_no_keys_keeps_everything():
    parsed = parse_merge_reply(reply())
    assert parsed == MergeReply((), ())


def test_a_cluster_and_a_disposition_parse():
    parsed = parse_merge_reply(
        reply(
            clusters=[{"ids": ["L1-F1", "L2-F1"], "reason": "one defect"}],
            dispositions=[
                {
                    "id": "L3-F1",
                    "action": "downgrade",
                    "severity": "nit",
                    "reason": "cosmetic",
                },
                {"id": "L4-F1", "action": "drop", "reason": "the quote is not there"},
            ],
        )
    )
    assert parsed.clusters[0].ids == ("L1-F1", "L2-F1")
    assert parsed.dispositions[0].severity is Severity.NIT
    assert parsed.dispositions[1].severity is None


def test_a_reply_buried_in_prose_parses_from_the_last_fence():
    text = (
        "I judged the findings.\n```json\n"
        + reply(clusters=[{"ids": ["L1-F1", "L2-F1"], "reason": "one defect"}])
        + "\n```"
    )
    assert parse_merge_reply(text).clusters[0].ids == ("L1-F1", "L2-F1")


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        "[]",
        '{"clusters": "no"}',
        '{"clusters": [{"ids": ["L1-F1"], "reason": "alone"}]}',
        '{"clusters": [{"ids": ["L1-F1", "L1-F1"], "reason": "twice"}]}',
        '{"clusters": [{"ids": ["L1-F1", "L2-F1"], "reason": " "}]}',
        '{"clusters": [{"ids": ["L1-F1", "L2-F1"], "reason": "x" * 601}]}',
        '{"dispositions": [{"id": "L1-F1", "action": "raise", "reason": "no"}]}',
        '{"dispositions": [{"id": "L1-F1", "action": "drop"}]}',
        '{"dispositions": [{"id": "L1-F1", "action": "drop", "reason": " "}]}',
        '{"dispositions": [{"id": "L1-F1", "action": "downgrade", "reason": "no severity"}]}',
        '{"dispositions": [{"id": "L1-F1", "action": "downgrade", "severity": "huge", "reason": "r"}]}',
        '{"dispositions": [{"id": "L1-F1", "action": "drop", "severity": "nit", "reason": "r"}]}',
        '{"dispositions": [{"id": "L1-F1", "action": "drop", "reason": "r", "extra": 1}]}',
    ],
)
def test_a_reply_out_of_shape_is_refused(text):
    with pytest.raises(ContractError):
        parse_merge_reply(text)


def test_a_cluster_merges_into_the_strongest_member_with_every_lens_named():
    kept, result = reconcile(
        parse_merge_reply(
            reply(clusters=[{"ids": ["L1-F1", "L2-F1"], "reason": "one defect"}])
        ),
        [
            minted("L1-F1", "tracing"),
            minted("L2-F1", "naming", severity=Severity.MAJOR),
        ],
    )
    assert [f.id for f in kept] == ["L2-F1"]
    assert kept[0].lenses == ("tracing", "naming")
    assert result.merged == (("L2-F1", ("L1-F1",)),)


def test_a_downgrade_is_an_annotation_and_the_finding_stays():
    kept, result = reconcile(
        parse_merge_reply(
            reply(
                dispositions=[
                    {
                        "id": "L1-F1",
                        "action": "downgrade",
                        "severity": "nit",
                        "reason": "cosmetic",
                    }
                ]
            )
        ),
        [minted("L1-F1", "tracing", severity=Severity.MINOR)],
    )
    assert [f.id for f in kept] == ["L1-F1"]
    assert kept[0].finding.severity is Severity.MINOR
    assert result.proposals == (
        ("L1-F1", "merge proposal: downgrade to nit -- cosmetic"),
    )
    assert result.downgrades == 1


def test_a_drop_is_an_annotation_and_the_finding_stays():
    kept, result = reconcile(
        parse_merge_reply(
            reply(
                dispositions=[
                    {"id": "L1-F1", "action": "drop", "reason": "the quote is wrong"}
                ]
            )
        ),
        [minted("L1-F1", "tracing")],
    )
    assert [f.id for f in kept] == ["L1-F1"]
    assert result.drops == 1
    assert result.proposals[0][1] == "merge proposal: drop -- the quote is wrong"


def test_an_unknown_id_refuses_the_whole_reply():
    with pytest.raises(ContractError, match="names no finding"):
        reconcile(
            parse_merge_reply(
                reply(clusters=[{"ids": ["L1-F1", "L9-F9"], "reason": "r"}])
            ),
            [minted("L1-F1", "tracing")],
        )


def test_a_finding_named_twice_refuses_the_whole_reply():
    with pytest.raises(ContractError, match="a second time"):
        reconcile(
            parse_merge_reply(
                reply(
                    clusters=[{"ids": ["L1-F1", "L2-F1"], "reason": "r"}],
                    dispositions=[{"id": "L1-F1", "action": "drop", "reason": "r"}],
                )
            ),
            [minted("L1-F1", "tracing"), minted("L2-F1", "naming")],
        )


def test_a_downgrade_that_is_not_strictly_lower_refuses_the_reply():
    for severity in ("blocker", "minor"):
        with pytest.raises(ContractError, match="not below its own"):
            reconcile(
                parse_merge_reply(
                    reply(
                        dispositions=[
                            {
                                "id": "L1-F1",
                                "action": "downgrade",
                                "severity": severity,
                                "reason": "r",
                            }
                        ]
                    )
                ),
                [minted("L1-F1", "tracing", severity=Severity.MINOR)],
            )


def test_a_cluster_mixing_verified_and_unverified_refuses_the_reply():
    """A cluster's members must share the claim's shape, the mechanical
    dedupe's own identity rule (round-1 review of #863, Major 1): the
    reply's severity-only ranking would otherwise seat an unverified
    Blocker over the verified Major it claims to duplicate, and the
    verified finding the verdict reads is merged away on model say-so.
    Mutant: the shape check dropped, which loses the verified Major and
    can approve."""

    unverified_blocker = MintedFinding(
        "L2-F1", "naming", a_finding(severity=Severity.BLOCKER), False, "not at that range"
    )  # fmt: skip
    with pytest.raises(ContractError, match="do not share the claim's shape"):
        reconcile(
            parse_merge_reply(
                reply(clusters=[{"ids": ["L2-F1", "L1-F1"], "reason": "one defect"}])
            ),
            [minted("L1-F1", "tracing"), unverified_blocker],
        )


def test_a_cluster_mixing_a_defect_and_an_improvement_refuses_the_reply():
    """A merged-away member loses its own standing entirely, so a praise
    entry must not be clustered under the defect it sits beside: the
    reply that merged them names one reading, and the controller cannot
    keep both. Mutant: the valence check dropped, which deletes the
    improvement finding from the report."""
    wish = minted("L2-F1", "naming", valence=Valence.IMPROVEMENT)
    with pytest.raises(ContractError, match="do not share the claim's shape"):
        reconcile(
            parse_merge_reply(
                reply(clusters=[{"ids": ["L1-F1", "L2-F1"], "reason": "r"}])
            ),
            [minted("L1-F1", "tracing"), wish],
        )


def test_a_cluster_mixing_introduced_and_pre_existing_refuses_the_reply():
    """The verdict treats an introduced defect and a pre-existing one
    differently (D55); a cluster over both would keep whichever reads
    stronger and lose the other's standing. Mutant: the attribution
    check dropped, which reports a pre-existing defect as introduced --
    or drops it -- on the reply's say-so."""
    older = minted("L2-F1", "naming", attribution=Attribution.PRE_EXISTING)
    with pytest.raises(ContractError, match="do not share the claim's shape"):
        reconcile(
            parse_merge_reply(
                reply(clusters=[{"ids": ["L1-F1", "L2-F1"], "reason": "r"}])
            ),
            [minted("L1-F1", "tracing"), older],
        )


def test_a_cluster_over_same_shape_members_of_different_severity_still_merges():
    """Severity is the one axis a cluster may span: the strongest
    severity represents the defect, which is the merge's point."""
    kept, result = reconcile(
        parse_merge_reply(
            reply(clusters=[{"ids": ["L1-F1", "L2-F1"], "reason": "one defect"}])
        ),
        [
            minted("L1-F1", "tracing"),
            minted("L2-F1", "naming", severity=Severity.MAJOR),
        ],
    )
    assert [f.id for f in kept] == ["L2-F1"]
    assert result.applied


def test_an_empty_reply_applies_as_a_no_op():
    kept, result = reconcile(parse_merge_reply(reply()), [minted("L1-F1", "tracing")])
    assert [f.id for f in kept] == ["L1-F1"]
    assert result.applied
    assert result.clusters == 0
    assert result.proposals == ()


def test_a_cluster_over_deduped_members_carries_the_whole_attribution_chain():
    """The dedupe's own clusters already travel as `lenses:` lists; a
    merge cluster over them unions the chains, so every lens that
    reported the defect stays named."""
    kept, _result = reconcile(
        parse_merge_reply(
            reply(clusters=[{"ids": ["L1-F1", "L2-F1"], "reason": "one defect"}])
        ),
        [
            MintedFinding(
                "L1-F1",
                "tracing",
                a_finding(),
                True,
                "head",
                lenses=("tracing", "naming"),
            ),
            minted("L2-F1", "restraint", severity=Severity.MAJOR),
        ],
    )
    assert kept[0].lenses == ("tracing", "naming", "restraint")
