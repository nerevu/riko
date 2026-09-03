# vim: sw=4:ts=4:expandtab
"""
One-shot lifecycle tests.

A pipe instance represents a single execution. It may be chained while NEW,
RUNNING, or EXHAUSTED — chaining wraps whatever source is left (all / leftovers /
nothing), like a native iterator; only a CLOSED or FAILED instance rejects
chaining with PipelineStateError. Iteration never raises: an exhausted, closed,
or failed instance re-iterates as an empty stream and never silently re-executes.
Sync and async behave alike, so ``TestSyncLifecycle`` and ``TestAsyncLifecycle``
mirror each other test-for-test.
"""

import pytest

from riko.bado.itertools import async_iter
from riko.collections import (
    AsyncCollection,
    AsyncPipe,
    PipeState,
    SyncCollection,
    SyncPipe,
)
from riko.exceptions import PipelineStateError
from riko.paths import get_path
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


# The three source kinds `AsyncPipe._resolve_source` accepts.
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


class TestSyncLifecycle:
    def test_new_state(self):
        assert SyncPipe("hash", source=SRC).state is PipeState.NEW

    def test_exhausted_after_full_iteration(self):
        flow = SyncPipe("hash", source=SRC)
        assert len(list(flow)) == 2
        assert flow.exhausted
        assert flow.state is PipeState.EXHAUSTED

    def test_exhausted_reiterates_empty_without_reexecution(self):
        flow = SyncPipe("hash", source=SRC)
        first = list(flow)
        second = list(flow)
        assert len(first) == 2
        assert second == []

    def test_chain_while_new_is_allowed(self):
        chained = SyncPipe("itembuilder", conf=BUILDER_CONF).hash()
        assert chained.state is PipeState.NEW

    def test_chain_after_partial_iteration_wraps_remainder(self):
        flow = SyncPipe("hash", source=SRC)
        next(flow)
        assert flow.state is PipeState.RUNNING
        assert list(flow.count()) == [{"count": 1}]

    def test_chain_after_exhaustion_is_allowed(self):
        flow = SyncPipe("hash", source=SRC)
        list(flow)
        assert list(flow.count()) == [{"count": 0}]

    def test_close_is_idempotent(self):
        flow = SyncPipe("hash", source=SRC)
        flow.close()
        flow.close()
        assert flow.closed
        assert flow.state is PipeState.CLOSED

    def test_chain_after_close_raises(self):
        flow = SyncPipe("hash", source=SRC)
        flow.close()

        with pytest.raises(PipelineStateError):
            flow.count()

    def test_chain_after_failure_raises(self):
        flow = SyncPipe("hash", source=_boom())

        with pytest.raises(RuntimeError):
            list(flow)

        with pytest.raises(PipelineStateError):
            flow.count()

    def test_iterate_after_run_then_close_is_empty(self):
        flow = SyncPipe("hash", source=SRC)
        assert len(list(flow)) == 2
        flow.close()
        assert list(flow) == []

    def test_close_before_iteration_does_not_execute(self):
        ran = []

        def source():
            ran.append(1)
            yield {"content": "x"}

        flow = SyncPipe("hash", source=source())
        flow.close()
        assert list(flow) == []
        assert ran == []

    def test_collection_close_before_iteration_does_not_execute(self):
        ran = []

        def sources():
            ran.append(1)
            yield {"url": get_path("feed.xml")}

        stream = SyncCollection(sources())
        stream.close()
        assert list(stream) == []
        assert ran == []

    def test_failed_state_reiterates_empty(self):
        flow = SyncPipe("hash", source=_boom())

        with pytest.raises(RuntimeError):
            list(flow)

        assert flow.state is PipeState.FAILED
        assert flow.failed
        assert list(flow) == []

    def test_context_manager_closes(self):
        with SyncPipe("hash", source=SRC) as flow:
            items = list(flow)

        assert len(items) == 2
        assert flow.closed
        assert flow.state is PipeState.CLOSED

    def test_collection_lifecycle(self):
        stream = SyncCollection([{"url": get_path("feed.xml")}])
        assert stream.state is PipeState.NEW
        assert list(stream)
        assert stream.exhausted
        assert list(stream) == []

    def test_collection_close_is_idempotent(self):
        stream = SyncCollection([{"url": get_path("feed.xml")}])
        stream.close()
        stream.close()
        assert stream.closed
        assert stream.state is PipeState.CLOSED

    def test_collection_failed_state(self):
        def boom_sources():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        stream = SyncCollection(boom_sources())

        try:
            list(stream)
        except RuntimeError:
            pass

        assert stream.state is PipeState.FAILED
        assert stream.failed
        assert list(stream) == []


