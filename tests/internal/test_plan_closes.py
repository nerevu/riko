"""Provides internal tests for closing seeds, sources, and streams at a run's end."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing, suppress
from functools import partial
from threading import Event as ThreadEvent
from time import perf_counter
from typing import TYPE_CHECKING, Self, cast

import pytest

from riko.bado._backend import CancelScope, async_sleep, fail_after
from riko.bado._util import maybe_async, syncify
from riko.bado.itertools import aauto_close, as_async
from riko.base._exceptions import InvalidPipelineError
from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._settings import ExecutionSettings
from riko.definitions._workflow_definition import Workflow
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.execution import _sync_execution as sync_execution_module
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.modules._decorators import splitter
from riko.modules.split import async_pipe as async_split
from riko.types._workflow import Endpoint
from tests import X_ROWS, async_test, skipif_sync
from tests._execution import (
    ASRC_NODE,
    BSRC_NODE,
    M_ARELAY_DEFINITION,
    M_NODE,
    PASS_DEFINITION,
    PASS_NODE,
    PROBE_NODE,
    PROCESSOR_PROBE,
    RELAY_DEFINITION,
    SPLIT_NODE,
    SRC_ECHO_DEFINITION,
    SRC_NODE,
    AsyncCloseAsyncIterator,
    ClosingAsyncIterator,
    RecordingBranch,
    agen_source,
    arelay_pipe,
    arun_items,
    build_async_definition,
    build_dispatcher,
    build_doubler_plan,
    build_module_plan,
    build_sync_definition,
    build_workflow,
    gen_closing_seed,
    mark_async_loopable,
    mark_loopable,
    run_items,
    tag_source,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from riko.definitions._module_definition import ModuleDefinition
    from riko.types._streams import (
        AsyncItemGenerator,
        AsyncStream,
        Cascade,
        Item,
        Stream,
    )
    from riko.types._wrappers import Func, SyncModuleWrapper


def _unbound_relay_workflow() -> Workflow:
    """Chains a source into a relay that binds a resource no context provides."""
    b = ModuleNode(id="b", name="relay", resources={"slot": "primary"})
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    return build_workflow([SRC_NODE, b], edges=(edge,), resources=("primary",))


async def _agen_closing_seed(closed: list[str]) -> AsyncItemGenerator:
    try:
        yield {"x": 1}
        yield {"x": 2}
    finally:
        closed.append("closed")


async def _agen_endless(closed: list[str]):
    try:
        while True:
            yield {"t": "a"}
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


def _bare_split_plan(
    closed: list[str], make: Callable[[list[str]], Cascade] = _FailingCascade
) -> ExecutionPlan:
    """Plans a source into a bare sync-only splitter that hands back its cascade."""

    def split(_items: object = None, **_: object) -> Cascade:
        return make(closed)

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
    src = tag_source(lambda _items=None, **_: iter([]))
    dispatcher = build_dispatcher(
        build_sync_definition(src), build_sync_definition(split, name="split")
    )
    nodes = [SRC_NODE, SPLIT_NODE]
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
        await async_sleep(0.3)
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


class FailingAsyncCloseIterator(ClosingAsyncIterator):
    """A two-item async iterator whose ``aclose`` records itself then fails."""

    async def aclose(self) -> None:
        await super().aclose()
        raise RuntimeError("close failed")


COUNTING_SOURCES = [
    pytest.param(_gen_counting, id="generator"),
    pytest.param(_CountingIterator, id="closable-iterator"),
]


def _seeded(make, closed: list[str]):
    return build_doubler_plan("double"), make(closed)


def _returned(make, closed: list[str]):
    returned = tag_source(lambda _=None, **__: make(closed))
    dispatcher = build_dispatcher(build_sync_definition(returned))
    return build_module_plan(dispatcher), None


def _streamed(make, closed: list[str]):
    src = tag_source(lambda _=None, **__: make(closed))
    dispatcher = build_dispatcher(build_sync_definition(src), PASS_DEFINITION)
    nodes = (SRC_NODE, PASS_NODE)
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
        build_async_definition(src), build_sync_definition(take_two, name="take")
    )
    nodes = (SRC_NODE, ModuleNode(id="b", name="take"))
    plan = ExecutionPlan.from_workflow(Workflow().with_nodes(*nodes), dispatcher)
    return plan, [{"x": 1}, {"x": 1}]


def _closing_return(closed: list[str]):
    returned = tag_source(lambda _=None, **__: ClosingIterator(closed))
    dispatcher = build_dispatcher(build_sync_definition(returned))
    plan = build_module_plan(dispatcher)
    return plan, [{"x": 1}, {"x": 2}]


# A sync worker node's input, and a sync endpoint's returned iterator.
EARLY_CLOSED_VALUES = [
    pytest.param(_endless_input, id="input"),
    pytest.param(_closing_return, id="raw-return"),
]


def _aclosing_relay(items, **_):
    return aauto_close(arelay_pipe(items), items)


# A native node's async input, closed by the run alone or by the node and the run.
NATIVE_CLOSED_INPUTS = [
    pytest.param(_agen_endless, arelay_pipe, id="generator"),
    pytest.param(ClosingAsyncIterator, _aclosing_relay, id="aclosing-iterator"),
]


class _ClosingAsyncCascade:
    """An async cascade of two one-item branches whose ``aclose`` records itself."""

    def __init__(self, closed: list[str]) -> None:
        self.closed = closed
        self.branches = iter([as_async([{"x": 1}]), as_async([{"x": 2}])])

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> AsyncStream:
        try:
            branch = next(self.branches)
        except StopIteration:
            raise StopAsyncIteration from None

        return branch

    async def aclose(self) -> None:
        self.closed.append("closed")


class _ClosingAsyncStream:
    """Reads an async stream and records each ``aclose`` before passing it on."""

    def __init__(self, stream: AsyncStream, closed: list[str]) -> None:
        self.stream, self.closed = stream, closed

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Item:
        return await anext(self.stream)

    async def aclose(self) -> None:
        self.closed.append("closed")

        if isinstance(self.stream, AsyncGenerator):
            await self.stream.aclose()


def _async_cascade_plan(closed: list[str], _: pytest.MonkeyPatch) -> ExecutionPlan:
    """Plans a source into an async-only splitter that returns a closing cascade."""

    @splitter(objectify=False)
    async def asplit(_stream, _: object, __: object, **___: object):
        return _ClosingAsyncCascade(closed)

    dispatcher = build_dispatcher(
        SRC_ECHO_DEFINITION, build_async_definition(asplit, name="split")
    )
    nodes = [SRC_NODE, SPLIT_NODE]
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("s", "in"))
    flow = build_workflow(
        nodes, edges=(edge,), outputs={"default": Endpoint("s", "out")}
    )
    return ExecutionPlan.from_workflow(flow, dispatcher)


class _ClosingCascade:
    """A sync cascade of two one-item branches whose ``close`` records itself."""

    def __init__(self, closed: list[str]) -> None:
        self.closed = closed
        self.branches = iter([iter([{"x": 1}]), iter([{"x": 2}])])

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> Stream:
        return next(self.branches)

    def close(self) -> None:
        self.closed.append("closed")


def _sync_cascade_plan(closed: list[str], _: pytest.MonkeyPatch) -> ExecutionPlan:
    """Plans a source into a bare sync-only splitter that returns a closing cascade."""
    return _bare_split_plan(closed, _ClosingCascade)


# A splitter's cascade, from a sync-only or an async-only splitter, with the run's
# seed and its output.
CLOSING_CASCADES = [
    pytest.param(_sync_cascade_plan, None, [], id="sync-only-cascade"),
    pytest.param(
        _async_cascade_plan,
        [{"x": 0}],
        [{"x": 1}],
        id="async-only-cascade",
        marks=_SKIP,
    ),
]


def _record_async_inputs(closed: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Records each close of an async input the sync execution builds."""
    to_async = sync_execution_module.to_async

    def recording_to_async(func, stream, **kwargs):
        return _ClosingAsyncStream(to_async(func, stream, **kwargs), closed)

    monkeypatch.setattr(sync_execution_module, "to_async", recording_to_async)


