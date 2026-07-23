# vim: sw=4:ts=4:expandtab
"""
Tests the AnyIO streaming primitive (riko.bado.streams.async_map_stream):
concurrent mapping, order-independent results, and bounded-memory backpressure.
"""

import pytest

from riko.bado import isasync, lowlevel, run
from riko.bado.streams import async_map_stream

pytestmark = pytest.mark.skipif(not isasync, reason="anyio not installed")


async def _double(x: int) -> int:
    return x * 2


def test_maps_all_items_order_independent():
    async def main():
        results = [r async for r in async_map_stream(_double, range(10), limit=4)]
        return sorted(results)

    assert run(main) == [x * 2 for x in range(10)]


def test_empty_source_yields_nothing():
    async def main():
        return [r async for r in async_map_stream(_double, [], limit=4)]

    assert run(main) == []


def test_accepts_async_source():
    async def gen():
        for i in range(5):
            yield i

    async def main():
        results = [r async for r in async_map_stream(_double, gen(), limit=2)]
        return sorted(results)

    assert run(main) == [0, 2, 4, 6, 8]


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
