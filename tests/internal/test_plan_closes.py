"""Provides internal tests for closing seeds, sources, and streams at a run's end."""

from __future__ import annotations

from contextlib import aclosing, suppress
from functools import partial
from threading import Event as ThreadEvent
from time import perf_counter
from typing import TYPE_CHECKING, Self, cast

import pytest

from riko.bado._backend import CancelScope, async_sleep, fail_after, lowlevel
from riko.bado._util import maybe_async, syncify
from riko.base._exceptions import InvalidPipelineError
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._settings import ExecutionSettings
from riko.definitions._workflow_definition import Workflow
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.types._workflow import Endpoint
from tests import async_test, skipif_sync
from tests._execution import (
    AsyncCloseAsyncIterator,
    ClosingAsyncIterator,
    agen_source,
    build_dispatcher,
    build_doubler_plan,
    build_workflow,
    gen_closing_seed,
    mark_async_loopable,
    mark_loopable,
    module_workflow,
    passthrough_pipe,
    relay_pipe,
    tag_source,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Generator

    from riko.types._streams import (
        AsyncItemGenerator,
        AsyncStream,
        Cascade,
        Item,
        Stream,
    )
    from riko.types._wrappers import AsyncModuleWrapper, Func, SyncModuleWrapper
    from tests._execution import AsyncPipeFunc


def _unbound_relay_workflow() -> Workflow:
    """Chains a source into a relay that binds a resource no context provides."""
    a = ModuleNode(id="a", name="src")
    b = ModuleNode(id="b", name="relay", resources={"slot": "primary"})
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    return build_workflow([a, b], edges=(edge,), resources=("primary",))


async def _agen_closing_seed(closed: list[str]) -> AsyncItemGenerator:
    try:
        yield {"x": 1}
        yield {"x": 2}
    finally:
        closed.append("closed")


class _TwoItems:
    """A two-item iterator."""

    def __init__(self, closed: list[str]) -> None:
        self.closed, self.index = closed, 0

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> Item:
        if self.index == 2:
            raise StopIteration

        self.index += 1
        return {"x": self.index}


class ClosingIterator(_TwoItems):
    """A two-item iterator with ``close`` that is not a generator."""

    def close(self) -> None:
        self.closed.append("closed")


class _FailingCascade:
    """A sync cascade whose second branch fails and whose ``close`` records itself."""

    def __init__(self, closed: list[str]) -> None:
        self.closed, self.taken = closed, 0

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> Stream:
        self.taken += 1

        if self.taken == 2:
            msg = "take failed"
            raise RuntimeError(msg)

        return iter([])

    def close(self) -> None:
        self.closed.append("closed")


def _failing_split_plan(closed: list[str]) -> ExecutionPlan:
    """Plans a source into a bare sync-only splitter that hands back its cascade."""

    def split(_items: object = None, **_: object) -> Cascade:
        return _FailingCascade(closed)

    stamp_wrapper_meta(
        split,
        name="split",
        module_type="splitter",
        subtype="splitter",
        subtypes={"splitter"},
        pollable=False,
        loopable=False,
        is_async=False,
    )
    src = cast("SyncModuleWrapper", tag_source(lambda _items=None, **_: iter([])))
    pipe = cast("SyncModuleWrapper", split)
    split_def = ModuleDefinition(name="split", sync_pipe=pipe)
    dispatcher = build_dispatcher(
        ModuleDefinition(name="src", sync_pipe=src), split_def
    )
    nodes = [ModuleNode(id="a", name="src"), ModuleNode(id="s", name="split")]
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("s", "in"))
    flow = build_workflow(nodes, edges=(edge,))
    return ExecutionPlan.from_workflow(flow, dispatcher)


class _CursorHandle:
    """A sync iterable, without a close of its own, over a fresh closable cursor."""

    def __init__(self, closed: list[str]) -> None:
        self.closed = closed

    def __iter__(self) -> Stream:
        return ClosingIterator(self.closed)


