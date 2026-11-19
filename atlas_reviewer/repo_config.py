# SPDX-License-Identifier: MIT
"""The reviewed repo's **merge-base** `REVIEW.md` config parse (D81's S1):
the schema-validated read of the settings lines the reviewer consumes from
the file the reviewed repo carries its policy in.

The file name is one constant (`REVIEW_MD`), not a design commitment -- a
`.atlas.yml`-style file remains the alternative if the key set outgrows
one-line-per-key. D81 Q1 keeps `REVIEW.md` and extends it rather than
adding a second file, so the constant is the only thing a rename would
touch.

The schema is a **closed set, not a pass-through** (the plan's §4): the
parse yields a dollar amount, lens names, and controller notes, and
nothing else -- no config key can widen network, secret, or Sprite
access, because no key reaches any of that. Keys the build does not
carry parse as **unsupported with named notes**: a line in the `review_`
key namespace -- the namespace every setting line in this file lives in
-- that neither this module's schema nor the admission read
(`service_admit.py`, the default branch, #756/#761) carries is ignored
fail-open and named, the generalization of D68's unusable-line note.
The unsupported scan skips lines inside a fenced code block -- a
documented example of a future key is not a configuration attempt --
while the known keys' own parsers read every line regardless of fences
(main's behavior, deliberately unchanged), so a fenced known key is
still live config. Every note names the key,
the condition, and the default that stands, and **never echoes the raw
rejected value**: the value is unvalidated author-controlled input
(merge-base `REVIEW.md` is author-controllable in same-repo and stacked
PRs), only schema-validated numbers may be named (D68's ceiling note),
and the key name a note carries is validated to a markup-free shape at
parse -- the same trust boundary D69's lens-shaped validation draws --
so no note can carry markup into the controller text.

Config values are untrusted data everywhere they reach a model. The read
stays bounded: the file is read under `MAX_CHECKED_BYTES` (64 KiB), and
a file over the bound is not parsed cut, because a truncation inside a
value could read as a value it is not. Both D68 lines keep their
existing **merge-base** read -- the tree the PR branched from, not the
base-ref tip and never the PR head -- so a PR cannot move its own
values; admission-class keys read the default branch instead, which is
S4's surface (`service_admit.py`), not this module's.

Today's keys:

- `review_ceiling_usd:` (D68) -- the repo's per-review dollar ceiling;
  it wins over the operator's `ATLAS_REVIEW_CEILING_USD` outright, in
  either direction (D81 Q2 keeps D68's semantics), and the ceiling
  actually used is resolved by `review_wide.resolve_ceiling` and named
  in the draft and the post through D68's ceiling note.
- `review_lens_include:` / `review_lens_exclude:` (D69) -- the lens
  preference that overrides the picker's guideline, applied by
  `picker`, whose protection set is the manifest's whole `tier: floor`
  (D69's 5:13 PM CT update), not the critical tier alone.
- `review_severity_floor:` / `review_post_verbosity:` (config slice S3,
  D84) -- the service's own post settings, parsed by this module's
  schema but **not read from the merge-base**: the floor decides which
  findings reach the post, and the verbosity decides which sections it
  carries, so a PR that could move either would suppress or quiet its
  own review. The service reads them from the repo's **default branch**
  at post time (the same default-branch window the admission-class keys
  are read from) through `parse_post_config`, whose read this module
  shares; the merge-base reads below neither honor nor name these two.

- `review_path_include:` / `review_path_exclude:` /
  `review_generated_files:` (config slice S5, D81 Q6) -- the path
  re-ranking the diff's files are ordered by. **Ordering and depth only,
  never exclusion**: no pattern drops a file from review; every file
  stays accounted for (sent, cut, or named unseen exactly as before),
  and whether anything may be excluded from review at all is Q25's
  undecided question, untouched. The values parse into
  `diffs.PathRanks`, applied by `diffs.rank_files` and recorded in the
  draft through `diffs.rerank_note`; the patterns themselves never
  reach a model -- only their effect on the order does.

- `review_test_commands:` (config slice S7, D88) -- the repo's
  **proposed additions** to the #734 execution-tool allow-list: declared
  test commands a `run_tests` call may name. A proposal is a **request,
  never a grant** (the #734 decision, D80): the command runs only when
  the run's operator-approval channel explicitly approves it, the
  approval lives in run-scoped state that dies with the run, and the
  argv the command runs is built by the bridge from the proposal's own
  tokens -- the model names the proposal, never a shell string. Parsed
  by `parse_run_proposals` from the **default branch** (the D84 read
  source: a same-repo or stacked PR must not carry its own execution
  proposals into its own review), like the S3 post keys and the
  admission keys -- never from the merge-base, whose copy of the key the
  merge-base read ignores silently (it is a known key, so no false
  unsupported note draws). An unusable value fails open to deny -- no
  proposal -- with a named note that counts and never echoes the
  rejected text; the grammar is a closed set (tokens, no shell
  metacharacters, workspace-relative program paths only), so no key can
  widen network, secret, or Sprite access and the runner stays deny-all
  and credential-free.

The admission-class keys (`review_base_include:` /
`review_base_exclude:` / `review_skip_events:`, #756 and #761) are
`service_admit.py`'s -- read from the repo's default branch, a different
window on the same file -- and the scan knows them by name so it never
calls them unsupported. The S3 post keys are in that same class from the
schema's side: the scan knows them by name too, so a repo whose
`REVIEW.md` sets its floor or its verbosity draws no false unsupported
note in the merge-base read either.

The reads are pure functions of the merge-base tarball. `read_repo_config`
parses the whole file once; the per-line reads are the consumers'
windows over it.
"""

