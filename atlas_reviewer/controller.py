# SPDX-License-Identifier: MIT
"""The trusted controller: one PR event in, one review draft out.

It is the only component holding credentials (inside the GitHub and
Sprites adapters it is handed). Untrusted data flows one way: fetched,
redacted, fenced into the prompt, rendered into the draft. Nothing here
writes to GitHub.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from atlas_reviewer.classify import classify
from atlas_reviewer.domain import (
    CleanupStatus,
    Evidence,
    EvidenceItem,
    Missing,
    PrEvent,
    RunnerReport,
    RunnerStatus,
    SourceKey,
    SourceKind,
)
from atlas_reviewer.draft import (
    DraftInput,
    NarrativeFailure,
    render_draft,
    render_evidence,
)
from atlas_reviewer.evidence import (
    DETAIL_CHARS,
    PullInfo,
    WorkflowRun,
    log_item,
    parse_artifacts,
    parse_check_runs,
    parse_pull,
    parse_workflow_runs,
    tool_evidence,
)
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    GitHubReader,
    Narrative,
    ReviewHarness,
    ReviewRequest,
    RunnerLedger,
    SpritesApi,
)
from atlas_reviewer.prompt import UntrustedBlock
from atlas_reviewer.redact import RedactedText, Redactor
from atlas_reviewer.runner import RunnerJob, ToolResult, ToolSpec, run_disposable

DIFF_CHARS = 60_000
MAX_TARBALL_BYTES = 9 * 1024 * 1024

DEFAULT_TOOLS = (
    ToolSpec("python-compileall", "python3 --version", "python3 -m compileall -q ."),
    ToolSpec(
        "ruff", "ruff --version", "ruff check --no-cache --output-format=concise ."
    ),
    ToolSpec(
        "shellcheck",
        "command -v shellcheck >/dev/null && shellcheck --version | sed -n 2p",
        "sh -c 'find . -name \"*.sh\" -print0 | xargs -0 -r shellcheck -f gcc'",
    ),
)


@dataclass(frozen=True)
class ReviewConfig:
    expected: tuple[SourceKey, ...] = ()
    include_issues: bool = False
    deadline_s: float = 600.0
    tools: tuple[ToolSpec, ...] = DEFAULT_TOOLS
    max_tarball_bytes: int = MAX_TARBALL_BYTES
    max_log_runs: int = 5
    mode: str = "live"


@dataclass(frozen=True)
class Deps:
    github: GitHubReader
    sprites: SpritesApi
    ledger: RunnerLedger
    harness: ReviewHarness
    clock: Clock
    redactor: Redactor
    runner_name: Callable[[], str]


@dataclass
class _Collected:
    items: list[EvidenceItem] = field(default_factory=list)
    failures: list[Missing] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def review(event: PrEvent, deps: Deps, config: ReviewConfig) -> str:
    pull = parse_pull(deps.github.get_pull(event.repo, event.pr_number), deps.redactor)
    collected = _Collected(notes=_head_notes(event, pull))
    _gather_ci(event, pull, deps, config, collected)
    runner = _run_tools(event, deps, config, collected)
    evidence = classify(
        event.head_sha, collected.items, config.expected, collected.failures
    )
    blocks = _blocks(event, pull, evidence, deps, config, collected)
    narrative = _narrate(event, blocks, deps)
    draft = render_draft(
        DraftInput(
            event=event,
            mode=config.mode,
            title=pull.title.text,
            evidence=evidence,
            runner=runner,
            narrative=narrative,
            notes=tuple(collected.notes),
            redactions=_redaction_total(pull, collected.items, blocks),
            generated_at=deps.clock.now(),
        )
    )
    # Check names, failure reasons and runner notes are untrusted too.
    return deps.redactor(draft).text


def _head_notes(event: PrEvent, pull: PullInfo) -> list[str]:
    if pull.head_sha == event.head_sha:
        return []
    note = (
        f"The PR head is now `{pull.head_sha[:12]}`, not the event SHA. This draft covers "
        f"`{event.head_sha[:12]}` only, and only evidence for that SHA counts."
    )
    return [note]


def _attempt[T](
    collected: _Collected, key: SourceKey, fetch: Callable[[], T]
) -> T | None:
    try:
        return fetch()
    except BoundaryError as exc:
        collected.failures.append(Missing(key, f"could not fetch: {exc}"))
        return None


def _gather_ci(
    event: PrEvent,
    pull: PullInfo,
    deps: Deps,
    config: ReviewConfig,
    collected: _Collected,
) -> None:
    gh, now, redactor = deps.github, deps.clock.now, deps.redactor
    checks = _attempt(
        collected,
        SourceKey(SourceKind.CHECK_RUN, "(all check runs)"),
        lambda: parse_check_runs(
            gh.list_check_runs(event.repo, event.head_sha), now(), redactor
        ),
    )
    collected.items.extend(checks or ())
    runs = _attempt(
        collected,
        SourceKey(SourceKind.WORKFLOW_RUN, "(all workflow runs)"),
        lambda: parse_workflow_runs(
            gh.list_workflow_runs(event.repo, pull.head_ref), now(), redactor
        ),
    )
    collected.items.extend(r.item for r in runs or ())
    at_head = [r for r in runs or () if r.item.head_sha == event.head_sha][
        : config.max_log_runs
    ]
    for run in at_head:
        _gather_run(event, run, deps, collected)


def _gather_run(
    event: PrEvent, run: WorkflowRun, deps: Deps, collected: _Collected
) -> None:
    gh, now, redactor = deps.github, deps.clock.now, deps.redactor
    name = run.item.provenance.key.name
    artifacts = _attempt(
        collected,
        SourceKey(SourceKind.ARTIFACT, f"(artifacts of {name})"),
        lambda: parse_artifacts(
            gh.list_run_artifacts(event.repo, run.run_id), now(), redactor
        ),
    )
    collected.items.extend(artifacts or ())
    log = _attempt(
        collected,
        SourceKey(SourceKind.WORKFLOW_LOG, name),
        lambda: log_item(run, gh.get_run_logs(event.repo, run.run_id), now(), redactor),
    )
    collected.items.extend((log,) if log else ())


def _tool_keys(config: ReviewConfig) -> list[SourceKey]:
    return [SourceKey(SourceKind.RUNNER_TOOL, t.name) for t in config.tools]


def _skip_runner(
    config: ReviewConfig, collected: _Collected, reason: str
) -> RunnerReport:
    collected.failures.extend(
        Missing(k, f"runner skipped: {reason}") for k in _tool_keys(config)
    )
    return RunnerReport(RunnerStatus.SKIPPED, CleanupStatus.NOT_CREATED, None, reason)


def _run_tools(
    event: PrEvent, deps: Deps, config: ReviewConfig, collected: _Collected
) -> RunnerReport:
    try:
        tarball = deps.github.get_tarball(event.repo, event.head_sha)
    except BoundaryError as exc:
        return _skip_runner(
            config, collected, f"could not fetch the head-SHA tarball: {exc}"
        )
    if len(tarball) > config.max_tarball_bytes:
        return _skip_runner(
            config,
            collected,
            f"tarball is {len(tarball)} bytes, over {config.max_tarball_bytes}",
        )
    name = deps.runner_name()
    result = run_disposable(
        deps.sprites,
        deps.ledger,
        RunnerJob(tarball, config.tools),
        name=name,
        deadline_s=config.deadline_s,
        clock=deps.clock,
    )
    _record_tool_results(event, deps, config, collected, result.results, result.report)
    return result.report


def _record_tool_results(
    event: PrEvent,
    deps: Deps,
    config: ReviewConfig,
    collected: _Collected,
    results: tuple[ToolResult, ...],
    report: RunnerReport,
) -> None:
    now = deps.clock.now()
    mapped = [
        tool_evidence(r, event.head_sha, report.runner_name or "", now, deps.redactor)
        for r in results
    ]
    collected.items.extend(m for m in mapped if isinstance(m, EvidenceItem))
    collected.failures.extend(m for m in mapped if isinstance(m, Missing))
    attempted = {r.tool.name for r in results}
    reason = f"runner {report.status.value} before this tool ran: {report.note}"
    collected.failures.extend(
        Missing(k, reason) for k in _tool_keys(config) if k.name not in attempted
    )


def _blocks(
    event: PrEvent,
    pull: PullInfo,
    evidence: tuple[Evidence, ...],
    deps: Deps,
    config: ReviewConfig,
    collected: _Collected,
) -> tuple[UntrustedBlock, ...]:
    r = deps.redactor
    blocks = [
        UntrustedBlock(
            "pull-request", r(f"Title: {pull.title.text}\n\n{pull.body.text}")
        ),
        UntrustedBlock("diff", _diff(event, deps, collected)),
        UntrustedBlock("ci-and-runner-evidence", r(render_evidence(evidence))),
    ]
    blocks.extend(_issue_blocks(event, pull, deps, config, collected))
    return tuple(blocks)


def _diff(event: PrEvent, deps: Deps, collected: _Collected) -> RedactedText:
    try:
        return deps.redactor(
            deps.github.get_pull_diff(event.repo, event.pr_number), DIFF_CHARS
        )
    except BoundaryError as exc:
        collected.notes.append(
            f"The PR diff could not be fetched ({exc}); the narrative has no diff."
        )
        return deps.redactor("(diff unavailable)")


def _issue_blocks(
    event: PrEvent,
    pull: PullInfo,
    deps: Deps,
    config: ReviewConfig,
    collected: _Collected,
) -> list[UntrustedBlock]:
    if not config.include_issues:
        collected.notes.append("Issue context: off (opt in with `--include-issues`).")
        return []
    blocks = [_issue_block(event, n, deps, collected) for n in pull.issue_refs]
    return [b for b in blocks if b is not None]


def _issue_block(
    event: PrEvent, number: int, deps: Deps, collected: _Collected
) -> UntrustedBlock | None:
    try:
        issue = deps.github.get_issue(event.repo, number)
    except BoundaryError as exc:
        collected.notes.append(f"Issue #{number} could not be fetched: {exc}")
        return None
    text = f"Title: {issue.get('title', '')}\n\n{issue.get('body') or ''}"
    return UntrustedBlock(f"issue-{number}", deps.redactor(text, DETAIL_CHARS))


def _narrate(
    event: PrEvent, blocks: tuple[UntrustedBlock, ...], deps: Deps
) -> Narrative | NarrativeFailure:
    request = ReviewRequest(event.repo, event.pr_number, event.head_sha, blocks)
    try:
        return deps.harness.review(request)
    except BoundaryError as exc:
        return NarrativeFailure(deps.harness.name, str(exc))


def _redaction_total(
    pull: PullInfo, items: list[EvidenceItem], blocks: tuple[UntrustedBlock, ...]
) -> int:
    inner = pull.title.redaction_count + pull.body.redaction_count
    return (
        inner
        + sum(i.detail.redaction_count for i in items)
        + sum(b.content.redaction_count for b in blocks)
    )
