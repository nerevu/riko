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


@pytest.mark.skipif(issync, reason="async support not available")
class TestAsyncLifecycle:
    def test_new_state(self):
        assert AsyncPipe("itembuilder", conf=BUILDER_CONF).state is PipeState.NEW

    def test_exhausted_after_full_iteration(self):
        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            items = [item async for item in pipe]
            return items, pipe.exhausted, pipe.state

        items, exhausted, state = run(main)
        assert items
        assert exhausted
        assert state is PipeState.EXHAUSTED

    def test_exhausted_reiterates_empty_without_reexecution(self):
        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            first = [item async for item in pipe]
            second = [item async for item in pipe]
            return first, second

        first, second = run(main)
        assert first
        assert second == []

    def test_chain_while_new_is_allowed(self):
        chained = AsyncPipe("itembuilder", conf=BUILDER_CONF).hash()
        assert chained.state is PipeState.NEW

    def test_chain_after_partial_iteration_wraps_remainder(self):
        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            await anext(pipe)
            return pipe.state, [item async for item in pipe.count()]

        state, rest = run(main)
        assert state is PipeState.RUNNING
        assert rest == [{"count": 2}]

    def test_chain_after_exhaustion_is_allowed(self):
        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            [item async for item in pipe]
            return [item async for item in pipe.count()]

        assert run(main) == [{"count": 0}]

    def test_close_is_idempotent(self):
        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF)
            await pipe.aclose()
            await pipe.aclose()
            return pipe.closed, pipe.state

        closed, state = run(main)
        assert closed
        assert state is PipeState.CLOSED

    def test_chain_after_close_raises(self):
        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF)
            await pipe.aclose()
            raised = False

            try:
                pipe.tokenizer()
            except PipelineStateError:
                raised = True

            return raised

        assert run(main) is True

    def test_chain_after_failure_raises(self):
        async def boom():
            raise RuntimeError("boom")

        async def main():
            pipe = AsyncPipe(source=boom())

            try:
                [item async for item in pipe]
            except RuntimeError:
                pass

            raised = False

            try:
                pipe.tokenizer()
            except PipelineStateError:
                raised = True

            return raised

        assert run(main) is True

    def test_iterate_after_run_then_close_is_empty(self):
        async def main():
            pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
            items = [item async for item in pipe]
            await pipe.aclose()
            after = [item async for item in pipe]
            return items, after

        items, after = run(main)
        assert items
        assert after == []

    def test_close_before_iteration_does_not_execute(self):
        ran = []

        async def source():
            ran.append(1)
            yield {"content": "x"}

        async def main():
            pipe = AsyncPipe("hash", source=source())
            await pipe.aclose()
            return [item async for item in pipe]

        assert run(main) == []
        assert ran == []

    def test_failed_state_reiterates_empty(self):
        async def boom():
            raise RuntimeError("boom")

        async def main():
            pipe = AsyncPipe(source=boom())

            try:
                [item async for item in pipe]
            except RuntimeError:
                pass

            return pipe.failed, pipe.state, [item async for item in pipe]

        failed, state, reiter = run(main)
        assert state is PipeState.FAILED
        assert failed
        assert reiter == []

    def test_context_manager_closes(self):
        async def main():
            items = None

            async with AsyncPipe("itembuilder", conf=BUILDER_CONF) as pipe:
                items = [item async for item in pipe]

            return items, pipe.closed

        items, closed = run(main)
        assert items
        assert closed

    def test_collection_lifecycle(self):
        async def main():
            stream = AsyncCollection([{"url": get_path("feed.xml")}])
            new = stream.state is PipeState.NEW
            items = [item async for item in stream]
            exhausted = stream.exhausted
            reiter = [item async for item in stream]
            return new, items, exhausted, reiter

        new, items, exhausted, reiter = run(main)
        assert new
        assert items
        assert exhausted
        assert reiter == []

    def test_collection_close_is_idempotent(self):
        async def main():
            stream = AsyncCollection([{"url": get_path("feed.xml")}])
            await stream.aclose()
            await stream.aclose()
            return stream.closed, stream.state

        closed, state = run(main)
        assert closed
        assert state is PipeState.CLOSED

    def test_collection_close_before_iteration_does_not_execute(self):
        ran = []

        def sources():
            ran.append(1)
            yield {"url": get_path("feed.xml")}

        async def main():
            stream = AsyncCollection(sources())
            await stream.aclose()
            return [item async for item in stream], stream.closed

        items, closed = run(main)
        assert items == []
        assert closed
        assert ran == []

    def test_await_after_partial_iteration_consumes_remainder(self):
        runs = []

        def count[T](item: T) -> T:
            runs.append(1)
            return item

        async def main():
            pipe = (
                AsyncPipe("itembuilder", conf=BUILDER_CONF)
                .tokenizer(emit=True)
                .udf(func=count)
            )
            first = await anext(pipe)
            rest = list(await pipe)
            return first, rest, len(runs)

        first, rest, run_count = run(main)
        assert first == {"content": "a"}
        assert rest == [{"content": "b"}, {"content": "c"}]
        assert run_count == 3

    def test_await_twice_after_exhaustion_is_empty(self):
        async def main():
            pipe = AsyncPipe(source=list(SRC))
            first = list(await pipe)
            second = list(await pipe)
            return first, second

        first, second = run(main)
        assert first == SRC
        assert second == []

    def test_collection_await_after_partial_iteration_consumes_remainder(self):
        async def main():
            full = AsyncCollection([{"url": get_path("feed.xml")}])
            total = len([item async for item in full])
            stream = AsyncCollection([{"url": get_path("feed.xml")}])
            await anext(stream)
            rest = len(list(await stream))
            return total, rest

        total, rest = run(main)
        assert total > 1
        assert rest == total - 1

    def test_collection_async_pipe_after_partial_iteration_consumes_remainder(self):
        async def main():
            full = AsyncCollection([{"url": get_path("feed.xml")}])
            total = len([item async for item in full])
            stream = AsyncCollection([{"url": get_path("feed.xml")}])
            await anext(stream)
            child = stream.async_pipe()
            rest = len([item async for item in child])
            return total, rest

        total, rest = run(main)
        assert total > 1
        assert rest == total - 1


@pytest.mark.skipif(issync, reason="async support not available")
class TestAsyncSourceAdapter:
    """
    ``AsyncPipe._resolve_source`` accepts a sync iterable (via ``async_iter``),
    an async iterable, and an awaitable. The lifecycle machine is source-agnostic
    once resolved, so only the source-touching behaviors are exercised per kind.
    """

    @pytest.mark.parametrize("make_source", GOOD_SOURCES)
    def test_source_iterates(self, make_source):
        async def main():
            pipe = AsyncPipe("hash", source=make_source())
            return [item async for item in pipe]

        assert len(run(main)) == len(SRC)

    @pytest.mark.parametrize("make_source", RAISING_SOURCES)
    def test_source_failure_propagates(self, make_source):
        async def main():
            pipe = AsyncPipe("hash", source=make_source())
            failed = False

            try:
                [item async for item in pipe]
            except RuntimeError:
                failed = pipe.failed

            return failed

        assert run(main) is True

    @pytest.mark.parametrize("make_source", GOOD_SOURCES)
    def test_source_closes(self, make_source):
        async def main():
            pipe = AsyncPipe("hash", source=make_source())
            items = [item async for item in pipe]
            await pipe.aclose()
            return items, pipe.closed

        items, closed = run(main)
        assert len(items) == len(SRC)
        assert closed is True
