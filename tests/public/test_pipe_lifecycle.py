# vim: sw=4:ts=4:expandtab
"""
One-shot lifecycle tests for the Phase 5 contract (docs/P5_CHECKLIST.md).

A pipe instance represents a single execution. It may be chained only while
NEW; once it has run it cannot be chained; an exhausted instance re-iterates as
an empty stream and never silently re-executes; a closed or failed instance
raises PipelineStateError on further iteration. Sync and async behave alike, so
``TestSyncLifecycle`` and ``TestAsyncLifecycle`` mirror each other test-for-test.
"""

import pytest

from riko import get_path
from riko.bado import issync, run
from riko.bado.itertools import async_iter
from riko.collections import (
    AsyncCollection,
    AsyncPipe,
    PipeState,
    SyncCollection,
    SyncPipe,
)
from riko.exceptions import PipelineStateError
from riko.types.modules import ItemBuilderConf

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


@pytest.mark.skipif(issync, reason="async support not available")
class TestAsyncLifecycle:
    def test_new_state(self):
        assert AsyncPipe("itembuilder", conf=BUILDER_CONF).state is PipeState.NEW

    def test_exhausted_after_full_iteration(self):
        result = {}

        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            result["items"] = [item async for item in pipe]
            result["exhausted"] = pipe.exhausted
            result["state"] = pipe.state

        run(main)

        assert result["items"]
        assert result["exhausted"]
        assert result["state"] is PipeState.EXHAUSTED

    def test_exhausted_reiterates_empty_without_reexecution(self):
        result = {}

        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            result["first"] = [item async for item in pipe]
            result["second"] = [item async for item in pipe]

        run(main)

        assert result["first"]
        assert result["second"] == []

    def test_chain_while_new_is_allowed(self):
        chained = AsyncPipe("itembuilder", conf=BUILDER_CONF).hash()
        assert chained.state is PipeState.NEW

    def test_chain_after_partial_iteration_wraps_remainder(self):
        result = {}

        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            await anext(pipe)
            result["state"] = pipe.state
            result["rest"] = [item async for item in pipe.count()]

        run(main)

        assert result["state"] is PipeState.RUNNING
        assert result["rest"] == [{"count": 2}]

    def test_chain_after_exhaustion_is_allowed(self):
        result = {}

        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            [item async for item in pipe]
            result["rest"] = [item async for item in pipe.count()]

        run(main)

        assert result["rest"] == [{"count": 0}]

    def test_close_is_idempotent(self):
        result = {}

        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF)
            await pipe.aclose()
            await pipe.aclose()
            result["closed"] = pipe.closed
            result["state"] = pipe.state

        run(main)

        assert result["closed"]
        assert result["state"] is PipeState.CLOSED

    def test_chain_after_close_raises(self):
        result = {}

        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF)
            await pipe.aclose()

            try:
                pipe.tokenizer()
            except PipelineStateError:
                result["raised"] = True

        run(main)

        assert result.get("raised") is True

    def test_chain_after_failure_raises(self):
        result = {}

        async def boom():
            raise RuntimeError("boom")

        async def main():
            pipe = AsyncPipe(source=boom())

            try:
                [item async for item in pipe]
            except RuntimeError:
                pass

            try:
                pipe.tokenizer()
            except PipelineStateError:
                result["raised"] = True

        run(main)

        assert result.get("raised") is True

    def test_iterate_after_run_then_close_is_empty(self):
        result = {}

        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            result["items"] = [item async for item in pipe]
            await pipe.aclose()
            result["after"] = [item async for item in pipe]

        run(main)

        assert result["items"]
        assert result["after"] == []

    def test_failed_state_reiterates_empty(self):
        result = {}

        async def boom():
            raise RuntimeError("boom")

        async def main():
            pipe = AsyncPipe(source=boom())

            try:
                [item async for item in pipe]
            except RuntimeError:
                pass

            result["failed"] = pipe.failed
            result["state"] = pipe.state
            result["reiter"] = [item async for item in pipe]

        run(main)

        assert result["state"] is PipeState.FAILED
        assert result["failed"]
        assert result["reiter"] == []

    def test_context_manager_closes(self):
        result = {}

        async def main():
            async with AsyncPipe("itembuilder", conf=BUILDER_CONF) as pipe:
                result["items"] = [item async for item in pipe]

            result["closed"] = pipe.closed

        run(main)

        assert result["items"]
        assert result["closed"]

    def test_collection_lifecycle(self):
        result = {}

        async def main():
            stream = AsyncCollection([{"url": get_path("feed.xml")}])
            result["new"] = stream.state is PipeState.NEW
            result["items"] = [item async for item in stream]
            result["exhausted"] = stream.exhausted
            result["reiter"] = [item async for item in stream]

        run(main)

        assert result["new"]
        assert result["items"]
        assert result["exhausted"]
        assert result["reiter"] == []

    def test_collection_close_is_idempotent(self):
        result = {}

        async def main():
            stream = AsyncCollection([{"url": get_path("feed.xml")}])
            await stream.aclose()
            await stream.aclose()
            result["closed"] = stream.closed
            result["state"] = stream.state

        run(main)

        assert result["closed"]
        assert result["state"] is PipeState.CLOSED

    def test_await_after_partial_iteration_consumes_remainder(self):
        result = {}
        runs = []

        def count(item):
            runs.append(1)
            return item

        async def main():
            pipe = (
                AsyncPipe("itembuilder", conf=BUILDER_CONF)
                .tokenizer(emit=True)
                .udf(func=count)
            )
            result["first"] = await anext(pipe)
            result["rest"] = list(await pipe)
            result["runs"] = len(runs)

        run(main)

        assert result["first"] == {"content": "a"}
        assert result["rest"] == [{"content": "b"}, {"content": "c"}]
        assert result["runs"] == 3

    def test_await_twice_after_exhaustion_is_empty(self):
        result = {}

        async def main():
            pipe = AsyncPipe(source=list(SRC))
            result["first"] = list(await pipe)
            result["second"] = list(await pipe)

        run(main)

        assert result["first"] == SRC
        assert result["second"] == []

    def test_collection_await_after_partial_iteration_consumes_remainder(self):
        result = {}

        async def main():
            full = AsyncCollection([{"url": get_path("feed.xml")}])
            result["total"] = len([item async for item in full])
            stream = AsyncCollection([{"url": get_path("feed.xml")}])
            await anext(stream)
            result["rest"] = len(list(await stream))

        run(main)

        assert result["total"] > 1
        assert result["rest"] == result["total"] - 1

    def test_collection_async_pipe_after_partial_iteration_consumes_remainder(self):
        result = {}

        async def main():
            full = AsyncCollection([{"url": get_path("feed.xml")}])
            result["total"] = len([item async for item in full])
            stream = AsyncCollection([{"url": get_path("feed.xml")}])
            await anext(stream)
            child = stream.async_pipe()
            result["rest"] = len([item async for item in child])

        run(main)

        assert result["total"] > 1
        assert result["rest"] == result["total"] - 1


