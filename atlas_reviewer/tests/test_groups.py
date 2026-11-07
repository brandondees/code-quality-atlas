# SPDX-License-Identifier: MIT
"""One CI gate is a check run, its job, its log and its workflow run. The
draft must count it once, and grouping must never hide a failure."""

from atlas_reviewer.classify import classify, tally
from atlas_reviewer.domain import (
    Conclusion,
    EvidenceItem,
    Outcome,
    Provenance,
    SourceKey,
    SourceKind,
    ToolInfo,
)
from atlas_reviewer.groups import Link, group_checks
from atlas_reviewer.redact import redact

from .helpers import HEAD, NOW, OLD

K = SourceKind


def mk(kind, name, source_id, conclusion=Conclusion.SUCCESS, sha=HEAD):
    return EvidenceItem(
        head_sha=sha,
        provenance=Provenance(SourceKey(kind, name), source_id),
        tool=ToolInfo("github-actions", "unreported"),
        fetched_at=NOW,
        conclusion=conclusion,
        detail=redact(""),
    )


def gate(conclusion=Conclusion.SUCCESS, run_conclusion=None):
    """check run 7 = job 7 (via check_run_url), its log, and workflow run 5."""
    items = [
        mk(K.CHECK_RUN, "gate", "check_run:7", conclusion),
        mk(K.JOB, "ci / gate", "job:7", conclusion),
        mk(K.WORKFLOW_LOG, "ci / gate", "job_log:7", conclusion),
        mk(K.WORKFLOW_RUN, "ci", "workflow_run:5", run_conclusion or conclusion),
    ]
    links = [
        Link("job_log:7", "job:7"),
        Link("job:7", "check_run:7"),
        Link("workflow_run:5", "job:7"),
    ]
    return items, links


def test_the_four_views_of_one_gate_count_as_one_passing_check():
    items, links = gate()
    evidence = classify(HEAD, items)
    assert tally(evidence).passed == 4
    t = tally(evidence, links)
    assert (t.passed, t.failed, t.unknown, t.supporting) == (1, 0, 0, 3)
    (group,) = group_checks(evidence, links)
    assert group.root.item.provenance.source_id == "check_run:7"
    assert {m.item.provenance.source_id for m in group.supporting} == {
        "job:7",
        "job_log:7",
    }
    assert [m.item.provenance.source_id for m in group.context] == ["workflow_run:5"]


def test_a_failing_gate_counts_one_failure_not_four():
    items, links = gate(Conclusion.FAILURE)
    t = tally(classify(HEAD, items), links)
    assert (t.passed, t.failed) == (0, 1)


def test_a_failing_supporting_view_fails_the_group_even_if_the_check_run_passed():
    items, links = gate()
    items[1] = mk(K.JOB, "ci / gate", "job:7", Conclusion.FAILURE)
    (group,) = group_checks(classify(HEAD, items), links)
    assert group.outcome is Outcome.FAIL


def test_unknown_supporting_view_makes_the_group_unknown_not_pass():
    items, links = gate()
    items[2] = mk(K.WORKFLOW_LOG, "ci / gate", "job_log:7", Conclusion.PENDING)
    (group,) = group_checks(classify(HEAD, items), links)
    assert group.outcome is Outcome.UNKNOWN


def test_a_run_failure_explained_by_one_job_does_not_fail_its_passing_sibling():
    items, links = gate()
    items += [
        mk(K.JOB, "ci / test", "job:8", Conclusion.FAILURE),
        mk(K.WORKFLOW_LOG, "ci / test", "job_log:8", Conclusion.FAILURE),
    ]
    items[3] = mk(K.WORKFLOW_RUN, "ci", "workflow_run:5", Conclusion.FAILURE)
    links += [Link("job_log:8", "job:8"), Link("workflow_run:5", "job:8")]
    groups = {
        g.root.item.provenance.source_id: g.outcome
        for g in group_checks(classify(HEAD, items), links)
    }
    assert groups == {"check_run:7": Outcome.PASS, "job:8": Outcome.FAIL}


def test_a_run_failure_no_job_explains_stays_an_independent_failure():
    items, links = gate()
    items[3] = mk(K.WORKFLOW_RUN, "ci", "workflow_run:5", Conclusion.FAILURE)
    t = tally(classify(HEAD, items), links)
    assert (t.passed, t.failed) == (1, 1)


def test_a_pending_run_with_only_passing_jobs_stays_independent_and_unknown():
    items, links = gate()
    items[3] = mk(K.WORKFLOW_RUN, "ci", "workflow_run:5", Conclusion.PENDING)
    t = tally(classify(HEAD, items), links)
    assert (t.passed, t.unknown) == (1, 1)


def test_a_job_without_its_check_run_is_its_own_check_with_its_log_and_run():
    items, links = gate()
    items = items[1:]
    t = tally(classify(HEAD, items), links)
    assert (t.passed, t.supporting) == (1, 2)


def test_unrelated_checks_are_not_merged():
    items, links = gate()
    items.append(mk(K.CHECK_RUN, "integration", "check_run:9", Conclusion.PENDING))
    items.append(mk(K.CHECK_RUN, "lint", "check_run:10", Conclusion.FAILURE))
    t = tally(classify(HEAD, items), links)
    assert (t.passed, t.failed, t.unknown) == (1, 1, 1)


def test_links_to_evidence_that_is_not_at_the_head_are_ignored():
    items, links = gate()
    items[0] = mk(K.CHECK_RUN, "gate", "check_run:7", sha=OLD)
    evidence = classify(HEAD, items)
    t = tally(evidence, links)
    assert t.stale == 1
    assert t.passed == 1
    assert [
        g.root.item.provenance.source_id for g in group_checks(evidence, links)
    ] == ["job:7"]


def test_missing_evidence_is_still_unknown_and_never_grouped_into_a_pass():
    items, links = gate()
    evidence = classify(HEAD, items, expected=[SourceKey(K.CHECK_RUN, "security-scan")])
    t = tally(evidence, links)
    assert (t.passed, t.unknown) == (1, 1)


def test_duplicate_source_ids_are_kept_not_dropped():
    a = mk(K.CHECK_RUN, "a", "check_run:1", Conclusion.FAILURE)
    b = mk(K.CHECK_RUN, "b", "check_run:1", Conclusion.SUCCESS)
    t = tally(classify(HEAD, [a, b]), [])
    assert (t.passed, t.failed) == (1, 1)


def test_a_cycle_in_links_cannot_hang_or_hide_a_failing_check():
    items = [mk(K.JOB, "x", "job:1"), mk(K.JOB, "y", "job:2", Conclusion.FAILURE)]
    links = [Link("job:1", "job:2"), Link("job:2", "job:1")]
    t = tally(classify(HEAD, items), links)
    assert (t.passed, t.failed) == (1, 1)


def test_a_cycle_reachable_from_a_real_check_terminates_and_counts_everything():
    items = [
        mk(K.CHECK_RUN, "root", "check_run:1"),
        mk(K.JOB, "a", "job:1", Conclusion.FAILURE),
        mk(K.JOB, "b", "job:2"),
    ]
    links = [
        Link("job:1", "check_run:1"),
        Link("job:2", "job:1"),
        Link("job:1", "job:2"),
    ]
    t = tally(classify(HEAD, items), links)
    assert t.failed + t.passed >= 1
    assert t.failed == 1
