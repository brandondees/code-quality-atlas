# SPDX-License-Identifier: MIT
# tests/test_ci_actions_are_sha_pinned.py
"""#496: every third-party action in .github/workflows/ci.yml is currently
pinned to a full commit SHA with a version comment -- correct today, but
nothing enforced that shape going forward. `actionlint` (the one workflow
linter this repo runs) doesn't check SHA-vs-tag pinning, so a future PR
adding e.g. `uses: some/action@v4` would pass every existing gate while
reintroducing a mutable, spoofable ref for a step that runs on every PR.

Mirrors this repo's established pattern of adding a permanent regression
test the moment an infra gap like this is found (`test_ci_pull_request_
runner_is_hosted.py` #471, `test_ci_shellcheck_glob_covers_tree.py` #379):
assert mechanically, from the workflow YAML itself, rather than trusting a
manual audit that the next PR won't repeat.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# A git commit SHA is 40 hex characters. GitHub Actions also accepts an
# abbreviated SHA in `uses:`, but that isn't actually pinned to one commit
# (it can become ambiguous as a repo grows) -- require the full form.
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _iter_uses_refs():
    """Yield (workflow_file, job_name, step_index, uses_value) for every
    `uses:` step across every workflow file, at every job's `steps:` list
    AND the top-level reusable-workflow `uses:` some jobs (currently none in
    this repo) can carry directly on the job itself, so a future reusable-
    workflow call isn't silently unchecked."""
    workflow_files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(
        WORKFLOWS_DIR.glob("*.yaml")
    )
    assert workflow_files, f"no workflow files found under {WORKFLOWS_DIR}"
    for wf_path in workflow_files:
        workflow = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        for job_name, job in (workflow.get("jobs") or {}).items():
            if isinstance(job, dict) and "uses" in job:
                yield wf_path, job_name, None, job["uses"]
            for i, step in enumerate(job.get("steps") or []):
                if isinstance(step, dict) and "uses" in step:
                    yield wf_path, job_name, i, step["uses"]


def _is_third_party_action_ref(uses: str) -> bool:
    """A `uses:` value is a pinnable third-party (or first-party-on-GitHub)
    action reference -- `owner/repo[/path]@ref` -- as opposed to a local
    composite action (`./path/to/action`, no ref to pin) or a Docker-image
    action (`docker://image:tag`, pinned by digest/tag, not a git SHA)."""
    return not uses.startswith("./") and not uses.startswith("docker://")


def test_workflow_files_exist():
    """Sanity check the other tests in this file rest on: an empty glob
    match would make every assertion below vacuously pass, hiding a real
    "CI moved and this guard now checks nothing" regression as green."""
    assert list(WORKFLOWS_DIR.glob("*.yml")) or list(WORKFLOWS_DIR.glob("*.yaml")), (
        f"{WORKFLOWS_DIR} has no workflow files -- has CI moved elsewhere? "
        "Update this guard's directory either way."
    )


def test_every_third_party_action_is_pinned_to_a_full_commit_sha():
    """The core #496 guard: a tag or branch ref (`@v4`, `@main`) is mutable
    and can be repointed by the action's maintainer -- or an attacker who
    compromises their account -- without any diff in this repo to review.
    Every non-local, non-Docker `uses:` must instead name one immutable
    commit."""
    unpinned = []
    for wf_path, job_name, step_index, uses in _iter_uses_refs():
        if not _is_third_party_action_ref(uses):
            continue
        if "@" not in uses:
            unpinned.append(
                (wf_path.name, job_name, step_index, uses, "no @ref at all")
            )
            continue
        ref = uses.rsplit("@", 1)[1]
        if not _FULL_SHA_RE.match(ref):
            location = f"job {job_name!r}" + (
                f", step {step_index}" if step_index is not None else ""
            )
            unpinned.append(
                (
                    wf_path.name,
                    job_name,
                    step_index,
                    uses,
                    f"{location} uses ref {ref!r}",
                )
            )
    assert not unpinned, (
        "the following `uses:` reference(s) are not pinned to a full "
        f"40-hex-char commit SHA: {unpinned} -- a tag or branch ref is "
        "mutable and can be repointed by the action's maintainer (or an "
        "attacker who compromises their account) without any diff in this "
        "repo to review. Pin to the exact commit SHA (keep the `# vX.Y.Z` "
        "comment for humans) as every other action in this file already is."
    )


def test_sha_pinned_actions_still_carry_a_human_readable_version_comment():
    """Not itself a security property, but the whole point of switching to a
    stable-looking SHA-vs-mutable-tag tradeoff (#496) is worthless if nobody
    can tell what version is actually pinned without resolving the commit on
    GitHub -- this repo's own existing pins all carry a trailing `# vX.Y.Z`
    comment for exactly that reason. Guard the convention, not just the
    security property, so a future pin bump doesn't quietly drop it."""
    missing_comment = []
    for wf_path in sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(
        WORKFLOWS_DIR.glob("*.yaml")
    ):
        for line_no, line in enumerate(
            wf_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = re.search(r"uses:\s*(\S+)@([0-9a-f]{40})(?!\S)(.*)$", line)
            if not match:
                continue
            trailing = match.group(3)
            if "#" not in trailing:
                missing_comment.append(f"{wf_path.name}:{line_no}: {line.strip()}")
    assert not missing_comment, (
        "the following SHA-pinned `uses:` line(s) have no trailing "
        f"`# vX.Y.Z`-style comment: {missing_comment} -- add one so a human "
        "reviewer can tell what's actually pinned without resolving the "
        "commit on GitHub."
    )
