# SPDX-License-Identifier: MIT
# tests/test_session_log_currency.py
"""docs/session-log.md's own header frames it as this project's working
narrative, but nothing enforced that narrative staying current: three
separate incidents (the #394-era gap, #513 opened 2026-09-18, #516 filed
2026-09-20) each found substantive PRs landing for three-to-five-day
stretches with no corresponding entry, caught only by luck of a later
scheduled audit noticing -- never by a mechanical gate.

This closes that loop with the simplest check that needs no git history at
all. A git-log-based "when did the last substantive commit land" check
would be unreliable here: this repo's CI checks out with `fetch-depth: 2`
(too shallow to walk back further), and on a `pull_request` run the
checked-out HEAD is GitHub's synthetic merge-ref commit, not the PR's own
commit -- its message and parentage aren't a reliable signal of what the
PR actually touched. Comparing the log's newest header to *today's* date
sidesteps both problems entirely: for a push-triggered run "today" IS
(within hours of) the landing commit's own date, and it's close enough for
a PR run authored around the same time.

This is NOT a perfect per-commit "did *this* commit need an entry" check --
it says nothing about whether an entry that does exist is any good. It's a
maintained tripwire against the multi-day silent drift the three incidents
above actually found, mirroring this repo's existing "good enough,
mechanically checked" gates (see
tests/test_ci_python_filter_covers_known_reads.py's own docstring for the
same trade-off made explicitly elsewhere).

A dependency-only PR landing after a quiet stretch used to trip this
through no fault of its own (#548) -- e.g. a Dependabot bump that touches
only requirements.txt, or only a pinned action SHA in ci.yml, days after
the log last got an entry from someone else's unrelated PR. ci.yml's
`tests` step now exports CI_EVENT_NAME plus a dedicated
`session_log_substantive` paths-filter output as
CI_FILTER_SESSION_LOG_SUBSTANTIVE; `_should_enforce_pr_diff_gate` below
uses them to skip the assertion on a `pull_request` run whose own diff
doesn't touch anything in that filter group. That group is deliberately
narrower than the `python` filter used elsewhere in this file (which also
gates the lint/mypy/eval steps and so, correctly for THAT purpose, includes
purely mechanical paths like `.github/workflows/ci.yml`/`pyproject.toml`):
reusing `python` verbatim here left a `github-actions`-ecosystem Dependabot
pin bump (which edits `ci.yml`) still tripping this gate, since `ci.yml` is
one of `python`'s paths (atlas review round 1 on #550). Touching
docs/session-log.md itself does NOT, on its own, exempt a PR from
enforcement -- only touching *something substantive* does; a substantive
PR that also edits the log still has its newly-added entry's date checked
by the existing `last <= today`/`not stale` assertions below, which pass
on their own once that entry is current (Copilot review round 1 on #550:
the file being touched proves nothing about whether the touch added a
*current* entry). `push`/`schedule` runs (and a contributor's local
`pytest`, which sets neither var) keep the original unconditional calendar
check: there is no single PR diff to reason about there, and that is
exactly the "many small, individually-innocent merges left the log stale"
case this test exists to catch.

Bump _SLACK_DAYS if this fires on a legitimate quiet stretch; do not delete
or skip the *test* to silence it -- `_should_enforce_pr_diff_gate`'s
`pytest.skip` below is a distinct, deliberate, narrowly-scoped mechanism
(diff-irrelevant pull_request runs only), not a workaround for the gate
firing on real drift.
"""

import os
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SESSION_LOG = ROOT / "docs" / "session-log.md"

_HEADER_DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})", re.MULTILINE)

# Generous on purpose: real work on this repo happens most days, but a
# legitimate quiet stretch (holidays, owner-only weeks) shouldn't be a false
# alarm. The three incidents this test guards against each ran 3-5 days
# before being caught -- this is set to fire before that repeats, not to
# fire on every multi-day gap.
_SLACK_DAYS = 5


def _latest_header_date(text: str) -> date:
    dates = _HEADER_DATE_RE.findall(text)
    assert dates, (
        f"{SESSION_LOG} has no '## YYYY-MM-DD' headers at all -- has its "
        "format changed? Update this test's parsing either way."
    )
    return max(date.fromisoformat(d) for d in dates)