from __future__ import annotations

import io
import re
import tarfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from atlas_reviewer.approval import CommandProposal
from atlas_reviewer.bridge_args import MAX_COMMAND_CHARS, path_problem
from atlas_reviewer.diffs import PathRanks
from atlas_reviewer.lens_contract import Severity
from atlas_reviewer.picker import LENS_NAME, LensPreferences
from atlas_reviewer.quotes import refused_archive

# The file the reviewed repo sets its configuration in (D81 Q1). One
# constant, deliberately: extending this file is the decided shape, and
# a `.atlas.yml`-style rename stays the alternative the key set can grow
# into, not a second file to add beside it.
REVIEW_MD = "REVIEW.md"

# The `REVIEW.md` line the reviewed repo sets its ceiling with. The value
# runs to a `#` comment or the end of the line, as the file's other
# settings do; the separator after the colon is optional (`review_ceiling_usd:15`
# parses, round-2 review of #717, m-7), and a bare `review_ceiling_usd:`
# with no value matches too -- a line present with nothing usable in it.
CEILING_LINE = re.compile(r"^review_ceiling_usd:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$")
# The `REVIEW.md` lines the reviewed repo overrides the picker's guideline
# with (D69): each value is a comma-separated list of lens names, same
# value grammar as the ceiling line's.
LENS_INCLUDE_LINE = re.compile(
    r"^review_lens_include:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
LENS_EXCLUDE_LINE = re.compile(
    r"^review_lens_exclude:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
# The `REVIEW.md` lines that re-rank the diff's paths (config slice S5,
# D81 Q6): each value is a comma-separated list of path patterns, same
# value grammar as the lens lines', and the generated-file line's value is
# one of two words. Ordering only, never exclusion -- no pattern drops a
# file from review, and whether anything may be excluded from review at
# all is Q25's undecided question, untouched here.
PATH_INCLUDE_LINE = re.compile(
    r"^review_path_include:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
PATH_EXCLUDE_LINE = re.compile(
    r"^review_path_exclude:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
GENERATED_FILES_LINE = re.compile(
    r"^review_generated_files:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
# What a seen-but-unusable ceiling line says (round-1 review of #717,
# m-5): the fail-open fallback is not silent.
_UNUSABLE_NOTE = (
    f"the reviewed repo's merge-base {REVIEW_MD} carries a "
    "review_ceiling_usd: line that is not a positive dollar amount; it is "
    "ignored and the configured ceiling (default $10) stands"
)
# What a seen-but-unusable lens preference line says (D69): the
# guideline stands, and the note says the lines were seen and ignored.
_UNUSABLE_LENSES_NOTE = (
    f"the reviewed repo's merge-base {REVIEW_MD} carries a "
    "review_lens_include: or review_lens_exclude: line that is not a "
    "comma-separated list of lens names; it is ignored and the picker's "
    "guideline stands"
)
# What a seen-but-unusable path-ranking line says (S5): the note names the
# key, the condition, and the default that stands -- the risk order -- and
# never echoes the rejected value. Built per offending key because the
# three keys' conditions differ; every part is controller-authored
# constant text.
_PATH_PATTERN_CONDITION = "a comma-separated list of path patterns"
_GENERATED_VALUE_CONDITION = "deprioritize or normal"
# Bound the file the ceiling line is read from, as `quotes` bounds the
# files it checks.
MAX_CHECKED_BYTES = 64 * 1024


# The service's two post-window lines (config slice S3, D84): the value
# grammar is the file's -- one line per key, running to a `#` comment or
# the end of the line, the separator after the colon optional.
SEVERITY_FLOOR_LINE = re.compile(
    r"^review_severity_floor:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
POST_VERBOSITY_LINE = re.compile(
    r"^review_post_verbosity:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
# The default-branch line that proposes additions to the #734
# execution-tool allow-list (config slice S7, D88): the value is a
# comma-separated list of declared test commands, each one program token
# plus optional fixed argument tokens separated by single spaces. A
# proposal is a request the operator approves, never a grant, and the
# argv it may become is built by the bridge from these tokens alone.
TEST_COMMANDS_LINE = re.compile(
    r"^review_test_commands:(?:[ \t]*([^#]*?))?[ \t]*(?:#.*)?$"
)
# The verbosity dial's closed set (D84): the current post body is the
# ceiling of verbosity, so the dial is lowering-only by construction --
# `brief` is the one value below it, and every other value fails open to
# the default rather than inventing a second dial position.
POST_VERBOSITIES = ("full", "brief")
POST_VERBOSITY_FULL = "full"
POST_VERBOSITY_BRIEF = "brief"
# The severity names the floor line accepts: the atlas severity
# vocabulary itself (`lens_contract.Severity`), lowercase, the same
# lowercase-strict convention the lens-name grammar uses. The protocol's
# prose capitalizes the names ("Major"); the setting takes the enum's
# own spelling.
_SEVERITY_NAMES = tuple(severity.value for severity in Severity)
# What a seen-but-unusable floor line says: the fail-open fallback is
# not silent, and the note never echoes the rejected value -- the
# accepted names are the schema's own, not the author's text.
_FLOOR_UNUSABLE_NOTE = (
    f"the reviewed repo's default-branch {REVIEW_MD} carries a "
    "review_severity_floor: line that is not one of the severity names "
    f"({', '.join(_SEVERITY_NAMES)}); it is ignored and the default "
    "(post every finding) stands"
)
_VERBOSITY_UNUSABLE_NOTE = (
    f"the reviewed repo's default-branch {REVIEW_MD} carries a "
    "review_post_verbosity: line that is not brief or full; it is "
    "ignored and the default (the full post) stands"
)


@dataclass(frozen=True)
class PostConfigRead:
    """The service's two post-window settings, parsed from the
    `REVIEW.md` on the repo's **default branch** (config slice S3, D84).

    `floor` is the severity floor a repo raised, None when the default
    stands -- post everything. `verbosity` is the post's dial, `full` by
    default and `brief` when the repo lowered it; there is no value
    above `full`, so the dial cannot raise the post past the body the
    service already sends. `notes` is controller text, non-empty only
    when a line was seen and ignored, so "line present but unusable" can
    be told apart from "no line"; each note names the key, the condition
    and the default that stands, and never the rejected value."""

    floor: Severity | None
    verbosity: str
    notes: tuple[str, ...]


DEFAULT_POST_CONFIG = PostConfigRead(None, POST_VERBOSITY_FULL, ())


# The #734 allow-list proposals' grammar (config slice S7, D88). A
# command is one program token plus optional fixed argument tokens,
# separated by single spaces; the tokens are a closed charset with no
# shell metacharacter, quote, expansion or separator in them, and the
# program's path shape is the bridge's own workspace-relative path rule
# (`path_problem`). The charset is what keeps metacharacters out -- it
# is **not** a containment guarantee: a proposal may name a shell
# interpreter or an interpreter at a workspace-relative path, and what
# bounds a named program is the operator's approval of the exact argv
# plus the deny-all, credential-free runner (D88's three controls), not
# this grammar. The bounds keep one line's parse bounded; a line over
# any of them is unusable, fail-open to deny.
_COMMAND_PROGRAM_TOKEN = re.compile(r"[A-Za-z0-9_.+/-]{1,512}")
_COMMAND_ARG_TOKEN = re.compile(r"[A-Za-z0-9_.+-]{1,120}")
# The traversal-shaped argument tokens (round-1 review of #775, F5): an
# argument token cannot carry a `/` (the charset above), so a `..` path
# segment inside one can only be the token itself -- the bare `.` and
# `..` are refused, which kills the `pytest --rootdir ..` shape by
# grammar rather than leaving it to the operator's approval to bound.
_TRAVERSAL_ARGS = frozenset({".", ".."})
_MAX_COMMAND_TOKENS = 8
_MAX_RUN_PROPOSALS = 8


def _test_commands(raw: str | None) -> tuple[CommandProposal, ...] | None:
    """The comma-separated declared commands of one line's value, or None
    when the value is unusable: empty, a token outside its grammar, a
    traversal-shaped argument token (`.` or `..`; the charset keeps `/`
    out of an argument, so a `..` segment inside one can only be the
    token itself), more tokens or commands than the bounds, a program
    whose path the bridge's own path rule refuses, or the same command
    twice. Whitespace runs inside a command are token separators at
    work, not part of a token; the canonical name is the tokens joined
    by single spaces, which is the exact string a `run_tests` call
    names."""
    if raw is None or not raw.strip():
        return None
    proposals: list[CommandProposal] = []
    for piece in raw.split(","):
        tokens = piece.split()
        if not tokens or len(tokens) > _MAX_COMMAND_TOKENS:
            return None
        program, *args = tokens
        if (
            not _COMMAND_PROGRAM_TOKEN.fullmatch(program)
            or path_problem(program) is not None
        ):
            return None
        if not all(
            _COMMAND_ARG_TOKEN.fullmatch(token) and token not in _TRAVERSAL_ARGS
            for token in args
        ):
            return None
        name = " ".join(tokens)
        if len(name) > MAX_COMMAND_CHARS or any(p.name == name for p in proposals):
            return None
        proposals.append(CommandProposal(name, (program, *args)))
    if len(proposals) > _MAX_RUN_PROPOSALS:
        return None
    return tuple(proposals)


def _unusable_commands_note(lines: int) -> str:
    """The note for the offending `review_test_commands:` lines: the key,
    the condition, the count, and the default that stands -- no command
    is proposed -- and never any rejected value."""
    if lines == 1:
        return (
            f"the reviewed repo's default-branch {REVIEW_MD} carries a "
            "review_test_commands: line it cannot use as the run's "
            "proposed test commands (a comma-separated list of declared "
            "test commands, one line per key); it is ignored and no "
            "command is proposed -- the execution tools run the built-in "
            "pytest entry only"
        )
    return (
        f"the reviewed repo's default-branch {REVIEW_MD} carries "
        f"{lines} review_test_commands: lines it cannot use as the run's "
        "proposed test commands (a comma-separated list of declared test "
        "commands, one line per key); they are ignored and no command is "
        "proposed -- the execution tools run the built-in pytest entry "
        "only"
    )


@dataclass(frozen=True)
class RunProposalsRead:
    """What the reviewed repo's **default-branch** `REVIEW.md` proposed
    for the #734 execution-tool allow-list (config slice S7, D88):
    `proposals` are the parsed, validated additions -- each becomes only
    an operator-approval request, never a grant; `notes` is controller
    text, non-empty only when a line was seen and ignored, so "line
    present but unusable" can be told apart from "no line". The note
    counts the ignored lines and never echoes the rejected text."""

    proposals: tuple[CommandProposal, ...]
    notes: tuple[str, ...]


DEFAULT_RUN_PROPOSALS = RunProposalsRead((), ())


def parse_run_proposals(text: str | None) -> RunProposalsRead:
    """The `review_test_commands:` line, parsed from one `REVIEW.md`
    **text** -- the default-branch file the service fetches, never the
    merge-base tarball and never the PR head (the D84 read source: a PR
    that could carry its own proposals would name commands into its own
    review's execution surface). No file, or no line for the key, reads
    as no proposal, silently, exactly as no request at all. A line that
    is present but unusable -- an empty or out-of-grammar value, or the
    key more than once -- fails open to deny: the whole line is dropped,
    nothing is proposed, and the note names the key, the condition, the
    count and the default, never the rejected text. Fence-blind by
    design: the known keys' parser is line-based, so a fenced known key
    is still live config, exactly as the ceiling's and the lens lines'
    own parsers read."""
    if text is None:
        return DEFAULT_RUN_PROPOSALS
    proposals: tuple[CommandProposal, ...] | None = None
    unusable = False
    matched = 0
    for line in text.splitlines():
        match = TEST_COMMANDS_LINE.match(line)
        if match is None:
            continue
        matched += 1
        parsed = _test_commands(match.group(1))
        if parsed is None or proposals is not None:
            # An unusable value, or a second line for the one-line-per-key
            # key: the whole read fails open to deny.
            unusable = True
            continue
        proposals = parsed
    if unusable:
        # The note counts every line the key carried, and never echoes a
        # rejected value.
        return RunProposalsRead((), (_unusable_commands_note(matched),))
    if proposals is None:
        return DEFAULT_RUN_PROPOSALS
    return RunProposalsRead(proposals, ())


def parse_post_config(text: str | None) -> PostConfigRead:
    """The service's two post-window lines, parsed from one `REVIEW.md`
    **text** -- the default-branch file the service fetches, never the
    merge-base tarball and never the PR head (D84: a PR that could move
    its own floor would suppress its own findings from the only surface
    a human reads). No file, or no line for a key, reads as that key's
    default, silently, exactly as no override at all; a line that is
    present but unusable -- a value outside the key's closed set, or a
    key that appears twice -- fails open to that key's default and is
    named, the keys independent the way the admission read's are."""
    if text is None:
        return DEFAULT_POST_CONFIG

    def value(raw: str | None) -> str:
        return raw.strip() if raw else ""

    floor: Severity | None = None
    verbosity: str = POST_VERBOSITY_FULL
    floor_seen = verbosity_seen = False
    floor_bad = verbosity_bad = False
    for line in text.splitlines():
        match = SEVERITY_FLOOR_LINE.match(line)
        if match is not None:
            if floor_seen:
                floor_bad = True
                floor = None
            else:
                floor_seen = True
                name = value(match.group(1))
                if name in _SEVERITY_NAMES:
                    floor = Severity(name)
                else:
                    floor_bad = True
            continue
        match = POST_VERBOSITY_LINE.match(line)
        if match is not None:
            if verbosity_seen:
                verbosity_bad = True
                verbosity = POST_VERBOSITY_FULL
            else:
                verbosity_seen = True
                name = value(match.group(1))
                if name in POST_VERBOSITIES:
                    verbosity = name
                else:
                    verbosity_bad = True
    notes: list[str] = []
    if floor_bad:
        notes.append(_FLOOR_UNUSABLE_NOTE)
    if verbosity_bad:
        notes.append(_VERBOSITY_UNUSABLE_NOTE)
    return PostConfigRead(floor, verbosity, tuple(notes))


@dataclass(frozen=True)
class CeilingRead:
    """What the reviewed repo's merge-base `REVIEW.md` said about the
    ceiling: `value` is the override, None when there is none; `note` is
    controller text, non-empty only when a ceiling line was seen and
    ignored, so "line present but unusable" can be told apart from "no
    line" (round-1 review of #717, m-5)."""

    value: Decimal | None
    note: str


@dataclass(frozen=True)
class LensPreferencesRead:
    """What the reviewed repo's merge-base `REVIEW.md` said about lens
    selection (D69): `preferences` is the override of the picker's
    guideline, None when there is none; `note` is controller text,
    non-empty only when preference lines were seen and ignored, so "lines
    present but unusable" can be told apart from "no lines"."""

    preferences: LensPreferences | None
    note: str


class _OverBound:
    """The REVIEW.md marker a shared read returns when the file exists but
    is over the read bound: not parsed cut, because a truncation inside a
    value could read as a value it is not."""


_REVIEW_MD_OVER_BOUND = _OverBound()


def _review_md_text(base_tarball: bytes) -> str | _OverBound | None:
    """The text of the reviewed repo's **merge-base** `REVIEW.md`, or None
    when there is no readable one (no tarball, an archive the fail-closed
    check refuses, a read error, no such file), or `_OverBound` when the
    file exists but is over the read bound. Shared by every setting this
    file carries, so the walk exists once."""
    if not base_tarball or refused_archive(base_tarball) is not None:
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(base_tarball), mode="r:gz") as archive:
            for member in archive:
                path = member.name.partition("/")[2]
                if path != REVIEW_MD or not member.isfile():
                    continue
                raw = archive.extractfile(member)
                if raw is None:
                    continue
                data = raw.read(MAX_CHECKED_BYTES + 1)
                if len(data) > MAX_CHECKED_BYTES:
                    return _REVIEW_MD_OVER_BOUND
                return data.decode("utf-8", errors="replace")
    except (tarfile.TarError, OSError, EOFError):
        return None
    return None


def _ceiling_value(text: str) -> CeilingRead:
    """The `review_ceiling_usd:` line's value. One line, one value; no
    line reads as absent (empty note); a line that is present but not a
    positive dollar amount -- or more than one -- reads as unusable, with
    the note that says so. Fence-blind by design: this is main's parser,
    unchanged, so a fenced known key is still live config."""
    found: Decimal | None = None
    seen_line = False
    for line in text.splitlines():
        match = CEILING_LINE.match(line)
        if match is None:
            continue
        if found is not None:
            return CeilingRead(None, _UNUSABLE_NOTE)
        seen_line = True
        raw = match.group(1)
        if raw is None or not raw.strip():
            return CeilingRead(None, _UNUSABLE_NOTE)
        try:
            found = Decimal(raw)
        except InvalidOperation:
            return CeilingRead(None, _UNUSABLE_NOTE)
    if found is None or not found.is_finite() or found <= 0:
        if seen_line:
            return CeilingRead(None, _UNUSABLE_NOTE)
        return CeilingRead(None, "")
    return CeilingRead(found, "")


def _lens_preferences(text: str) -> LensPreferencesRead:
    """The `review_lens_include:` and `review_lens_exclude:` lines' values
    (D69). One line per key; no line for a key reads as absent. Any line
    that is present but carries no comma-separated list of lens-shaped
    names, or a key that appears twice, makes the whole read unusable: the
    guideline stands, fail-open, with the note that says so. Fence-blind
    by design: this is main's parser, unchanged."""
    values: dict[str, list[str]] = {}
    for pattern, key in (
        (LENS_INCLUDE_LINE, "include"),
        (LENS_EXCLUDE_LINE, "exclude"),
    ):
        for line in text.splitlines():
            match = pattern.match(line)
            if match is None:
                continue
            if key in values:
                return LensPreferencesRead(None, _UNUSABLE_LENSES_NOTE)
            raw = match.group(1)
            names = _lens_names(raw)
            if names is None:
                return LensPreferencesRead(None, _UNUSABLE_LENSES_NOTE)
            values[key] = names
    if not values:
        return LensPreferencesRead(None, "")
    return LensPreferencesRead(
        LensPreferences(
            include=tuple(values.get("include", ())),
            exclude=tuple(values.get("exclude", ())),
        ),
        "",
    )


def _lens_names(raw: str | None) -> list[str] | None:
    """A comma-separated list of lens-shaped names, deduplicated in file
    order, or None when the value is empty or any name is not lens-shaped.
    Whitespace around a name is the list's separator at work, not part of
    one."""
    if raw is None or not raw.strip():
        return None
    names: list[str] = []
    for piece in raw.split(","):
        name = piece.strip()
        if not LENS_NAME.fullmatch(name) or len(name) > 80:
            return None
        if name not in names:
            names.append(name)
    return names


# The shape of one path pattern (S5): glob-lite, the characters a repo
# path plausibly holds plus fnmatch's `*` and `?`. Bracket classes are
# outside the grammar -- fnmatch would honor them, but their content is
# the one place a pattern could carry markup or a `[!...]` surprise, and
# `*` and `?` cover the shapes repos actually write (`src/**`,
# `*.min.js`, `dist/**` -- a pattern with no wildcard must match the
# whole path exactly, so a bare directory prefix matches nothing). A
# pattern never reaches a model: only its effect
# on the order does, so this bound is the whole trust boundary the
# pattern carries.
_PATH_PATTERN = re.compile(r"[A-Za-z0-9/_.\- *?]{1,200}")
# How many distinct patterns one line may carry; a longer list is
# unusable, fail-open, rather than silently truncated.
_MAX_PATH_PATTERNS = 32


def _path_patterns(raw: str | None) -> list[str] | None:
    """A comma-separated list of path patterns, deduplicated in file
    order, or None when the value is empty, any pattern is outside the
    grammar above, or there are more than `_MAX_PATH_PATTERNS`. Whitespace
    around a pattern is the list's separator at work, not part of one."""
    if raw is None or not raw.strip():
        return None
    patterns: list[str] = []
    for piece in raw.split(","):
        pattern = piece.strip()
        if not _PATH_PATTERN.fullmatch(pattern):
            return None
        if pattern not in patterns:
            patterns.append(pattern)
    if len(patterns) > _MAX_PATH_PATTERNS:
        return None
    return patterns


def _path_ranks(text: str) -> PathRanksRead:
    """The `review_path_include:`, `review_path_exclude:` and
    `review_generated_files:` lines' values (S5, D81 Q6). One line per
    key; no line for a key reads as absent. Any line that is present but
    unusable -- a value outside its key's grammar, or a key that appears
    twice -- makes the whole read unusable: the risk order stands,
    fail-open, with the note that names each offending key, its condition
    and the default, never the rejected value. Fence-blind by design:
    this is the known keys' line-based parser, so a fenced known key is
    still live config, exactly as the ceiling's and the lens lines' own
    parsers read."""
    patterns: dict[str, list[str]] = {}
    generated: bool | None = None
    bad: list[tuple[str, str]] = []
    for regex, key in (
        (PATH_INCLUDE_LINE, "review_path_include"),
        (PATH_EXCLUDE_LINE, "review_path_exclude"),
    ):
        for line in text.splitlines():
            match = regex.match(line)
            if match is None:
                continue
            if key in patterns:
                bad.append((key, _PATH_PATTERN_CONDITION))
                continue
            parsed = _path_patterns(match.group(1))
            if parsed is None:
                bad.append((key, _PATH_PATTERN_CONDITION))
                continue
            patterns[key] = parsed
    for line in text.splitlines():
        match = GENERATED_FILES_LINE.match(line)
        if match is None:
            continue
        if generated is not None:
            bad.append(("review_generated_files", _GENERATED_VALUE_CONDITION))
            continue
        raw = match.group(1)
        value = raw.strip() if raw is not None else ""
        if value == "deprioritize":
            generated = True
        elif value == "normal":
            generated = False
        else:
            bad.append(("review_generated_files", _GENERATED_VALUE_CONDITION))
    if bad:
        return PathRanksRead(None, _unusable_ranks_note(bad))
    if not patterns and generated is None:
        return PathRanksRead(None, "")
    return PathRanksRead(
        PathRanks(
            include=tuple(patterns.get("review_path_include", ())),
            exclude=tuple(patterns.get("review_path_exclude", ())),
            generated=bool(generated),
        ),
        "",
    )


def _unusable_ranks_note(bad: list[tuple[str, str]]) -> str:
    """The note for the offending path-ranking keys: each key named with
    its own condition, the default that stands, and no rejected value."""
    parts = [
        f"a {key}: line that is not {condition}"
        for key, condition in dict.fromkeys(bad)
    ]
    if len(parts) == 1:
        named = parts[0]
        return (
            f"the reviewed repo's merge-base {REVIEW_MD} carries {named}; "
            "it is ignored and the risk order stands"
        )
    named = ", ".join(parts[:-1]) + " and " + parts[-1]
    return (
        f"the reviewed repo's merge-base {REVIEW_MD} carries {named}; "
        "they are ignored and the risk order stands"
    )


# A config attempt the schema does not carry: a line in the `review_`
# key namespace, the namespace every setting line in this file lives in.
# The key a note names is bounded and markup-free by the same regex, so
# naming it carries no author-controlled text past validation. Lines
# outside the namespace -- a policy file's ordinary prose, an uppercase
# variant -- are not config attempts in this grammar and stay unremarked,
# exactly as they read today.
_UNSUPPORTED_KEY_LINE = re.compile(r"^review_([a-z0-9_]{1,80}):")
# The keys the build carries. The first five are this module's own
# schema -- the merge-base reads' three, plus the service's two
# post-window keys (S3), parsed by `parse_post_config` from the
# default-branch file -- and the rest are the default-branch-class keys
# other modules read and honor from the repo's default branch: the
# admission keys `service_admit.py` reads (#756, #761) and the S7
# execution-tool allow-list proposals `parse_run_proposals` reads (D88)
# -- the same file serves both windows, so a key a default-branch read
# carries is supported by the build, and naming it "unsupported" here
# would be the false note the named-note pattern exists to prevent.
# They are checked against `service_admit` `_ADMISSION_KEYS` by a test,
# so a key added there without this set fails rather than drawing a
# false note. All of them match the unsupported scan's shape, so the
# scan excludes them by name.
_KNOWN_KEYS = frozenset(
    {
        "review_ceiling_usd",
        "review_lens_include",
        "review_lens_exclude",
        "review_path_include",
        "review_path_exclude",
        "review_generated_files",
        "review_severity_floor",
        "review_post_verbosity",
        "review_base_include",
        "review_base_exclude",
        "review_skip_events",
        "review_test_commands",
    }
)
# How many distinct unsupported keys one note names; the remainder is
# counted, never listed, so the note is bounded controller text no
# matter how many unknown keys a file packs.
_UNSUPPORTED_KEYS_NAMED = 8

# A fenced code block's edge, the simple CommonMark subset the
# unsupported scan walks: up to three leading spaces, then at least
# three backticks or tildes. A closing fence is the same character at at
# least the open fence's length, carries no info string, and sits inside
# the same indent bound; a 4-space-indented marker is an indented code
# block, not a fence.
_FENCE_MARKER = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _unsupported_notes(text: str) -> tuple[str, ...]:
    """The named note for the keys the schema does not carry: one note,
    naming each distinct unknown `review_` key (at most
    `_UNSUPPORTED_KEYS_NAMED` of them, the remainder counted), the
    condition, and the default that stands -- never any rejected value.
    The key names are validated markup-free by the scan's regex, so the
    note carries no author-controlled text past validation.

    Lines inside a fenced code block are skipped: a repo's policy file
    may document a future key in an example, and an example is not a
    configuration attempt. The fence walk is CommonMark's fence-edge
    subset -- up to three leading spaces then at least three backticks
    or tildes opens; the same character at at least the open fence's
    length, with no info string, closes -- so a ``` example and a `~~~`
    example are both skipped, and a 4-space-indented marker is an
    indented code block, not a fence. An unbalanced fence flips the
    state for the rest of the file -- a missed or an extra note, either
    way fail-open and bounded, never a wrong value: the known keys' own
    parsers are line-based and unchanged, so a fenced known key is still
    live config."""
    seen: list[str] = []
    fence: str | None = None  # the open fence's marker run, e.g. "```"
    for line in text.splitlines():
        marker = _FENCE_MARKER.match(line)
        if fence is not None:
            if (
                marker is not None
                and marker.group(1)[0] == fence[0]
                and len(marker.group(1)) >= len(fence)
                and not line[marker.end() :].strip()
            ):
                fence = None
            continue
        if marker is not None:
            fence = marker.group(1)
            continue
        match = _UNSUPPORTED_KEY_LINE.match(line)
        if match is None:
            continue
        key = f"review_{match.group(1)}"
        if key in _KNOWN_KEYS or key in seen:
            continue
        seen.append(key)
    if not seen:
        return ()
    named = seen[:_UNSUPPORTED_KEYS_NAMED]
    listed = ", ".join(f"{key}:" for key in named)
    extra = len(seen) - len(named)
    if extra:
        listed += f", and {extra} more unsupported key(s)"
    if len(named) == 1:
        note = (
            f"the reviewed repo's merge-base {REVIEW_MD} carries a {listed} "
            "line, which this build does not support; it is ignored and "
            "the default stands"
        )
    else:
        note = (
            f"the reviewed repo's merge-base {REVIEW_MD} carries unsupported "
            f"setting lines {listed}, which this build does not support; "
            "they are ignored and the defaults stand"
        )
    return (note,)


@dataclass(frozen=True)
class PathRanksRead:
    """What the reviewed repo's merge-base `REVIEW.md` said about path
    ranking (config slice S5, D81 Q6): `ranks` is the ordering-only
    override, None when there is none; `note` is controller text,
    non-empty only when a ranking line was seen and ignored, so "lines
    present but unusable" can be told apart from "no lines". The value
    the note never carries is the rejected one: the risk order stands."""

    ranks: PathRanks | None
    note: str


@dataclass(frozen=True)
class RepoConfig:
    """The whole parse of the reviewed repo's **merge-base** `REVIEW.md`:
    `ceiling`, `lenses` and `ranks` are the D68/D69/S5 reads, and
    `unsupported_notes` name the keys the schema does not carry, empty
    when there are none -- a plain policy file reads exactly as it did
    before this module."""

    ceiling: CeilingRead
    lenses: LensPreferencesRead
    ranks: PathRanksRead = PathRanksRead(None, "")
    unsupported_notes: tuple[str, ...] = ()


def read_repo_config(base_tarball: bytes) -> RepoConfig:
    """The reviewed repo's merge-base `REVIEW.md`, parsed once against the
    closed schema: the D68/D69 lines, the S5 path-ranking lines, and the
    unsupported keys' named notes. A tarball that fails the fail-closed
    archive check or no file at all reads as an empty config, silently; a
    file over the read bound is not parsed cut and names the bound on
    every read."""
    text = _review_md_text(base_tarball)
    if isinstance(text, _OverBound):
        bound = (
            f"the reviewed repo's merge-base {REVIEW_MD} is over the "
            f"{MAX_CHECKED_BYTES}-byte read bound, so its "
        )
        return RepoConfig(
            CeilingRead(
                None,
                bound + "review_ceiling_usd: line, if any, was not read; the "
                "configured ceiling (default $10) stands",
            ),
            LensPreferencesRead(
                None,
                bound + "review_lens_include: and review_lens_exclude: lines, if "
                "any, were not read; the picker's guideline stands",
            ),
            PathRanksRead(
                None,
                bound + "review_path_include:, review_path_exclude: and "
                "review_generated_files: lines, if any, were not read; the "
                "risk order stands",
            ),
        )
    if text is None:
        return RepoConfig(
            CeilingRead(None, ""),
            LensPreferencesRead(None, ""),
            PathRanksRead(None, ""),
        )
    return RepoConfig(
        _ceiling_value(text),
        _lens_preferences(text),
        _path_ranks(text),
        _unsupported_notes(text),
    )


def review_md_ceiling(base_tarball: bytes) -> CeilingRead:
    """The reviewed repo's `review_ceiling_usd:` line in its **merge-base**
    `REVIEW.md` (D68) -- the base tarball the review already fetches, the
    tree the PR branched from, not the base-ref tip; a ceiling the repo
    changes on the base tip takes effect for pull requests branched after
    it, and a PR cannot raise or lower its own ceiling either way. A
    tarball that fails the fail-closed archive check, a missing file, or
    no ceiling line read as `CeilingRead(None, "")` -- the default stands,
    silently, exactly as no override at all. A line that is present but
    not a positive dollar amount, more than one, or a file over the read
    bound read as `CeilingRead(None, note)`: the default still stands,
    fail-open, and the note says the line was seen and ignored."""
    return read_repo_config(base_tarball).ceiling


def review_md_lens_preferences(base_tarball: bytes) -> LensPreferencesRead:
    """The reviewed repo's `review_lens_include:` and
    `review_lens_exclude:` lines in its **merge-base** `REVIEW.md` (D69) --
    the same tree the ceiling is read from, so a PR cannot move its own
    override either. No lines read as `LensPreferencesRead(None, "")`: the
    guideline stands, exactly as no override at all. Lines that are
    present but not comma-separated lists of lens-shaped names, a key
    repeated, or a file over the read bound read as
    `LensPreferencesRead(None, note)`: the guideline still stands,
    fail-open, and the note says the lines were seen and ignored. A name
    that is lens-shaped but matches no bundle lens is kept: an include
    shows up as its own NOT RUN line and an exclude as the recorded
    override, never silently guessed or dropped."""
    return read_repo_config(base_tarball).lenses


def review_md_path_ranks(base_tarball: bytes) -> PathRanksRead:
    """The reviewed repo's path-ranking lines in its **merge-base**
    `REVIEW.md` (config slice S5, D81 Q6) -- the same tree the ceiling and
    the lens preference are read from, so a PR cannot move its own
    ranking either. No line reads as `PathRanksRead(None, "")`: the risk
    order stands, exactly as no setting at all. A line that is present
    but outside its key's grammar, a key repeated, or a file over the
    read bound reads as `PathRanksRead(None, note)`: the risk order still
    stands, fail-open, and the note names the key, the condition and the
    default -- never the rejected value. Ordering only, never exclusion:
    whatever the parsed `PathRanks` carries, `diffs.rank_files` only
    re-orders, and no file ever leaves the review (Q25 untouched)."""
    return read_repo_config(base_tarball).ranks
