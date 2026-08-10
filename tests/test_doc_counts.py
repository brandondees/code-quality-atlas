# SPDX-License-Identifier: MIT
# tests/test_doc_counts.py
"""Assert documented skill/lens counts in prose files match the manifest (issue #95)."""
import re
from pathlib import Path
from typing import NamedTuple

from tooling.manifest import load_manifest

ROOT = Path(__file__).resolve().parent.parent


def _counts() -> dict[str, int]:
    m = load_manifest(str(ROOT / "skills" / "manifest.yaml"))
    composition = ((1 if m.router else 0) + (1 if m.prepass else 0)
                   + (1 if m.synthesizer else 0))
    return {
        "lenses": len(m.skills),
        "diff": sum(1 for s in m.skills if s.shape == "diff"),
        "repo": sum(1 for s in m.skills if s.shape == "repo"),
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
    "docs/review-depth-modes.md",
    "tooling/vendor-skills.sh",
    "tooling/package-account-zips.sh",
    # docs/open-questions.md is otherwise excluded (see above): it mixes
    # dated historical deltas with live-standing answers throughout, so a
    # blanket sweep would false-positive on the former. Included here, but
    # gated per-line by _LIVE_COUNT_MARKER (issue #219) rather than swept in
    # full, so a live claim like Q8's "the ten repo-shaped audits" can opt in
    # without exposing every dated entry to the check.
    "docs/open-questions.md",
)
_MARKER_GATED_FILES = frozenset({"docs/open-questions.md"})
# Placed on its own line immediately above a live-standing count claim in a
# _MARKER_GATED_FILES file, to opt that one claim into the sweep without
# reopening the whole file to false positives from historical prose.
_LIVE_COUNT_MARKER = "<!-- doc-counts:live -->"
# Any two-digit token not glued to a taxonomy/issue ref ("#38"), another
# digit/letter, or a decimal point on either side (so "2026", "v0.35", "35.2"
# etc. never match). Originally decade-scoped to "3x", which made the sweep go
# blind the moment a count crossed 39 — it caught that crossing once (37 lenses
# / 40 total, when the tool-grounding pre-pass landed) and would have had to
# catch it again at 49. The keyword filter is what keeps this specific enough;
# widening the decade costs nothing (verified: no new false positives across
# _LIVING_COUNT_FILES) and removes a recurring maintenance step.
_CANDIDATE_RE = re.compile(r"(?<![#\w.])[1-9][0-9](?![\w.])")
# Spelled-out equivalent (issue #219): "the ten repo-shaped audits" drifted to
# "nine" unnoticed because the guard only ever matched digit tokens. Scoped
# to ten-and-up, mirroring _CANDIDATE_RE's own two-digit-only scope -- a
# single-digit word ("one lens", "two things") is far too common in unrelated
# prose to sweep safely, exactly the noise _CANDIDATE_RE already excludes by
# skipping single digits.
_NUMBER_WORD_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9,
}
_NUMBER_WORD_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_NUMBER_WORD_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}


def _build_number_words() -> dict[str, int]:
    words = dict(_NUMBER_WORD_TEENS)
    for tens_word, tens_val in _NUMBER_WORD_TENS.items():
        words[tens_word] = tens_val
        for ones_word, ones_val in _NUMBER_WORD_ONES.items():
            words[f"{tens_word}-{ones_word}"] = tens_val + ones_val
            words[f"{tens_word} {ones_word}"] = tens_val + ones_val
    return words


_NUMBER_WORDS = _build_number_words()
# Longest-first so an alternation match on a compound ("twenty-five") is
# attempted before its shorter prefix ("twenty") — both are valid standalone
# words, and regex alternation doesn't prefer the longer match on its own.
_WORD_NUM_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_KEYWORD_RE = re.compile(r"\b(skills?|lens(?:es)?|zips?|uploads?|audits?)\b", re.IGNORECASE)
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


class _Candidate(NamedTuple):
    start: int
    end: int
    text: str
    value: int


def _line_candidates(line: str) -> list[_Candidate]:
    """All digit- and word-form number candidates on a single line, sorted
    by position. The two regexes match disjoint token shapes (digits vs.
    letters) so they can't overlap."""
    found = [_Candidate(m.start(), m.end(), m.group(), int(m.group()))
             for m in _CANDIDATE_RE.finditer(line)]
    found += [_Candidate(m.start(), m.end(), m.group(), _NUMBER_WORDS[m.group().lower()])
              for m in _WORD_NUM_RE.finditer(line)]
    return sorted(found, key=lambda c: c.start)


def _wrapped_candidates(lines: list[str], i: int) -> list[_Candidate]:
    """Candidate numbers on `lines[i]` whose keyword is on this line or, for a
    tail-anchored number, the next one."""
    line = lines[i]
    same = _KEYWORD_RE.search(line)
    following = _KEYWORD_RE.search(lines[i + 1]) if i + 1 < len(lines) else None
    if not (same or following):
        return []
    return [c for c in _line_candidates(line)
            if same or len(line) - c.end <= _WRAP_TAIL]