def _is_stale(last_log_date: date, today: date, slack_days: int = _SLACK_DAYS) -> bool:
    return (today - last_log_date).days > slack_days


def _should_enforce_pr_diff_gate(env: dict[str, str] | None = None) -> bool:
    """Decide whether the calendar-staleness assertion applies to this run.

    `push`/`schedule` runs, and any invocation that doesn't set
    CI_EVENT_NAME at all (a contributor's local `pytest`), always enforce
    -- unconditional, same as before #548. A `pull_request` run only
    enforces when its own diff touches something in the
    `session_log_substantive` paths-filter group (
    CI_FILTER_SESSION_LOG_SUBSTANTIVE == "true"); otherwise this PR's own
    change can't be the cause of the drift and the assertion is skipped.
    Deliberately does NOT look at whether docs/session-log.md itself was
    touched -- that would let a substantive PR bypass the check by editing
    the file without adding a current entry (Copilot review round 1 on
    #550); the existing calendar assertions already validate sufficiency.
    """
    env = os.environ if env is None else env
    if env.get("CI_EVENT_NAME") != "pull_request":
        return True
    return env.get("CI_FILTER_SESSION_LOG_SUBSTANTIVE") == "true"


@pytest.mark.parametrize(
    ("last_log_date", "expected", "reason"),
    [
        (date(2026, 9, 15), False, "exactly at the slack boundary should not be stale"),
        (date(2026, 9, 14), True, "one day past the slack boundary should be stale"),
        (date(2026, 9, 20), False, "zero gap should never be stale"),
        (
            date(2026, 9, 25),
            False,
            "a future date alone isn't rejected here -- test_session_log_is_current's separate last <= today assertion does that",
        ),
    ],
)
def test_is_stale_pure_logic(last_log_date, expected, reason):
    base = date(2026, 9, 20)
    assert _is_stale(last_log_date, base, slack_days=5) is expected, reason


def test_latest_header_date_picks_the_max_not_the_last_occurrence():
    # Headers are expected in chronological order, but the parser doesn't
    # rely on that -- a manually-inserted backfill entry (exactly what
    # landed earlier in this file, out of file-order, still in date order)
    # must not fool it into picking an earlier date just because it's the
    # last line in a snippet.
    text = "## 2026-09-10 — a\n\n## 2026-09-05 — b\n"
    assert _latest_header_date(text) == date(2026, 9, 10)


@pytest.mark.parametrize(
    ("env", "expected", "reason"),
    [
        ({}, True, "no CI_EVENT_NAME (local pytest) always enforces"),
        (
            {"CI_EVENT_NAME": "push"},
            True,
            "push always enforces regardless of filter outputs",
        ),
        (
            {"CI_EVENT_NAME": "schedule"},
            True,
            "schedule always enforces -- no single diff to reason about",
        ),
        (
            {"CI_EVENT_NAME": "pull_request"},
            False,
            "missing filter output on a pull_request run can't be the cause either",
        ),
        (
            {
                "CI_EVENT_NAME": "pull_request",
                "CI_FILTER_SESSION_LOG_SUBSTANTIVE": "false",
            },
            False,
            (
                "PR touching nothing substantive (a dependency bump, Python "
                "or github-actions) can't be the cause"
            ),
        ),
        (
            {
                "CI_EVENT_NAME": "pull_request",
                "CI_FILTER_SESSION_LOG_SUBSTANTIVE": "true",
            },
            True,
            (
                "PR touches substantive code -- still enforced even if it "
                "also edits docs/session-log.md in the same diff; the "
                "calendar assertions, not this gate, judge whether that "
                "edit is current"
            ),
        ),
    ],
)
def test_should_enforce_pr_diff_gate(env, expected, reason):
    assert _should_enforce_pr_diff_gate(env) is expected, reason


def _load_ci_yml() -> dict:
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return yaml.safe_load(ci_text)


