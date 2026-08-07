# SPDX-License-Identifier: MIT
# tests/test_doc_counts.py
"""Assert documented skill/lens counts in prose files match the manifest (issue #95)."""
import re
from pathlib import Path

from tooling.manifest import load_manifest

ROOT = Path(__file__).resolve().parent.parent


def _counts() -> dict[str, int]:
    m = load_manifest(str(ROOT / "skills" / "manifest.yaml"))
    composition = ((1 if m.router else 0) + (1 if m.prepass else 0)
                   + (1 if m.synthesizer else 0))
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
        f"{c['total']} (={c['lenses']} lenses + the composition skills: "
        f"router, tool-grounding pre-pass, synthesizer)"
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
    # plugin.json quotes the *lens* count and names the router and synthesizer as
    # additions; marketplace.json quotes the *total*. Both said "N code-review and
    # maintenance skills", so every reviewer who compared the two files read the
    # difference as drift (flagged 5x across PRs #199/#201 by three reviewers).
    # The counts were always right; the shared phrasing was the defect. plugin.json
    # now says "lenses" so the two lines can no longer be misread as the
    # same claim.
    assert _has(plugin, f"{c['lenses']} code-review and maintenance lenses"), (
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
# shape of bug, just a bigger list), sweep every two-digit number that sits on
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
# Any two-digit token not glued to a taxonomy/issue ref ("#38"), another
# digit/letter, or a decimal point on either side (so "2026", "v0.35", "35.2"
# etc. never match). Originally decade-scoped to "3x", which made the sweep go
# blind the moment a count crossed 39 — it caught that crossing once (37 lenses
# / 40 total, when the tool-grounding pre-pass landed) and would have had to
# catch it again at 49. The keyword filter is what keeps this specific enough;
# widening the decade costs nothing (verified: no new false positives across
# _LIVING_COUNT_FILES) and removes a recurring maintenance step.
_CANDIDATE_RE = re.compile(r"(?<![#\w.])[1-9][0-9](?![\w.])")
_KEYWORD_RE = re.compile(r"\b(skills?|lens(?:es)?|zips?|uploads?)\b", re.IGNORECASE)
# "33+" is a threshold phrase ("once past 33"), not a claimed current count.
_THRESHOLD_SUFFIX = "+"
# "27->30" / "27→30" style historical deltas, if they ever appear in a living
# file — skip both sides rather than assert either is "the" current count.
_ARROW_RE = re.compile(r"\d\s*(?:→|->)\s*\d")
# A wrapped sentence puts the count on one line and its noun on the next:
#     "... instead of the 39 standalone
#      skills (skills/)"
# A strictly line-local scan is blind to those, and two such counts in
# docs/distribution.md went stale under it (CodeRabbit review on #206). So a
# candidate also counts when the *next* line carries the keyword -- but only
# when the number sits in the tail of its own line, i.e. the clause plausibly
# continues. Without that anchor the window swallows unrelated numbers from a
# neighbouring sentence: a "2026-06-25" date and a "and 11 more" aside both
# false-positived when the window was widened symmetrically. Looking backward
# is what admitted the second one, so the window is forward-only.
_WRAP_TAIL = 24


def _wrapped_candidates(lines: list[str], i: int) -> list[re.Match]:
    """Candidate numbers on `lines[i]` whose keyword is on this line or, for a
    tail-anchored number, the next one."""
    line = lines[i]
    same = _KEYWORD_RE.search(line)
    following = _KEYWORD_RE.search(lines[i + 1]) if i + 1 < len(lines) else None
    if not (same or following):
        return []
    return [m for m in _CANDIDATE_RE.finditer(line)
            if same or len(line) - m.end() <= _WRAP_TAIL]


def test_living_docs_count_sweep():
    c = _counts()
    # _CANDIDATE_RE only matches *2-digit* tokens. The counts climb steadily
    # (31->32->33/34->35/36->37 lenses), so assert they're still in that range --
    # if a future addition pushes either to 100+, this fails loudly instead of
    # the sweep silently going blind to new drift.
    assert 10 <= c["lenses"] < 100 and 10 <= c["total"] < 100, (
        f"lenses={c['lenses']} total={c['total']} have crossed out of the 2-digit "
        "range _CANDIDATE_RE covers -- widen the regex (and this range) before "
        "relying on the living-docs sweep further"
    )
    valid = {c["lenses"], c["total"]}
    failures: list[str] = []
    for rel in _LIVING_COUNT_FILES:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            lineno = i + 1
            for m in _wrapped_candidates(lines, i):
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
    # A real bare count is still matched -- in any decade, now that the sweep
    # is no longer scoped to "3x".
    assert _CANDIDATE_RE.findall("37 skills") == ["37"]
    assert _CANDIDATE_RE.findall("40 skills") == ["40"]
    # Still not a taxonomy/issue reference.
    assert _CANDIDATE_RE.findall("category #40 lenses") == []


def test_wrap_window_sees_a_count_whose_noun_is_on_the_next_line():
    """The exact shape a line-local scan missed: two stale counts sat in
    docs/distribution.md because "39 standalone" ended the line and "skills"
    began the next. Assert the detector fires on that, not merely that today's
    tree is clean."""
    lines = ["`--collapsed` vendors the 4 collapsed entrypoints instead of the 39 standalone",
             "skills (skills/)."]
    found = [m.group() for m in _wrapped_candidates(lines, 0)]
    assert "39" in found, "a wrapped count is still invisible to the sweep"


def test_wrap_window_does_not_swallow_a_neighbouring_sentence():
    """The anchor that keeps the widened window honest. A number far from the
    end of its line belongs to its own clause, not to the next line's noun —
    a date and a mid-sentence aside both false-positived without this."""
    dated = ["*Status: design approved 2026-06-25, build pending. Resolves **Q20**",
             "(top-level skill count).*"]
    assert [m.group() for m in _wrapped_candidates(dated, 0)] == []
    # Looking *backward* is what admitted "and 11 more" under a lens-bearing
    # line above it; the window is forward-only, so it stays out.
    backward = ["  artifact lens that reviews authored artifacts,",
                "  standard, and 11 more). Each",
                "  leads with a one-line tagline."]
    assert [m.group() for m in _wrapped_candidates(backward, 1)] == []
