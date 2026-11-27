# SPDX-License-Identifier: MIT
# conftest.py
"""Empty on purpose: its only job is to sit at the repo root so pytest's
rootdir/import-mode auto-detection anchors here regardless of the directory
pytest is invoked from, letting `tests/*.py` do `from tooling import ...`
without a src-layout or installed package. Most test modules additionally
anchor their own on-disk fixture/fixture-tree paths with their own
`ROOT = Path(__file__).resolve().parent.parent` rather than relying on this
file to fix the process's current working directory, which it does not do
(see #390 for the CWD-dependent modules that lacked their own anchor)."""
