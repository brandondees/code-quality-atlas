# SPDX-License-Identifier: MIT
# tests/test_ci_runners_are_github_hosted.py
"""D78 (2026-11-17): every event of every job in every workflow under
`.github/workflows/` runs on a GitHub-hosted runner. Before this, `ci.yml`'s
`gate` job used an event-conditional `runs-on:` expression -- `pull_request`
on `ubuntu-latest` (#471's fork-exposure narrowing), `push`/`schedule` on
the repo's self-hosted fleet -- and when that fleet's runner went down,
main's push runs sat `queued` indefinitely with no conclusion (the incident
that prompted D78).

This replaces the #471-era guard (`test_ci_pull_request_runner_is_hosted.py`,
removed in the same change), which pinned the split shape. The split's
rationale went away with the persistent hardware itself, so the guard flips:
every job's `runs-on` must be a plain hosted label -- no `self-hosted` label
anywhere, and no `${{ ... }}` expression conditioning the runner on
`github.event_name`, which is the shape the old split took. The guard globs
every `*.yml`/`*.yaml` workflow file, not just `ci.yml` (round-1 review of
#746, Minor 3: a second workflow file carrying `[self-hosted, Linux]`
slipped past the ci.yml-only version, exactly the silent re-add D78's
revisit trigger says must not pass unflagged), and asserts the glob is
non-empty so a moved/renamed workflows directory cannot silence it
vacuously. It does NOT (and can't, from a checkout) verify the Settings-side
protections #471's residual gap lives in (e.g. "Require approval for all
outside collaborators"); those are not represented in any file in this repo.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

_HOSTED_PREFIXES = ("ubuntu-", "windows-", "macos-")


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS_DIR.glob("*.y*ml"))
    assert files, (
        f"{WORKFLOWS_DIR} contains no *.yml/*.yaml workflow files -- has "
        "the directory moved or the extension changed? Update this guard's "
        "glob either way."
    )
    return files


def _job_runs_on_by_file() -> list[tuple[Path, str, object]]:
    found: list[tuple[Path, str, object]] = []
    for path in _workflow_files():
        # PyYAML parses the bare word `on:` as the boolean key `True` unless
        # quoted -- these files' `on:` keys are unquoted, so `jobs` is the
        # only top-level key safe to index by its literal string name here.
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        jobs = workflow.get("jobs", {}) if isinstance(workflow, dict) else {}
        assert jobs, (
            f"{path} defines no jobs -- an empty workflow is still a real "
            "file in the Actions tab, and this guard refuses to pass "
            "vacuously over it; if it is deliberately jobless, update this "
            "guard either way."
        )
        for name, job in jobs.items():
            found.append((path, name, job.get("runs-on")))
    return found


def test_every_job_in_every_workflow_runs_on_a_github_hosted_runner():
    for path, name, runs_on in _job_runs_on_by_file():
        assert isinstance(runs_on, str) and runs_on.startswith(_HOSTED_PREFIXES), (
            f"{path.name} job {name!r}'s runs-on is {runs_on!r} -- expected "
            "a plain GitHub-hosted runner label (ubuntu-latest or a pinned "
            "ubuntu image). A self-hosted label here routes runs to the "
            "personal fleet D78 moved this repo off."
        )


def test_no_job_conditions_its_runner_on_the_event():
    # The #471-era shape was an expression like
    # `pull_request && 'ubuntu-latest' || fromJSON('["self-hosted", ...]')`.
    # If that split ever comes back it would be an expression, not a bare
    # label -- catch it here rather than letting a push run silently queue
    # on the fleet again.
    for path, name, runs_on in _job_runs_on_by_file():
        assert "${{" not in str(runs_on), (
            f"{path.name} job {name!r}'s runs-on ({runs_on!r}) is an "
            "expression, not a plain label -- the event-conditional "
            "self-hosted/hosted split D78 removed appears to have come back."
        )