@pytest.mark.skipif(issync, reason="async support not available")
class TestAsyncSourceAdapter:
    """
    ``AsyncPipe._resolve_source`` accepts a sync iterable (via ``async_iter``),
    an async iterable, and an awaitable. The lifecycle machine is source-agnostic
    once resolved, so only the source-touching behaviors are exercised per kind.
    """

    @pytest.mark.parametrize("make_source", GOOD_SOURCES)
    def test_source_iterates(self, make_source):
        result = {}

        async def main():
            pipe = AsyncPipe("hash", source=make_source())
            result["items"] = [item async for item in pipe]

        run(main)

        assert len(result["items"]) == len(SRC)

    @pytest.mark.parametrize("make_source", RAISING_SOURCES)
    def test_source_failure_propagates(self, make_source):
        result = {}

        async def main():
            pipe = AsyncPipe("hash", source=make_source())

            try:
                [item async for item in pipe]
            except RuntimeError:
                result["failed"] = pipe.failed

        run(main)

        assert result.get("failed") is True

    @pytest.mark.parametrize("make_source", GOOD_SOURCES)
    def test_source_closes(self, make_source):
        result = {}

        async def main():
            pipe = AsyncPipe("hash", source=make_source())
            result["items"] = [item async for item in pipe]
            await pipe.aclose()
            result["closed"] = pipe.closed

        run(main)

        assert len(result["items"]) == len(SRC)
        assert result["closed"] is True
