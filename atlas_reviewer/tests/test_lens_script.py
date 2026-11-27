# SPDX-License-Identifier: MIT
"""The dry-run lens script: the loader's validation, and the scripted
model's turn policy against hand-built turns in the shape the loop sends.
No runner and no subprocess here; the end-to-end dry run has its own
test."""

import json
from decimal import Decimal

import pytest

from atlas_reviewer.coordinator import first_turn
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.lens_loop import (
    AssistantCalls,
    FinalReply,
    ToolCalls,
    ToolRequest,
    ToolResults,
    TurnRequest,
    UserText,
)
from atlas_reviewer.lens_script import (
    LensScriptError,
    LensScriptModel,
    load_lens_script,
)
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.synthesis import MERGE_TARGET_PREFIX
from atlas_reviewer.tests.helpers import FIXTURE, HEAD

EVENT = PrEvent("example-org/example-app", 42, HEAD)
DIFF = (FIXTURE / "pull.diff").read_text(encoding="utf-8")
NONCE = "f00dfeedf00dfeed"
LENS = "tracing-correctness-and-invariants"
DIGEST = "a" * 64
BLOCKER = FIXTURE / "scenarios" / "blocker.json"


def script(tmp_path, raw):
    path = tmp_path / "script.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_lens_script(path)


def system():
    return f"=== lens body begins: {LENS} (sha256 {DIGEST}) ==="


def base_message():
    return UserText(first_turn(EVENT, DIFF, (), NONCE))


def result_line(tool, args_json, status="ok", page=None):
    tail = f"; next page at offset {page}" if page is not None else ""
    return (
        f'<untrusted-data id="{NONCE}" label="tool-result">\n'
        f"{tool} {args_json}: {status}{tail}\n"
        "content\n"
        f'</untrusted-data id="{NONCE}">'
    )


def diff_turn(calls_only=False):
    """The conversation the loop leaves after the first diff turn: the
    first turn, the model's two `diff_file` calls, and their results."""
    calls = AssistantCalls(
        (
            ToolRequest("diff_file", {"path": "calc.py", "offset": 0}),
            ToolRequest("diff_file", {"path": "settings.ini", "offset": 0}),
        )
    )
    if calls_only:
        return calls
    results = ToolResults(
        (
            result_line("diff_file", '{"offset": 0, "path": "calc.py"}'),
            result_line("diff_file", '{"offset": 0, "path": "settings.ini"}'),
        )
    )
    return calls, results


def request_with(*messages):
    return TurnRequest(system(), messages, ())


def test_the_shipped_default_scenario_loads_and_names_a_blocker():
    loaded = load_lens_script(BLOCKER)
    (finding,) = loaded.findings_for("tracing-correctness-and-invariants")
    assert finding["severity"] == "blocker"
    assert finding["location"] == "calc.py:4"
    assert loaded.unread == frozenset()


def test_an_unknown_top_level_key_is_refused(tmp_path):
    with pytest.raises(
        LensScriptError,
        match=(
            "keys outside findings, unread, reassessment, carryforward, decisions and merge"
        ),
    ):
        script(tmp_path, {"findings": {}, "unread": [], "depth": 2})


def test_findings_must_be_an_object_of_lists(tmp_path):
    with pytest.raises(LensScriptError, match="findings must be an object"):
        script(tmp_path, {"findings": []})
    with pytest.raises(LensScriptError, match="list of finding objects"):
        script(tmp_path, {"findings": {"lens": "not a list"}})


def test_a_finding_must_be_an_object_of_strings(tmp_path):
    with pytest.raises(LensScriptError, match="object of strings"):
        script(tmp_path, {"findings": {"lens": [{"severity": 3}]}})


def test_a_finding_outside_the_contract_is_refused_at_load(tmp_path):
    with pytest.raises(LensScriptError, match="finding 1 for 'lens'"):
        script(tmp_path, {"findings": {"lens": [{"location": "calc.py:1"}]}})


