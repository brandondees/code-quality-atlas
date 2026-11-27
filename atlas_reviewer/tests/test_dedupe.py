# SPDX-License-Identifier: MIT
"""The controller-side dedupe (issue #822): findings from different
lenses that name the same defect collapse into one representative that
carries every lens attribution. Pure: no bridge, no model, no ledger."""

from atlas_reviewer.dedupe import (
    SPAN_PROXIMITY_LINES,
    claim_key,
    dedupe,
    same_target,
)
from atlas_reviewer.findings import MintedFinding
from atlas_reviewer.lens_contract import (
    Attribution,
    DesignRef,
    Finding,
    LineRange,
    PullBody,
    Route,
    Severity,
    Valence,
    WholeFile,
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
    }
    return Finding(**{**base, **kw})


def minted(lens: str, index: int, n: int = 1, **kw) -> MintedFinding:
    finding = kw.pop("finding", None) or a_finding(**kw)
    return MintedFinding(f"L{index}-F{n}", lens, finding, True, "head")


def test_identical_restatements_from_two_lenses_are_one_finding():
    merged = dedupe([minted("tracing", 1), minted("naming", 2)])
    assert len(merged) == 1
    assert merged[0].lens == "tracing"
    assert merged[0].lenses == ("tracing", "naming")
    assert merged[0].id == "L1-F1"


def test_the_cluster_carries_every_distinct_lens_in_first_seen_order():
    merged = dedupe(
        [
            minted("tracing", 1),
            minted("naming", 2),
            minted("tracing", 1, n=2),
            minted("restraint", 3),
        ]
    )
    assert merged[0].lenses == ("tracing", "naming", "restraint")


def test_a_single_lens_finding_names_no_lens_list():
    (finding,) = dedupe([minted("tracing", 1)])
    assert finding.lenses == ()


def test_nearby_spans_merge_but_distant_ones_do_not():
    near = a_finding(location=LineRange("calc.py", 2, 2))
    beside = a_finding(location=LineRange("calc.py", 2 + SPAN_PROXIMITY_LINES, 2))
    far = a_finding(location=LineRange("calc.py", 500, 500))
    assert same_target(minted("a", 1, finding=near), minted("b", 2, finding=beside))
    assert not same_target(minted("a", 1, finding=near), minted("b", 2, finding=far))
    assert len(dedupe([minted("a", 1, finding=near), minted("b", 2, finding=far)])) == 2


def test_the_window_reaches_both_directions_from_either_span():
    low = a_finding(location=LineRange("calc.py", 2, 3))
    high = a_finding(location=LineRange("calc.py", 12, 12))
    assert SPAN_PROXIMITY_LINES == 10
    assert same_target(minted("a", 1, finding=low), minted("b", 2, finding=high))
    assert same_target(minted("a", 1, finding=high), minted("b", 2, finding=low))


def test_the_same_claim_at_different_paths_stays_separate():
    moved = a_finding(location=LineRange("config/keys.py", 2, 2))
    assert len(dedupe([minted("a", 1), minted("b", 2, finding=moved)])) == 2


def test_the_same_span_with_a_different_claim_stays_separate():
    other = a_finding(finding="swallows the OSError the write raises")
    assert len(dedupe([minted("a", 1), minted("b", 2, finding=other)])) == 2


def test_an_introduced_and_a_pre_existing_claim_never_merge():
    older = a_finding(attribution=Attribution.PRE_EXISTING)
    assert len(dedupe([minted("a", 1), minted("b", 2, finding=older)])) == 2


def test_a_defect_and_an_improvement_never_merge():
    wish = a_finding(valence=Valence.IMPROVEMENT)
    assert len(dedupe([minted("a", 1), minted("b", 2, finding=wish)])) == 2


def test_a_verified_and_an_unverified_copy_never_merge():
    unverified = minted("b", 2)
    unverified = MintedFinding(
        unverified.id, unverified.lens, unverified.finding, False, "the quote is not there"
    )  # fmt: skip
    assert len(dedupe([minted("a", 1), unverified])) == 2


def test_the_claim_key_folds_case_whitespace_and_trailing_punctuation():
    assert claim_key(
        "  Rounds each item   before summing, so totals drift. "
    ) == claim_key("rounds each item before summing, so totals drift")
    assert claim_key("") == ""


def test_an_empty_claim_never_merges():
    blank = a_finding(finding="")
    assert (
        len(dedupe([minted("a", 1, finding=blank), minted("b", 2, finding=blank)])) == 2
    )


def test_a_whole_file_location_overlaps_a_range_in_that_file():
    whole = a_finding(location=WholeFile("calc.py"))
    assert same_target(minted("a", 1, finding=whole), minted("b", 2))


def test_whole_file_locations_merge_only_within_one_path():
    whole = a_finding(location=WholeFile("config/keys.py"))
    assert not same_target(minted("a", 1, finding=whole), minted("b", 2))


def test_a_design_reference_merges_only_on_the_identical_string():
    ref = a_finding(location=DesignRef("boundary:runner→bridge"))
    other = a_finding(location=DesignRef("boundary:runner→bridge"))
    another = a_finding(location=DesignRef("boundary:bridge→runner"))
    assert same_target(minted("a", 1, finding=ref), minted("b", 2, finding=other))
    assert not same_target(minted("a", 1, finding=ref), minted("b", 2, finding=another))


def test_the_pull_request_body_merges_only_on_itself():
    body = a_finding(location=PullBody())
    assert same_target(minted("a", 1, finding=body), minted("b", 2, finding=body))
    assert not same_target(minted("a", 1, finding=body), minted("b", 2))


def test_the_representative_is_the_cluster_strongest_finding():
    minor = minted("a", 1, finding=a_finding(severity=Severity.MINOR))
    blocker = minted("b", 2, finding=a_finding(severity=Severity.BLOCKER))
    (merged,) = dedupe([minor, blocker])
    assert merged.finding.severity is Severity.BLOCKER
    assert merged.lens == "b"
    assert merged.lenses == ("a", "b")


def test_the_representative_order_keeps_the_first_on_a_tie():
    one = minted("a", 1, finding=a_finding(location=LineRange("calc.py", 2, 2)))
    two = minted("b", 2, finding=a_finding(location=LineRange("calc.py", 3, 3)))
    (merged,) = dedupe([one, two])
    assert merged.id == "L1-F1"


def test_clusters_do_not_chain_through_a_member():
    """A~B and B~C does not merge A into C unless A matches C too: the
    comparison is against each cluster's representative, never a member."""
    at_two = minted("a", 1, finding=a_finding(location=LineRange("calc.py", 2, 2)))
    at_twelve = minted("b", 2, finding=a_finding(location=LineRange("calc.py", 12, 12)))
    at_twenty_two = minted(
        "c", 3, finding=a_finding(location=LineRange("calc.py", 22, 22))
    )
    merged = dedupe([at_two, at_twelve, at_twenty_two])
    assert [f.lens for f in merged] == ["a", "c"]
    assert merged[0].lenses == ("a", "b")


def test_distinct_findings_keep_their_mint_order():
    findings = [
        minted("a", 1, finding=a_finding(location=LineRange("calc.py", 2, 2))),
        minted("b", 2, finding=a_finding(location=LineRange("calc.py", 500, 500))),
        minted("c", 3, finding=a_finding(location=WholeFile("config/keys.py"))),
    ]
    assert [f.id for f in dedupe(findings)] == ["L1-F1", "L2-F1", "L3-F1"]