class _ClosingCursorHandle(_CursorHandle):
    """A closable sync iterable over a fresh closable cursor."""

    def close(self) -> None:
        self.closed.append("handle")


class _AsyncCursorHandle:
    """An async iterable, without a close of its own, over a fresh closable cursor."""

    def __init__(self, closed: list[str]) -> None:
        self.closed = closed

    def __aiter__(self) -> AsyncStream:
        return ClosingAsyncIterator(self.closed)


class _ClosingAsyncCursorHandle(_AsyncCursorHandle):
    """An ``aclose``-able async iterable over a fresh closable async cursor."""

    async def aclose(self) -> None:
        self.closed.append("handle")


class _SlowAcloseIterator(_TwoItems):
    """A two-item iterator whose only close, ``aclose``, outlasts shutdown."""

    async def aclose(self) -> None:
        await async_sleep(1)
        self.closed.append("closed")


class _FailingAsyncIterator:
    """An ``aclose``-able async iterator that fails on its first read."""

    def __init__(self, closed: list[str]) -> None:
        self.closed = closed

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Item:
        raise RuntimeError("read failed")

    async def aclose(self) -> None:
        self.closed.append("closed")


class _LoopBoundHandle:
    """An async iterable that opens its iterator only on a running event loop."""

    def __aiter__(self) -> AsyncStream:
        lowlevel.current_token()
        return agen_source()


# A sync root reads the seed on a worker thread, and the caller may close the output
# stream, or drain it, before the execution exits.
SEED_READERS = [
    pytest.param(False, False, id="sync-root"),
    pytest.param(True, False, id="sync-root-closed-early"),
    pytest.param(False, True, id="sync-root-drained"),
]


class ClosingAsyncHandle:
    """An ``aclose``-able handle that hands out a fresh two-item async iterator."""

    def __init__(self, closed: list[str]) -> None:
        self.closed = closed

    def __aiter__(self) -> AsyncStream:
        return agen_source()

    async def aclose(self) -> None:
        self.closed.append("closed")


_BOTH = ["closed", "handle"]
_CLOSED = ["closed"]
_SKIP = skipif_sync
CLOSING_SEEDS = [
    pytest.param(gen_closing_seed, _CLOSED, id="generator"),
    pytest.param(_CursorHandle, _CLOSED, id="cursor-handle"),
    pytest.param(_ClosingCursorHandle, _BOTH, id="closing-cursor-handle"),
    pytest.param(_agen_closing_seed, _CLOSED, id="async-generator", marks=_SKIP),
    pytest.param(ClosingAsyncIterator, _CLOSED, id="async-iterator", marks=_SKIP),
    pytest.param(_AsyncCursorHandle, _CLOSED, id="async-cursor-handle", marks=_SKIP),
    pytest.param(ClosingAsyncHandle, _CLOSED, id="async-handle", marks=_SKIP),
    pytest.param(
        _ClosingAsyncCursorHandle, _BOTH, id="closing-async-cursor-handle", marks=_SKIP
    ),
    pytest.param(
        AsyncCloseAsyncIterator, _CLOSED, id="async-close-iterator", marks=_SKIP
    ),
]


def _gen_counting(closed: list[bool]) -> Stream:
    index = 0

    try:
        while True:
            yield {"x": index}
            index += 1
    finally:
        closed.append(True)


class _CountingIterator:
    """An endless closable item iterator that is not a generator."""

    def __init__(self, closed: list[bool]) -> None:
        self.closed, self.index = closed, -1

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> Item:
        self.index += 1
        return {"x": self.index}

    def close(self) -> None:
        self.closed.append(True)


class AsyncCloseIterator(_TwoItems):
    """A two-item iterator whose only close is an ``async def close``."""

    async def close(self) -> None:
        self.closed.append("closed")


class AcloseOnlyIterator(_TwoItems):
    """A two-item iterator whose only close is ``aclose``."""

    async def aclose(self) -> None:
        self.closed.append("closed")


