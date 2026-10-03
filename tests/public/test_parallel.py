# vim: sw=4:ts=4:expandtab
"""
Bounded-parallelism tripwires for asynchronous pipeline iteration.

A pipeline carrying concurrency settings maps a loopable node over its source with
bounded concurrency and backpressure: results arrive as they complete unless
``ordered=True`` preserves source order, and the source advances only as workers
free up, so it is never pre-materialized. A fan-in graph gets the same treatment
over its source feeds.

The primitives' precise ``limit + buffer`` bound is covered in
``tests/internal/test_streams.py``. Here we assert the *pipeline-level* contract:
same results as sequential, order control, and non-materialization. Every case is
written against the settings surface it will have once concurrency lands.
"""

import pytest

from riko import Pipeline, parse_dag
from riko.base._paths import get_path
from riko.types._compiler import DagModule, PipeDag
from riko.types._guards import is_mapping
from riko.types.modules import ConfArg, FetchRawConf, ItemBuilderConf
from tests import skipif_issync

pytestmark = pytest.mark.slow

BUILDER_CONF = ItemBuilderConf({"attrs": {"key": "content", "value": "a,bb,ccc,dddd"}})
SOURCES = [get_path("feed.xml"), get_path("ouseful.xml")]

EXECUTION_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.with_execution() does not configure concurrency yet"
)


def _by_content(items):
    return sorted(items, key=lambda item: item["content"])


def _tokenized() -> Pipeline:
    source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
    return source.tokenizer(options={"emit": True}).hash(options={"assign": "h"})


def _fetch_node(index: int, url: str) -> DagModule:
    """Builds one fetch module entry for the fan-in dag."""
    conf = FetchRawConf({"url": ConfArg(type="url", value=url)})
    return DagModule(id=f"f{index}", type="fetch", conf=conf)


def _fanned_in(urls: list[str]) -> Pipeline:
    """Builds a pipeline whose single union node merges one fetch per url."""
    fetches = [_fetch_node(index, url) for index, url in enumerate(urls)]
    ports = ["in" if index == 0 else f"in:{index}" for index in range(len(urls))]
    wires = [[f"f{index}", "u", port] for index, port in enumerate(ports)]
    union = DagModule(id="u", type="union")
    dag = PipeDag(modules=[*fetches, union], wires=wires)
    return Pipeline(parse_dag(dag))


@skipif_issync
@EXECUTION_PENDING
class TestAsyncBoundedParallel:
    @pytest.mark.anyio
    async def test_parallel_matches_sequential_as_multiset(self):
        flow = _tokenized()
        sequential = [item async for item in flow]
        parallel = [item async for item in flow.with_execution(concurrency=4)]
        assert len(parallel) == len(sequential) == 4
        assert _by_content(parallel) == _by_content(sequential)

    @pytest.mark.anyio
    async def test_ordered_parallel_preserves_order(self):
        flow = _tokenized()
        sequential = [item async for item in flow]
        settings = flow.with_execution(concurrency=4, ordered=True)
        assert [item async for item in settings] == sequential

    @pytest.mark.parametrize("ordered", [False, True])
    @pytest.mark.anyio
    async def test_bounded_source_is_not_fully_drained(self, ordered):
        consumed: list[int] = []

        async def tracking():
            for index in range(20):
                consumed.append(index)
                yield {"content": str(index)}

        flow = (tracking() | Pipeline.from_module("hash")).with_execution(
            concurrency=2, ordered=ordered
        )
        stream = aiter(flow)
        first = await anext(stream)
        await stream.aclose()
        assert is_mapping(first)
        assert first.get("content") in {str(index) for index in range(20)}
        assert len(consumed) < 20

    @pytest.mark.parametrize("ordered", [False, True])
    @pytest.mark.anyio
    async def test_early_close_is_clean(self, ordered):
        """Ensure early closure tears down a bounded pipeline cleanly."""

        async def unbounded():
            index = 0

            while True:
                yield {"content": str(index)}
                index += 1

        flow = (unbounded() | Pipeline.from_module("hash")).with_execution(
            concurrency=2, ordered=ordered
        )
        stream = aiter(flow)
        first = await anext(stream)
        await stream.aclose()
        assert is_mapping(first)
        assert first.get("content")


@skipif_issync
@EXECUTION_PENDING
class TestAsyncFanInParallel:
    @pytest.mark.anyio
    async def test_ordered_matches_unordered_as_multiset(self):
        flow = _fanned_in(SOURCES)
        unordered = [item async for item in flow.with_execution(concurrency=2)]
        settings = flow.with_execution(concurrency=2, ordered=True)
        ordered = [item async for item in settings]
        assert unordered
        assert ordered
        assert sorted(map(str, ordered)) == sorted(map(str, unordered))

    @pytest.mark.parametrize("ordered", [False, True])
    @pytest.mark.anyio
    async def test_streams_more_sources_than_limit(self, ordered):
        urls = [get_path("feed.xml")] * 5
        single = [item async for item in _fanned_in(urls[:1])]
        flow = _fanned_in(urls).with_execution(concurrency=2, ordered=ordered)
        everything = [item async for item in flow]
        assert single
        assert len(everything) == 5 * len(single)