def test_ci_yml_wires_the_pr_diff_gate_env_vars():
    """Pins the CI wiring `_should_enforce_pr_diff_gate` depends on (atlas
    review round 1 on #550): a renamed filter key or a dropped/misnamed
    `env:` entry on the `tests` step would silently make
    CI_FILTER_SESSION_LOG_SUBSTANTIVE absent on every pull_request run --
    which `_should_enforce_pr_diff_gate` reads the same as "doesn't touch
    anything substantive", silently disabling this gate on every PR rather
    than erroring loudly.
    """
    ci = _load_ci_yml()
    steps = ci["jobs"]["gate"]["steps"]
    filter_step = next(
        s for s in steps if s.get("uses", "").startswith("dorny/paths-filter@")
    )
    filters = yaml.safe_load(filter_step["with"]["filters"])
    assert "session_log_substantive" in filters, (
        "ci.yml's paths-filter step no longer defines `session_log_substantive` "
        "-- _should_enforce_pr_diff_gate reads it via "
        "CI_FILTER_SESSION_LOG_SUBSTANTIVE"
    )

    tests_step = next(s for s in steps if s.get("name") == "tests")
    env = tests_step.get("env", {})
    assert env.get("CI_EVENT_NAME") == "${{ github.event_name }}", (
        "ci.yml's `tests` step must export CI_EVENT_NAME from github.event_name"
    )
    assert (
        env.get("CI_FILTER_SESSION_LOG_SUBSTANTIVE")
        == "${{ steps.filter.outputs.session_log_substantive }}"
    ), (
        "ci.yml's `tests` step must export CI_FILTER_SESSION_LOG_SUBSTANTIVE "
        "from steps.filter.outputs.session_log_substantive -- a renamed "
        "filter key here must be updated in lockstep"
    )


# The four purely mechanical paths `session_log_substantive` deliberately
# excludes from `python` (a path a Dependabot `github-actions`/`pip` bump
# can touch on its own, per the Major finding this filter split fixed).
_MECHANICAL_PATHS_EXCLUDED_FROM_SESSION_LOG_GATE = frozenset(
    {
        ".github/workflows/ci.yml",
        "pyproject.toml",
        ".python-version",
        ".pre-commit-config.yaml",
    }
)


def test_session_log_substantive_filter_tracks_python_filter():
    """`session_log_substantive` is hand-maintained in ci.yml as a copy of
    `python` minus four mechanical paths (atlas review round 2 on #550,
    Minor finding) -- a path added to `python` later but not mirrored here
    would silently make the pull_request gate skip for a PR touching only
    that new path, the same class of gap the filter split itself fixed.
    Pins the derived relationship instead of trusting the two
    hand-maintained lists to stay in sync.
    """
    ci = _load_ci_yml()
    steps = ci["jobs"]["gate"]["steps"]
    filter_step = next(
        s for s in steps if s.get("uses", "").startswith("dorny/paths-filter@")
    )
    filters = yaml.safe_load(filter_step["with"]["filters"])
    expected = [
        p
        for p in filters["python"]
        if p not in _MECHANICAL_PATHS_EXCLUDED_FROM_SESSION_LOG_GATE
    ]
    assert filters["session_log_substantive"] == expected, (
        "`session_log_substantive` has drifted from `python` minus the "
        "mechanical paths in ci.yml -- update it to match (see this test's "
        "docstring), or add the newly-mechanical path to "
        "_MECHANICAL_PATHS_EXCLUDED_FROM_SESSION_LOG_GATE above"
    )


def test_session_log_is_current():
    if not _should_enforce_pr_diff_gate():
        pytest.skip(
            "pull_request run whose own diff doesn't touch anything in the "
            "session_log_substantive filter group -- calendar staleness is "
            "still enforced on push/schedule (#548)."
        )
    text = SESSION_LOG.read_text(encoding="utf-8")
    last = _latest_header_date(text)
    # UTC, matching this repo's other date-stamped automation (the weekly
    # `schedule: cron` trigger in ci.yml is itself UTC) -- a naive
    # date.today() would silently use the runner's local timezone instead.
    today = datetime.now(UTC).date()
    # A future-dated header (a typo, or a clock skew during authoring) would
    # otherwise make `_is_stale` report "not stale" for the wrong reason --
    # catch that case explicitly rather than let it pass silently.
    assert last <= today, (
        f"docs/session-log.md's newest entry is dated {last}, which is in "
        f"the future relative to today ({today}) -- check for a typo."
    )
    assert not _is_stale(last, today), (
        f"docs/session-log.md's newest entry is dated {last}, more than "
        f"{_SLACK_DAYS} days before today ({today}). This has silently "
        "drifted before (the #394-era gap, #513, #516) -- add a "
        "session-log entry for whatever substantive work has landed "
        "since, even a short one, before merging."
    )
