# vim: sw=4:ts=4:expandtab
"""
Bounded-parallelism for the async engine (P10). A ``parallel=True`` AsyncPipe
maps a loopable pipe over its source with bounded concurrency and backpressure:
``async_map_stream`` yields results as they complete (unordered, matching sync's
``imap_unordered`` default) while ``async_map_ordered_stream`` (``ordered=True``)
preserves source order — both advance the source only as workers free up, so it
is never pre-materialized. ``AsyncCollection`` uses the same seam over its source
feeds (always fanned out).

The primitives' precise ``limit + buffer`` bound is covered in
``tests/internal/test_streams.py``; here we assert the *pipe/collection-level*
contract: same results as sequential, order control, and non-materialization.
"""

import pytest

from riko import get_path
from riko.bado import run
from riko.collections import AsyncCollection, AsyncPipe
from riko.types.modules import ItemBuilderConf
from tests import skipif_issync

BUILDER_CONF = ItemBuilderConf({"attrs": {"key": "content", "value": "a,bb,ccc,dddd"}})
SOURCES = [{"url": get_path("feed.xml")}, {"url": get_path("ouseful.xml")}]


def _by_content(items):
    return sorted(items, key=lambda item: item["content"])


@skipif_issync
class TestAsyncBoundedParallel:
    def test_parallel_matches_sequential_as_multiset(self):
        def build(parallel):
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF, parallel=parallel)
            return pipe.tokenizer(emit=True).hash(assign="h")

        async def main():
            seq = [item async for item in build(False)]
            par = [item async for item in build(True)]
            return seq, par

        seq, par = run(main)
        assert len(par) == len(seq) == 4
        assert _by_content(par) == _by_content(seq)

    def test_ordered_parallel_preserves_order(self):
        async def main():
            pipe = (
                AsyncPipe("itembuilder", conf=BUILDER_CONF)
                .tokenizer(emit=True)
                .hash(assign="h")
            )
            seq = [item async for item in pipe]

            pipe = (
                AsyncPipe("itembuilder", conf=BUILDER_CONF, parallel=True, ordered=True)
                .tokenizer(emit=True)
                .hash(assign="h")
            )
            par = [item async for item in pipe]
            return seq, par

        seq, par = run(main)
        assert par == seq

    @pytest.mark.parametrize("ordered", [False, True])
    def test_bounded_source_is_not_fully_drained(self, ordered):
        consumed: list[int] = []

        async def tracking():
            for index in range(20):
                consumed.append(index)
                yield {"content": str(index)}

        async def main():
            pipe = AsyncPipe(
                "hash",
                source=tracking(),
                parallel=True,
                ordered=ordered,
                connections=2,
            )
            first = await anext(pipe)
            await pipe.aclose()
            return first

        first = run(main)
        assert first.get("content") in {str(i) for i in range(20)}
        assert len(consumed) < 20

    @pytest.mark.parametrize("ordered", [False, True])
    def test_early_close_is_clean(self, ordered):
        """
        Closing a bounded pipe mid-flight (via ``async with`` + ``break``) tears
        the inner task-group stream down in the owning task — no cross-task
        cancel-scope error, no wrapped ``GeneratorExit`` (P7.5).
        """

        async def unbounded():
            index = 0

            while True:
                yield {"content": str(index)}
                index += 1

        async def main():
            pipe = AsyncPipe(
                "hash",
                source=unbounded(),
                parallel=True,
                ordered=ordered,
                connections=2,
            )
            async with pipe:
                async for item in pipe:
                    return item

        first = run(main)
        assert first.get("content") is not None


@skipif_issync
class TestAsyncCollectionParallel:
    def test_ordered_matches_unordered_as_multiset(self):
        async def main():
            unordered = [item async for item in AsyncCollection(SOURCES)]
            ordered = [item async for item in AsyncCollection(SOURCES, ordered=True)]
            return unordered, ordered

        unordered, ordered = run(main)
        assert unordered
        assert ordered
        assert sorted(map(str, ordered)) == sorted(map(str, unordered))

    @pytest.mark.parametrize("ordered", [False, True])
    def test_streams_more_sources_than_limit(self, ordered):
        sources = [{"url": get_path("feed.xml")}] * 5

        async def main():
            single = [item async for item in AsyncCollection(sources[:1])]
            collection = AsyncCollection(sources, ordered=ordered, connections=2)
            everything = [item async for item in collection]
            return single, everything

        single, everything = run(main)
        assert single
        assert len(everything) == 5 * len(single)
