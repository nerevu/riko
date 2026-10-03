# vim: sw=4:ts=4:expandtab
"""
Run lifetime and source adaptation for asynchronous pipeline iteration.

A ``Pipeline`` is a definition, not a run: the lifetime belongs to the execution
that each async iterator creates, so there is no pipeline-level state to inspect.
Iterating again starts a fresh execution, and closing an iterator tears that one
execution down without touching the definition.
"""

from __future__ import annotations

import pytest

from riko import Pipeline, parse_dag
from riko.bado.itertools import async_iter
from riko.base._paths import get_path
from riko.types._compiler import DagModule, PipeDag
from riko.types.modules import ConfArg, FetchRawConf, ItemBuilderConf
from tests import async_test

BUILDER_CONF = ItemBuilderConf({"attrs": [{"key": "content", "value": "a,b,c"}]})
SRC = [{"content": "x"}, {"content": "y"}]


def _boom():
    raise RuntimeError("boom")
    yield  # pragma: no cover


async def _coro_source():
    return list(SRC)


async def _raising_coro_source():
    raise RuntimeError("boom")


GOOD_SOURCES = [
    pytest.param(lambda: list(SRC), id="sync-iterable"),
    pytest.param(lambda: async_iter(SRC), id="async-iterable"),
    pytest.param(_coro_source, id="awaitable"),
]

RAISING_SOURCES = [
    pytest.param(_boom, id="sync-iterable"),
    pytest.param(lambda: async_iter(_boom()), id="async-iterable"),
    pytest.param(_raising_coro_source, id="awaitable"),
]


def _tokenized() -> Pipeline:
    source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
    return source.tokenizer(options={"emit": True})


def _fetch_node(index: int, url: str) -> DagModule:
    """Builds one fetch module entry for the fan-in dag."""
    conf = FetchRawConf({"url": ConfArg(type="url", value=url)})
    return DagModule(id=f"f{index}", type="fetch", conf=conf)


def _fanned_in(*urls: str) -> Pipeline:
    """Builds a pipeline whose single union node merges one fetch per url."""
    fetches = [_fetch_node(index, url) for index, url in enumerate(urls)]
    ports = ["in" if index == 0 else f"in:{index}" for index in range(len(urls))]
    wires = [[f"f{index}", "u", port] for index, port in enumerate(ports)]
    union = DagModule(id="u", type="union")
    dag = PipeDag(modules=[*fetches, union], wires=wires)
    return Pipeline(parse_dag(dag))


class TestAsyncSourceAdapter:
    """Every source kind an asynchronous execution accepts."""

    @pytest.mark.parametrize("make_source", GOOD_SOURCES)
    @async_test
    async def test_source_iterates(self, make_source):
        flow = make_source() | Pipeline.from_module("hash")
        assert len([item async for item in flow]) == len(SRC)

    @pytest.mark.parametrize("make_source", RAISING_SOURCES)
    @async_test
    async def test_source_failure_propagates(self, make_source):
        flow = make_source() | Pipeline.from_module("hash")

        with pytest.raises(RuntimeError, match="boom"):
            _ = [item async for item in flow]

    @pytest.mark.parametrize("make_source", GOOD_SOURCES)
    @async_test
    async def test_source_closes(self, make_source):
        flow = make_source() | Pipeline.from_module("hash")
        stream = aiter(flow)
        items = [item async for item in stream]
        await stream.aclose()
        assert len(items) == len(SRC)


class TestAsyncReiteration:
    @async_test
    async def test_module_source_replays(self):
        flow = _tokenized()
        assert len([item async for item in flow]) == 3
        assert len([item async for item in flow]) == 3

    @async_test
    async def test_one_shot_source_is_seen_consumed(self):
        flow = iter(SRC) | Pipeline.from_module("hash")
        assert len([item async for item in flow]) == len(SRC)
        assert [item async for item in flow] == []

    @async_test
    async def test_iteration_after_partial_iteration_restarts(self):
        flow = _tokenized()
        stream = aiter(flow)
        assert await anext(stream) == {"content": "a"}
        await stream.aclose()
        assert len([item async for item in flow]) == 3


class TestAsyncClose:
    @async_test
    async def test_close_before_the_first_item_never_runs_the_source(self):
        ran: list[int] = []

        async def source():
            ran.append(1)
            yield {"content": "x"}

        stream = aiter(source() | Pipeline.from_module("hash"))
        await stream.aclose()
        assert [item async for item in stream] == []
        assert ran == []

    @async_test
    async def test_close_is_idempotent(self):
        stream = aiter(_tokenized())
        await stream.aclose()
        await stream.aclose()
        assert [item async for item in stream] == []

    @async_test
    async def test_early_close_stops_a_partially_consumed_run(self):
        consumed: list[int] = []

        async def source():
            for index in range(20):
                consumed.append(index)
                yield {"content": str(index)}

        stream = aiter(source() | Pipeline.from_module("hash"))
        assert await anext(stream)
        await stream.aclose()
        assert len(consumed) < 20


class TestAsyncFanIn:
    @async_test
    async def test_fan_in_merges_every_source(self):
        single = _fanned_in(get_path("feed.xml"))
        doubled = _fanned_in(get_path("feed.xml"), get_path("feed.xml"))
        one = len([item async for item in single])
        both = len([item async for item in doubled])
        assert one
        assert both == 2 * one

    @async_test
    async def test_fan_in_replays(self):
        flow = _fanned_in(get_path("feed.xml"))
        first = [item async for item in flow]
        second = [item async for item in flow]
        assert first
        assert len(first) == len(second)

    @async_test
    async def test_fan_in_close_before_iteration_produces_nothing(self):
        stream = aiter(_fanned_in(get_path("feed.xml")))
        await stream.aclose()
        assert [item async for item in stream] == []