def _line_is_marked_live(lines: list[str], i: int) -> bool:
    """True when `lines[i]` opts into the sweep via _LIVE_COUNT_MARKER,
    either on the line itself or the immediately preceding line (so the
    marker can sit on its own line right above the sentence it flags)."""
    if _LIVE_COUNT_MARKER in lines[i]:
        return True
    return i > 0 and _LIVE_COUNT_MARKER in lines[i - 1]


def test_living_docs_count_sweep():
    c = _counts()
    # _CANDIDATE_RE / _WORD_NUM_RE only match *2-digit* (or two-digit-valued
    # word) tokens. The counts climb steadily (31->32->33/34->35/36->37
    # lenses), so assert they're still in that range -- if a future addition
    # pushes any of them to 100+, this fails loudly instead of the sweep
    # silently going blind to new drift.
    assert 10 <= c["lenses"] < 100 and 10 <= c["total"] < 100 and 10 <= c["repo"] < 100, (
        f"lenses={c['lenses']} total={c['total']} repo={c['repo']} have crossed out "
        "of the 2-digit range _CANDIDATE_RE/_WORD_NUM_RE cover -- widen them (and "
        "this range) before relying on the living-docs sweep further"
    )
    valid = {c["lenses"], c["total"], c["repo"]}
    failures: list[str] = []
    for rel in _LIVING_COUNT_FILES:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        marker_gated = rel in _MARKER_GATED_FILES
        for i, line in enumerate(lines):
            if marker_gated and not _line_is_marked_live(lines, i):
                continue
            lineno = i + 1
            for cand in _wrapped_candidates(lines, i):
                if cand.end < len(line) and line[cand.end] == _THRESHOLD_SUFFIX:
                    continue
                window = line[max(0, cand.start - 4) : min(len(line), cand.end + 4)]
                if _ARROW_RE.search(window):
                    continue
                if cand.value not in valid:
                    failures.append(
                        f"{rel}:{lineno}: {cand.value} ({cand.text!r}) is not a current "
                        f"count {sorted(valid)} (={c['lenses']} lenses / {c['total']} "
                        f"total / {c['repo']} repo-shaped audits) — {line.strip()!r}"
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
    found = [c.text for c in _wrapped_candidates(lines, 0)]
    assert "39" in found, "a wrapped count is still invisible to the sweep"


def test_wrap_window_does_not_swallow_a_neighbouring_sentence():
    """The anchor that keeps the widened window honest. A number far from the
    end of its line belongs to its own clause, not to the next line's noun —
    a date and a mid-sentence aside both false-positived without this."""
    dated = ["*Status: design approved 2026-06-25, build pending. Resolves **Q20**",
             "(top-level skill count).*"]
    assert [c.text for c in _wrapped_candidates(dated, 0)] == []
    # Looking *backward* is what admitted "and 11 more" under a lens-bearing
    # line above it; the window is forward-only, so it stays out.
    backward = ["  artifact lens that reviews authored artifacts,",
                "  standard, and 11 more). Each",
                "  leads with a one-line tagline."]
    assert [c.text for c in _wrapped_candidates(backward, 1)] == []


def test_wrapped_candidates_also_matches_spelled_out_numbers():
    """Issue #219: "the nine repo-shaped audits" drifted to ten unnoticed
    because the sweep only ever matched digit tokens. A spelled-out count
    next to a tracked keyword must be caught the same as a digit one."""
    lines = ["The ten repo-shaped audits are the repo arm of the comprehensive tier."]
    found = [(c.text, c.value) for c in _wrapped_candidates(lines, 0)]
    assert ("ten", 10) in found


def test_wrapped_candidates_matches_hyphenated_and_spaced_compounds():
    lines = ["forty-three lenses ship today, or forty three lenses if you prefer."]
    found = [(c.text, c.value) for c in _wrapped_candidates(lines, 0)]
    assert ("forty-three", 43) in found
    assert ("forty three", 43) in found
    # The compound must win over its "forty" prefix -- not two separate
    # candidates (forty=40 and three=3) that would falsely validate against
    # unrelated current counts.
    assert not any(c.text == "forty" for c in _wrapped_candidates(lines, 0))


def test_wrapped_candidates_ignores_single_digit_number_words():
    """Mirrors _CANDIDATE_RE's own exclusion of single digits: "one lens" /
    "two skills" are far too common in unrelated prose (enumerations,
    examples) to sweep safely without the keyword-adjacency signal alone
    producing constant false positives."""
    lines = ["one lens down, two more skills to go."]
    assert _wrapped_candidates(lines, 0) == []


def test_line_is_marked_live_checks_this_line_and_the_previous_one():
    lines = [
        "unrelated context line",
        _LIVE_COUNT_MARKER,
        "the ten repo-shaped audits are scheduled detectors",
        "a later line with no marker nearby",
    ]
    assert not _line_is_marked_live(lines, 0)
    assert _line_is_marked_live(lines, 1)  # marker on the line itself
    assert _line_is_marked_live(lines, 2)  # marker on the immediately preceding line
    assert not _line_is_marked_live(lines, 3)
