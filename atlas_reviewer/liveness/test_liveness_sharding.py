# SPDX-License-Identifier: MIT
"""Behavioral tests for the LIVENESS_SHARD selector the CI matrix drives.

These run inside every shard's own ``pytest atlas_reviewer/liveness`` job
too, so they take the shard spec as an argument and never read the process
environment: a shard's own ``LIVENESS_SHARD`` cannot change what they
assert. They assert observable selection behavior -- which specs a shard
runs -- not internals of the grouping.
"""

from collections.abc import Sequence

import pytest

from atlas_reviewer.liveness import sharding
from atlas_reviewer.liveness.sharding import Pair

# The spec kinds the grouping branches on, spelled out where the tests
# lean on them rather than re-derived from fixture JSON by hand.
_MUTANT = "mutant"


def _labels(pairs: Sequence[Pair]) -> list[str]:
    return [sharding.label(pair) for pair in pairs]


def _mutant_labels(pairs: Sequence[Pair]) -> list[str]:
    return [
        sharding.label(pair)
        for pair in pairs
        if pair[0].liveness[pair[1]].kind == _MUTANT
    ]


def test_every_spec_lands_in_exactly_one_shard() -> None:
    pairs = sharding.all_pairs()
    assert pairs, (
        "the parity key carries no liveness specs at all -- the sharded "
        "liveness jobs would all run empty while looking green. Restore "
        "the key's liveness entries."
    )
    groups = sharding.groups_for(pairs)
    seen = [label for group in groups for label in _labels(group)]
    assert sorted(seen) == sorted(_labels(pairs))
    assert len(seen) == len(set(seen)), "a spec landed in more than one shard"


def test_shard_count_matches_the_emitted_specs() -> None:
    pairs = sharding.all_pairs()
    specs = sharding.shard_specs()
    groups = sharding.groups_for(pairs)
    assert len(specs) == len(groups)
    for index, spec in enumerate(specs, start=1):
        assert sharding.select_pairs(pairs, spec) == groups[index - 1]


def test_unset_shard_selects_all_specs() -> None:
    pairs = sharding.all_pairs()
    # None is the caller-visible "unsharded: run everything" result the
    # liveness test module maps to the full parametrize list.
    assert sharding.select_pairs(pairs, None) is None
    assert sharding.select_from_env(pairs, env={}) is None


def test_each_spec_selects_its_own_shards_labels() -> None:
    pairs = sharding.all_pairs()
    groups = sharding.groups_for(pairs)
    for index, group in enumerate(groups, start=1):
        selected = sharding.select_pairs(pairs, f"{index}/{len(groups)}")
        assert selected is not None
        assert sorted(_labels(selected)) == sorted(_labels(group))


def test_each_mutant_gets_its_own_shard_and_the_cheap_reads_share_one() -> None:
    pairs = sharding.all_pairs()
    mutants = _mutant_labels(pairs)
    assert mutants, "the test's shape assumes the key still carries mutants"
    groups = sharding.groups_for(pairs)
    shards_with_mutant = [
        [label for label in _labels(group) if label in mutants] for group in groups
    ]
    # Each mutant alone in its shard, so its anchor baseline (cached
    # per-process) runs beside the splice it serves.
    assert sorted(label for labels in shards_with_mutant for label in labels) == (
        sorted(mutants)
    )
    assert all(len(labels) == 1 for labels in shards_with_mutant if labels)
    # The quote/absent reads ride in exactly one shard (the first), not a
    # job of their own.
    cheap = [label for label in _labels(pairs) if label not in mutants]
    if cheap:
        assert [label for label in _labels(groups[0]) if label in cheap] == cheap
        assert all(
            not [label for label in _labels(group) if label in cheap]
            for group in groups[1:]
        )


def test_grouping_is_deterministic_across_calls() -> None:
    pairs = sharding.all_pairs()
    first = [_labels(group) for group in sharding.groups_for(pairs)]
    second = [_labels(group) for group in sharding.groups_for(pairs)]
    assert first == second


@pytest.mark.parametrize(
    "spec",
    ["", "nonsense", "1", "0/2", "02/3", "1/0", "3/2", "2/", "/2", "1/2/3"],
)
def test_a_malformed_or_out_of_range_spec_fails_loudly(spec: str) -> None:
    pairs = sharding.all_pairs()
    with pytest.raises(ValueError, match="LIVENESS_SHARD"):
        sharding.select_pairs(pairs, spec)


def test_a_spec_total_the_key_does_not_define_fails_loudly() -> None:
    pairs = sharding.all_pairs()
    groups = sharding.groups_for(pairs)
    wrong_total = f"1/{len(groups) + 1}"
    with pytest.raises(ValueError, match="defines"):
        sharding.select_pairs(pairs, wrong_total)
    # The workflow computes the total from the key, so this mismatch can
    # only mean the two disagree mid-flight. An index past a total that
    # DOES match the key fails at the parse instead.
    with pytest.raises(ValueError, match="exceeds the total"):
        sharding.select_pairs(pairs, f"{len(groups) + 1}/{len(groups)}")