def _async_relay_input_plan(
    closed: list[str], monkeypatch: pytest.MonkeyPatch
) -> ExecutionPlan:
    """Plans a sync source read by an async-only relay, recording its input's close."""
    _record_async_inputs(closed, monkeypatch)
    dispatcher = build_dispatcher(SRC_ECHO_DEFINITION, M_ARELAY_DEFINITION)
    nodes = (SRC_NODE, M_NODE)
    return ExecutionPlan.from_workflow(Workflow().with_nodes(*nodes), dispatcher)


def _async_split_input_plan(
    closed: list[str], monkeypatch: pytest.MonkeyPatch
) -> ExecutionPlan:
    """Plans a sync source into a lazy async-only split, recording its input's close."""
    _record_async_inputs(closed, monkeypatch)
    dispatcher = build_dispatcher(
        SRC_ECHO_DEFINITION, build_async_definition(async_split, name="split")
    )
    nodes = [SRC_NODE, SPLIT_NODE]
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("s", "in"))
    outputs = {"default": Endpoint("s", "out")}
    flow = build_workflow(nodes, edges=(edge,), outputs=outputs)
    return ExecutionPlan.from_workflow(flow, dispatcher)


# Plans whose run closes an async value it reads through the portal.
RUN_OWNED_ASYNC_VALUES = [
    pytest.param(_async_cascade_plan, id="async-only-cascade"),
    pytest.param(_async_relay_input_plan, id="async-only-relay-input"),
    pytest.param(_async_split_input_plan, id="async-only-split-input"),
]


