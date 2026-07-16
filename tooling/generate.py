# SPDX-License-Identifier: MIT
# tooling/generate.py
"""Backward-compatible re-export surface. The generation logic used to live
entirely in this module; it is now split by concern into generate_common.py
(shared helpers), generate_skill.py, generate_router.py, generate_synthesizer.py,
and generate_collapsed.py, so each concern's edits land in one file instead of
all landing here. Import from those modules directly in new code — this module
exists so `from tooling.generate import X` keeps working for existing callers
(tooling/cli.py, tests/)."""
from __future__ import annotations

from tooling.generate_common import (
    _KIND_TITLE, _TOOLING_PREAMBLE, _escape_table_cell, _scope_line,
    build_reference, modes_section, primary_owners,
)
from tooling.generate_skill import (
    _CROSS_REF_QUOTA, _TOP_CHECKS_BUDGET, _cross_ref_note,
    _team_preferences_note, build_artifact_rubric, build_skill_md,
    generate_skill, top_checks,
)
from tooling.generate_router import build_router_md, generate_router
from tooling.generate_synthesizer import (
    build_synthesizer_md, generate_synthesizer, mode_floor_policy,
)
from tooling.generate_collapsed import (
    CollapsedOverlapError, _checklist_body, _gen_header,
    build_collapsed_synthesis, build_entrypoint_md,
    collapsed_plugin_manifest, entrypoint_lenses, generate_collapsed,
    generate_lens_bundle, lens_bundle_body,
)

__all__ = [
    "CollapsedOverlapError",
    "build_artifact_rubric", "build_collapsed_synthesis", "build_entrypoint_md",
    "build_reference", "build_router_md", "build_skill_md", "build_synthesizer_md",
    "collapsed_plugin_manifest", "entrypoint_lenses", "generate_collapsed",
    "generate_lens_bundle", "generate_router", "generate_skill",
    "generate_synthesizer", "lens_bundle_body", "mode_floor_policy",
    "modes_section", "primary_owners", "top_checks",
]
