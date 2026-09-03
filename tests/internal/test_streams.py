# vim: sw=4:ts=4:expandtab
"""
Tests the AnyIO streaming primitives in riko.bado.itertools: ``async_map_stream``
(concurrent, order-independent, bounded-memory) and ``async_map_ordered_stream``
(same bound, results in source order).
"""

from time import monotonic

import pytest

from riko.bado._backend import Semaphore, async_sleep, lowlevel
from riko.bado._util import async_return, gather_results
from riko.bado.itertools import (
    async_map,
    async_map_ordered_stream,
    async_map_stream,
    async_merge,
)
from riko.modules.timeout import AsyncTimeoutIterator
from tests import aresolve, async_test, skipif_issync


@async_test
async def test_gather_results_preserves_none_positions():
    """A legitimate ``None`` result stays in place; the output aligns with inputs."""
    awaitables = [async_return(None), async_return(1), async_return(None)]
    result = await gather_results(awaitables)
    assert result == [None, 1, None]


async def _double(x: int) -> int:
    return x * 2


@pytest.mark.timeout(5)
@pytest.mark.xfail(
    strict=True,
    reason="AsyncTimeoutIterator only checks its deadline between anexts. A source that"
    "stalls past the deadline is awaited to completion rather than interrupted.",
)
@async_test
async def test_timeout_interrupts_a_stalled_source():
    """
    A stalled source must be abandoned after timeout, not awaited to completion.
    """

    async def source():
        yield {"x": 0}
        await async_sleep(1.0)
        yield {"x": 1}

    it = AsyncTimeoutIterator(source(), timeout_ms=50)
    start = monotonic()
    [item async for item in it]
    run_time = monotonic() - start
    assert run_time < 0.5


@skipif_issync
def test_maps_all_items_order_independent():
    results = aresolve(async_map_stream(_double, range(10), limit=4))
    assert sorted(results) == [x * 2 for x in range(10)]


@skipif_issync
def test_empty_source_yields_nothing():
    assert aresolve(async_map_stream(_double, [], limit=4)) == []


@skipif_issync
def test_accepts_async_source():
    async def gen():
        for i in range(5):
            yield i

    results = aresolve(async_map_stream(_double, gen(), limit=2))
    assert sorted(results) == [0, 2, 4, 6, 8]


@async_test
async def test_backpressure_bounds_inflight():
    """An unbounded-ish source with a slow consumer must not run far ahead."""
    limit, buffer, total = 3, 2, 200
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

    assert produced == total
    assert seen == total


@skipif_issync
def test_ordered_preserves_source_order_under_skew():
    """The slowest item is first, so an unordered map would reorder it."""

    async def slow_first(i: int) -> int:
        await async_sleep((5 - i) * 0.01)
        return i

    result = aresolve(async_map_ordered_stream(slow_first, range(6), limit=3))
    assert result == list(range(6))


@skipif_issync
def test_ordered_empty_source_yields_nothing():
    assert aresolve(async_map_ordered_stream(_double, [], limit=4)) == []


@async_test
async def test_ordered_backpressure_bounds_inflight():
    limit, buffer, total = 3, 2, 200
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

    assert produced == total == seen


@async_test
async def test_shared_budget_caps_nested_fanout():
    """
    A budget shared across the *leaf* maps caps their combined concurrency: an
    outer fan-out over 4 items, each fanning out to 5 leaf ops (20 potential),
    never exceeds a budget of 3. The outer stays unbudgeted (else it deadlocks).
    """
    state = {"current": 0, "peak": 0}
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
    results = [r async for r in outer]
    assert len(results) == 4
    assert state["peak"] <= 3


@skipif_issync
@pytest.mark.parametrize("stream", [async_map_stream, async_map_ordered_stream])
def test_stream_rejects_bad_limit(stream):
    with pytest.raises(ValueError, match="limit must be at least 1"):
        aresolve(stream(_double, range(3), limit=0))


@skipif_issync
@pytest.mark.parametrize("stream", [async_map_stream, async_map_ordered_stream])
def test_stream_rejects_negative_buffer(stream):
    with pytest.raises(ValueError, match="buffer cannot be negative"):
        aresolve(stream(_double, range(3), buffer=-1))


@async_test
async def test_async_map_rejects_negative_connections():
    with pytest.raises(ValueError, match="connections cannot be negative"):
        await async_map(_double, range(3), -1)


@async_test
async def test_async_map_allows_unlimited_connections():
    result = await async_map(_double, range(3), 0)
    assert result == [0, 2, 4]


async def _afeed(items, delay=0.0):
    for item in items:
        if delay:
            await async_sleep(delay)

        yield item


@skipif_issync
def test_async_merge_yields_all_records():
    feeds = [_afeed([1, 2]), _afeed([3, 4]), _afeed([5])]
    assert sorted(aresolve(async_merge(feeds, limit=2))) == [1, 2, 3, 4, 5]


@async_test
async def test_async_merge_interleaves_across_feeds():
    """A fast feed's records surface before a slow feed finishes (incremental)."""
    slow = _afeed(["slow1", "slow2"], delay=0.05)
    fast = _afeed(["fast1", "fast2"])
    out = [item async for item in async_merge([slow, fast], limit=2)]
    assert sorted(out) == ["fast1", "fast2", "slow1", "slow2"]
    assert out.index("fast2") < out.index("slow2")


@skipif_issync
def test_async_merge_rejects_bad_limit():
    with pytest.raises(ValueError, match="limit must be at least 1"):
        aresolve(async_merge([_afeed([1])], limit=0))


@skipif_issync
def test_async_merge_rejects_negative_buffer():
    with pytest.raises(ValueError, match="buffer cannot be negative"):
        aresolve(async_merge([_afeed([1])], buffer=-1))