def _tag_loopable_source(fn: Func[object]) -> SyncModuleWrapper:
    return tag_source(mark_loopable(fn))


# Tags a source that runs over its whole input, or once per input item.
SOURCE_TAGS = [
    pytest.param(tag_source, id="whole-stream"),
    pytest.param(_tag_loopable_source, id="per-item"),
]


def _gen_rows(rows, **_):
    yield from rows


_GEN_PROBE = build_sync_definition(_gen_rows, name="probe")


_ASYNC_PROBE = build_async_definition(arelay_pipe, name="probe")


# A node that reads a source over its whole input, once per item, or async-only.
SOURCE_READERS = [
    pytest.param(_GEN_PROBE, id="whole-stream"),
    pytest.param(PROCESSOR_PROBE, id="per-item"),
    pytest.param(_ASYNC_PROBE, id="async-only", marks=skipif_sync),
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
        src = tag(lambda _items=None, **_: build(closed))
        dispatcher = build_dispatcher(build_sync_definition(src), PASS_DEFINITION)
        flow = Workflow().with_nodes(SRC_NODE, PASS_NODE)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

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

        dispatcher = build_dispatcher(build_async_definition(src, name="asrc"))
        plan = build_module_plan(dispatcher, "asrc")

        with SyncExecution() as execution:
            stream = execution.run(plan)
            assert next(stream) == {"x": 1}
            assert closed == []

        assert closed == ["closed"]

    @skipif_sync
    def test_run_closes_an_async_only_source_once_through_an_async_only_relay(
        self,
    ) -> None:
        closed: list[str] = []

        @tag_source
        def src(_items=None, **_):
            return ClosingAsyncIterator(closed)

        dispatcher = build_dispatcher(
            build_async_definition(src, name="asrc"), M_ARELAY_DEFINITION
        )
        nodes = (ASRC_NODE, M_NODE)
        plan = ExecutionPlan.from_workflow(Workflow().with_nodes(*nodes), dispatcher)

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == [{"x": 1}, {"x": 2}]

        assert closed == ["closed"]

    def test_run_rejects_an_item_result_whose_close_must_be_awaited(self) -> None:
        closed: list[str] = []
        make = partial(AwaitableCloseIterator, closed)
        src = _tag_loopable_source(lambda _items=None, **_: make())
        dispatcher = build_dispatcher(build_sync_definition(src))
        plan = build_module_plan(dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="async resource cleanup"),
        ):
            list(execution.run(plan))

        assert closed == []

    @skipif_sync
    def test_run_closes_an_unfinished_async_only_item_on_the_portal(self) -> None:
        closed: list[str] = []
        src = mark_async_loopable(lambda _items=None, **_: _agen_endless(closed))
        pipe = tag_source(src)
        dispatcher = build_dispatcher(build_async_definition(pipe))
        plan = build_module_plan(dispatcher)

        with SyncExecution() as execution:
            stream = run_items(execution, plan)
            assert next(stream) == {"t": "a"}
            stream.close()
            assert closed == ["closed"]

    @skipif_sync
    def test_run_closes_an_unfinished_async_only_stream_on_the_portal(self) -> None:
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: _agen_endless(closed))
        dispatcher = build_dispatcher(build_async_definition(src))
        plan = build_module_plan(dispatcher)

        with SyncExecution() as execution:
            stream = run_items(execution, plan)
            assert next(stream) == {"t": "a"}
            stream.close()
            assert closed == ["closed"]

    @skipif_sync
    def test_run_closes_an_async_only_value_whose_first_read_fails(self) -> None:
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: _FailingAsyncIterator(closed))
        dispatcher = build_dispatcher(build_async_definition(src))
        plan = build_module_plan(dispatcher)

        with SyncExecution() as execution:
            with pytest.raises(RuntimeError, match="read failed"):
                list(execution.run(plan))

            assert closed == ["closed"]

    @skipif_sync
    def test_build_envelope_stream_closes_an_abandoned_async_only_stream_on_exit(
        self,
    ) -> None:
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: _agen_endless(closed))
        dispatcher = build_dispatcher(build_async_definition(src))
        plan = build_module_plan(dispatcher)

        with SyncExecution() as execution:
            assert next(execution.build_envelope_stream(plan)).value == {"t": "a"}

        assert closed == ["closed"]

    @skipif_sync
    def test_run_closes_a_drained_async_only_item_result_on_the_portal(self) -> None:
        # Not an async generator, so only an explicit aclose can end it.
        closed: list[str] = []
        pipe = mark_async_loopable(lambda _item, **_: ClosingAsyncIterator(closed))
        dispatcher = build_dispatcher(build_async_definition(pipe, name="m"))
        plan = build_module_plan(dispatcher, "m")

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed={"x": 0})) == [{"x": 1}, {"x": 2}]
            assert closed == ["closed"]

    def test_run_closes_built_streams_when_a_later_node_fails(self) -> None:
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: ClosingIterator(closed))
        dispatcher = build_dispatcher(build_sync_definition(src), RELAY_DEFINITION)
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
        dispatcher = build_dispatcher(build_sync_definition(src), RELAY_DEFINITION)
        plan = ExecutionPlan.from_workflow(_unbound_relay_workflow(), dispatcher)

        with pytest.raises(ExceptionGroup) as info, SyncExecution() as execution:
            execution.run(plan)

        primary, cleanup = info.value.exceptions
        assert isinstance(primary, InvalidPipelineError)
        assert isinstance(cleanup, RuntimeError)
        assert closed == ["closed"]

    def test_run_closes_a_sync_source_when_its_output_closes(self) -> None:
        closed: list[bool] = []
        src = tag_source(lambda _items=None, **_: _gen_counting(closed))
        dispatcher = build_dispatcher(build_sync_definition(src), PASS_DEFINITION)
        flow = Workflow().with_nodes(SRC_NODE, PASS_NODE)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        with SyncExecution() as execution:
            stream = execution.run(plan)
            assert next(stream) == {"x": 0}
            stream.close()  # pyright: ignore[reportAttributeAccessIssue]
            assert closed == [True]

    @skipif_sync
    @pytest.mark.parametrize("build", RUN_OWNED_ASYNC_VALUES)
    def test_run_closes_a_run_owned_async_value_once_with_its_run(
        self, build, monkeypatch
    ) -> None:
        closed: list[str] = []
        plan = build(closed, monkeypatch)

        with SyncExecution() as execution:
            stream = execution.run(plan, seed=X_ROWS)
            assert next(stream) == {"x": 1}
            stream.close()  # pyright: ignore[reportAttributeAccessIssue]
            assert closed == ["closed"]

        assert closed == ["closed"]

    @pytest.mark.parametrize(("build", "seed", "expected"), CLOSING_CASCADES)
    def test_run_closes_a_cascade_once_its_streams_are_taken(
        self, build, seed, expected, monkeypatch
    ) -> None:
        closed: list[str] = []
        plan = build(closed, monkeypatch)

        with SyncExecution() as execution:
            stream = execution.run(plan, seed=seed)
            assert closed == ["closed"]
            assert list(stream) == expected

        assert closed == ["closed"]

    @pytest.mark.parametrize("probe", SOURCE_READERS)
    def test_run_closing_its_output_before_a_read_closes_the_source(
        self, probe: ModuleDefinition
    ) -> None:
        events: list[str] = []

        @tag_source
        def src(_items=None, **_):
            return RecordingBranch([{"x": 0}], events, "src")

        dispatcher = build_dispatcher(build_sync_definition(src), probe)
        flow = Workflow().with_nodes(SRC_NODE, PROBE_NODE)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        with SyncExecution() as execution:
            run = execution.build_envelope_stream(plan)
            run.output.close()  # pyright: ignore[reportAttributeAccessIssue]
            assert events == ["src-close"]

        assert events == ["src-close"]

    @pytest.mark.parametrize(("build", "make"), ASYNC_ONLY_CLOSES)
    def test_run_rejects_a_value_whose_only_close_is_async(self, build, make) -> None:
        plan, seed = build(make, [])

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="only close is async"),
        ):
            execution.run(plan, seed=seed)


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
            stream = await arun_items(execution, plan, seed=seed)
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
            stream = await arun_items(execution, plan, seed=seed)
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

        dispatcher = build_dispatcher(build_sync_definition(tag_source(src)))
        plan = build_module_plan(dispatcher)

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
        dispatcher = build_dispatcher(build_sync_definition(src), RELAY_DEFINITION)
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
        plan = _bare_split_plan(closed)

        async with AsyncExecution() as execution:
            with pytest.raises(RuntimeError, match="take failed"):
                await execution.arun(plan)

        assert closed == ["closed"]

    @pytest.mark.parametrize("build", RUN_CLOSED_VALUES)
    @async_test
    async def test_arun_closing_the_output_before_a_read_closes_the_source(self, build):
        closed: list[str] = []
        plan, seed = build(ClosingIterator, closed)

        async with AsyncExecution() as execution:
            stream = await arun_items(execution, plan, seed=seed)
            await stream.aclose()
            assert closed == ["closed"]

        assert closed == ["closed"]

    @pytest.mark.parametrize(("build", "seed", "expected"), CLOSING_CASCADES)
    @async_test
    async def test_arun_closes_a_cascade_once_its_streams_are_taken(
        self, build, seed, expected, monkeypatch
    ):
        closed: list[str] = []
        plan = build(closed, monkeypatch)

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan, seed=seed)
            assert closed == ["closed"]
            assert [item async for item in stream] == expected

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
        dispatcher = build_dispatcher(build_sync_definition(src))
        plan = build_module_plan(dispatcher)
        seen = []

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = await arun_items(execution, plan)

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
        dispatcher = build_dispatcher(build_async_definition(src), RELAY_DEFINITION)
        plan = ExecutionPlan.from_workflow(_unbound_relay_workflow(), dispatcher)

        with pytest.raises(InvalidPipelineError, match="not provided"):
            async with AsyncExecution() as execution:
                await execution.arun(plan)

        assert closed == ["closed"]

    @async_test
    async def test_arun_reports_a_failed_close_beside_the_build_error(self) -> None:
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: FailingAsyncCloseIterator(closed))
        dispatcher = build_dispatcher(build_async_definition(src), RELAY_DEFINITION)
        plan = ExecutionPlan.from_workflow(_unbound_relay_workflow(), dispatcher)

        with pytest.raises(ExceptionGroup) as info:
            async with AsyncExecution() as execution:
                await execution.arun(plan)

        primary, cleanup = info.value.exceptions
        assert isinstance(primary, InvalidPipelineError)
        assert isinstance(cleanup, RuntimeError)
        assert closed == ["closed"]

    @pytest.mark.parametrize("tag", SOURCE_TAGS)
    @pytest.mark.parametrize("build", COUNTING_SOURCES)
    @async_test
    async def test_arun_closes_a_sync_source_once_on_early_exit(
        self, build, tag
    ) -> None:
        closed: list[bool] = []
        src = tag(lambda _items=None, **_: build(closed))
        dispatcher = build_dispatcher(build_sync_definition(src), PASS_DEFINITION)
        flow = Workflow().with_nodes(SRC_NODE, PASS_NODE)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = await arun_items(execution, plan)
                assert await anext(stream) == {"x": 0}
                assert closed == []

        assert closed == [True]

    @async_test
    async def test_arun_closes_a_sync_worker_nodes_async_input_once(self):
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: ClosingAsyncIterator(closed))
        dispatcher = build_dispatcher(build_async_definition(src), RELAY_DEFINITION)
        nodes = (SRC_NODE, ModuleNode(id="b", name="relay"))
        plan = ExecutionPlan.from_workflow(Workflow().with_nodes(*nodes), dispatcher)

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = await arun_items(execution, plan)
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

            return src

        def interleave(items, others=None, **_):
            for row in zip(items, *(others or ()), strict=False):
                yield from row

        dispatcher = build_dispatcher(
            build_async_definition(tagged("a"), name="asrc"),
            build_async_definition(tagged("b"), name="bsrc"),
            build_sync_definition(interleave, name="interleave"),
        )
        nodes = [ASRC_NODE, BSRC_NODE, ModuleNode(id="m", name="interleave")]
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("m", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("m", "in:1")),
        )
        flow = build_workflow(nodes, edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        upstream_closed = []

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = await arun_items(execution, plan)
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
            build_async_definition(src, name="asrc"),
            build_async_definition(downstream, name="apass"),
        )
        nodes = [ASRC_NODE, ModuleNode(id="p", name="apass")]
        edges = (StreamEdge(Endpoint("a", "out"), Endpoint("p", "in")),)
        flow = build_workflow(nodes, edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        upstream_closed = []

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = await arun_items(execution, plan)
                await anext(stream)
                await stream.aclose()
                upstream_closed = list(closed)

        assert upstream_closed == ["closed"]

    @async_test
    async def test_arun_closes_a_native_async_nodes_abandoned_input(self) -> None:
        """A native async node may stop reading its input without closing it."""
        closed: list[str] = []
        src = tag_source(lambda _items=None, **_: _agen_endless(closed))

        async def take_one(items, **_):
            it = aiter(items)
            yield await anext(it)

        dispatcher = build_dispatcher(
            build_async_definition(src, name="asrc"),
            build_async_definition(take_one, name="take"),
        )
        nodes = [ASRC_NODE, ModuleNode(id="t", name="take")]
        edges = (StreamEdge(Endpoint("a", "out"), Endpoint("t", "in")),)
        plan = ExecutionPlan.from_workflow(
            build_workflow(nodes, edges=edges), dispatcher
        )

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = await execution.arun(plan)
                assert [item async for item in stream] == [{"t": "a"}]

        assert closed == ["closed"]

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

        dispatcher = build_dispatcher(build_sync_definition(src))
        plan = build_module_plan(dispatcher)

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
                release.wait(0.5)

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