async def _record_close(closed: list[str]) -> None:
    closed.append("closed")


class AwaitableCloseIterator(_TwoItems):
    """A two-item iterator whose sync ``close`` returns an awaitable."""

    def close(self) -> Awaitable[None]:
        return _record_close(self.closed)


class FailingCloseIterator(_TwoItems):
    """A two-item iterator whose ``close`` records itself then fails."""

    def close(self) -> None:
        self.closed.append("closed")
        raise RuntimeError("close failed")


class FailingAcloseIterator(_TwoItems):
    """A two-item iterator whose only close, ``aclose``, records itself then fails."""

    async def aclose(self) -> None:
        self.closed.append("closed")
        raise RuntimeError("close failed")


COUNTING_SOURCES = [
    pytest.param(_gen_counting, id="generator"),
    pytest.param(_CountingIterator, id="closable-iterator"),
]


def _seeded(make, closed: list[str]):
    return build_doubler_plan("double"), make(closed)


def _returned(make, closed: list[str]):
    returned = tag_source(lambda _=None, **__: make(closed))
    src = cast("SyncModuleWrapper", returned)
    dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=src))
    return ExecutionPlan.from_workflow(module_workflow("src"), dispatcher), None


def _streamed(make, closed: list[str]):
    src = cast("SyncModuleWrapper", tag_source(lambda _=None, **__: make(closed)))
    dispatcher = build_dispatcher(
        ModuleDefinition(name="src", sync_pipe=src),
        ModuleDefinition(name="pass", sync_pipe=passthrough_pipe),
    )
    nodes = (ModuleNode(id="a", name="src"), ModuleNode(id="b", name="pass"))
    return ExecutionPlan.from_workflow(Workflow().with_nodes(*nodes), dispatcher), None


# Each value's only close is async: a seed, a sync pipe's returned iterator, and a
# non-output node's stream.
ASYNC_ONLY_CLOSES = [
    pytest.param(_seeded, AsyncCloseIterator, id="seed-async-close"),
    pytest.param(_seeded, AcloseOnlyIterator, id="seed-aclose"),
    pytest.param(_returned, AsyncCloseIterator, id="return-async-close"),
    pytest.param(_returned, AcloseOnlyIterator, id="return-aclose"),
    pytest.param(_streamed, AsyncCloseIterator, id="node-stream-async-close"),
    pytest.param(_streamed, AcloseOnlyIterator, id="node-stream-aclose"),
]


# Values the run's own close reaches (a seed closes with the execution instead).
RUN_CLOSED_VALUES = [
    pytest.param(_returned, id="return"),
    pytest.param(_streamed, id="node-stream"),
]


# A run whose output stream the caller never closes, unread or read once.
ABANDONED_RUNS = [
    pytest.param(_returned, 0, id="return-unread"),
    pytest.param(_returned, 1, id="return-read-once"),
    pytest.param(_streamed, 0, id="node-stream-unread"),
    pytest.param(_streamed, 1, id="node-stream-read-once"),
]


def _endless_input(closed: list[str]):
    # The source stays referenced and never ends, so only the node finishing can
    # close it before the run itself is closed.
    sources = []

    async def gen():
        try:
            while True:
                yield {"x": 1}
        finally:
            closed.append("closed")

    @tag_source
    def src(_items=None, **_):
        sources.append(gen())
        return sources[-1]

    def take_two(items, **_):
        for index, item in enumerate(items):
            if index == 2:
                break

            yield item

    dispatcher = build_dispatcher(
        ModuleDefinition(name="src", async_pipe=cast("AsyncModuleWrapper", src)),
        ModuleDefinition(name="take", sync_pipe=cast("SyncModuleWrapper", take_two)),
    )
    nodes = (ModuleNode(id="a", name="src"), ModuleNode(id="b", name="take"))
    plan = ExecutionPlan.from_workflow(Workflow().with_nodes(*nodes), dispatcher)
    return plan, [{"x": 1}, {"x": 1}]


