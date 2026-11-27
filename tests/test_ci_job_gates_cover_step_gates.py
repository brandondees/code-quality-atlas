# SPDX-License-Identifier: MIT
# tests/test_ci_job_gates_cover_step_gates.py
"""Every step gate must be reachable from its own job's gate.

The r1 Major on #855: the split `lint` job's first draft gated the whole
job on `python || requirements`, which skipped the job -- and with it the
markdownlint/shellcheck/actionlint steps whose `if:` gates can then never
fire -- on markdown-only, shell-only and workflows-only PRs, exactly the
coverage #339's per-step gating exists to keep (a new workflow file under
`.github/` gets no actionlint at all, since the `python` filter lists only
ci.yml there). The `gate` aggregator counts a skipped job as passing by
design, so the drop reported green rather than red: no CI signal would
have caught it. This is that signal, in the repo's established
`test_ci_*` shape: for every job in ci.yml, every `needs.changes.outputs.*`
name that the job's own `if` or any step's `if` reads must be defined by
the `changes` job, and every output a step reads must also be covered by
its job's gate -- a step whose trigger class the job gate omits is dead on
every run where it would matter, and fails here instead.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"

_OUTPUT_REF = re.compile(r"needs\.changes\.outputs\.(\w+)")


def _load_ci() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))


def test_changes_outputs_exist():
    """Sanity check the other tests here rest on: an empty outputs map would
    make the reachability checks below vacuously pass (and the whole
    split's gating scheme is nonsense without them)."""
    outputs = _load_ci()["jobs"]["changes"].get("outputs") or {}
    assert outputs, (
        "ci.yml's `changes` job defines no outputs -- the downstream jobs "
        "gate on these; update this guard either way."
    )


def test_every_referenced_output_is_defined():
    """A job or step gate naming an output the `changes` job doesn't define
    evaluates empty and reads as 'false' -- a gate that silently never
    opens. (The r1 review's reachability guard, mirrored onto definitions:
    the same rename-drift class, one layer up.)"""
    ci = _load_ci()
    defined = set(ci["jobs"]["changes"].get("outputs") or {})
    dangling = []
    for job_name, job in ci["jobs"].items():
        for name in _OUTPUT_REF.findall(job.get("if", "") or ""):
            if name not in defined:
                dangling.append(f"job {job_name!r}: if reads undefined {name!r}")
        for index, step in enumerate(job.get("steps", []), start=1):
            step_if = step.get("if", "") or ""
            for name in _OUTPUT_REF.findall(step_if):
                if name not in defined:
                    label = step.get("name", f"step {index}")
                    dangling.append(
                        f"job {job_name!r} step {label!r}: if reads undefined {name!r}"
                    )
    assert not dangling, (
        f"ci.yml gates read outputs the `changes` job does not define: "
        f"{dangling} -- a renamed filter key must be updated at every "
        "reader in lockstep"
    )


def test_every_step_gate_is_reachable_from_its_job_gate():
    """The r1 Major's guard: a job-level gate that omits a trigger class one
    of its steps depends on skips the whole job exactly when that step's
    coverage is needed, and the aggregator's skipped-means-passing makes it
    green -- so the shape itself must fail here, not in CI."""
    ci = _load_ci()
    unreachable = []
    for job_name, job in ci["jobs"].items():
        job_outputs = set(_OUTPUT_REF.findall(job.get("if", "") or ""))
        for index, step in enumerate(job.get("steps", []), start=1):
            step_if = step.get("if", "") or ""
            reads = set(_OUTPUT_REF.findall(step_if))
            excess = reads - job_outputs
            if excess:
                label = step.get("name", f"step {index}")
                unreachable.append(
                    f"job {job_name!r} step {label!r} gates on "
                    f"{sorted(excess)} but the job's own if only covers "
                    f"{sorted(job_outputs) or 'nothing'} -- the step can "
                    "never run on a PR that touches only that class"
                )
    assert not unreachable, (
        "ci.yml has steps whose trigger class the job gate omits (the "
        "r1-Major shape: the whole job skips, the step inside never runs, "
        f"and the skipped-means-passing aggregator stays green): "
        f"{unreachable} -- widen the job's if to cover every class its "
        "steps read, or drop the dead step"
    )