def test_an_unknown_severity_loads_because_dropping_it_is_a_scenario(tmp_path):
    loaded = script(
        tmp_path,
        {
            "findings": {
                "lens": [
                    {
                        "location": "calc.py:1",
                        "severity": "severe",
                        "valence": "defect",
                        "route": "eng",
                        "attribution": "introduced",
                        "finding": "f",
                        "fix": "x",
                        "evidence": "gross = price_cents * quantity",
                    }
                ]
            }
        },
    )
    (finding,) = loaded.findings_for("lens")
    assert finding["severity"] == "severe"


def test_unread_must_be_a_list_of_paths(tmp_path):
    with pytest.raises(LensScriptError, match="unread must be a list"):
        script(tmp_path, {"unread": "calc.py"})
    with pytest.raises(LensScriptError, match="unread must be a list"):
        script(tmp_path, {"unread": [1]})


def test_a_missing_script_file_is_refused(tmp_path):
    with pytest.raises(LensScriptError, match="cannot read lens script"):
        load_lens_script(tmp_path / "absent.json")


def test_the_first_turn_diffs_every_listed_file():
    model = LensScriptModel(load_lens_script(BLOCKER))
    turn = model.turn(request_with(base_message()))
    assert isinstance(turn, ToolCalls)
    assert [(c.tool, dict(c.args)) for c in turn.calls] == [
        ("diff_file", {"path": "calc.py", "offset": 0}),
        ("diff_file", {"path": "settings.ini", "offset": 0}),
    ]


def test_an_unread_file_is_never_diffed(tmp_path):
    loaded = script(tmp_path, {"findings": {}, "unread": ["settings.ini"]})
    model = LensScriptModel(loaded)
    turn = model.turn(request_with(base_message()))
    assert [(c.tool, dict(c.args)) for c in turn.calls] == [
        ("diff_file", {"path": "calc.py", "offset": 0}),
    ]


def test_the_next_page_is_requested_while_a_page_was_cut():
    model = LensScriptModel(load_lens_script(BLOCKER))
    model.turn(request_with(base_message()))
    calls, _results = diff_turn()
    results = ToolResults(
        (
            result_line("diff_file", '{"offset": 0, "path": "calc.py"}', page=393),
            result_line("diff_file", '{"offset": 0, "path": "settings.ini"}'),
        )
    )
    turn = model.turn(request_with(base_message(), calls, results))
    assert [(c.tool, dict(c.args)) for c in turn.calls] == [
        ("diff_file", {"path": "calc.py", "offset": 393}),
    ]


def test_a_completed_read_goes_to_the_cited_head_file_then_the_final_reply():
    model = LensScriptModel(load_lens_script(BLOCKER))
    calls, results = diff_turn()
    turn = model.turn(request_with(base_message(), calls, results))
    assert [(c.tool, dict(c.args)) for c in turn.calls] == [
        ("read_file", {"path": "calc.py"}),
    ]
    read = AssistantCalls((ToolRequest("read_file", {"path": "calc.py"}),))
    reads = ToolResults(
        (
            result_line(
                "read_file",
                '{"end": 400, "path": "calc.py", "rev": "HEAD", "start": 1}',
            ),
        )
    )
    final = model.turn(request_with(base_message(), calls, results, read, reads))
    assert isinstance(final, FinalReply)
    reply = json.loads(final.text)
    assert reply["lens"] == LENS
    assert reply["body_sha256"] == DIGEST
    assert [f["severity"] for f in reply["findings"]] == ["blocker"]


