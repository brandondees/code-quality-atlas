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
# Split so a candidate's *category* -- which current count it must equal --
# can be pinned down, not just "is some tracked keyword nearby" (issue #219
# follow-up, CodeRabbit finding on PR #220): "skill"-category claims validate
# against the lens/total set (the sweep's original, deliberately loose
# either-is-fine posture for those two, unchanged); "audit"-category claims
# must equal the repo count specifically, so a repo-shaped-audit sentence
# that accidentally quotes the total or lens count is still caught rather
# than passing because that number happens to be valid for something else.
_SKILL_KEYWORD_RE = re.compile(r"\b(skills?|lens(?:es)?|zips?|uploads?)\b", re.IGNORECASE)
_AUDIT_KEYWORD_RE = re.compile(r"\baudits?\b", re.IGNORECASE)
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
    categories: frozenset[str]  # subset of {"skill", "audit"}


def _keyword_categories(line: str) -> frozenset[str]:
    cats = set()
    if _SKILL_KEYWORD_RE.search(line):
        cats.add("skill")
    if _AUDIT_KEYWORD_RE.search(line):
        cats.add("audit")
    return frozenset(cats)


def _span_distance(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    """Character gap between two non-overlapping spans (0 if they touch or
    overlap, which shouldn't happen for a number and a keyword in practice)."""
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def _nearest_keyword_category(line: str, start: int, end: int) -> frozenset[str]:
    """Category of whichever tracked keyword occurrence is positionally
    *nearest* to a candidate's span on the same line, rather than "any
    tracked keyword present anywhere on the line."

    Round-2 self-review finding on PR #220: a line mentioning both an audit
    and a skill/lens keyword -- exactly `docs/collapsed-entrypoints-and-
    depth-modes.md`'s "diff lenses -> ...; the 10 audits -> ..." line, which
    this fix itself edits -- would otherwise grant every number on that line
    the union of both categories, letting a repo-shaped-audit number quietly
    validate against the lens/total count too (the same false-pass shape
    issue #219 and round 1's finding both targeted, reopened at line
    granularity instead of file granularity)."""
    best_dist: int | None = None
    best_cats: set[str] = set()
    for cat, kw_re in (("skill", _SKILL_KEYWORD_RE), ("audit", _AUDIT_KEYWORD_RE)):
        for m in kw_re.finditer(line):
            dist = _span_distance(start, end, m.start(), m.end())
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_cats = {cat}
            elif dist == best_dist:
                best_cats.add(cat)
    return frozenset(best_cats)


def _line_candidates(
    line: str, fallback_categories: frozenset[str] | None = None
) -> list[_Candidate]:
    """All digit- and word-form number candidates on a single line, sorted
    by position. The two regexes match disjoint token shapes (digits vs.
    letters) so they can't overlap.

    Each candidate is tagged with the nearest tracked keyword's category on
    this same line -- unless `fallback_categories` is given, used for the
    tail-wrap case where the keyword lives on a *different* line entirely
    (the "... the 39 standalone / skills (skills/)" shape), so there's no
    same-line proximity to measure and every candidate on the anchor line
    shares the next line's keyword category(ies) instead.
    """
    def categories_for(start: int, end: int) -> frozenset[str]:
        if fallback_categories is not None:
            return fallback_categories
        return _nearest_keyword_category(line, start, end)

    found = [_Candidate(m.start(), m.end(), m.group(), int(m.group()),
                         categories_for(m.start(), m.end()))
             for m in _CANDIDATE_RE.finditer(line)]
    found += [_Candidate(m.start(), m.end(), m.group(), _NUMBER_WORDS[m.group().lower()],
                          categories_for(m.start(), m.end()))
              for m in _WORD_NUM_RE.finditer(line)]
    return sorted(found, key=lambda c: c.start)


def _wrapped_candidates(lines: list[str], i: int) -> list[_Candidate]:
    """Candidate numbers on `lines[i]` whose keyword is on this line or, for a
    tail-anchored number, the next one. Each candidate carries the keyword
    category (skill vs. audit) of whichever keyword occurrence is nearest to
    it, so a caller can validate it against the matching count rather than
    any tracked count."""
    line = lines[i]
    same = _KEYWORD_RE.search(line)
    following = _KEYWORD_RE.search(lines[i + 1]) if i + 1 < len(lines) else None
    if not (same or following):
        return []
    if same:
        return _line_candidates(line)
    following_cats = _keyword_categories(lines[i + 1])
    return [c for c in _line_candidates(line, fallback_categories=following_cats)
            if len(line) - c.end <= _WRAP_TAIL]


def _line_is_marked_live(lines: list[str], i: int) -> bool:
    """True when `lines[i]` opts into the sweep via _LIVE_COUNT_MARKER,
    either on the line itself or the immediately preceding line (so the
    marker can sit on its own line right above the sentence it flags)."""
    if _LIVE_COUNT_MARKER in lines[i]:
        return True
    return i > 0 and _LIVE_COUNT_MARKER in lines[i - 1]


def _allowed_values(categories: frozenset[str], counts: dict[str, int]) -> set[int]:
    """The set of current counts a candidate is allowed to equal, given
    which keyword category(ies) supplied its match. "skill"-category claims
    (skills/lenses/zips/uploads) keep the sweep's original either-is-fine
    posture against lens/total. "audit"-category claims must equal the repo
    count specifically -- a candidate carrying both categories (a line
    mentioning both, however unlikely) is valid against either set, matching
    the union a same-line reader would allow."""
    allowed: set[int] = set()
    if "skill" in categories:
        allowed |= {counts["lenses"], counts["total"]}
    if "audit" in categories:
        allowed |= {counts["repo"]}
    return allowed


def _candidate_failure(cand: _Candidate, line: str, counts: dict[str, int]) -> str | None:
    """None if `cand` is a valid current count for its category; otherwise a
    failure message. Shared by the full sweep and by direct unit tests, so
    the exact logic that had a bug (CodeRabbit finding on PR #220: every
    candidate validated against one combined {lenses, total, repo} set, so
    an audit claim quoting the lens/total count false-passed) is what gets
    exercised either way."""
    if cand.end < len(line) and line[cand.end] == _THRESHOLD_SUFFIX:
        return None
    window = line[max(0, cand.start - 4) : min(len(line), cand.end + 4)]
    if _ARROW_RE.search(window):
        return None
    allowed = _allowed_values(cand.categories, counts)
    if cand.value in allowed:
        return None
    return (
        f"{cand.value} ({cand.text!r}) is not a current count for "
        f"{sorted(cand.categories)} {sorted(allowed)} (={counts['lenses']} lenses / "
        f"{counts['total']} total / {counts['repo']} repo-shaped audits)"
    )


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
    failures: list[str] = []
    for rel in _LIVING_COUNT_FILES:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        marker_gated = rel in _MARKER_GATED_FILES
        for i, line in enumerate(lines):
            if marker_gated and not _line_is_marked_live(lines, i):
                continue
            lineno = i + 1
            for cand in _wrapped_candidates(lines, i):
                msg = _candidate_failure(cand, line, c)
                if msg:
                    failures.append(f"{rel}:{lineno}: {msg} — {line.strip()!r}")
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


def test_wrapped_candidates_tags_audit_and_skill_claims_with_distinct_categories():
    """CodeRabbit finding on PR #220: an earlier version of the sweep
    validated every candidate against one combined {lenses, total, repo}
    set, so a repo-shaped-audit claim quoting the (wrong) lens/total count
    would have false-passed just because that number happened to be valid
    for something else. Candidates must carry which count they're actually
    claiming, not just "some tracked count or other"."""
    audit_line = ["The ten repo-shaped audits are the repo arm of the comprehensive tier."]
    (audit_cand,) = [c for c in _wrapped_candidates(audit_line, 0) if c.text == "ten"]
    assert audit_cand.categories == frozenset({"audit"})

    skill_line = ["This suite ships 40 lenses across the taxonomy."]
    (skill_cand,) = [c for c in _wrapped_candidates(skill_line, 0) if c.text == "40"]
    assert skill_cand.categories == frozenset({"skill"})


def test_wrapped_candidates_uses_nearest_keyword_on_a_mixed_keyword_line():
    """Round-2 self-review finding on PR #220: the exact line this fix
    itself edits mentions both a skill keyword ("lenses") and an audit
    keyword ("audits") in one sentence. Per-line (rather than per-candidate-
    proximity) category tagging would grant every number on the line the
    union of both categories, reopening the false-pass the fix exists to
    close -- a mismatched audit count would validate fine as long as it
    happened to equal the (unrelated, much farther away) lens/total count.
    Each number must instead be tagged by whichever keyword occurrence sits
    closest to it."""
    line = ["fields: diff lenses -> `reviewing-a-change`; the 10 audits -> `auditing-a-repository`;"]
    (lens_adjacent,) = [c for c in _wrapped_candidates(line, 0) if c.text == "10"]
    assert lens_adjacent.categories == frozenset({"audit"})

    # Same shape, numbers swapped, to prove it's proximity-driven and not
    # positional (e.g. "always the second number is the audit one").
    swapped = ["fields: diff 40 lenses -> `reviewing-a-change`; the audits -> `auditing-a-repository`;"]
    (near_lenses,) = [c for c in _wrapped_candidates(swapped, 0) if c.text == "40"]
    assert near_lenses.categories == frozenset({"skill"})


def test_candidate_failure_rejects_an_audit_claim_using_the_lens_or_total_count():
    """CodeRabbit finding on PR #220, reproduced directly against
    _candidate_failure -- the exact function the full sweep calls per
    candidate. Before the category split, every candidate validated against
    one combined {lenses, total, repo} set, so a repo-shaped-audit sentence
    quoting the (wrong) lens/total count would have false-passed just
    because that number happened to be valid for something else."""
    counts = {"lenses": 40, "total": 43, "repo": 10}
    line = "The 40 repo-shaped audits are the repo arm of the comprehensive tier."
    (cand,) = [c for c in _wrapped_candidates([line], 0) if c.value == 40]
    assert "audit" in cand.categories
    msg = _candidate_failure(cand, line, counts)
    assert msg is not None, "an audit claim quoting the lens count must be flagged"
    assert "40" in msg and "[10]" in msg


def test_candidate_failure_accepts_an_audit_claim_using_the_repo_count():
    counts = {"lenses": 40, "total": 43, "repo": 10}
    line = "The ten repo-shaped audits are the repo arm of the comprehensive tier."
    (cand,) = [c for c in _wrapped_candidates([line], 0) if c.text == "ten"]
    assert _candidate_failure(cand, line, counts) is None


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
