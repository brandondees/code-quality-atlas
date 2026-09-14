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
_VERSION_COMMENT_RE = re.compile(r"#\s*v\d+(?:\.\d+){0,2}\s*$")


def _mapping_get(node: yaml.Node | None, key: str) -> yaml.Node | None:
    """Look up `key` in a composed YAML MappingNode, returning its value
    node (not a plain Python value -- callers that need the real value use
    `.value`, and every node still carries `.start_mark.line`)."""
    if node is None or not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return value_node
    return None


def _iter_uses_refs():
    """Yield (workflow_file, job_name, step_index, line_no, uses_value) for
    every `uses:` step across every workflow file, at every job's `steps:`
    list AND the top-level reusable-workflow `uses:` some jobs (currently
    none in this repo) can carry directly on the job itself, so a future
    reusable-workflow call isn't silently unchecked.

    Walks the composed YAML *node* tree (`yaml.compose`), not
    `yaml.safe_load`'s plain dicts, so each yielded `uses:` value carries
    its real source line (`start_mark.line`, 1-indexed here). This is what
    lets `test_sha_pinned_actions_still_carry_a_version_formatted_comment`
    below inspect that exact line's trailing comment (PyYAML doesn't
    preserve comments in its data model at all, so raw text is
    unavoidable) without a *separate* raw-text regex scan that could match
    an unrelated line merely mentioning `uses:` in prose rather than a real
    step (round-1 atlas review finding on this file, #496 PR)."""
    workflow_files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(
        WORKFLOWS_DIR.glob("*.yaml")
    )
    assert workflow_files, f"no workflow files found under {WORKFLOWS_DIR}"
    for wf_path in workflow_files:
        root = yaml.compose(wf_path.read_text(encoding="utf-8"))
        jobs_node = _mapping_get(root, "jobs")
        if not isinstance(jobs_node, yaml.MappingNode):
            continue
        for job_name_node, job_node in jobs_node.value:
            job_name = job_name_node.value
            job_uses = _mapping_get(job_node, "uses")
            if job_uses is not None:
                yield (
                    wf_path,
                    job_name,
                    None,
                    job_uses.start_mark.line + 1,
                    job_uses.value,
                )
            steps_node = _mapping_get(job_node, "steps")
            if not isinstance(steps_node, yaml.SequenceNode):
                continue
            for i, step_node in enumerate(steps_node.value):
                step_uses = _mapping_get(step_node, "uses")
                if step_uses is not None:
                    yield (
                        wf_path,
                        job_name,
                        i,
                        step_uses.start_mark.line + 1,
                        step_uses.value,
                    )


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
    for wf_path, job_name, step_index, line_no, uses in _iter_uses_refs():
        if not _is_third_party_action_ref(uses):
            continue
        if "@" not in uses:
            unpinned.append(f"{wf_path.name}:{line_no} ({uses!r}): no @ref at all")
            continue
        ref = uses.rsplit("@", 1)[1]
        if not _FULL_SHA_RE.match(ref):
            location = f"job {job_name!r}" + (
                f", step {step_index}" if step_index is not None else ""
            )
            unpinned.append(f"{wf_path.name}:{line_no} ({location}): uses ref {ref!r}")
    assert not unpinned, (
        "the following `uses:` reference(s) are not pinned to a full "
        f"40-hex-char commit SHA: {unpinned} -- a tag or branch ref is "
        "mutable and can be repointed by the action's maintainer (or an "
        "attacker who compromises their account) without any diff in this "
        "repo to review. Pin to the exact commit SHA (keep the `# vX.Y.Z` "
        "comment for humans) as every other action in this file already is."
    )


def test_sha_pinned_actions_still_carry_a_version_formatted_comment():
    """Not itself a security property, but the whole point of switching to a
    stable-looking SHA-vs-mutable-tag tradeoff (#496) is worthless if nobody
    can tell what version is actually pinned without resolving the commit on
    GitHub -- this repo's own existing pins all carry a trailing `# vX.Y.Z`
    comment for exactly that reason. Guard the *format* of that comment, not
    just the presence of some `#` (a `# TODO` would otherwise satisfy this),
    so a future pin bump doesn't quietly drop the human-readable version
    while technically keeping a comment."""
    lines_by_file: dict[Path, list[str]] = {}
    missing_or_malformed = []
    for wf_path, _job_name, _step_index, line_no, uses in _iter_uses_refs():
        if not _is_third_party_action_ref(uses) or "@" not in uses:
            continue
        ref = uses.rsplit("@", 1)[1]
        if not _FULL_SHA_RE.match(ref):
            continue  # not SHA-pinned; test_every_third_party_action_... flags this
        if wf_path not in lines_by_file:
            lines_by_file[wf_path] = wf_path.read_text(encoding="utf-8").splitlines()
        line = lines_by_file[wf_path][line_no - 1]
        _, _, trailing = line.partition(f"@{ref}")
        if not _VERSION_COMMENT_RE.search(trailing):
            missing_or_malformed.append(f"{wf_path.name}:{line_no}: {line.strip()}")
    assert not missing_or_malformed, (
        "the following SHA-pinned `uses:` line(s) have no trailing "
        f"`# vX.Y.Z`-style version comment: {missing_or_malformed} -- add "
        "one (or fix its format) so a human reviewer can tell what's "
        "actually pinned without resolving the commit on GitHub."
    )