def _closing_return(closed: list[str]):
    returned = tag_source(lambda _=None, **__: ClosingIterator(closed))
    src = cast("SyncModuleWrapper", returned)
    dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=src))
    plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)
    return plan, [{"x": 1}, {"x": 2}]


# A sync worker node's input, and a sync endpoint's returned iterator.
EARLY_CLOSED_VALUES = [
    pytest.param(_endless_input, id="input"),
    pytest.param(_closing_return, id="raw-return"),
]


async def _agen_endless(closed: list[str]):
    try:
        while True:
            yield {"t": "a"}
    finally:
        closed.append("closed")


async def _apassthrough(items, **_):
    async for item in items:
        yield item


async def _aclosing_passthrough(items, **_):
    async with aclosing(items) as _items:
        async for item in _items:
            yield item


# A native node's async input, closed by the run alone or by the node and the run.
NATIVE_CLOSED_INPUTS = [
    pytest.param(_agen_endless, _apassthrough, id="generator"),
    pytest.param(ClosingAsyncIterator, _aclosing_passthrough, id="aclosing-iterator"),
]


def _tag_loopable_source(fn: Func[object]) -> SyncModuleWrapper:
    return tag_source(mark_loopable(fn))


# Tags a source that runs over its whole input, or once per input item.
SOURCE_TAGS = [
    pytest.param(tag_source, id="whole-stream"),
    pytest.param(_tag_loopable_source, id="per-item"),
]


