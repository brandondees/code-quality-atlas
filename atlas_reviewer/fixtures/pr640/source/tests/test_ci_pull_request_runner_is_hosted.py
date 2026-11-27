# SPDX-License-Identifier: MIT
# tests/test_ci_pull_request_runner_is_hosted.py
"""#471: the `gate` job in .github/workflows/ci.yml used to run
unconditionally on this fleet's persistent self-hosted hardware, gated only
by an in-tree `if:` that a hostile PR could itself edit away. The fix moved
`pull_request`-triggered runs onto a GitHub-hosted runner (`push`/`schedule`
stay self-hosted, since neither can be forged by an untrusted PR branch) --
narrowing the default exposure window even though (per that fix's own
corrected comment) it is not a structural closure of #471 on its own.

Round-1 review (`dees-bot`, Major) on the PR that shipped this fix pointed
out that nothing in this repo's suite would catch a silent revert of that
`runs-on:` line back to an unconditional `[self-hosted, Linux]` -- exactly
this repo's established pattern of adding a regression guard the moment an
infra/security gap is found (`test_ci_shellcheck_glob_covers_tree.py` #379,
`test_ci_python_filter_covers_known_reads.py`,
`test_no_private_repo_names_in_runner_docs.py`). This is that guard.

It asserts the `gate` job's `runs-on` is still the event-conditional
expression, not a bare self-hosted (or bare hosted) label -- catching an
accidental revert either direction, not just the specific string that
shipped. It does NOT (and can't, from a checkout) verify the actual
backstop this fix depends on: the GitHub Settings "Require approval for all
outside collaborators" value, which is not represented in any file in this
repo.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _load_gate_runs_on() -> object:
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    # PyYAML parses the bare word `on:` as the boolean key `True` unless
    # quoted -- this file's `on:` key is unquoted, so `jobs` is the only
    # top-level key safe to index by its literal string name here.
    return workflow["jobs"]["gate"]["runs-on"]


def test_gate_job_exists_with_runs_on():
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    assert "gate" in workflow.get("jobs", {}), (
        f"{CI_YML} no longer defines a `gate` job -- has it been renamed or "
        "restructured? Update this guard's job name either way."
    )


def test_pull_request_runs_are_not_pinned_to_self_hosted():
    runs_on = _load_gate_runs_on()
    # A bare list/string (`[self-hosted, Linux]` or `self-hosted`) means
    # EVERY event -- including `pull_request` -- lands on this fleet's
    # persistent self-hosted hardware again, silently reopening #471's
    # default-exposure gap with zero CI signal.
    assert isinstance(runs_on, str) and "${{" in runs_on, (
        f"gate.runs-on is {runs_on!r} -- expected a GitHub Actions "
        "expression string that varies by github.event_name, not a bare "
        "runner label. A bare self-hosted label here means pull_request "
        "runs land on persistent self-hosted hardware again (#471)."
    )
    assert "github.event_name" in runs_on and "pull_request" in runs_on, (
        f"gate.runs-on ({runs_on!r}) no longer conditions on "
        "github.event_name == 'pull_request' -- #471's pull_request/"
        "push-schedule split has been lost."
    )
    assert "self-hosted" in runs_on, (
        f"gate.runs-on ({runs_on!r}) no longer mentions self-hosted at all "
        "-- push/schedule runs should still land on this fleet's own "
        "hardware, not GitHub-hosted, per the fix's own reasoning."
    )


def test_pull_request_branch_of_the_expression_is_github_hosted():
    runs_on = _load_gate_runs_on()
    # Loose substring check, not an exact-string match: this pins the
    # *shape* (pull_request -> a github.com-hosted label, not self-hosted)
    # without over-fitting to today's specific `ubuntu-latest` choice, which
    # may legitimately change (e.g. a pinned hosted image) without being a
    # regression.
    assert "ubuntu-" in runs_on or "windows-" in runs_on or "macos-" in runs_on, (
        f"gate.runs-on ({runs_on!r}) doesn't appear to route pull_request "
        "events to any recognizable GitHub-hosted runner label -- verify "
        "the expression still sends pull_request runs off self-hosted "
        "hardware (#471)."
    )
