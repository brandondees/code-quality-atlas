# SPDX-License-Identifier: MIT
"""Shard the parity-key liveness specs across CI matrix jobs.

The liveness step is the single CI ``gate`` job's dominant cost because a
``mutant`` spec pays the anchor's whole test suite twice -- once as the
baseline, once under the splice -- and the anchor baselines are only cached
within one process. Sharding therefore puts each ``mutant`` spec in its own
shard, so its baseline runs in the same process as the splice it serves,
and lets the cheap ``quote``/``absent`` file reads ride in the first shard.

The shard list is computed from the parity key itself, never hardcoded in
the workflow: a new liveness-carrying key record is picked up automatically
(``shard_specs`` feeds the CI matrix job's output directly). Selection is
driven by a ``LIVENESS_SHARD=i/n`` environment variable that the liveness
test module reads at collection time; unset means "run everything", which
is what a contributor's local ``pytest atlas_reviewer/liveness`` does.

This module imports only the standard library so CI's shard-list job can
run it without installing the dependency set.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence

from atlas_reviewer.parity_key import KEY_DIR, KeyFinding, load_key

SHARD_ENV_VAR = "LIVENESS_SHARD"
# ``i/n``: 1-based shard index out of a declared total. A leading zero
# ("02/3") is not a shard index anyone writes by hand and is rejected, as
# is any other malformed shape, so a typo fails at collection instead of
# silently running the wrong slice.
_SPEC = re.compile(r"([1-9][0-9]*)/([1-9][0-9]*)")

Pair = tuple[KeyFinding, int]


def all_pairs() -> list[Pair]:
    """Every liveness spec in the key: one pair per (finding, spec index)."""
    pairs: list[Pair] = []
    for finding in load_key(KEY_DIR):
        for index in range(len(finding.liveness)):
            pairs.append((finding, index))
    return pairs


def label(pair: Pair) -> str:
    """The pytest id the liveness test module parametrizes this spec under."""
    finding, index = pair
    return f"{finding.id}-{finding.liveness[index].kind}-{index}"


def groups_for(pairs: Sequence[Pair]) -> list[list[Pair]]:
    """Partition specs into shards: one shard per ``mutant`` spec, with the
    quote/absent reads riding in the first shard.

    A mutant needs its anchor's baseline suite, and the baseline cache is
    per-process -- so the mutant and its baseline must land in the same
    shard, which one-shard-per-mutant guarantees by construction. The cheap
    specs join the first shard (deterministically: key file order, then
    finding order, then spec index -- ``load_key`` reads the JSON files in
    file name order) rather than getting a job of their own, because a
    quote/absent check is a file read, not a suite run.

    Never returns an empty partition: a key with no liveness specs at all
    yields one empty shard, so ``shard_specs`` and ``select_pairs`` keep a
    single consistent shape to agree on.
    """
    mutants: list[list[Pair]] = []
    cheap: list[Pair] = []
    for pair in pairs:
        if pair[0].liveness[pair[1]].kind == "mutant":
            mutants.append([pair])
        else:
            cheap.append(pair)
    if mutants:
        mutants[0].extend(cheap)
        return mutants
    return [cheap]


def shard_specs() -> list[str]:
    """The ``i/n`` spec for every shard, for CI's matrix to fan out over."""
    groups = groups_for(all_pairs())
    return [f"{index}/{len(groups)}" for index in range(1, len(groups) + 1)]


def _parse(spec: str) -> tuple[int, int]:
    match = _SPEC.fullmatch(spec.strip())
    if match is None:
        raise ValueError(
            f"{SHARD_ENV_VAR} must look like 'i/n' (1-based shard index of "
            f"its total), got {spec!r}"
        )
    index, total = int(match[1]), int(match[2])
    if index > total:
        raise ValueError(
            f"{SHARD_ENV_VAR} names shard {index} of {total}: the index "
            f"exceeds the total it declares, in {spec!r}"
        )
    return index, total


def select_pairs(pairs: Sequence[Pair], spec: str | None) -> list[Pair] | None:
    """The specs one CI shard should run.

    ``None`` means unsharded -- run everything (``LIVENESS_SHARD`` unset,
    the local-run default). A set ``spec`` selects exactly one shard's
    pairs; a malformed or out-of-range spec raises, so a bad value fails
    the job loudly instead of silently running nothing.
    """
    if spec is None:
        return None
    index, total = _parse(spec)
    groups = groups_for(pairs)
    if total != len(groups):
        raise ValueError(
            f"{SHARD_ENV_VAR} declares {total} shard(s) but the parity key "
            f"defines {len(groups)} -- the workflow's matrix and the key "
            "disagree; recompute the matrix from shard_specs()"
        )
    return groups[index - 1]


def select_from_env(
    pairs: Sequence[Pair], env: Mapping[str, str] | None = None
) -> list[Pair] | None:
    """``select_pairs`` against ``LIVENESS_SHARD`` in ``env`` (default: the
    process environment -- what the liveness test module reads at
    collection time). Takes the mapping as an argument so tests can drive
    it without mutating the real environment."""
    if env is None:
        env = os.environ
    return select_pairs(pairs, env.get(SHARD_ENV_VAR))
