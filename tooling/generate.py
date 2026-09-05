# SPDX-License-Identifier: MIT
# tooling/generate.py
"""Backward-compatible re-export surface. The generation logic used to live
entirely in this module; it is now split by concern into generate_common.py
(shared helpers), generate_skill.py, generate_router.py, generate_synthesizer.py,
and generate_collapsed.py, so each concern's edits land in one file instead of
all landing here. Import from those modules directly in new code — this module
exists so `from tooling.generate import X` keeps working for existing callers
(tooling/cli.py, tests/).

This facade supports *calling* a re-exported name, not *patching* it. A name
like `_escape_table_cell` resolves inside `generate_collapsed`'s own globals
when called from `generate_collapsed.lens_bundle_body`, so `monkeypatch.setattr`
(or any rebind) on `tooling.generate._escape_table_cell` does not reach that
call — patch the defining submodule directly instead, as tests/test_collapsed.py
does for `_checklist_body`, a same-module helper with the identical hazard."""

from __future__ import annotations

from tooling.generate_collapsed import (
    CollapsedOverlapError,
    build_collapsed_synthesis,
    build_entrypoint_md,
    collapsed_plugin_manifest,
    entrypoint_lenses,
    generate_collapsed,
    generate_lens_bundle,
    lens_bundle_body,
)
from tooling.generate_common import (
    _escape_table_cell,  # noqa: F401 -- call-based re-export, see tests/test_generate.py
    build_reference,
    modes_section,
    primary_owners,
)
from tooling.generate_prepass import (
    build_collapsed_prepass,
    build_prepass_md,
    generate_prepass,
)
from tooling.generate_router import build_router_md, generate_router
from tooling.generate_skill import (
    build_artifact_rubric,
    build_skill_md,
    generate_skill,
    heuristics_is_duplicate,
    top_checks,
)
from tooling.generate_synthesizer import (
    build_synthesizer_md,
    generate_synthesizer,
    mode_floor_policy,
)

__all__ = [
    "CollapsedOverlapError",
    "build_artifact_rubric",
    "build_collapsed_prepass",
    "build_collapsed_synthesis",
    "build_entrypoint_md",
    "build_prepass_md",
    "build_reference",
    "build_router_md",
    "build_skill_md",
    "build_synthesizer_md",
    "collapsed_plugin_manifest",
    "entrypoint_lenses",
    "generate_collapsed",
    "generate_lens_bundle",
    "generate_prepass",
    "generate_router",
    "generate_skill",
    "generate_synthesizer",
    "heuristics_is_duplicate",
    "lens_bundle_body",
    "mode_floor_policy",
    "modes_section",
    "primary_owners",
    "top_checks",
]