def test_a_failed_diff_call_stops_its_file_instead_of_looping():
    model = LensScriptModel(load_lens_script(BLOCKER))
    calls, _ok = diff_turn()
    results = ToolResults(
        (
            result_line(
                "diff_file", '{"offset": 0, "path": "calc.py"}', status="timed out"
            ),
            result_line("diff_file", '{"offset": 0, "path": "settings.ini"}'),
        )
    )
    turn = model.turn(request_with(base_message(), calls, results))
    # The timed-out file is not asked again; the next turn is the cited
    # head file, and the attempt then ends with the tool gap recorded.
    assert [(c.tool, dict(c.args)) for c in turn.calls] == [
        ("read_file", {"path": "calc.py"}),
    ]


def test_a_lens_with_no_findings_finalizes_after_the_diff():
    loaded = load_lens_script(FIXTURE / "scenarios" / "approve.json")
    model = LensScriptModel(loaded)
    calls, results = diff_turn()
    final = model.turn(request_with(base_message(), calls, results))
    assert isinstance(final, FinalReply)
    assert json.loads(final.text)["findings"] == []


def test_a_nudge_turn_finalizes_with_what_the_script_says():
    model = LensScriptModel(load_lens_script(BLOCKER))
    calls, results = diff_turn()
    nudge = UserText("Your reply is not accepted as a final review: you have not read")
    final = model.turn(request_with(base_message(), calls, results, nudge))
    assert isinstance(final, FinalReply)
    assert json.loads(final.text)["findings"]


def test_a_retry_attempt_starts_its_coverage_over():
    """A retry reuses the model instance; its state from the failed attempt
    must not make the retry answer from memory."""
    model = LensScriptModel(load_lens_script(BLOCKER))
    calls, results = diff_turn()
    model.turn(request_with(base_message(), calls, results))
    replayed = model.turn(request_with(base_message()))
    assert isinstance(replayed, ToolCalls)


def test_a_missing_body_marker_is_refused():
    model = LensScriptModel(load_lens_script(BLOCKER))
    with pytest.raises(BoundaryError, match="body markers are missing"):
        model.turn(TurnRequest("no markers here", (UserText("x"),), ()))


def test_a_missing_changed_file_list_is_refused():
    model = LensScriptModel(load_lens_script(BLOCKER))
    with pytest.raises(BoundaryError, match="changed-file list is missing"):
        model.turn(TurnRequest(system(), (UserText("no listing"),), ()))


def test_every_turn_costs_the_same_small_worst_case():
    model = LensScriptModel(load_lens_script(BLOCKER))
    assert model.worst_case_usd(request_with(base_message())) == Decimal("0.01")


# ------------------------------------------------- D73: the reassessment turn


def reassess_message():
    return UserText(
        "Re-assessment target (from the controller): example-org/example-app#42 at "
        + HEAD
        + "\n\nprior findings follow"
    )


def test_the_merge_section_loads_and_validates_its_entries(tmp_path):
    loaded = script(
        tmp_path,
        {
            "findings": {},
            "unread": [],
            "merge": {
                "clusters": [{"ids": ["L1-F1", "L2-F1"], "reason": "one defect"}],
                "dispositions": [
                    {
                        "id": "L3-F1",
                        "action": "downgrade",
                        "severity": "nit",
                        "reason": "cosmetic",
                    },
                    {"id": "L4-F1", "action": "drop", "reason": "the quote is wrong"},
                ],
            },
        },
    )
    (cluster,) = loaded.merge.clusters
    assert cluster["ids"] == ["L1-F1", "L2-F1"]
    downgrade, drop = loaded.merge.dispositions
    assert downgrade["severity"] == "nit"
    assert drop["action"] == "drop"


@pytest.mark.parametrize(
    "raw",
    [
        {"clusters": [{"ids": ["L1-F1"], "reason": "alone"}]},
        {"clusters": [{"ids": ["L1-F1", "L9-F9"], "reason": ""}]},
        {"dispositions": [{"id": "L1-F1", "action": "keep", "reason": "no"}]},
        {
            "dispositions": [
                {
                    "id": "L1-F1",
                    "action": "downgrade",
                    "severity": "huge",
                    "reason": "r",
                }
            ]
        },
        {"extra": {}},
    ],
    ids=[
        "lone-cluster",
        "blank-reason",
        "unknown-action",
        "bad-severity",
        "unknown-key",
    ],
)
def test_a_malformed_merge_entry_is_refused_at_load(tmp_path, raw):
    with pytest.raises(LensScriptError):
        script(tmp_path, {"findings": {}, "unread": [], "merge": raw})