class TestPlanClose:
    @pytest.mark.parametrize(("make_seed", "expected"), CLOSING_SEEDS)
    def test_run_closes_a_seed_once_on_exit(self, make_seed, expected) -> None:
        closed: list[str] = []
        plan = build_doubler_plan("double")

        with SyncExecution() as execution:
            stream = execution.run(plan, seed=make_seed(closed))
            assert next(stream) == {"x": 2}
            assert closed == []

        assert closed == expected

    @pytest.mark.parametrize("tag", SOURCE_TAGS)
    @pytest.mark.parametrize("build", COUNTING_SOURCES)
    def test_run_closes_a_sync_source_once_on_early_exit(self, build, tag) -> None:
        closed: list[bool] = []
        src = cast("SyncModuleWrapper", tag(lambda _items=None, **_: build(closed)))
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=src),
            ModuleDefinition(name="pass", sync_pipe=passthrough_pipe),
        )
        a, b = ModuleNode(id="a", name="src"), ModuleNode(id="b", name="pass")
        plan = ExecutionPlan.from_workflow(Workflow().with_nodes(a, b), dispatcher)

        with SyncExecution() as execution:
            stream = execution.run(plan)
            assert next(stream) == {"x": 0}
            assert closed == []

        assert closed == [True]

    @skipif_sync
    def test_run_closes_an_async_native_source_on_exit(self) -> None:
        # Not an async generator, so only an explicit aclose can end it.
        closed: list[str] = []

        @tag_source
        def src(_items=None, **_):
            return ClosingAsyncIterator(closed)

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=cast("AsyncModuleWrapper", src))
        )
        plan = ExecutionPlan.from_workflow(module_workflow("asrc"), dispatcher)

        with SyncExecution() as execution:
            stream = execution.run(plan)
            assert next(stream) == {"x": 1}
            assert closed == []

        assert closed == ["closed"]

    def test_run_rejects_an_item_result_whose_close_must_be_awaited(self) -> None:
        closed: list[str] = []
        make = partial(AwaitableCloseIterator, closed)
        src = _tag_loopable_source(lambda _items=None, **_: make())
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=src))
        plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="async resource cleanup"),
        ):
            list(execution.run(plan))

        assert closed == []

    @skipif_sync
    def test_run_closes_an_unfinished_async_only_item_on_the_portal(self) -> None:
        closed: list[str] = []

        async def src(_items=None, **_):
            try:
                while True:
                    yield {"x": 1}
            finally:
                closed.append("closed")

        pipe = tag_source(mark_async_loopable(src))
        dispatcher = build_dispatcher(ModuleDefinition(name="src", async_pipe=pipe))
        plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)

        with SyncExecution() as execution:
            stream = cast("Generator[Item]", execution.run(plan))
            assert next(stream) == {"x": 1}
            stream.close()
            assert closed == ["closed"]

    @skipif_sync
    def test_run_closes_an_unfinished_async_only_stream_on_the_portal(self) -> None:
        closed: list[str] = []

        @tag_source
        async def src(_items=None, **_):
            try:
                while True:
                    yield {"x": 1}
            finally:
                closed.append("closed")

        pipe = cast("AsyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", async_pipe=pipe))
        plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)

        with SyncExecution() as execution:
            stream = cast("Generator[Item]", execution.run(plan))
            assert next(stream) == {"x": 1}
            stream.close()
            assert closed == ["closed"]

    @skipif_sync
    def test_run_closes_an_async_only_value_whose_first_read_fails(self) -> None:
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: _FailingAsyncIterator(closed))
        pipe = cast("AsyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", async_pipe=pipe))
        plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)

        with SyncExecution() as execution:
            with pytest.raises(RuntimeError, match="read failed"):
                list(execution.run(plan))

            assert closed == ["closed"]

    @skipif_sync
    def test_run_opens_an_async_only_stream_on_the_portal(self) -> None:
        @tag_source
        def src(_items=None, **_):
            lowlevel.current_token()
            return agen_source()

        pipe = cast("AsyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", async_pipe=pipe))
        plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == [{"x": 1}, {"x": 2}]

    @skipif_sync
    def test_run_opens_an_async_only_item_result_on_the_portal(self) -> None:
        def item(_item, **_) -> AsyncStream:
            lowlevel.current_token()
            return agen_source()

        pipe = mark_async_loopable(cast("AsyncPipeFunc", item))
        dispatcher = build_dispatcher(ModuleDefinition(name="m", async_pipe=pipe))
        plan = ExecutionPlan.from_workflow(module_workflow("m"), dispatcher)

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed={"x": 0})) == [{"x": 1}, {"x": 2}]

    @skipif_sync
    def test_run_opens_an_async_seed_on_the_portal(self) -> None:
        plan = build_doubler_plan("double")

        with SyncExecution() as execution:
            stream = execution.run(plan, seed=_LoopBoundHandle())
            assert list(stream) == [{"x": 2}, {"x": 4}]

    @skipif_sync
    def test_run_envelopes_closes_an_abandoned_async_only_stream_on_exit(self) -> None:
        closed: list[str] = []

        @tag_source
        async def src(_items=None, **_):
            try:
                while True:
                    yield {"x": 1}
            finally:
                closed.append("closed")

        pipe = cast("AsyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", async_pipe=pipe))
        plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)

        with SyncExecution() as execution:
            assert next(execution.run_envelopes(plan)).value == {"x": 1}

        assert closed == ["closed"]

    @skipif_sync
    def test_run_closes_a_drained_async_only_item_result_on_the_portal(self) -> None:
        # Not an async generator, so only an explicit aclose can end it.
        closed: list[str] = []
        pipe = mark_async_loopable(lambda _item, **_: ClosingAsyncIterator(closed))
        dispatcher = build_dispatcher(ModuleDefinition(name="m", async_pipe=pipe))
        plan = ExecutionPlan.from_workflow(module_workflow("m"), dispatcher)

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed={"x": 0})) == [{"x": 1}, {"x": 2}]
            assert closed == ["closed"]

    def test_run_closes_built_streams_when_a_later_node_fails(self) -> None:
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: ClosingIterator(closed))
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(name="relay", sync_pipe=relay_pipe),
        )
        plan = ExecutionPlan.from_workflow(_unbound_relay_workflow(), dispatcher)

        with (
            pytest.raises(InvalidPipelineError, match="not provided"),
            SyncExecution() as execution,
        ):
            execution.run(plan)

        assert closed == ["closed"]

    def test_run_reports_a_failed_close_beside_the_build_error(self) -> None:
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: FailingCloseIterator(closed))
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(name="relay", sync_pipe=relay_pipe),
        )
        plan = ExecutionPlan.from_workflow(_unbound_relay_workflow(), dispatcher)

        with pytest.raises(ExceptionGroup) as info, SyncExecution() as execution:
            execution.run(plan)

        primary, cleanup = info.value.exceptions
        assert isinstance(primary, InvalidPipelineError)
        assert isinstance(cleanup, RuntimeError)
        assert closed == ["closed"]

    @pytest.mark.parametrize(("build", "make"), ASYNC_ONLY_CLOSES)
    def test_run_rejects_a_value_whose_only_close_is_async(self, build, make) -> None:
        plan, seed = build(make, [])

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="only close is async"),
        ):
            execution.run(plan, seed=seed)

    def test_run_closes_a_sync_source_when_its_output_closes(self) -> None:
        closed: list[bool] = []
        src = tag_source(lambda _items=None, **_: _gen_counting(closed))
        src = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=src),
            ModuleDefinition(name="pass", sync_pipe=passthrough_pipe),
        )
        a, b = ModuleNode(id="a", name="src"), ModuleNode(id="b", name="pass")
        plan = ExecutionPlan.from_workflow(Workflow().with_nodes(a, b), dispatcher)

        with SyncExecution() as execution:
            stream = execution.run(plan)
            assert next(stream) == {"x": 0}
            stream.close()  # pyright: ignore[reportAttributeAccessIssue]
            assert closed == [True]


