# vim: sw=4:ts=4:expandtab
"""Async-only pipe lifecycle and source-adapter behavior."""

import pytest

from riko.bado.itertools import async_iter
from riko.base._paths import get_path
from riko.runtime.collections import AsyncCollection, AsyncPipe
from riko.types.modules import ItemBuilderConf
from tests import skipif_issync

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


@skipif_issync
class TestAsyncAwaitLifecycle:
    @pytest.mark.anyio
    async def test_await_after_partial_iteration_consumes_remainder(self):
        runs = []

        def count[T](item: T) -> T:
            runs.append(1)
            return item

        pipe = (
            AsyncPipe("itembuilder", conf=BUILDER_CONF)
            .tokenizer(emit=True)
            .udf(func=count)
        )
        assert await anext(pipe) == {"content": "a"}
        assert [item async for item in pipe] == [{"content": "b"}, {"content": "c"}]
        assert len(runs) == 3

    @pytest.mark.anyio
    async def test_await_twice_after_exhaustion_is_empty(self):
        pipe = AsyncPipe(source=list(SRC))
        assert list(await pipe) == SRC
        assert list(await pipe) == []

    @pytest.mark.anyio
    async def test_iteration_after_exhaustion_is_empty(self):
        pipe = AsyncPipe(source=list(SRC))
        assert [item async for item in pipe] == SRC
        assert [item async for item in pipe] == []

    @pytest.mark.anyio
    async def test_collection_await_after_partial_iteration_consumes_remainder(self):
        full = AsyncCollection([{"url": get_path("feed.xml")}])
        total = len([item async for item in full])
        stream = AsyncCollection([{"url": get_path("feed.xml")}])
        await anext(stream)
        rest = len(list(await stream))

        assert total > 1
        assert rest == total - 1

    @pytest.mark.anyio
    async def test_collection_iteration_after_partial_iteration_consumes_remainder(
        self,
    ):
        full = AsyncCollection([{"url": get_path("feed.xml")}])
        total = len([item async for item in full])
        stream = AsyncCollection([{"url": get_path("feed.xml")}])
        await anext(stream)
        rest = len([item async for item in stream])

        assert total > 1
        assert rest == total - 1

    @pytest.mark.anyio
    async def test_collection_async_pipe_after_partial_iteration_consumes_remainder(
        self,
    ):
        full = AsyncCollection([{"url": get_path("feed.xml")}])
        total = len([item async for item in full])
        stream = AsyncCollection([{"url": get_path("feed.xml")}])
        await anext(stream)
        child = stream.async_pipe()
        rest = len([item async for item in child])

        assert total > 1
        assert rest == total - 1


@skipif_issync
class TestAsyncSourceAdapter:
    """Exercise each source kind accepted by ``AsyncPipe._resolve_source``."""

    @pytest.mark.parametrize("make_source", GOOD_SOURCES)
    @pytest.mark.anyio
    async def test_source_iterates(self, make_source):
        pipe = AsyncPipe("hash", source=make_source())
        result = [item async for item in pipe]
        assert len(result) == len(SRC)

    @pytest.mark.parametrize("make_source", RAISING_SOURCES)
    @pytest.mark.anyio
    async def test_source_failure_propagates(self, make_source):
        pipe = AsyncPipe("hash", source=make_source())

        with pytest.raises(RuntimeError):
            [item async for item in pipe]

        assert pipe.failed

    @pytest.mark.parametrize("make_source", GOOD_SOURCES)
    @pytest.mark.anyio
    async def test_source_closes(self, make_source):
        pipe = AsyncPipe("hash", source=make_source())
        items = [item async for item in pipe]
        await pipe.aclose()
        assert len(items) == len(SRC)
        assert pipe.closed is True
