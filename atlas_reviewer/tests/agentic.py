# SPDX-License-Identifier: MIT
"""Shared fixtures for the agentic lens loop and coordinator tests: a small
base/head repository, its diff, one lens body, limits and reply builders.
The bridge runs for real through `LocalSprites`; the model is scripted."""

import json
from decimal import Decimal

from atlas_reviewer.attestation import body_digest
from atlas_reviewer.bridge_staging import SourceTrees
from atlas_reviewer.lens_loop import AgenticLimits, FinalReply, ToolCalls, ToolRequest

from .helpers import HEAD, OLD, fake_token, source_tarball

LENS = "tracing-correctness-and-invariants"
BODY = (
    "# Tracing correctness and invariants\n\n"
    "Trace every branch of the change and check what it claims.\n"
)
DIGEST = body_digest(BODY)
TOKEN = fake_token("ghp_")
TOP = "example-org-example-app-abc1234"
BASE_FILES = {
    "calc.py": b"def total(xs):\n    return sum(xs)\n",
    "docs/notes.md": b"rounding notes\n",
}
HEAD_FILES = {
    **BASE_FILES,
    "calc.py": b"def total(xs):\n    return sum(round(x, 2) for x in xs)\n",
    "config/keys.py": f'TOKEN = "{TOKEN}"\n'.encode(),
}
DIFF = f"""\
diff --git a/calc.py b/calc.py
index 1111111..2222222 100644
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def total(xs):
-    return sum(xs)
+    return sum(round(x, 2) for x in xs)
diff --git a/config/keys.py b/config/keys.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/config/keys.py
@@ -0,0 +1 @@
+TOKEN = "{TOKEN}"
"""
CHANGED = frozenset({"calc.py", "config/keys.py"})
HEAD_TARBALL = source_tarball(HEAD_FILES, TOP)
LIMITS = AgenticLimits(
    reservation_usd=Decimal("1.00"),
    max_calls=20,
    max_turns=6,
    lens_wall_s=300,
    review_wall_s=600,
)
COST = Decimal("0.02")


def trees():
    return SourceTrees(source_tarball(BASE_FILES, TOP), HEAD_TARBALL, OLD, HEAD)


def tools(*calls):
    return ToolCalls(tuple(ToolRequest(t, a) for t, a in calls), COST)


READ_DIFF = tools(("diff_file", {"path": "calc.py"}))


def finding(**overrides):
    base = {
        "location": "calc.py:2",
        "evidence": "return sum(round(x, 2) for x in xs)",
        "severity": "major",
        "valence": "defect",
        "route": "eng",
        "attribution": "introduced",
        "finding": "rounds each item before summing, so totals drift",
        "fix": "sum first, then round once",
    }
    return {**base, **overrides}


def final(*findings, lens=LENS, digest=DIGEST, text=None):
    if text is None:
        text = json.dumps(
            {"lens": lens, "body_sha256": digest, "findings": list(findings)}
        )
    return FinalReply(text, COST)
