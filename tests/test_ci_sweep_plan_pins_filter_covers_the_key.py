# SPDX-License-Identifier: MIT
# tests/test_ci_sweep_plan_pins_filter_covers_the_key.py
"""The sweep-plan anchor pins exist to re-prove the plan against the
parity key's own anchors, so the CI filter gating their job must fire
when the key changes: a re-anchor, a moved span or a new finding is
exactly the event the pins re-prove (the r1b Major on #859 — the filter
omitted the key's fixtures while the pins are skipped inside the sharded
liveness job, so a key-only PR ran no pins under a green gate, and a
re-anchor that unfixed the plan's reach surfaced only on main).

The check is deliberately narrow and mechanical: the two CI filters that
name the key's fixtures — the parity-key `liveness` job's and the pins
job's — must both still list the same fixture glob, and the pins filter
must still name the two modules the pins exercise (`bridge.py` and
`diffs.py`, which the `liveness` filter deliberately does not). Dropping
any of those lines — by drift or by deletion — fails here instead of
silencing the pins on the pull request that needs them."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
KEY_GLOB = "atlas_reviewer/fixtures/parity-key/**"
# The modules the pins exercise and the `liveness` filter deliberately
# does not cover: dropping either from the pins filter reopens the r1b
# gap (a planner regression that skips its own PR's CI).
_PLANNER_PATHS = ("atlas_reviewer/bridge.py", "atlas_reviewer/diffs.py")


def _filters() -> dict:
    """The `changes` job's dorny/paths-filter filter map, parsed out of
    the step's embedded YAML string."""
    ci = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    steps = ci["jobs"]["changes"]["steps"]
    step = next(s for s in steps if "dorny/paths-filter" in str(s.get("uses", "")))
    return yaml.safe_load(step["with"]["filters"])


def test_the_pins_filter_fires_on_a_parity_key_change():
    filters = _filters()
    assert KEY_GLOB in filters["sweep_plan_pins"], (
        "the sweep_plan_pins filter no longer lists the parity key's "
        "fixtures: a re-anchor, a moved span or a new finding then runs "
        "no sweep-plan pins under a green gate"
    )


def test_the_liveness_filter_keeps_covering_the_key():
    filters = _filters()
    assert KEY_GLOB in filters["liveness"], (
        "the liveness filter no longer lists the parity key's fixtures: "
        "the anchor-suite checks the pins do not run would not fire on a "
        "key change"
    )


def test_the_pins_filter_still_names_the_modules_it_exercises():
    filters = _filters()
    for path in _PLANNER_PATHS:
        assert path in filters["sweep_plan_pins"], (
            f"the sweep_plan_pins filter no longer lists {path}: a "
            "sweep_specs or risk_tier regression would skip its own PR's "
            "CI and fail main afterwards"
        )
