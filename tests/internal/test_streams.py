# vim: sw=4:ts=4:expandtab
"""
Tests the AnyIO streaming primitives in riko.bado.itertools: ``async_map_stream``
(concurrent, order-independent, bounded-memory) and ``async_map_ordered_stream``
(same bound, results in source order).
"""

import pytest

from riko.bado import Semaphore, async_sleep, isasync, lowlevel, run
from riko.bado.itertools import (
    async_map,
    async_map_ordered_stream,
    async_map_stream,
    async_merge,
)
from tests import aresolve


async def _double(x: int) -> int:
    return x * 2


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_maps_all_items_order_independent():
    results = aresolve(async_map_stream(_double, range(10), limit=4))
    assert sorted(results) == [x * 2 for x in range(10)]


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_empty_source_yields_nothing():
    assert aresolve(async_map_stream(_double, [], limit=4)) == []


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_accepts_async_source():
    async def gen():
        for i in range(5):
            yield i

    results = aresolve(async_map_stream(_double, gen(), limit=2))
    assert sorted(results) == [0, 2, 4, 6, 8]


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_backpressure_bounds_inflight():
    """An unbounded-ish source with a slow consumer must not run far ahead."""
    limit, buffer, total = 3, 2, 200

    async def main():
        produced = 0

        async def gen():
            nonlocal produced
            for i in range(total):
                produced += 1
                yield i

        seen = 0

        async for _ in async_map_stream(_double, gen(), limit=limit, buffer=buffer):
            seen += 1
            assert produced - seen <= limit + buffer + 2
            await lowlevel.checkpoint()

        return produced, seen

    produced, seen = run(main)
    assert produced == total
    assert seen == total


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_ordered_preserves_source_order_under_skew():
    """The slowest item is first, so an unordered map would reorder it."""

    async def slow_first(i: int) -> int:
        await async_sleep((5 - i) * 0.01)
        return i

    result = aresolve(async_map_ordered_stream(slow_first, range(6), limit=3))
    assert result == list(range(6))


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_ordered_empty_source_yields_nothing():
    assert aresolve(async_map_ordered_stream(_double, [], limit=4)) == []


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_ordered_backpressure_bounds_inflight():
    limit, buffer, total = 3, 2, 200

    async def main():
        produced = 0

        async def gen():
            nonlocal produced
            for i in range(total):
                produced += 1
                yield i

        seen = 0

        stream = async_map_ordered_stream(_double, gen(), limit=limit, buffer=buffer)

        async for _ in stream:
            seen += 1
            assert produced - seen <= 2 * (limit + buffer)
            await lowlevel.checkpoint()

        return produced, seen

    produced, seen = run(main)
    assert produced == total == seen


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_shared_budget_caps_nested_fanout():
    """
    A budget shared across the *leaf* maps caps their combined concurrency: an
    outer fan-out over 4 items, each fanning out to 5 leaf ops (20 potential),
    never exceeds a budget of 3. The outer stays unbudgeted (else it deadlocks).
    """
    state = {"current": 0, "peak": 0}

    async def main():
        budget = Semaphore(3)

        async def leaf(x: int) -> int:
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
            await async_sleep(0.01)
            state["current"] -= 1
            return x

        async def source(i: int) -> list[int]:
            leaves = async_map_stream(leaf, range(5), limit=10, budget=budget)
            return [r async for r in leaves]

        outer = async_map_stream(source, range(4), limit=10)
        return [r async for r in outer]

    results = run(main)
    assert len(results) == 4
    assert state["peak"] <= 3


@pytest.mark.skipif(not isasync, reason="anyio not installed")
@pytest.mark.parametrize("stream", [async_map_stream, async_map_ordered_stream])
def test_stream_rejects_bad_limit(stream):
    with pytest.raises(ValueError, match="limit must be at least 1"):
        aresolve(stream(_double, range(3), limit=0))


@pytest.mark.skipif(not isasync, reason="anyio not installed")
@pytest.mark.parametrize("stream", [async_map_stream, async_map_ordered_stream])
def test_stream_rejects_negative_buffer(stream):
    with pytest.raises(ValueError, match="buffer cannot be negative"):
        aresolve(stream(_double, range(3), buffer=-1))


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_async_map_rejects_negative_connections():
    with pytest.raises(ValueError, match="connections cannot be negative"):
        run(lambda: async_map(_double, range(3), -1))


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_async_map_allows_unlimited_connections():
    assert run(lambda: async_map(_double, range(3), 0)) == [0, 2, 4]


async def _afeed(items, delay=0.0):
    for item in items:
        if delay:
            await async_sleep(delay)

        yield item


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_async_merge_yields_all_records():
    feeds = [_afeed([1, 2]), _afeed([3, 4]), _afeed([5])]
    assert sorted(aresolve(async_merge(feeds, limit=2))) == [1, 2, 3, 4, 5]


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_async_merge_interleaves_across_feeds():
    """A fast feed's records surface before a slow feed finishes (incremental)."""

    async def main():
        slow = _afeed(["slow1", "slow2"], delay=0.05)
        fast = _afeed(["fast1", "fast2"])
        return [item async for item in async_merge([slow, fast], limit=2)]

    out = run(main)
    assert sorted(out) == ["fast1", "fast2", "slow1", "slow2"]
    assert out.index("fast2") < out.index("slow2")


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_async_merge_rejects_bad_limit():
    with pytest.raises(ValueError, match="limit must be at least 1"):
        aresolve(async_merge([_afeed([1])], limit=0))


@pytest.mark.skipif(not isasync, reason="anyio not installed")
def test_async_merge_rejects_negative_buffer():
    with pytest.raises(ValueError, match="buffer cannot be negative"):
        aresolve(async_merge([_afeed([1])], buffer=-1))