@skipif_issync
class TestAsyncLifecycle:
    def test_new_state(self):
        assert AsyncPipe("itembuilder", conf=BUILDER_CONF).state is PipeState.NEW

    @pytest.mark.anyio
    async def test_exhausted_after_full_iteration(self):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
        items = [item async for item in pipe]
        assert items
        assert pipe.exhausted
        assert pipe.state is PipeState.EXHAUSTED

    @pytest.mark.anyio
    async def test_exhausted_reiterates_empty_without_reexecution(self):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
        first = [item async for item in pipe]
        second = [item async for item in pipe]
        assert first
        assert second == []

    def test_chain_while_new_is_allowed(self):
        chained = AsyncPipe("itembuilder", conf=BUILDER_CONF).hash()
        assert chained.state is PipeState.NEW

    @pytest.mark.anyio
    async def test_chain_after_partial_iteration_wraps_remainder(self):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
        await anext(pipe)
        assert pipe.state is PipeState.RUNNING
        assert [item async for item in pipe.count()] == [{"count": 2}]

    @pytest.mark.anyio
    async def test_chain_after_exhaustion_is_allowed(self):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
        [item async for item in pipe]
        result = [item async for item in pipe.count()]
        assert result == [{"count": 0}]

    @pytest.mark.anyio
    async def test_close_is_idempotent(self):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF)
        await pipe.aclose()
        await pipe.aclose()
        assert pipe.closed
        assert pipe.state is PipeState.CLOSED

    @pytest.mark.anyio
    async def test_chain_after_close_raises(self):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF)
        await pipe.aclose()

        with pytest.raises(PipelineStateError):
            pipe.tokenizer()

    @pytest.mark.anyio
    async def test_chain_after_failure_raises(self):
        async def boom():
            raise RuntimeError("boom")

        pipe = AsyncPipe(source=boom())

        try:
            [item async for item in pipe]
        except RuntimeError:
            pass

        with pytest.raises(PipelineStateError):
            pipe.tokenizer()

    @pytest.mark.anyio
    async def test_iterate_after_run_then_close_is_empty(self):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
        items = [item async for item in pipe]
        await pipe.aclose()
        after = [item async for item in pipe]
        assert items
        assert after == []

    @pytest.mark.anyio
    async def test_close_before_iteration_does_not_execute(self):
        ran = []

        async def source():
            ran.append(1)
            yield {"content": "x"}

        pipe = AsyncPipe("hash", source=source())
        await pipe.aclose()
        result = [item async for item in pipe]

        assert result == []
        assert ran == []

    @pytest.mark.anyio
    async def test_failed_state_reiterates_empty(self):
        async def boom():
            raise RuntimeError("boom")

        pipe = AsyncPipe(source=boom())

        try:
            [item async for item in pipe]
        except RuntimeError:
            pass

        reiter = [item async for item in pipe]

        assert pipe.state is PipeState.FAILED
        assert pipe.failed
        assert reiter == []

    @pytest.mark.anyio
    async def test_context_manager_closes(self):
        items = None

        async with AsyncPipe("itembuilder", conf=BUILDER_CONF) as pipe:
            items = [item async for item in pipe]

        assert items
        assert pipe.closed

    @pytest.mark.anyio
    async def test_collection_lifecycle(self):
        stream = AsyncCollection([{"url": get_path("feed.xml")}])
        assert stream.state is PipeState.NEW
        assert [item async for item in stream]
        assert stream.exhausted
        assert [item async for item in stream] == []

    @pytest.mark.anyio
    async def test_collection_close_is_idempotent(self):
        stream = AsyncCollection([{"url": get_path("feed.xml")}])
        await stream.aclose()
        await stream.aclose()
        assert stream.closed
        assert stream.state is PipeState.CLOSED

    @pytest.mark.anyio
    async def test_collection_close_before_iteration_does_not_execute(self):
        ran = []

        def sources():
            ran.append(1)
            yield {"url": get_path("feed.xml")}

        stream = AsyncCollection(sources())
        await stream.aclose()
        assert [item async for item in stream] == []
        assert stream.closed
        assert ran == []

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
        assert list(await pipe) == [{"content": "b"}, {"content": "c"}]
        assert len(runs) == 3

    @pytest.mark.anyio
    async def test_await_twice_after_exhaustion_is_empty(self):
        pipe = AsyncPipe(source=list(SRC))
        assert list(await pipe) == SRC
        assert list(await pipe) == []

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
    """
    ``AsyncPipe._resolve_source`` accepts a sync iterable (via ``async_iter``),
    an async iterable, and an awaitable. The lifecycle machine is source-agnostic
    once resolved, so only the source-touching behaviors are exercised per kind.
    """

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