def test_the_merge_turn_is_answered_from_the_scenario(tmp_path):
    """The merge/verify turn opens with the controller's merge subject and
    offers no tools; the scripted reviewer answers it with the scenario's
    merge reply, not with a tool call -- and an ordinary first turn still
    starts the coverage walk (the mutant that answers every no-schema
    turn as a merge fails the second half)."""
    loaded = script(
        tmp_path,
        {
            "findings": {LENS: []},
            "unread": [],
            "merge": {
                "dispositions": [
                    {"id": "L1-F1", "action": "drop", "reason": "the quote is wrong"}
                ]
            },
        },
    )
    model = LensScriptModel(loaded)
    reply = model.turn(
        TurnRequest(
            "the merge call's system prompt", (UserText(MERGE_TARGET_PREFIX + "x"),), ()
        )
    )
    payload = json.loads(reply.text)
    assert payload["dispositions"] == [
        {"id": "L1-F1", "action": "drop", "reason": "the quote is wrong"}
    ]
    assert payload["clusters"] == []
    walk = model.turn(TurnRequest(system(), (base_message(),), ()))
    # An ordinary first turn is still a lens run: the coverage walk, not
    # another merge reply.
    assert isinstance(walk, ToolCalls)
    assert walk.calls[0].tool == "diff_file"


def test_the_reassessment_section_loads_and_validates_its_entries(tmp_path):
    loaded = script(
        tmp_path,
        {
            "findings": {},
            "unread": [],
            "reassessment": {
                "findings": {
                    LENS: [
                        {
                            "location": "calc.py:4",
                            "evidence": "discount = round(gross * discount_pct / 100)",
                            "severity": "blocker",
                            "valence": "defect",
                            "route": "eng",
                            "attribution": "introduced",
                            "finding": "the CI run confirms the drift",
                            "fix": "sum first, then round once",
                            "revises": "P1",
                            "reason": "the newer run failed",
                        }
                    ]
                },
                "withdrawn": {LENS: [{"id": "P2", "reason": "the check passes"}]},
            },
        },
    )
    (finding,) = loaded.reassessment_for(LENS)
    assert finding["revises"] == "P1"
    (withdrawn,) = loaded.withdrawn_for(LENS)
    assert withdrawn == {"id": "P2", "reason": "the check passes"}


@pytest.mark.parametrize(
    "raw",
    [
        {"findings": {LENS: [{"location": "calc.py:4"}]}},
        {"withdrawn": {LENS: [{"id": "P1"}]}},
        {"withdrawn": {LENS: [{"id": "P1", "reason": ""}]}},
        {"extra": {}},
    ],
    ids=["bad-finding", "no-reason", "blank-reason", "unknown-key"],
)
def test_a_malformed_reassessment_entry_is_refused_at_load(tmp_path, raw):
    with pytest.raises(LensScriptError):
        script(tmp_path, {"findings": {}, "unread": [], "reassessment": raw})


def test_the_reassessment_turn_is_answered_from_the_scenario(tmp_path):
    """The reuse path's turn opens with the controller's re-assessment
    subject and offers no tools; the scripted reviewer answers it with the
    scenario's re-assessment reply, not with a tool call -- and an
    ordinary first turn still starts the coverage walk (the mutant that
    answers every no-schema turn as a re-assessment fails the second
    half)."""
    loaded = script(
        tmp_path,
        {
            "findings": {LENS: []},
            "unread": [],
            "reassessment": {
                "withdrawn": {LENS: [{"id": "P1", "reason": "the check passes"}]}
            },
        },
    )
    model = LensScriptModel(loaded)
    reply = model.turn(TurnRequest(system(), (reassess_message(),), ()))
    payload = json.loads(reply.text)
    assert payload["withdrawn"] == [{"id": "P1", "reason": "the check passes"}]
    assert payload["findings"] == []
    walk = model.turn(request_with(base_message()))
    assert isinstance(walk, ToolCalls)


