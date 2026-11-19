# SPDX-License-Identifier: MIT
"""Split a unified diff into files, rank them by risk, and pack them into
parts that each fit one model call. Pure.

Selection is risk-first, not diff-order-first: when the whole diff cannot
be reviewed within the call cap, what goes unseen is the lowest-risk
material (tests, fixtures, docs); unseen files are named in risk order up
to the caller's limit, and the rest are counted. CI
workflows, dependency manifests and lockfiles rank just below security
code: they are where a change reaches the build, its secrets and its
supply chain.

Only `diff --git` sections are split out. A combined diff (`diff --cc` or
`diff --combined`, as git prints for a merge commit) is not parsed: its
text stays in the preceding file's section, or in the unparsed pseudo-file
when it comes first, so it is still sent and counted, but under that name
and tier rather than its own.

The reviewed repo's merge-base `REVIEW.md` can re-rank this order
(config slice S5, D81 Q6): `rank_files` applies the parse module's
`PathRanks` -- include patterns rank their matches ahead of the rest,
exclude patterns and the `review_generated_files: deprioritize` setting
rank their matches last -- and `rerank_note` is the note the draft
carries. Ordering and depth only, never exclusion: no pattern removes a
file from the set, every file stays accounted for (sent, cut, or named
unseen exactly as before), and whether anything may be excluded from
review at all stays Q25's undecided question.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from functools import reduce

from atlas_reviewer.notes import quote_untrusted

_QUOTED = r'"{side}/(?P<q{name}>(?:[^"\\\n]|\\.)*)"'
_HEADER = re.compile(
    r"^diff --git (?:"
    + _QUOTED.format(side="a", name="old")
    + r"|a/(?P<old>.+?)) (?:"
    + _QUOTED.format(side="b", name="new")
    + r"|b/(?P<new>.+))$",
    re.MULTILINE,
)
_HUNK_START = re.compile(r"^(?:@@ |Binary files |GIT binary patch)", re.MULTILINE)
_C_ESCAPE = re.compile(r"\\([0-7]{3}|.)")
_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13}
UNPARSED_PATH = "(diff text without file headers)"
MAX_FIT_ROUNDS = 8
CUT_MARKER = "\n[... file diff cut by atlas_reviewer to fit one model call ...]\n"


@dataclass(frozen=True)
class RiskTier:
    rank: int
    label: str
    pattern: str


SECURITY = RiskTier(
    0,
    "security, auth, secrets and redaction",
    r"secur|auth(?!or)|redact|secret|token|credential|crypt|permission|polic|"
    r"sanitiz|escap|\bkeys?\b|_key",
)
SUPPLY_CHAIN = RiskTier(
    1,
    "CI workflows, dependency manifests, lockfiles and build hooks",
    r"(^|/)\.github/(workflows|actions)/|(^|/)action\.ya?ml$|(^|/)\.gitlab-ci\.ya?ml$|"
    r"(^|/)\.circleci/|(^|/)Jenkinsfile$|(^|/)\.github/dependabot\.ya?ml$|"
    r"(^|/)requirements[^/]*\.(txt|in)$|(^|/)constraints[^/]*\.txt$|"
    r"(^|/)(pyproject\.toml|setup\.py|setup\.cfg|Pipfile|package\.json|go\.mod|"
    r"go\.sum|Cargo\.toml|Gemfile|composer\.json|pom\.xml|build\.gradle(\.kts)?)$|"
    r"\.gemspec$|\.lock(file)?$|(^|/)(package-lock|npm-shrinkwrap)\.json$|"
    r"(^|/)pnpm-lock\.ya?ml$|(^|/)(Dockerfile|Makefile)[^/]*$|(^|/)conftest\.py$",
)
BOUNDARY = RiskTier(
    2,
    "runner, sandbox, HTTP and model boundary",
    r"runner|sandbox|sprite|exec|http|transport|client|_api\b|api\.|network|"
    r"request|fetch|download|upload|webhook|ledger|openrouter|provider|prompt|llm",
)
SOURCE = RiskTier(3, "other code", r"")
CONFIG = RiskTier(4, "other config", r"(^|/)\.github/|\.ya?ml$|\.toml$|\.cfg$|\.ini$")
TESTS = RiskTier(
    5,
    "tests and fixtures",
    r"(^|/)(tests?|spec|__tests__|fixtures?)/|(^|/)test_[^/]*$|_test\.[a-z]+$|"
    r"\.(test|spec)\.[a-z]+$",
)
DOCS = RiskTier(6, "docs", r"\.(md|rst|txt|adoc)$|(^|/)docs?/|(^|/)(LICENSE|NOTICE)")
RISK_TIERS = (SECURITY, SUPPLY_CHAIN, BOUNDARY, SOURCE, CONFIG, TESTS, DOCS)
# Precedence differs from rank: tests/test_redact.py is a test, and
# docs/security.md is a doc, whatever their names suggest. CI, dependency
# and build files are matched first, so no directory a PR author picks
# (`tests/`, `docs/`, `fixtures/`) can demote them. Security is matched
# before config, so config/secrets.yaml is not ranked as other config.
_MATCH_ORDER = (SUPPLY_CHAIN, TESTS, DOCS, SECURITY, CONFIG, BOUNDARY)


def risk_tier(path: str) -> RiskTier:
    return next(
        (t for t in _MATCH_ORDER if re.search(t.pattern, path, re.IGNORECASE)),
        SOURCE,
    )


@dataclass(frozen=True)
class FileDiff:
    """`text` is what a model call gets; `full_chars` is the file's whole
    diff length, so `text` shorter than that means the file was cut."""

    path: str
    text: str
    full_chars: int
    tier: RiskTier

    @property
    def cut(self) -> bool:
        return len(self.text) < self.full_chars

    @property
    def shown_chars(self) -> int:
        return len(self.text) - len(CUT_MARKER) if self.cut else len(self.text)


@dataclass(frozen=True)
class DiffPart:
    files: tuple[FileDiff, ...]

    @property
    def chars(self) -> int:
        return sum(len(f.text) for f in self.files)

    @property
    def text(self) -> str:
        return "".join(f.text for f in self.files)


@dataclass(frozen=True)
class DiffSelection:
    total_files: int
    total_chars: int
    parts: tuple[DiffPart, ...]
    unseen: tuple[FileDiff, ...]
    part_chars: int = 0

    @property
    def cut(self) -> tuple[FileDiff, ...]:
        return tuple(f for p in self.parts for f in p.files if f.cut)

    @property
    def full(self) -> tuple[FileDiff, ...]:
        return tuple(f for p in self.parts for f in p.files if not f.cut)

    @property
    def kept_chars(self) -> int:
        return sum(p.chars for p in self.parts)

    @property
    def complete(self) -> bool:
        return not self.unseen and not self.cut


def diff_paths(diff: str) -> tuple[str, ...]:
    """New-side path of every file in the diff, in order."""
    return tuple(f.path for f in _sections(diff))


def scope_text(diff: str, paths: Iterable[str]) -> str:
    """The diff text of exactly the named paths, in diff order: the
    material a shared diff prefix for that scope fences (D65). Naming
    every section's path gives back the whole diff, because the sections
    concatenate to it."""
    wanted = frozenset(paths)
    return "".join(f.text for f in split_files(diff) if f.path in wanted)


def _sections(diff: str) -> list[FileDiff]:
    headers = list(_HEADER.finditer(diff))
    ends = [h.start() for h in headers[1:]] + [len(diff)] * bool(headers)
    return [
        _file(_section_path(h, text), text, _source_path(text))
        for h, end in zip(headers, ends, strict=True)
        for text in (diff[h.start() : end],)
    ]


def _meta_lines(text: str) -> list[str]:
    """The extended header lines: after `diff --git`, before the first hunk."""
    hunk = _HUNK_START.search(text)
    return text[: hunk.start() if hunk else len(text)].split("\n")[1:]


def _source_path(text: str) -> str | None:
    """The old path of a rename or copy, which is ranked as well as the new one."""
    lines = _meta_lines(text)
    renamed = _field(lines, "rename from ")
    return _field(lines, "copy from ") if renamed is None else renamed


def _section_path(header: re.Match[str], text: str) -> str:
    """The `diff --git` line is ambiguous when an unquoted path holds " b/",
    so the path comes from the `+++` line, else `rename to` or `copy to`,
    else a header whose two sides are equal (always so for a deletion, whose
    `+++` line is /dev/null), and only then from splitting the header. Only
    lines before the first hunk are read."""
    lines = _meta_lines(text)
    new = _field(lines, "+++ ")
    if new is not None and new != "/dev/null":
        return new.removeprefix("b/")
    moved = _field(lines, "rename to ")
    moved = _field(lines, "copy to ") if moved is None else moved
    if moved is not None:
        return moved
    sides = header.group(0).removeprefix("diff --git ")
    half = (len(sides) - 5) // 2
    if sides == f"a/{sides[2 : 2 + half]} b/{sides[2 : 2 + half]}":
        return sides[2 : 2 + half]
    quoted = header.group("qnew")
    return header.group("new") if quoted is None else _unquote(quoted)


def _field(lines: list[str], key: str) -> str | None:
    """git appends a tab to a `---`/`+++` name holding a space."""
    value = next((s[len(key) :] for s in lines if s.startswith(key)), None)
    if value is None:
        return None
    value = value.removesuffix("\t")
    quoted = len(value) >= 2 and value[0] == value[-1] == '"'
    return _unquote(value[1:-1]) if quoted else value


def _unquote(quoted: str) -> str:
    """Git C-quotes a path holding a tab, newline, quote, backslash or (by
    default) a non-ASCII byte; octal escapes are UTF-8 bytes."""
    raw = bytearray()
    pos = 0
    for esc in _C_ESCAPE.finditer(quoted):
        raw += quoted[pos : esc.start()].encode()
        code = esc.group(1)
        if len(code) == 3:
            raw.append(int(code, 8) & 0xFF)
        else:
            raw += bytes([_C_ESCAPES[code]]) if code in _C_ESCAPES else code.encode()
        pos = esc.end()
    raw += quoted[pos:].encode()
    return raw.decode("utf-8", errors="replace")


def split_files(diff: str) -> tuple[FileDiff, ...]:
    """Every file section in diff order. Text before the first header (or a
    diff with no headers at all) becomes one pseudo-file, so no input
    character is silently dropped."""
    first = _HEADER.search(diff)
    files = _sections(diff)
    preamble = diff[: first.start()] if first else diff
    return tuple([_file(UNPARSED_PATH, preamble)] * bool(preamble.strip()) + files)


def _file(path: str, text: str, source: str | None = None) -> FileDiff:
    """A rename or copy is as risky as the riskier of its two paths: moving
    src/auth.py to docs/changelog.md still changes auth code."""
    tiers = [risk_tier(p) for p in (path, source) if p is not None]
    return FileDiff(path, text, len(text), min(tiers, key=lambda t: t.rank))


def by_risk(files: tuple[FileDiff, ...]) -> tuple[FileDiff, ...]:
    """Highest risk first; diff order within a tier."""
    return tuple(sorted(files, key=lambda f: f.tier.rank))


@dataclass(frozen=True)
class PathRanks:
    """The reviewed repo's path-ranking settings (config slice S5, D81
    Q6), parsed by `repo_config` and applied here. Ordering only, never
    exclusion (Q25's undecided question, untouched): `include` patterns
    rank their matches ahead of the rest, `exclude` patterns rank their
    matches last, and `generated` deprioritizes the paths that look
    machine-generated. Exclude wins over include and an explicit include
    wins over the generated heuristic -- the repo named it -- so every
    file lands in exactly one group."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    generated: bool = False

    @property
    def applies(self) -> bool:
        """Whether any key is set: an absent or all-default read re-ranks
        nothing and is recorded nowhere."""
        return bool(self.include or self.exclude or self.generated)


# The path shapes the `review_generated_files: deprioritize` setting ranks
# last (S5): build and tool output, vendored and dependency trees,
# lockfiles, and the common machine-generated-code suffixes. A heuristic
# over paths only -- nothing in a file's content is read -- so it is
# cheap, deterministic, and wrong about at least one repo; the repo's own
# include and exclude patterns override it (an include match wins), and a
# repo that dislikes a shape it names can exclude it explicitly.
_GENERATED_SHAPES = (
    (
        r"(^|/)(?:dist|build|coverage|vendor|node_modules|bower_components"
        r"|__pycache__|__snapshots__|\.venv|venv|\.tox|target)/"
    ),
    r"\.(?:min\.(?:js|css)|(?:js|css)\.map)$",
    (
        r"(^|/)(?:package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml"
        r"|yarn\.lock|bun\.lockb?|poetry\.lock|pdm\.lock|uv\.lock"
        r"|Pipfile\.lock|Cargo\.lock|go\.sum|go\.work\.sum|composer\.lock"
        r"|Gemfile\.lock|packages\.lock\.json|project\.assets\.json)$"
    ),
    r"\.pb\.(?:go|py|h|cc|ts)$",
    r"[\w]*_pb2(?:_grpc)?\.py$",
    r"\.generated\.(?:ts|js|mjs|cjs|dart|java|kt|cs|go|py|swift)$",
    r"\.snap$",
)
_GENERATED_RE = re.compile("|".join(_GENERATED_SHAPES), re.IGNORECASE)


def is_generated(path: str) -> bool:
    """Whether the path looks machine-generated (S5's heuristic above):
    path-shaped only, case-insensitive like the tier match."""
    return _GENERATED_RE.search(path) is not None


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    """fnmatch globs, case-insensitively like the tier match. fnmatch's
    `*` crosses `/`, so `src/**` and `src/*` name the same set; the parse
    module validates the pattern shape, and a pattern never reaches a
    model -- only its effect on the order does."""
    lowered = path.lower()
    return any(fnmatchcase(lowered, pattern.lower()) for pattern in patterns)


def _rank_groups(
    files: Iterable[FileDiff], ranks: PathRanks
) -> tuple[list[FileDiff], list[FileDiff], list[FileDiff]]:
    """The files split into S5's three groups, each in risk order:
    include-matched first, then everything the config did not move, then
    the deprioritized (exclude-matched, or generated under the
    `deprioritize` setting)."""
    ordered = by_risk(tuple(files))
    front: list[FileDiff] = []
    middle: list[FileDiff] = []
    back: list[FileDiff] = []
    for f in ordered:
        if _matches(f.path, ranks.exclude):
            back.append(f)
        elif _matches(f.path, ranks.include):
            front.append(f)
        elif ranks.generated and is_generated(f.path):
            back.append(f)
        else:
            middle.append(f)
    return front, middle, back


def rank_files(files: Iterable[FileDiff], ranks: PathRanks) -> tuple[FileDiff, ...]:
    """The files in the review order the repo's path settings ask for:
    include-matched, then the unranked rest, then the deprioritized, each
    group in risk order. The output is a permutation of the input -- the
    same files, never fewer: user config re-ranks, it never drops (Q25)."""
    front, middle, back = _rank_groups(files, ranks)
    return (*front, *middle, *back)


_RERANK_NAMED = 25
"""The deprioritized paths one rerank note names; the remainder is
counted, so the note is bounded controller text no matter how many files
a config moves."""


def _named_group(files: list[FileDiff], *, scrub: Callable[[str], str]) -> str:
    return describe_by_risk(tuple(files), _RERANK_NAMED, scrub=scrub)


def rerank_note(
    files: Iterable[FileDiff], ranks: PathRanks, *, scrub: Callable[[str], str]
) -> str:
    """The draft note recording the repo's path re-ranking (S5's
    done-when: the re-ranking is recorded in the draft, and the config is
    named for what it deprioritized). Every path is quoted as data
    (`describe_by_risk`); the patterns themselves are never echoed -- they
    are author-controlled text and only their validated effect on the
    order is reported. Empty when the settings rank nothing, so an
    unconfigured review's draft reads exactly as it did."""
    if not ranks.applies:
        return ""
    files = tuple(files)
    front, middle, back = _rank_groups(files, ranks)
    total = len(front) + len(middle) + len(back)
    back_keys_set = bool(ranks.exclude or ranks.generated)
    sentences = []
    if ranks.include:
        if not front:
            # The front group is empty for two different reasons, and the
            # note must not mistake one for the other: no pattern matched,
            # or patterns matched and `review_path_exclude:` took the
            # matches (exclude wins on every path, D69's rule carried to
            # paths). A false "none match" would record a wrong reason
            # next to a correct exclude sentence.
            matched = sum(1 for f in files if _matches(f.path, ranks.include))
            if matched:
                sentences.append(
                    f"review_path_include: ranked nothing ahead: its "
                    f"{matched} matching file(s) were deprioritized by "
                    "review_path_exclude"
                )
            else:
                sentences.append(
                    f"review_path_include: ranked nothing: none of this diff's "
                    f"{total} file(s) match its patterns"
                )
        elif not (middle or back):
            sentences.append(
                f"review_path_include: ranked all {total} file(s) first; "
                "nothing ranks behind them"
            )
        elif not back_keys_set:
            # Include alone: everything not matching is the set it
            # deprioritized, and the note names it.
            sentences.append(
                f"review_path_include: ranked {len(front)} matching file(s) "
                f"ahead of the other {len(middle)}, listed highest risk "
                f"first: {_named_group(middle, scrub=scrub)}"
            )
        else:
            # Combined with a deprioritizing key: the back group is named
            # by that key's sentence below, so this one names only the
            # middle and counts the rest.
            behind = (
                f", listed highest risk first: {_named_group(middle, scrub=scrub)}"
                if middle
                else ""
            )
            sentences.append(
                f"review_path_include: ranked {len(front)} matching file(s) "
                f"ahead of the other {len(middle or back)} file(s) ranking "
                f"behind them{behind}"
            )
    if back_keys_set:
        keys = "review_path_exclude:" if ranks.exclude else ""
        if ranks.exclude and ranks.generated:
            keys += " and the "
        elif ranks.generated:
            keys += "the "
        if ranks.generated:
            keys += "review_generated_files: deprioritize setting"
        if not back:
            sentences.append(
                f"{keys} ranked nothing: none of this diff's {total} file(s) match"
            )
        else:
            sentences.append(
                f"{keys} ranked {len(back)} file(s) last, listed highest "
                f"risk first: {_named_group(back, scrub=scrub)}"
            )
    return (
        "The reviewed repo's merge-base REVIEW.md re-ranked this review's "
        "changed files (ordering only: no file was dropped from review): "
        + " ".join(sentence + "." for sentence in sentences)
    )


@dataclass(frozen=True)
class _Packing:
    parts: tuple[DiffPart, ...] = ()
    unseen: tuple[FileDiff, ...] = ()


def select_diff(diff: str, max_parts: int, part_chars: int) -> DiffSelection:
    """First-fit packing in risk order into at most `max_parts` parts of at
    most `part_chars` characters. A file larger than one part is cut to fit
    a part of its own; a file that fits nowhere once every part is in use
    is unseen. A part must hold more than `CUT_MARKER`, or a cut file
    would carry none of its own text."""
    if part_chars <= len(CUT_MARKER):
        raise ValueError(
            f"part_chars must exceed the {len(CUT_MARKER)}-character cut marker"
        )
    files = split_files(diff)

    def place(acc: _Packing, f: FileDiff) -> _Packing:
        return _place(acc, f, max_parts, part_chars)

    packed = reduce(place, by_risk(files), _Packing())
    return DiffSelection(len(files), len(diff), packed.parts, packed.unseen, part_chars)


def fit_diff(
    diff: str,
    max_parts: int,
    part_chars: int,
    overflow: Callable[[DiffSelection], int],
    min_chars: int,
) -> DiffSelection:
    """`select_diff` with the part size shrunk until `overflow(selection)`,
    how far the largest part's whole prompt exceeds its token bound in UTF-8
    bytes, is not positive. Each round shrinks from the byte-largest part's
    actual size by the overflow converted to its characters. After
    `MAX_FIT_ROUNDS`, or once a selection at `min_chars` has been measured,
    the last selection is returned and the per-call token check refuses any
    part still too big."""
    if min_chars <= len(CUT_MARKER):
        raise ValueError(
            f"min_chars must exceed the {len(CUT_MARKER)}-character cut marker"
        )
    selection = select_diff(diff, max_parts, part_chars)
    for _ in range(MAX_FIT_ROUNDS):
        over = overflow(selection)
        if over <= 0 or selection.part_chars <= min_chars:
            return selection
        smaller = max(min_chars, _shrunk(selection, over))
        selection = select_diff(diff, max_parts, smaller)
    return selection


def _shrunk(sel: DiffSelection, over_bytes: int) -> int:
    if not sel.parts:
        return sel.part_chars - over_bytes
    part = max(sel.parts, key=lambda p: len(p.text.encode("utf-8")))
    size = max(len(part.text.encode("utf-8")), 1)
    return min(sel.part_chars, part.chars) - math.ceil(over_bytes * part.chars / size)


def _place(acc: _Packing, f: FileDiff, max_parts: int, budget: int) -> _Packing:
    slot = next(
        (i for i, p in enumerate(acc.parts) if p.chars + len(f.text) <= budget), None
    )
    if slot is not None:
        grown = DiffPart((*acc.parts[slot].files, f))
        return replace(acc, parts=(*acc.parts[:slot], grown, *acc.parts[slot + 1 :]))
    if len(acc.parts) >= max_parts:
        return replace(acc, unseen=(*acc.unseen, f))
    return replace(acc, parts=(*acc.parts, DiffPart((_fit(f, budget),))))


def describe_by_risk(
    files: tuple[FileDiff, ...], limit: int, *, scrub: Callable[[str], str]
) -> str:
    """`[tier] "path", "path"; [tier] "path"` for the first `limit` files in
    risk order, then a count of the rest. Paths are chosen by the PR author,
    so each is quoted as data."""
    shown = by_risk(files)[:limit]
    groups = (
        (tier, [quote_untrusted(f.path, scrub=scrub) for f in shown if f.tier is tier])
        for tier in RISK_TIERS
    )
    listed = "; ".join(
        f"[{t.label}] {', '.join(paths)}" for t, paths in groups if paths
    )
    more = len(files) - len(shown)
    return listed + (f"; and {more} more" if more > 0 else "")


def _fit(f: FileDiff, budget: int) -> FileDiff:
    if len(f.text) <= budget:
        return f
    head = f.text[: max(budget - len(CUT_MARKER), 0)]
    newline = head.rfind("\n")
    kept = head[: newline + 1] if newline > 0 else head
    return replace(f, text=kept + CUT_MARKER)