class TestAsyncPlanClose:
    @pytest.mark.parametrize(("make_seed", "expected"), CLOSING_SEEDS)
    @pytest.mark.parametrize(("early", "drain"), SEED_READERS)
    @async_test
    async def test_arun_closes_a_seed_once_on_exit(
        self, make_seed, expected, early, drain
    ) -> None:
        closed: list[str] = []
        plan = build_doubler_plan("double")

        async with AsyncExecution() as execution:
            run = await execution.arun(plan, seed=make_seed(closed))
            stream = cast("AsyncItemGenerator", run)
            assert await anext(stream) == {"x": 2}
            assert closed == []

            if early:
                await stream.aclose()
            elif drain:
                assert [item async for item in stream]

        assert closed == expected

    @pytest.mark.parametrize(("build", "make"), ASYNC_ONLY_CLOSES)
    @async_test
    async def test_arun_closes_a_value_whose_only_close_is_async(self, build, make):
        closed: list[str] = []
        plan, seed = build(make, closed)

        async with AsyncExecution() as execution:
            stream = cast("AsyncItemGenerator", await execution.arun(plan, seed=seed))
            assert await anext(stream)
            await stream.aclose()

        assert closed == ["closed"]

    @pytest.mark.parametrize("build", RUN_CLOSED_VALUES)
    @async_test
    async def test_arun_does_not_retry_a_failed_close(self, build):
        """A close that fails raises once, to its caller, and exit leaves it alone."""
        closed: list[str] = []
        plan, seed = build(FailingAcloseIterator, closed)

        async with AsyncExecution() as execution:
            stream = cast("AsyncItemGenerator", await execution.arun(plan, seed=seed))
            assert await anext(stream)

            with pytest.raises(RuntimeError, match="close failed"):
                await stream.aclose()

        assert closed == ["closed"]

    @pytest.mark.timeout(1)
    @async_test
    async def test_arun_closes_a_sync_only_value_when_cancelled_mid_start(self):
        closed: list[str] = []
        scope = CancelScope()

        def src(_items=None, **_):
            syncify(maybe_async, scope.cancel)
            return ClosingIterator(closed)

        pipe = cast("SyncModuleWrapper", tag_source(src))
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=pipe))
        plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)

        async with AsyncExecution() as execution:
            with scope:
                await execution.arun(plan)

        assert scope.cancelled_caught
        assert closed == ["closed"]

    @pytest.mark.timeout(1)
    @async_test
    async def test_arun_bounds_a_failed_run_close_by_the_shutdown_timeout(self):
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: _SlowAcloseIterator(closed))
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(name="relay", sync_pipe=relay_pipe),
        )
        plan = ExecutionPlan.from_workflow(_unbound_relay_workflow(), dispatcher)
        settings = ExecutionSettings(shutdown_timeout=0.05)

        async def run_failing() -> None:
            async with AsyncExecution(settings=settings) as execution:
                with pytest.raises(InvalidPipelineError, match="not provided"):
                    await execution.arun(plan)

        with pytest.raises(TimeoutError):
            await run_failing()

        assert closed == []

    @async_test
    async def test_arun_closes_a_sync_only_cascade_whose_take_fails(self):
        closed: list[str] = []
        plan = _failing_split_plan(closed)

        async with AsyncExecution() as execution:
            with pytest.raises(RuntimeError, match="take failed"):
                await execution.arun(plan)

        assert closed == ["closed"]

    @pytest.mark.parametrize(("build", "pulls"), ABANDONED_RUNS)
    @async_test
    async def test_arun_closes_an_unclosed_run_at_exit(self, build, pulls: int):
        """The execution closes what a run built when its output is never closed."""
        closed: list[str] = []
        plan, seed = build(AsyncCloseIterator, closed)

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan, seed=seed)

            for _ in range(pulls):
                assert await anext(stream)

        assert closed == ["closed"]

    @pytest.mark.parametrize("tag", SOURCE_TAGS)
    @pytest.mark.parametrize("build", COUNTING_SOURCES)
    @async_test
    async def test_arun_sync_only_source_closes_on_early_exit(self, build, tag):
        closed = []
        src = tag(lambda _items=None, **_: build(closed))
        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )
        seen = []

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = cast("AsyncItemGenerator", await execution.arun(plan))

                async for item in stream:
                    seen.append(item)

                    if len(seen) == 3:
                        break

                await stream.aclose()

        assert seen == [{"x": 0}, {"x": 1}, {"x": 2}]
        assert closed == [True]

    @async_test
    async def test_arun_closes_built_streams_when_a_later_node_fails(self) -> None:
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: ClosingAsyncIterator(closed))
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", async_pipe=cast("AsyncModuleWrapper", src)),
            ModuleDefinition(name="relay", sync_pipe=relay_pipe),
        )
        plan = ExecutionPlan.from_workflow(_unbound_relay_workflow(), dispatcher)

        with pytest.raises(InvalidPipelineError, match="not provided"):
            async with AsyncExecution() as execution:
                await execution.arun(plan)

        assert closed == ["closed"]

    @async_test
    async def test_arun_closes_a_sync_worker_nodes_async_input_once(self):
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: ClosingAsyncIterator(closed))
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", async_pipe=cast("AsyncModuleWrapper", src)),
            ModuleDefinition(name="relay", sync_pipe=relay_pipe),
        )
        nodes = (ModuleNode(id="a", name="src"), ModuleNode(id="b", name="relay"))
        plan = ExecutionPlan.from_workflow(Workflow().with_nodes(*nodes), dispatcher)

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = cast("AsyncItemGenerator", await execution.arun(plan))
                assert await anext(stream) == {"x": 1}
                await stream.aclose()

        assert closed == ["closed"]

    @pytest.mark.parametrize("build", EARLY_CLOSED_VALUES)
    @async_test
    async def test_arun_sync_worker_node_closes_its_input_once_it_finishes(
        self, build
    ) -> None:
        closed: list[str] = []
        plan, expected = build(closed)

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = await execution.arun(plan)
                assert [item async for item in stream] == expected
                assert closed == ["closed"]

    @async_test
    async def test_arun_sync_worker_node_closes_its_async_inputs_on_early_exit(
        self,
    ) -> None:
        # The sources stay referenced, so only the stream's own close can end them.
        closed, sources = [], []

        def tagged(tag):
            async def gen():
                try:
                    while True:
                        yield {"t": tag}
                finally:
                    closed.append(tag)

            @tag_source
            def src(_items=None, **_):
                sources.append(gen())
                return sources[-1]

            return cast("AsyncModuleWrapper", src)

        def interleave(items, others=None, **_):
            for row in zip(items, *(others or ()), strict=False):
                yield from row

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=tagged("a")),
            ModuleDefinition(name="bsrc", async_pipe=tagged("b")),
            ModuleDefinition(
                name="interleave", sync_pipe=cast("SyncModuleWrapper", interleave)
            ),
        )
        nodes = [
            ModuleNode(id="a", name="asrc"),
            ModuleNode(id="b", name="bsrc"),
            ModuleNode(id="m", name="interleave"),
        ]
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("m", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("m", "in:1")),
        )
        flow = build_workflow(nodes, edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        upstream_closed = []

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = cast("AsyncItemGenerator", await execution.arun(plan))
                await anext(stream)
                await stream.aclose()
                upstream_closed = sorted(closed)

        assert upstream_closed == ["a", "b"]

    @pytest.mark.parametrize(("build", "downstream"), NATIVE_CLOSED_INPUTS)
    @async_test
    async def test_arun_native_async_node_closes_its_input_stream_on_early_exit(
        self, build, downstream
    ) -> None:
        # The source stays referenced, so only a close can end it.
        closed, sources = [], []

        @tag_source
        def src(_items=None, **_):
            sources.append(build(closed))
            return sources[-1]

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=cast("AsyncModuleWrapper", src)),
            ModuleDefinition(
                name="apass", async_pipe=cast("AsyncModuleWrapper", downstream)
            ),
        )
        nodes = [ModuleNode(id="a", name="asrc"), ModuleNode(id="p", name="apass")]
        edges = (StreamEdge(Endpoint("a", "out"), Endpoint("p", "in")),)
        flow = build_workflow(nodes, edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        upstream_closed = []

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = cast("AsyncItemGenerator", await execution.arun(plan))
                await anext(stream)
                await stream.aclose()
                upstream_closed = list(closed)

        assert upstream_closed == ["closed"]

    @async_test
    async def test_arun_unconsumed_sync_only_source_does_not_block_exit(self) -> None:
        pulled: list[int] = []

        @tag_source
        def src(_items=None, **_):
            for index in range(10_000):
                if len(pulled) >= 100:
                    raise RuntimeError("exit drained the unconsumed source")

                pulled.append(index)
                yield {"x": index}

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )

        with fail_after(1):
            async with AsyncExecution() as execution:
                await execution.arun(plan)

        assert pulled == []

    @pytest.mark.timeout(3)
    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="a shutdown bound on a blocking sync seed close is not yet implemented",
    )
    @async_test
    async def test_arun_bounds_a_blocking_sync_seed_close(self) -> None:
        release = ThreadEvent()

        class BlockingSeed:
            def __iter__(self) -> Stream:
                return iter([{"x": 1}])

            def close(self) -> None:
                release.wait(1)

        settings = ExecutionSettings(shutdown_timeout=0.05)
        start = perf_counter()

        with suppress(TimeoutError):
            async with AsyncExecution(settings=settings) as execution:
                run = await execution.arun(
                    build_doubler_plan("double"), seed=BlockingSeed()
                )

                async with aclosing(cast("AsyncItemGenerator", run)) as items:
                    assert await anext(items) == {"x": 2}

        assert perf_counter() - start < 0.25