# ------------------------------------------- #702: the carry-forward turn


def _carry_message():
    from atlas_reviewer.delta import carry_turn
    from atlas_reviewer.prompt import RepoText, UntrustedBlock

    return UserText(
        carry_turn(
            EVENT,
            UntrustedBlock(
                "prior-findings", RepoText("P1 blocker calc.py:4 rounds per line")
            ),
            UntrustedBlock("delta-diff", RepoText("diff --git a/calc.py b/calc.py")),
            NONCE,
        )
    )


def test_the_carryforward_section_loads_and_validates_its_entries(tmp_path):
    loaded = script(
        tmp_path,
        {
            "findings": {},
            "unread": [],
            "carryforward": {
                "findings": [
                    {
                        "location": "calc.py:4",
                        "evidence": "discount = round(gross * discount_pct / 100)",
                        "severity": "blocker",
                        "valence": "defect",
                        "route": "eng",
                        "attribution": "introduced",
                        "finding": "rounds per line, restated",
                        "fix": "round once",
                        "revises": "P1",
                        "reason": "the code is unchanged",
                    }
                ],
                "withdrawn": [
                    {
                        "id": "P2",
                        "reason": "the delta replaced it",
                        "evidence": "old_call(x)",
                    }
                ],
            },
        },
    )
    (finding,) = loaded.carryforward.findings
    assert finding["revises"] == "P1"
    (withdrawn,) = loaded.carryforward.withdrawn
    assert withdrawn == {
        "id": "P2",
        "reason": "the delta replaced it",
        "evidence": "old_call(x)",
    }


@pytest.mark.parametrize(
    "raw",
    [
        {"findings": [{"location": "calc.py:4"}]},
        {"withdrawn": [{"id": "P1"}]},
        {"withdrawn": [{"id": "P1", "reason": "r"}]},
        {"extra": []},
        {"findings": "not a list"},
    ],
    ids=[
        "bad-finding",
        "no-reason",
        "no-evidence",
        "unknown-key",
        "findings-not-a-list",
    ],
)
def test_a_malformed_carryforward_entry_is_refused_at_load(tmp_path, raw):
    with pytest.raises(LensScriptError):
        script(tmp_path, {"findings": {}, "unread": [], "carryforward": raw})


def test_the_carryforward_turn_is_answered_from_the_scenario(tmp_path):
    """The delta review's carry-forward turn (#702) opens with the
    controller's carry-forward subject and offers no tools and no lens
    body markers; the scripted reviewer answers it with the scenario's
    `carryforward` reply -- and an ordinary first turn still starts the
    coverage walk (the mutant that answers every marker-less turn as a
    carry-forward fails the second half)."""
    loaded = script(
        tmp_path,
        {
            "findings": {LENS: []},
            "unread": [],
            "carryforward": {
                "withdrawn": [
                    {
                        "id": "P1",
                        "reason": "the delta replaced it",
                        "evidence": "old_code()",
                    }
                ]
            },
        },
    )
    model = LensScriptModel(loaded)
    reply = model.turn(TurnRequest("no body markers here", (_carry_message(),), ()))
    payload = json.loads(reply.text)
    assert payload["withdrawn"] == [
        {"id": "P1", "reason": "the delta replaced it", "evidence": "old_code()"}
    ]
    assert payload["findings"] == []
    walk = model.turn(request_with(base_message()))
    assert isinstance(walk, ToolCalls)
