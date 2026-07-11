# SPDX-License-Identifier: MIT
# tests/test_doc_counts.py
"""Assert documented skill/lens counts in prose files match the manifest (issue #95)."""
import re
from pathlib import Path

from tooling.manifest import load_manifest

ROOT = Path(__file__).resolve().parent.parent


def _counts() -> dict[str, int]:
    m = load_manifest(str(ROOT / "skills" / "manifest.yaml"))
    composition = (1 if m.router else 0) + (1 if m.synthesizer else 0)
    return {
        "lenses": len(m.skills),
        "diff": sum(1 for s in m.skills if s.shape == "diff"),
        "total": len(m.skills) + composition,
    }


def _has(path: Path, needle: str) -> bool:
    return needle in path.read_text(encoding="utf-8")


def test_skills_dir_matches_manifest():
    dirs = [p for p in (ROOT / "skills").iterdir() if p.is_dir()]
    c = _counts()
    assert len(dirs) == c["total"], (
        f"skills/ has {len(dirs)} directories but the manifest implies "
        f"{c['total']} (={c['lenses']} lenses + router + synthesizer)"
    )


def test_documented_counts_match_manifest():
    c = _counts()
    readme = ROOT / "README.md"
    plugin = ROOT / ".claude-plugin" / "plugin.json"
    market = ROOT / ".claude-plugin" / "marketplace.json"
    dist = ROOT / "docs" / "distribution.md"
    # Match the plain count text, not its markdown presentation — the count is the
    # invariant; bold/heading formatting is incidental and may change.
    assert _has(readme, f"{c['total']} review skills"), "README total skill count is stale"
    assert _has(readme, f"{c['lenses']} review lenses"), "README lens count is stale"
    assert _has(plugin, f"{c['lenses']} code-review and maintenance skills"), (
        "plugin.json lens count is stale"
    )
    assert _has(market, f"{c['total']} code-review and maintenance skills"), (
        "marketplace.json total skill count is stale"
    )
    assert _has(market, f"{c['diff']} diff-shaped review lenses"), (
        "marketplace.json diff-shaped lens count is stale"
    )
    # distribution.md repeats the total in several phrasings (#95 drift originated
    # partly here); guard the stable ones so a count bump can't skip this file.
    assert _has(dist, f"standalone ({c['total']})"), "distribution.md standalone total is stale"
    assert _has(dist, f"Standalone ({c['total']} skills)"), "distribution.md Standalone heading is stale"
    assert _has(dist, f"~{c['total']} total"), "distribution.md upload count is stale"


# --- issue #131: the phrase-allowlist above only reached 4 files, so the count
# grew again (36->37 total) and drifted unnoticed in several other files that
# mention it. Rather than extend the allowlist with more exact phrases (the same
# shape of bug, just a bigger list), sweep every "3x"-shaped number that sits on
# a line mentioning skills/lenses/zips/uploads across the suite's *living*
# (current-state) docs and scripts, and require it to be a real current count.
# A new sentence added to one of these files is covered automatically -- no
# allowlist entry to remember.
#
# Scope is deliberately these "living" files, not every tracked .md/.sh: files
# like docs/session-log.md, docs/research/**, docs/map-gaps.md, docs/plans/**,
# and the dated per-entry history in docs/open-questions.md are narrative logs
# that intentionally freeze *past* counts at the time they were written (e.g.
# "README 31->32 lenses / 33->34 total") -- sweeping those would false-positive
# on correct historical prose, not catch drift.
_LIVING_COUNT_FILES = (
    "README.md",
    "docs/distribution.md",
    "docs/install.md",
    "docs/collapsed-entrypoints-and-depth-modes.md",
    "tooling/vendor-skills.sh",
    "tooling/package-account-zips.sh",
)
# A "3x" token not glued to a taxonomy/issue ref ("#38"), another digit/letter,
# or a decimal point on either side (so "2026", "v0.35", "35.2" etc. never
# match).
_CANDIDATE_RE = re.compile(r"(?<![#\w.])3[0-9](?![\w.])")
_KEYWORD_RE = re.compile(r"\b(skills?|lens(?:es)?|zips?|uploads?)\b", re.IGNORECASE)
# "33+" is a threshold phrase ("once past 33"), not a claimed current count.
_THRESHOLD_SUFFIX = "+"
# "27->30" / "27→30" style historical deltas, if they ever appear in a living
# file — skip both sides rather than assert either is "the" current count.
_ARROW_RE = re.compile(r"\d\s*(?:→|->)\s*\d")


def test_living_docs_count_sweep():
    c = _counts()
    valid = {c["lenses"], c["total"]}
    failures: list[str] = []
    for rel in _LIVING_COUNT_FILES:
        path = ROOT / rel
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not _KEYWORD_RE.search(line):
                continue
            for m in _CANDIDATE_RE.finditer(line):
                start, end = m.span()
                if end < len(line) and line[end] == _THRESHOLD_SUFFIX:
                    continue
                window = line[max(0, start - 4) : min(len(line), end + 4)]
                if _ARROW_RE.search(window):
                    continue
                n = int(m.group())
                if n not in valid:
                    failures.append(
                        f"{rel}:{lineno}: {n} is not a current count {sorted(valid)} "
                        f"(={c['lenses']} lenses / {c['total']} total) — {line.strip()!r}"
                    )
    assert not failures, "stale skill/lens count(s) found by the living-docs sweep:\n" + "\n".join(
        failures
    )


def test_candidate_re_ignores_decimal_versions():
    # Regression: (?<![#\w]) alone doesn't exclude a preceding "." (a decimal
    # point is neither a word char nor "#"), so "v0.35" / "35.2"-style version
    # numbers next to a keyword would previously be misread as a claimed
    # current count. Both sides of the decimal point must be excluded.
    assert _CANDIDATE_RE.findall("v0.35 skills released") == []
    assert _CANDIDATE_RE.findall("35.2 lenses") == []
    # A real bare count is still matched.
    assert _CANDIDATE_RE.findall("37 skills") == ["37"]
