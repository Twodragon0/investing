"""Sharding correctness for the falsifiability harness.

The harness mutates real repository files, so two cases that target the same
file cannot run concurrently in one checkout. CI parallelises by *sharding*
instead: each matrix job gets a disjoint slice and its own checkout.

That only holds if the partition is exact. A shard split that silently dropped
a case would leave a guard unverified while CI stayed green — the same class of
failure the harness exists to catch.
"""

from __future__ import annotations

import pytest
from tools.guard_falsifiability import CASES, STATIC_CASES, parse_shard, select_shard


@pytest.mark.parametrize("total", [1, 2, 3, 5, 8, 47, 64])
def test_shards_partition_every_case_exactly_once(total: int) -> None:
    """Union of all shards == the full list, with no duplicates."""
    items = list(range(len(CASES) + len(STATIC_CASES)))
    collected: list[int] = []
    for index in range(1, total + 1):
        collected.extend(select_shard(items, (index, total)))

    assert sorted(collected) == items
    assert len(collected) == len(set(collected)), "a case landed in more than one shard"


def test_no_shard_argument_runs_everything() -> None:
    items = list(range(10))
    assert select_shard(items, None) == items


def test_shards_are_balanced_within_one_case() -> None:
    """Round-robin keeps sizes within 1 of each other, so no shard is the tail."""
    items = list(range(47))
    sizes = [len(select_shard(items, (i, 8))) for i in range(1, 9)]
    assert max(sizes) - min(sizes) <= 1


def test_more_shards_than_cases_yields_empty_slices_not_errors() -> None:
    items = list(range(3))
    slices = [select_shard(items, (i, 6)) for i in range(1, 7)]
    assert sum(len(s) for s in slices) == 3
    assert any(s == [] for s in slices)


@pytest.mark.parametrize("spec", ["3/8", "1/1", "8/8"])
def test_parse_shard_accepts_valid_specs(spec: str) -> None:
    index, total = parse_shard(spec)
    assert 1 <= index <= total


@pytest.mark.parametrize("spec", ["0/8", "9/8", "-1/4", "3/0", "abc", "3", "3/x", ""])
def test_parse_shard_rejects_invalid_specs(spec: str) -> None:
    """A malformed spec must stop the run, not silently verify a subset."""
    with pytest.raises(SystemExit):
        parse_shard(spec)
