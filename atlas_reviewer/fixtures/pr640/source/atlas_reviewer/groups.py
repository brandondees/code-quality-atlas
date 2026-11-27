# SPDX-License-Identifier: MIT
"""Group CI evidence that is one check seen several ways. Pure.

GitHub Actions reports one gate as a check run, a job (whose
`check_run_url` names that check run), the job's log, and the workflow run
containing it. They are one independent check with supporting evidence, so
the draft counts the check once. Links come only from ids the controller
read (`Link`); nothing is inferred from names.

A workflow run that explains itself through its jobs (it failed and a job
failed, or it is still pending and a job is) is context for those jobs. A run
no job explains stays an independent check, so a failure is never hidden by
grouping.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from atlas_reviewer.domain import Evidence, Matched, Outcome, SourceKind, outcome

RUN_KIND = SourceKind.WORKFLOW_RUN


@dataclass(frozen=True)
class Link:
    """`supporter` is one more view of `supported` (both are `source_id`s)."""

    supporter: str
    supported: str


@dataclass(frozen=True)
class CheckGroup:
    root: Matched
    supporting: tuple[Matched, ...]
    context: tuple[Matched, ...]
    outcome: Outcome


def _id(m: Matched) -> str:
    return m.item.provenance.source_id


def _is_run(m: Matched) -> bool:
    return m.item.provenance.key.kind is RUN_KIND


def group_checks(
    evidence: Iterable[Evidence], links: Iterable[Link]
) -> tuple[CheckGroup, ...]:
    """One group per independent check at the head SHA. Stale and missing
    evidence is never grouped; it stays UNKNOWN on its own."""
    matched = _by_id(evidence)
    edges = _usable_edges(matched, tuple(links))
    supported_by: dict[str, list[str]] = {}
    for link in edges:
        supported_by.setdefault(link.supported, []).append(link.supporter)
    has_parent = {link.supporter for link in edges}
    roots = sorted(set(matched) - has_parent)
    groups = [_group(matched, root, supported_by) for root in roots]
    covered = {*roots, *(i for root in roots for i in _members(root, supported_by))}
    # Only a cycle can leave evidence unreached; each stays a check of its own.
    groups += (
        CheckGroup(matched[i], (), (), _verdict((matched[i],)))
        for i in sorted(set(matched) - covered)
    )
    return tuple(groups)


def _by_id(evidence: Iterable[Evidence]) -> dict[str, Matched]:
    """Source ids are unique in practice; if two items ever share one, the
    later ones stay separate, ungrouped checks instead of being dropped."""
    matched: dict[str, Matched] = {}
    for e in evidence:
        if isinstance(e, Matched):
            key = _id(e)
            while key in matched:
                key += "#dup"
            matched[key] = e
    return matched


def _usable_edges(matched: dict[str, Matched], links: tuple[Link, ...]) -> list[Link]:
    present = [
        link
        for link in links
        if link.supporter in matched and link.supported in matched
    ]
    return [link for link in present if _explained(link, matched, present)]


def _explained(link: Link, matched: dict[str, Matched], links: list[Link]) -> bool:
    """A run supports a job only if some job of the run carries its verdict."""
    run = matched[link.supporter]
    if not _is_run(run):
        return True
    verdict = outcome(run)
    if verdict is Outcome.PASS:
        return True
    jobs = (matched[x.supported] for x in links if x.supporter == link.supporter)
    return any(outcome(job) is verdict for job in jobs)


def _members(root: str, supported_by: dict[str, list[str]]) -> list[str]:
    seen: dict[str, None] = {}
    stack = [root]
    while stack:
        for supporter in supported_by.get(stack.pop(), ()):
            if supporter not in seen and supporter != root:
                seen[supporter] = None
                stack.append(supporter)
    return sorted(seen)


def _group(
    matched: dict[str, Matched], root: str, supported_by: dict[str, list[str]]
) -> CheckGroup:
    members = [matched[i] for i in _members(root, supported_by)]
    supporting = tuple(m for m in members if not _is_run(m))
    context = tuple(m for m in members if _is_run(m))
    return CheckGroup(
        matched[root], supporting, context, _verdict((matched[root], *supporting))
    )


def _verdict(voters: Iterable[Matched]) -> Outcome:
    outcomes = {outcome(m) for m in voters} - {Outcome.INFO}
    for worst in (Outcome.FAIL, Outcome.UNKNOWN, Outcome.PASS):
        if worst in outcomes:
            return worst
    return Outcome.INFO
