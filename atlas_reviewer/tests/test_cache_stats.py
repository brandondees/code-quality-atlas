# SPDX-License-Identifier: MIT
"""The prompt-cache session tracker and its run-summary lines (issue #695).

Pure unit tests over reported usage numbers; no model call."""

from atlas_reviewer.cache_stats import (
    CacheLedger,
    CacheSession,
    CacheTurn,
    by_label,
    session_lines,
)


def turn(prompt, cached=None, written=None):
    return CacheTurn(prompt, cached, written)


def session(label, *turns):
    return CacheSession(label, tuple(turns))


# --- the miss rule ---------------------------------------------------------


def test_the_first_turn_of_a_session_is_never_a_miss():
    one = session("", turn(20_000, cached=0, written=20_000))
    assert one.misses == 0


def test_a_turn_that_reads_the_previous_prompt_is_a_hit():
    one = session(
        "",
        turn(20_000, cached=0, written=20_000),
        turn(26_000, cached=20_000, written=6_000),
    )
    assert one.misses == 0


def test_a_turn_short_of_the_previous_prompt_is_a_miss():
    one = session(
        "",
        turn(20_000, cached=0, written=20_000),
        turn(26_000, cached=100, written=25_900),
    )
    assert one.misses == 1


def test_a_turn_with_no_reported_cache_count_is_a_miss():
    one = session("", turn(20_000, written=20_000), turn(26_000))
    assert one.misses == 1


def test_a_turn_whose_previous_prompt_is_unreported_is_a_miss():
    one = session("", turn(None), turn(26_000, cached=25_000))
    assert one.misses == 1


def test_every_turn_after_the_first_counts_when_no_cache_counts_arrive():
    one = session("", turn(10), turn(20), turn(30))
    assert one.misses == 2


def test_misses_count_each_failing_turn_not_the_session():
    one = session(
        "",
        turn(20_000, cached=0, written=20_000),
        turn(26_000, cached=100),
        turn(30_000, cached=26_000),
        turn(34_000, cached=0),
    )
    assert one.misses == 2


# --- the per-session figures ----------------------------------------------


def test_cache_writes_sum_and_unreported_writes_add_nothing():
    one = session(
        "",
        turn(20_000, cached=0, written=20_000),
        turn(26_000, cached=20_000, written=6_000),
        turn(30_000, cached=26_000),
    )
    assert one.cache_write_tokens == 26_000
    assert one.final_prompt_tokens == 30_000


def test_final_context_is_the_last_reported_prompt_count():
    one = session("", turn(20_000), turn(None), turn(30_000), turn(None))
    assert one.final_prompt_tokens == 30_000


def test_a_session_with_no_reported_prompt_counts_has_no_final_context():
    one = session("", turn(None), turn(None))
    assert one.final_prompt_tokens is None


# --- the ledger ------------------------------------------------------------


def test_a_session_opens_on_start_and_closes_on_the_next_start():
    ledger = CacheLedger()
    ledger.start_session("lens-a")
    ledger.observe(20_000, 0, 20_000)
    ledger.observe(26_000, 20_000, 6_000)
    ledger.start_session("lens-b")
    ledger.observe(30_000, 0, 30_000)
    first, second = ledger.sessions()
    assert first.label == "lens-a"
    assert len(first.turns) == 2
    assert second.label == "lens-b"
    assert len(second.turns) == 1


def test_sessions_closes_the_open_session_and_an_empty_start_records_nothing():
    ledger = CacheLedger()
    ledger.start_session("lens-a")
    ledger.start_session("lens-b")
    ledger.observe(10, 0, 10)
    (only,) = ledger.sessions()
    assert only.label == "lens-b"
    assert len(only.turns) == 1


def test_an_observation_with_no_session_opens_an_unlabeled_one():
    ledger = CacheLedger()
    ledger.observe(10, 0, 10)
    ledger.observe(20, 10, 10)
    (only,) = ledger.sessions()
    assert only.label == ""
    assert only.misses == 0


def test_sessions_repeatedly_return_the_same_closed_sessions():
    ledger = CacheLedger()
    ledger.start_session("lens-a")
    ledger.observe(10, 0, 10)
    first = ledger.sessions()
    assert ledger.sessions() == first


# --- the summary lines -----------------------------------------------------


def test_one_session_renders_no_total_line():
    lines = session_lines([session("lens-a", turn(20_000, cached=0, written=20_000))])
    assert lines == (
        (
            "session 1 (lens-a): 1 turn(s), 0 cache miss(es), 20000 cache-write "
            "token(s), final context 20000 token(s)."
        ),
    )


def test_several_sessions_render_a_total_line_to_check_writes_against_context():
    lines = session_lines(
        [
            session(
                "lens-a",
                turn(20_000, cached=0, written=20_000),
                turn(26_000, cached=20_000, written=6_000),
            ),
            session("lens-b", turn(30_000, cached=0, written=30_000)),
        ]
    )
    assert lines[0] == (
        "session 1 (lens-a): 2 turn(s), 0 cache miss(es), 26000 cache-write "
        "token(s), final context 26000 token(s)."
    )
    assert lines[1] == (
        "session 2 (lens-b): 1 turn(s), 0 cache miss(es), 30000 cache-write "
        "token(s), final context 30000 token(s)."
    )
    assert lines[2] == (
        "total: 3 turn(s), 0 cache miss(es), 56000 cache-write token(s) "
        "against 56000 token(s) of final context."
    )


def test_an_unlabeled_session_keeps_its_ordinal():
    lines = session_lines([session("", turn(10))])
    assert lines[0].startswith("session 1:")


def test_a_total_with_no_reported_context_says_so():
    lines = session_lines([session("", turn(None)), session("", turn(None))])
    assert lines[-1].endswith("against no reported tokens of final context.")


def test_a_custom_label_renderer_replaces_the_default():
    lines = session_lines(
        [session("hunting-silent-failures", turn(10))],
        label_of=lambda _session, number: f"lens {number}",
    )
    assert lines[0].startswith("lens 1:")


# --- the draft's ordering (round-2 review, Nit 1) ---------------------------


def test_by_label_orders_sessions_by_lens_and_keeps_each_lens_attempt_order():
    sessions = [
        session("tracing-correctness-and-invariants", turn(30_000)),
        session("sweeping-for-security", turn(10_000)),
        session(
            "tracing-correctness-and-invariants", turn(20_000), turn(26_000, 20_000)
        ),
        session("reviewing-concurrency-and-async", turn(40_000)),
    ]
    ordered = by_label(sessions)
    assert [s.label for s in ordered] == [
        "reviewing-concurrency-and-async",
        "sweeping-for-security",
        "tracing-correctness-and-invariants",
        "tracing-correctness-and-invariants",
    ]
    # The stable sort keeps the lens's own attempts in run order: the
    # one-turn attempt stays ahead of the two-turn one.
    assert [len(s.turns) for s in ordered if s.label.startswith("tracing")] == [1, 2]


def test_the_rendered_lines_follow_the_by_label_order():
    sessions = by_label(
        [
            session("tracing-correctness-and-invariants", turn(30_000)),
            session("sweeping-for-security", turn(10_000)),
        ]
    )
    lines = session_lines(sessions)
    assert lines[0].startswith("session 1 (sweeping-for-security):")
    assert lines[1].startswith("session 2 (tracing-correctness-and-invariants):")
