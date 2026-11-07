# SPDX-License-Identifier: MIT
"""Choose review lenses for a change and load their bodies. Pure apart from
reading the repo's own skill bundle.

The model has no file tools, so naming a lens in a prompt is not running it:
the controller picks lenses from the diff's file paths and the PR text,
reads each lens's `body.md`, and inlines as much as the size budget allows.
Which lenses were included, truncated or omitted is reported in the draft.

`ROUTES` is a code-side digest of the route table in
`collapsed/skills/reviewing-a-change/SKILL.md`; a test checks that every lens
named here exists in the bundle.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from atlas_reviewer.prompt import LoadedLens

BUNDLE_ROOT = (
    Path(__file__).resolve().parent.parent
    / "collapsed"
    / "skills"
    / "reviewing-a-change"
)
MAX_LENSES = 6
LENS_BUDGET_CHARS = 60_000
MIN_TRUNCATED_CHARS = 4_000
TRUNCATION_NOTE = (
    "\n[... lens body truncated by atlas_reviewer: {kept} of {total} characters ...]\n"
)


@dataclass(frozen=True)
class Route:
    label: str
    lenses: tuple[str, ...]
    path_re: str = ""
    text_re: str = ""
    only_paths: bool = False


_TESTS = r"(^|/)(tests?|spec|__tests__)/|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$"
_DOCS = r"\.(md|rst|txt)$|(^|/)docs?/"

ROUTES: tuple[Route, ...] = (
    Route(
        "tests only",
        ("reviewing-test-quality", "checking-idioms-and-consistency"),
        _TESTS,
        only_paths=True,
    ),
    Route("docs only", ("reviewing-pr-and-process-hygiene",), _DOCS, only_paths=True),
    Route(
        "design doc",
        (
            "tracing-correctness-and-invariants",
            "reviewing-conceptual-integrity",
            "reviewing-api-contract-safety",
        ),
        r"(^|/)docs?/(plans?|adrs?|rfcs?|design)[^/]*/|(^|/)(adr|rfc)[-_ ]",
    ),
    Route(
        "migration or schema",
        (
            "reviewing-migration-and-data-safety",
            "tracing-correctness-and-invariants",
            "hunting-silent-failures",
        ),
        r"migrat|alembic|schema\.(sql|rb)|(^|/)db/",
        r"\bmigrat",
    ),
    Route(
        "data plane",
        (
            "reviewing-data-transformations-and-contracts",
            "tracing-correctness-and-invariants",
            "hunting-silent-failures",
            "reviewing-migration-and-data-safety",
        ),
        r"\.sql$|(^|/)dbt_|(^|/)models/[^/]+\.(sql|ya?ml)$",
    ),
    Route(
        "async or concurrent",
        (
            "reviewing-concurrency-and-async",
            "tracing-correctness-and-invariants",
            "hunting-silent-failures",
        ),
        r"async|queue|worker|thread|(^|[/_])locks?\b|concurren|mutex",
        r"\basync|\brace\b|concurren|deadlock|\bthread",
    ),
    Route(
        "public API or contract",
        (
            "reviewing-api-contract-safety",
            "reviewing-module-design",
            "sweeping-for-security",
        ),
        r"openapi|swagger|\.proto$|(^|/)(api|routes?|controllers?|endpoints?|webhooks?)(/|\.)|(^|/)sdk",
        r"\bapi\b|endpoint|webhook|backward.compat|breaking change",
    ),
    Route(
        "auth or untrusted input",
        (
            "sweeping-for-security",
            "hunting-silent-failures",
            "tracing-correctness-and-invariants",
        ),
        r"auth|login|session|token|password|crypto|secret|permission|oauth|sanitiz|redact",
        r"auth|password|secret|injection|vulnerab|\bxss\b|\bcsrf\b|credential",
    ),
    Route(
        "LLM integration",
        (
            "reviewing-llm-integration",
            "sweeping-for-security",
            "checking-restraint",
        ),
        r"llm|openai|anthropic|openrouter|prompts?(/|\.|_)|embedding|completion",
        r"\bllm\b|openai|anthropic|openrouter|\bprompt|model call",
    ),
    Route(
        "agent or tool use",
        (
            "reviewing-agentic-safety",
            "reviewing-llm-integration",
            "sweeping-for-security",
        ),
        r"agent|\bmcp\b|sandbox|tool[-_]?use",
        r"\bagent|\bmcp\b|sandbox|tool use",
    ),
    Route(
        "UI",
        (
            "reviewing-usability-and-interaction",
            "reviewing-accessibility-and-i18n",
            "checking-idioms-and-consistency",
            "reviewing-naming-and-readability",
            "reviewing-conceptual-integrity",
        ),
        r"\.(tsx|jsx|vue|svelte|html|css|scss)$|(^|/)(components?|templates?|views?)/",
    ),
    Route(
        "observability or operability",
        ("reviewing-observability-and-operability", "sweeping-for-security"),
        r"logging|metrics|telemetry|alert|feature[-_]?flag|rollback|observab",
        r"logging|metrics|telemetry|rollback|feature flag",
    ),
    Route(
        "performance",
        (
            "reviewing-performance-and-efficiency",
            "checking-restraint",
            "tracing-correctness-and-invariants",
        ),
        r"",
        r"\bperf|faster|speed ?up|optimi[sz]|latency|\bcache",
    ),
    Route(
        "error handling or resilience",
        (
            "hunting-silent-failures",
            "reviewing-observability-and-operability",
            "reviewing-concurrency-and-async",
        ),
        r"retry|timeout|fallback|backoff|circuit",
        r"\bretr(y|ies)|timeout|fallback|backoff|resilien",
    ),
    Route(
        "refactor",
        (
            "reviewing-module-design",
            "checking-restraint",
            "checking-idioms-and-consistency",
            "reviewing-naming-and-readability",
        ),
        r"",
        r"refactor|restructur|\brename|clean ?up",
    ),
    Route(
        "bug fix",
        (
            "tracing-correctness-and-invariants",
            "reviewing-test-quality",
            "hunting-silent-failures",
        ),
        r"",
        r"\bfix(es|ed)?\b|\bbug|regression|\bcrash",
    ),
    Route(
        "dependency change",
        ("checking-restraint", "reviewing-ai-authored-code"),
        r"requirements[^/]*\.(in|txt)$|package(-lock)?\.json$|pyproject\.toml$|cargo\.(toml|lock)$|go\.(mod|sum)$|gemfile|poetry\.lock$",
    ),
    Route(
        "CI, build or infrastructure config",
        ("sweeping-for-security",),
        r"(^|/)\.github/|dockerfile|makefile|\.tf$|(^|/)(helm|k8s|kubernetes)/|cloudformation|\.ya?ml$",
    ),
    Route(
        "install, packaging or CLI surface",
        ("reviewing-install-and-upgrade-experience", "reviewing-api-contract-safety"),
        r"install|setup\.|packaging|upgrade|(^|/)cli\.|__main__",
        r"install|upgrade guide|packaging|\bcli\b",
    ),
    Route(
        "external standards or protocols",
        ("reviewing-interoperability",),
        r"http|oauth|oidc|iso8601|unicode|cron|\.csv$",
        r"\bhttp\b|oauth|oidc|iso ?8601|\bcron\b|\bcsv\b|\brfc ?\d|unicode",
    ),
    Route(
        "agent-onboarding files",
        (
            "reviewing-agent-legibility",
            "reviewing-naming-and-readability",
        ),
        r"(^|/)(agents|claude)\.md$|llms\.txt$",
    ),
    Route(
        "AI-assisted change",
        (
            "reviewing-ai-authored-code",
            "tracing-correctness-and-invariants",
            "sweeping-for-security",
        ),
        r"",
        r"copilot|claude|cursor agent|ai[- ](generated|assisted)|generated by",
    ),
)

BASELINE = Route("any pull request", ("reviewing-pr-and-process-hygiene",))
GENERAL = Route(
    "general change",
    (
        "tracing-correctness-and-invariants",
        "reviewing-test-quality",
        "checking-restraint",
        "reviewing-naming-and-readability",
    ),
)
SPECIFIC_WEIGHT = 10


@dataclass(frozen=True)
class LensChoice:
    name: str
    score: int
    why: tuple[str, ...]


def _matches(route: Route, paths: Sequence[str], text: str) -> bool:
    if route.only_paths:
        return bool(paths) and all(
            re.search(route.path_re, p, re.IGNORECASE) for p in paths
        )
    in_paths = bool(route.path_re) and any(
        re.search(route.path_re, p, re.IGNORECASE) for p in paths
    )
    in_text = (
        bool(route.text_re)
        and re.search(route.text_re, text, re.IGNORECASE) is not None
    )
    return in_paths or in_text


def rank_lenses(paths: Sequence[str], text: str) -> tuple[LensChoice, ...]:
    """Every lens some route selected, best first. Specific routes outweigh
    the baseline and general-change fallbacks; within a route, earlier
    lenses weigh more. Ties keep first-seen order."""
    hit = tuple(r for r in ROUTES if _matches(r, paths, text))
    narrow = any(r.only_paths for r in hit)
    weighted = [(r, SPECIFIC_WEIGHT) for r in hit]
    weighted.append((BASELINE, 1))
    if not narrow:
        weighted.append((GENERAL, 1))
    scores: dict[str, int] = {}
    reasons: dict[str, list[str]] = {}
    for route, weight in weighted:
        for index, name in enumerate(route.lenses):
            scores[name] = scores.get(name, 0) + weight * (len(route.lenses) - index)
            reasons.setdefault(name, []).append(route.label)
    ordered = sorted(scores, key=lambda n: -scores[n])
    return tuple(LensChoice(n, scores[n], tuple(reasons[n])) for n in ordered)


class LensStatus(Enum):
    INCLUDED = "included"
    TRUNCATED = "truncated"
    OMITTED = "omitted"


@dataclass(frozen=True)
class LensUse:
    name: str
    status: LensStatus
    total_chars: int
    kept_chars: int
    why: str


@dataclass(frozen=True)
class LensPlan:
    uses: tuple[LensUse, ...]
    loaded: tuple[LoadedLens, ...]

    def coverage(self) -> str:
        parts = []
        for status in LensStatus:
            names = [_describe(u) for u in self.uses if u.status is status]
            if names:
                parts.append(f"{status.value}: {', '.join(names)}")
        return "; ".join(parts) or "no lens selected"


def _describe(use: LensUse) -> str:
    if use.status is LensStatus.TRUNCATED:
        return f"{use.name} ({use.kept_chars} of {use.total_chars} characters)"
    return use.name


class LensLibrary:
    def __init__(self, root: Path = BUNDLE_ROOT) -> None:
        self._lenses = root / "reference" / "lenses"

    def names(self) -> frozenset[str]:
        return frozenset(p.name for p in self._lenses.iterdir() if p.is_dir())

    def body(self, name: str) -> str | None:
        path = self._lenses / name / "body.md"
        return path.read_text(encoding="utf-8") if path.is_file() else None


def plan_lenses(
    library: LensLibrary,
    ranked: Iterable[LensChoice],
    max_lenses: int = MAX_LENSES,
    budget_chars: int = LENS_BUDGET_CHARS,
) -> LensPlan:
    uses: list[LensUse] = []
    loaded: list[LoadedLens] = []
    left = budget_chars
    for position, choice in enumerate(ranked):
        why = ", ".join(choice.why)
        body = library.body(choice.name)
        if body is None:
            uses.append(
                LensUse(
                    choice.name, LensStatus.OMITTED, 0, 0, "no body.md in the bundle"
                )
            )
        elif position >= max_lenses:
            uses.append(
                LensUse(
                    choice.name,
                    LensStatus.OMITTED,
                    len(body),
                    0,
                    f"below the cap of {max_lenses} lenses ({why})",
                )
            )
        elif len(body) <= left:
            uses.append(
                LensUse(choice.name, LensStatus.INCLUDED, len(body), len(body), why)
            )
            loaded.append(LoadedLens(choice.name, body))
            left -= len(body)
        elif left >= MIN_TRUNCATED_CHARS:
            cut = _cut(body, left)
            note = TRUNCATION_NOTE.format(kept=len(cut), total=len(body))
            uses.append(
                LensUse(choice.name, LensStatus.TRUNCATED, len(body), len(cut), why)
            )
            loaded.append(LoadedLens(choice.name, cut + note))
            left = 0
        else:
            uses.append(
                LensUse(
                    choice.name,
                    LensStatus.OMITTED,
                    len(body),
                    0,
                    f"size budget of {budget_chars} characters spent ({why})",
                )
            )
    return LensPlan(tuple(uses), tuple(loaded))


def _cut(body: str, limit: int) -> str:
    head = body[:limit]
    newline = head.rfind("\n")
    return head[: newline + 1] if newline > 0 else head
