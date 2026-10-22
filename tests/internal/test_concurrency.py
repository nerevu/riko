# vim: sw=4:ts=4:expandtab
"""Provides internal tests for worker pools, mapping policy, and concurrency."""

from __future__ import annotations

import pickle  # noqa: S403
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from functools import partial
from itertools import chain, pairwise
from multiprocessing.pool import ThreadPool
from threading import Lock, Thread, get_ident
from time import sleep
from typing import TYPE_CHECKING, Any, cast

import pytest

from riko.bado._backend import async_sleep, create_task_group, fail_after, lowlevel
from riko.base._config import get_worker_cnt
from riko.base._config import settings as config
from riko.base.exceptions import InvalidPipelineError, PipelineStateError
from riko.definitions._context import Context
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._resource_definition import Resource
from riko.definitions._settings import AsyncPolicy, ExecutionSettings, SyncPolicy
from riko.execution import _async_execution, _sync_execution
from riko.execution._async_execution import AsyncExecution
from riko.execution._concurrency import (
    _load_call,
    build_item_call,
    run_item,
    run_shipped_item,
)
from riko.execution._pools import _PoolLifetime
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.modules import join, union
from riko.runtime._resolver import dispatcher
from riko.types._enums import Executor
from riko.types._workflow import Endpoint
from tests import async_test
from tests._execution import build_chain, build_dispatcher, build_workflow

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from riko.types._events import EventSink
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper


ITEMS = [{"x": x} for x in range(20)]


def _loopable(func) -> Any:
    func.loopable = True
    func.type = "processor"
    return func


def _hash_plan(*names):
    nodes = [ModuleNode(id=f"n{i}", name=name) for i, name in enumerate(names)]
    return ExecutionPlan.from_workflow(build_chain(*nodes), dispatcher)


def _key(item):
    return tuple(sorted(item.items()))


class _Sink:
    def emit(self, event: object) -> None:
        pass


class _Unpicklable:
    """A pipe callable that raises a non-pickle error when pickled."""

    def __call__(self, item, **_):
        return iter([item])

    def __reduce__(self):
        raise RuntimeError("no pickling here")


class TestExecutionSettings:
    def test_unknown_executor_lists_the_known_executors(self) -> None:
        message = "ExecutionSettings 'executor': 'bogus'. Expected one of auto, inline"

        with pytest.raises(ValueError, match=message):
            ExecutionSettings(executor="bogus")

    def test_settings_supply_the_event_sink_and_shutdown_timeout(self) -> None:
        sink, explicit = cast("EventSink", _Sink()), cast("EventSink", _Sink())
        settings = ExecutionSettings(event_sink=sink, shutdown_timeout=1.5)
        assert SyncExecution(settings=settings).events is sink
        assert SyncExecution(events=explicit, settings=settings).events is explicit
        assert AsyncExecution(settings=settings).shutdown_timeout == pytest.approx(1.5)


INLINE, THREAD, PROCESS = Executor.INLINE, Executor.THREAD, Executor.PROCESS
THREADS, PROCS = get_worker_cnt(threads=True), get_worker_cnt(threads=False)
LIMIT = config.concurrency_limit

SYNC_POLICIES = [
    pytest.param({"concurrency": 1}, SyncPolicy(INLINE, None), id="one"),
    pytest.param({"executor": "inline"}, SyncPolicy(INLINE, None), id="inline"),
    pytest.param({"executor": "thread"}, SyncPolicy(THREAD, 1), id="thread"),
    pytest.param({"executor": "process"}, SyncPolicy(PROCESS, 1), id="process"),
    pytest.param({"concurrency": "auto"}, SyncPolicy(THREAD, THREADS), id="auto"),
    pytest.param(
        {"executor": "inline", "concurrency": 4},
        SyncPolicy(INLINE, None),
        id="inline-4",
    ),
    pytest.param(
        {"executor": "thread", "concurrency": 3}, SyncPolicy(THREAD, 3), id="thread-3"
    ),
    pytest.param(
        {"executor": "process", "concurrency": 2},
        SyncPolicy(PROCESS, 2),
        id="process-2",
    ),
    pytest.param(
        {"executor": "thread", "concurrency": "auto"},
        SyncPolicy(THREAD, THREADS),
        id="thread-auto",
    ),
    pytest.param(
        {"executor": "process", "concurrency": "auto"},
        SyncPolicy(PROCESS, PROCS),
        id="process-auto",
    ),
    pytest.param(
        {"executor": "inline", "concurrency": "auto"},
        SyncPolicy(INLINE, None),
        id="inline-auto",
    ),
]

ASYNC_POLICIES = [
    pytest.param({}, AsyncPolicy(None, False), id="default"),
    pytest.param({"executor": "inline"}, AsyncPolicy(1, True), id="inline"),
    pytest.param({"executor": "thread"}, AsyncPolicy(1, False), id="thread"),
    pytest.param({"concurrency": "auto"}, AsyncPolicy(LIMIT, False), id="auto"),
    pytest.param(
        {"executor": "inline", "concurrency": 3}, AsyncPolicy(3, True), id="inline-3"
    ),
    pytest.param(
        {"executor": "thread", "concurrency": 3}, AsyncPolicy(3, False), id="thread-3"
    ),
    pytest.param(
        {"executor": "inline", "concurrency": "auto"},
        AsyncPolicy(LIMIT, True),
        id="inline-auto",
    ),
]


def _pair(item: str) -> list[str]:
    return [item, item]


ITEM_CALLS = [
    pytest.param(THREAD, run_item, (_pair,), id="thread"),
    pytest.param(PROCESS, run_shipped_item, (pickle.dumps(_pair),), id="process"),
]


class TestMappingPolicy:
    @pytest.mark.parametrize(("kwargs", "expected"), SYNC_POLICIES)
    def test_sync_policy_table(self, kwargs, expected) -> None:
        assert ExecutionSettings(**kwargs).sync_policy == expected

    @pytest.mark.parametrize(("kwargs", "expected"), ASYNC_POLICIES)
    def test_async_policy_table(self, kwargs, expected) -> None:
        assert ExecutionSettings(**kwargs).async_policy == expected

    @pytest.mark.parametrize(("executor", "func", "args"), ITEM_CALLS)
    def test_item_call_binds_the_pipe_for_its_executor(self, executor, func, args):
        call = build_item_call(_pair, executor)
        assert isinstance(call, partial)
        assert (call.func, call.args) == (func, args)
        assert call("a") == ["a", "a"]

    def test_shipped_call_is_unpickled_once_per_worker(self) -> None:
        _load_call.cache_clear()
        func = build_item_call(_pair, Executor.PROCESS)
        assert (func("a"), func("b")) == (["a", "a"], ["b", "b"])
        assert _load_call.cache_info()[:2] == (1, 1)

    def test_prepared_node_reports_loopable(self) -> None:
        plan = _hash_plan("hash", "count")
        assert plan.nodes["n0"].loopable is True
        assert plan.nodes["n1"].loopable is False

    @pytest.mark.parametrize("port", ["in:1", "in:side"])
    def test_secondary_input_stream_makes_a_node_unmappable(self, port) -> None:
        def echo(item, **_):
            return iter([item])

        dispatcher = build_dispatcher(
            ModuleDefinition(name="echo", sync_pipe=_loopable(echo))
        )
        nodes = [ModuleNode(id=id_, name="echo") for id_ in ("a", "b", "c")]
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("c", port)),
        )
        plan = ExecutionPlan.from_workflow(
            build_workflow(nodes, edges=edges), dispatcher
        )
        assert plan.nodes["a"].is_mappable is True
        assert plan.nodes["c"].is_mappable is False


def _run_sync(plan, settings=None, source=ITEMS):
    kwargs = {} if settings is None else {"settings": settings}
    execution = SyncExecution(**kwargs)
    result: list = []

    with execution:
        result = list(execution.run(plan, source=source))

    return result


@pytest.fixture
def opened(monkeypatch):
    calls: list[tuple[Executor, int]] = []

    def record(pool, window):
        executor = Executor.THREAD if isinstance(pool, ThreadPool) else Executor.PROCESS
        calls.append((executor, getattr(pool, "_processes")))  # noqa: B009
        return _PoolLifetime(pool, window)

    monkeypatch.setattr(_sync_execution, "_PoolLifetime", record)
    return calls


@pytest.fixture
def released(monkeypatch):
    calls: list[str] = []
    close, terminate = _PoolLifetime.close, _PoolLifetime.terminate

    def record_close(self):
        calls.append("close")
        close(self)

    def record_terminate(self):
        calls.append("terminate")
        terminate(self)

    monkeypatch.setattr(_PoolLifetime, "close", record_close)
    monkeypatch.setattr(_PoolLifetime, "terminate", record_terminate)
    return calls


def _loop_dispatcher():
    def fakeloop(item, **_):
        return iter([item])

    up = cast("AsyncModuleWrapper", lambda item, **_: item)
    return build_dispatcher(
        ModuleDefinition(name="fakeloop", sync_pipe=_loopable(fakeloop)),
        ModuleDefinition(name="up", async_pipe=up),
    )


class TestSyncConcurrency:
    def test_sync_run_without_settings_opens_no_pool(self, opened) -> None:
        plan = _hash_plan("hash")
        assert len(_run_sync(plan)) == len(ITEMS)
        assert opened == []

    def test_sync_sequential_run_has_no_worker_pool(self) -> None:
        with SyncExecution() as execution, pytest.raises(PipelineStateError):
            _ = execution._pool

    @pytest.mark.slow
    def test_sync_concurrency_maps_on_a_thread_pool(self, opened, released) -> None:
        plan = _hash_plan("hash", "hash")
        expected = _run_sync(plan)
        result = _run_sync(plan, ExecutionSettings(concurrency=4))

        assert Counter(map(_key, result)) == Counter(map(_key, expected))
        assert opened == [(Executor.THREAD, 4)]
        assert released == ["close"]

    def test_sync_inline_executor_never_opens_a_pool(self, opened) -> None:
        plan = _hash_plan("hash")
        settings = ExecutionSettings(executor="inline", concurrency=4)
        assert _run_sync(plan, settings) == _run_sync(plan)
        assert opened == []

    @pytest.mark.slow
    def test_sync_process_executor_maps_items(self, opened) -> None:
        plan = _hash_plan("hash")
        settings = ExecutionSettings(executor="process", concurrency=2)
        result = _run_sync(plan, settings)

        assert Counter(map(_key, result)) == Counter(map(_key, _run_sync(plan)))
        assert opened == [(Executor.PROCESS, 2)]

    def test_sync_non_loopable_node_is_never_mapped(self, opened) -> None:
        plan = _hash_plan("count")
        assert _run_sync(plan, ExecutionSettings(concurrency=4)) == [{"count": 20}]
        assert opened == []

    @pytest.mark.parametrize("executor", ["thread", "process"])
    def test_sync_node_with_stream_input_is_never_mapped(
        self, opened, executor
    ) -> None:
        # Such a node runs in-process, so the process executor does not refuse its
        # resources.
        def joiner(items, side=None, **_):
            yield from items

            if side is not None:
                yield from side

        def source(_items=None, **_):
            yield {"t": "side"}

        dispatcher = build_dispatcher(
            ModuleDefinition(name="side", sync_pipe=cast("SyncModuleWrapper", source)),
            ModuleDefinition(name="joiner", sync_pipe=_loopable(joiner)),
        )
        side = ModuleNode(id="s", name="side")
        joined = ModuleNode(id="j", name="joiner", resources={"slot": "primary"})
        edge = StreamEdge(Endpoint("s", "out"), Endpoint("j", "in:side"))
        flow = build_workflow([side, joined], edges=(edge,), resources=("primary",))
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        context = Context().with_resource("primary", Resource.from_external(object()))
        settings = ExecutionSettings(executor=executor, concurrency=4)
        result: list = []

        with SyncExecution(context, settings=settings) as execution:
            result = list(execution.run(plan))

        assert result == [{"forever": True}, {"t": "side"}]
        assert opened == []

    @pytest.mark.slow
    @pytest.mark.parametrize("ordered", [False, True])
    def test_sync_pool_terminates_when_a_mapped_item_fails(
        self, released, ordered
    ) -> None:
        def explode(item, **_):
            if item["x"] == 3:
                raise ValueError("boom")

            return iter([item])

        dispatcher = build_dispatcher(
            ModuleDefinition(name="explode", sync_pipe=_loopable(explode))
        )
        flow = build_workflow([ModuleNode(id="n", name="explode")])
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        with pytest.raises(ValueError, match="boom"):
            _run_sync(plan, ExecutionSettings(concurrency=2, ordered=ordered))

        assert released == ["terminate"]

    @pytest.mark.slow
    def test_sync_pool_terminates_when_the_stream_is_closed_early(
        self, released
    ) -> None:
        plan = _hash_plan("hash")

        with SyncExecution(settings=ExecutionSettings(concurrency=2)) as execution:
            stream = cast("Generator", execution.run(plan, source=ITEMS))
            next(stream)
            stream.close()

        assert released == ["terminate"]

    @pytest.mark.slow
    @pytest.mark.parametrize("ordered", [False, True])
    def test_sync_chained_mapping_reads_the_source_on_demand(self, ordered) -> None:
        pulled: list[int] = []
        concurrency = 2

        def tracked():
            for x in range(10_000):
                pulled.append(x)
                yield {"x": x}

        plan = _hash_plan("hash", "hash")
        settings = ExecutionSettings(concurrency=concurrency, ordered=ordered)

        def consume() -> None:
            with SyncExecution(settings=settings) as execution:
                stream = cast("Generator", execution.run(plan, source=tracked()))
                next(stream)
                stream.close()

        worker = Thread(target=consume, daemon=True)
        worker.start()
        worker.join(timeout=10)

        assert not worker.is_alive(), (
            "chained mapped nodes deadlocked on the shared pool"
        )
        assert len(pulled) <= 2 * concurrency + 1

    def test_sync_mapping_waits_for_the_first_pull(self, opened) -> None:
        plan = _hash_plan("hash")

        with SyncExecution(settings=ExecutionSettings(concurrency=2)) as execution:
            execution.run(plan, source=ITEMS)

        assert opened == []

    def test_process_executor_refuses_a_resource_node(self, opened) -> None:
        # Of two unsafe nodes, the upstream one is reported however ids hash.
        binding = {"slot": "primary"}
        nodes = [ModuleNode(id=id_, name="hash", resources=binding) for id_ in "za"]
        edge = StreamEdge(Endpoint("z", "out"), Endpoint("a", "in"))
        flow = build_workflow(nodes, edges=(edge,), resources=("primary",))
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        context = Context().with_resource("primary", Resource.from_external(object()))
        settings = ExecutionSettings(executor="process", concurrency=2)
        execution = SyncExecution(context, settings=settings)

        with (
            execution,
            pytest.raises(InvalidPipelineError, match="node 'z' cannot run"),
        ):
            execution.run(plan, source=ITEMS)

        assert opened == []

    def test_process_executor_refuses_an_async_only_embed(self, opened) -> None:
        node = ModuleNode(id="loop", name="fakeloop", embed={"name": "up", "conf": {}})
        plan = ExecutionPlan.from_workflow(
            build_workflow([node]), dispatcher=_loop_dispatcher()
        )
        settings = ExecutionSettings(executor="process", concurrency=2)
        execution = SyncExecution(settings=settings)

        with (
            execution,
            pytest.raises(InvalidPipelineError, match="node 'loop' cannot run"),
        ):
            execution.run(plan, source=ITEMS)

        assert opened == []

    def test_process_executor_refuses_an_unpicklable_pipe(self, opened) -> None:
        def local(item, **_):
            return iter([item])

        dispatcher = build_dispatcher(
            ModuleDefinition(name="local", sync_pipe=_loopable(local))
        )
        flow = build_workflow([ModuleNode(id="n", name="local")])
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        settings = ExecutionSettings(executor="process", concurrency=2)
        execution = SyncExecution(settings=settings)

        with (
            execution,
            pytest.raises(InvalidPipelineError, match="node 'n' cannot run") as info,
        ):
            execution.run(plan, source=ITEMS)

        assert info.value.__cause__ is not None
        assert opened == []

    def test_process_executor_wraps_any_pickling_failure(self, opened) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="local", sync_pipe=_loopable(_Unpicklable()))
        )
        flow = build_workflow([ModuleNode(id="n", name="local")])
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        settings = ExecutionSettings(executor="process", concurrency=2)
        execution = SyncExecution(settings=settings)

        with (
            execution,
            pytest.raises(InvalidPipelineError, match="node 'n' cannot run") as info,
        ):
            execution.run(plan, source=ITEMS)

        assert isinstance(info.value.__cause__, RuntimeError)
        assert opened == []


def _passthru(stream, **_):
    yield from stream


_passthru.type = "operator"  # pyright: ignore[reportFunctionMemberAccess]


async def _arun(plan, settings, source=ITEMS):
    execution = AsyncExecution(settings=settings)
    result: list = []

    async with execution:
        stream = await execution.arun(plan, source=source)
        result = [item async for item in stream]

    return result


def _thread_probe():
    threads: list[int] = []

    def probe(item, **_):
        threads.append(get_ident())
        return iter([item])

    definition = ModuleDefinition(name="probe", sync_pipe=_loopable(probe))
    flow = build_workflow([ModuleNode(id="n", name="probe")])
    return threads, ExecutionPlan.from_workflow(
        flow, dispatcher=build_dispatcher(definition)
    )


@dataclass
class _ThreadGauge:
    """Counts the node threads running a node's code at once."""

    active: int = 0
    peak: int = 0
    lock: Lock = field(default_factory=Lock)

    @contextmanager
    def held(self) -> Generator[None]:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

        try:
            yield
        finally:
            with self.lock:
                self.active -= 1


def _gauged_plan(gauge: _ThreadGauge, depth: int) -> ExecutionPlan:
    def gauged(stream, **_):
        iterator = iter(stream)

        while True:
            with gauge.held():
                item = next(iterator, None)
                sleep(0.001)

            if item is None:
                break

            yield item

    gauged.type = "operator"  # pyright: ignore[reportFunctionMemberAccess]
    definition = ModuleDefinition(name="gauged", sync_pipe=cast("Any", gauged))
    nodes = [ModuleNode(id=f"n{i}", name="gauged") for i in range(depth)]
    return ExecutionPlan.from_workflow(
        build_chain(*nodes), dispatcher=build_dispatcher(definition)
    )


def _passthru_plan(depth: int) -> ExecutionPlan:
    pipe = cast("SyncModuleWrapper", _passthru)
    definition = ModuleDefinition(name="passthru", sync_pipe=pipe)
    nodes = [ModuleNode(id=f"n{i}", name="passthru") for i in range(depth)]
    return ExecutionPlan.from_workflow(
        build_chain(*nodes), dispatcher=build_dispatcher(definition)
    )


@pytest.fixture
def node_threads(monkeypatch):
    def set_budget(total: int) -> None:
        budgets = lowlevel.RunVar("node_threads")
        monkeypatch.setattr(_async_execution, "_budgets", budgets)
        patched = replace(config, node_threads=total)
        monkeypatch.setattr(_async_execution, "config", patched)

    return set_budget


THREAD_BUDGET_OVERFLOWS = [
    pytest.param(config.node_threads, config.node_threads + 1, id="default-budget"),
    pytest.param(4, 5, id="small-budget"),
]

SEQUENTIAL_FAN_INS = [
    pytest.param(union, "in:1", 6, id="union"),
    pytest.param(join, "in:other", 9, id="join"),
]


class TestAsyncConcurrency:
    def test_thread_budget_without_anyio_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(_async_execution, "_budgets", None)

        with pytest.raises(RuntimeError, match="anyio is required"):
            _async_execution._resolve_thread_budget()

    @async_test
    async def test_async_long_sync_only_chain_completes(self, node_threads) -> None:
        # Each sync-only node holds a worker thread while it pulls its upstream, so
        # a chain within the node-thread budget must still get a thread each.
        node_threads(45)
        plan = _passthru_plan(45)
        result: list = []

        with fail_after(20):
            async with AsyncExecution() as execution:
                stream = await execution.arun(plan, source=ITEMS[:2])
                result = [item async for item in stream]

        assert result == ITEMS[:2]

    @pytest.mark.parametrize(("budget", "depth"), THREAD_BUDGET_OVERFLOWS)
    @async_test
    async def test_async_chain_over_thread_budget_raises_before_reading(
        self, node_threads, budget, depth
    ) -> None:
        node_threads(budget)
        read: list = []

        def source():
            read.append(True)
            yield from ITEMS[:2]

        with fail_after(20):
            async with AsyncExecution() as execution:
                with pytest.raises(InvalidPipelineError, match="RIKO_NODE_THREADS"):
                    await execution.arun(_passthru_plan(depth), source=source())

        assert read == []

    @async_test
    async def test_async_mapped_sync_chain_holds_no_node_threads(
        self, node_threads
    ) -> None:
        node_threads(1)

        def echo(item, **_):
            return iter([item])

        definition = ModuleDefinition(name="echo", sync_pipe=_loopable(echo))
        nodes = [ModuleNode(id=f"n{i}", name="echo") for i in range(3)]
        plan = ExecutionPlan.from_workflow(
            build_chain(*nodes), dispatcher=build_dispatcher(definition)
        )

        with fail_after(20):
            result = await _arun(plan, ExecutionSettings(concurrency=2), ITEMS[:2])

        assert Counter(map(_key, result)) == Counter(map(_key, ITEMS[:2]))

    @async_test
    async def test_async_runs_share_the_node_thread_budget(self, node_threads) -> None:
        node_threads(6)
        gauge = _ThreadGauge()
        plan = _gauged_plan(gauge, 3)
        results: list[list] = []

        async def consume() -> None:
            results.append(await _arun(plan, ExecutionSettings(), ITEMS[:5]))

        with fail_after(20):
            async with create_task_group() as tg:
                for _ in range(4):
                    tg.start_soon(consume)

        assert results == [ITEMS[:5]] * 4
        assert 0 < gauge.peak <= 6

    @pytest.mark.parametrize("reads", [1, 0], ids=["after-read", "before-read"])
    @async_test
    async def test_async_closed_stream_returns_its_node_threads(
        self, node_threads, reads
    ) -> None:
        node_threads(3)
        plan = _passthru_plan(3)
        result: list = []

        with fail_after(20):
            async with AsyncExecution() as execution:
                stream = await execution.arun(plan, source=ITEMS[:2])

                for _ in range(reads):
                    await anext(stream)

                await stream.aclose()  # pyright: ignore[reportAttributeAccessIssue]
                rerun = await execution.arun(plan, source=ITEMS[:2])
                result = [item async for item in rerun]

        assert result == ITEMS[:2]

    @async_test
    async def test_async_closing_while_waiting_for_threads_keeps_the_budget(
        self, node_threads
    ) -> None:
        node_threads(1)
        plan = _passthru_plan(1)
        errors: list[type[BaseException]] = []
        waiter = AsyncExecution()

        async def wait_for_threads() -> None:
            try:
                await waiter.arun(plan, source=ITEMS[:2])
            except PipelineStateError as error:
                errors.append(type(error))

        with fail_after(20):
            async with AsyncExecution() as holder, create_task_group() as tg:
                held = await holder.arun(plan, source=ITEMS[:2])
                await anext(held)
                tg.start_soon(wait_for_threads)
                await async_sleep(0.05)
                await waiter.aclose()
                await held.aclose()  # pyright: ignore[reportAttributeAccessIssue]

        assert errors == [PipelineStateError]
        assert _async_execution._resolve_thread_budget().available == 1

    @async_test
    async def test_async_run_beside_own_open_stream_over_budget_raises(
        self, node_threads
    ) -> None:
        node_threads(3)
        plan = _passthru_plan(2)
        rest: list = []

        with fail_after(20):
            async with AsyncExecution() as execution:
                stream = await execution.arun(plan, source=ITEMS[:2])
                await anext(stream)

                with pytest.raises(InvalidPipelineError, match="open output streams"):
                    await execution.arun(plan, source=ITEMS[:2])

                rest = [item async for item in stream]

        assert rest == ITEMS[1:2]

    @async_test
    async def test_async_interleaved_fan_in_fits_its_thread_budget(
        self, node_threads
    ) -> None:
        # Each pull runs on its own, so a node interleaving its input streams still
        # reads them one at a time: the deepest input chain sets the demand, not their
        # sum.
        node_threads(3)

        def src(_items=None, **_):
            yield from ITEMS[:3]

        def zipped(items, others=None, **_):
            yield from chain.from_iterable(zip(items, *(others or ()), strict=False))

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(
                name="passthru", sync_pipe=cast("SyncModuleWrapper", _passthru)
            ),
            ModuleDefinition(name="zip", sync_pipe=cast("SyncModuleWrapper", zipped)),
        )
        names = {"a": "src", "a1": "passthru", "b": "src", "b1": "passthru", "z": "zip"}
        nodes = [ModuleNode(id=id_, name=name) for id_, name in names.items()]
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("a1", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("b1", "in")),
            StreamEdge(Endpoint("a1", "out"), Endpoint("z", "in")),
            StreamEdge(Endpoint("b1", "out"), Endpoint("z", "in:1")),
        )
        flow = build_workflow(nodes, edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        with fail_after(10):
            result = await _arun(plan, ExecutionSettings(), None)

        assert result == list(
            chain.from_iterable(zip(ITEMS[:3], ITEMS[:3], strict=True))
        )

    @pytest.mark.parametrize(("module", "port", "count"), SEQUENTIAL_FAN_INS)
    @async_test
    async def test_async_sequential_fan_in_needs_only_its_deepest_input(
        self, node_threads, module, port, count
    ) -> None:
        # Two 25-node sync chains would need 50 threads if read together, but the
        # module finishes one input before it starts the other, so 25 fit in 40.
        node_threads(40)

        def src(_items=None, **_):
            yield from ITEMS[:3]

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(
                name="passthru", sync_pipe=cast("SyncModuleWrapper", _passthru)
            ),
            ModuleDefinition(
                name="fan_in", sync_pipe=module.pipe, async_pipe=module.async_pipe
            ),
        )
        chains = [
            [
                ModuleNode(id=f"{side}{i}", name="passthru" if i else "src")
                for i in range(25)
            ]
            for side in "ab"
        ]
        fan_in = ModuleNode(id="f", name="fan_in")
        edges = [
            StreamEdge(Endpoint(x.id, "out"), Endpoint(y.id, "in"))
            for nodes in chains
            for x, y in pairwise(nodes)
        ]
        edges += [
            StreamEdge(Endpoint(chains[0][-1].id, "out"), Endpoint("f", "in")),
            StreamEdge(Endpoint(chains[1][-1].id, "out"), Endpoint("f", port)),
        ]
        flow = build_workflow([*chains[0], *chains[1], fan_in], edges=tuple(edges))
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        with fail_after(20):
            result = await _arun(plan, ExecutionSettings(), None)

        assert plan.get_thread_demand("default", mapped=False) == 25
        assert len(result) == count

    @async_test
    async def test_async_concurrency_collects_async_iterable_results(self) -> None:
        async def twice(item, **_):
            yield item
            yield item

        definition = ModuleDefinition(name="twice", async_pipe=_loopable(twice))
        flow = build_workflow([ModuleNode(id="n", name="twice")])
        plan = ExecutionPlan.from_workflow(
            flow, dispatcher=build_dispatcher(definition)
        )
        result = await _arun(plan, ExecutionSettings(concurrency=2))

        assert Counter(map(_key, result)) == Counter(map(_key, ITEMS * 2))

    @async_test
    async def test_async_concurrency_is_one_ceiling_across_nodes(self) -> None:
        active = peak = 0

        async def slow(item, **_):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await async_sleep(0.01)
            active -= 1
            return [item]

        definition = ModuleDefinition(name="slow", async_pipe=_loopable(slow))
        nodes = [ModuleNode(id="a", name="slow"), ModuleNode(id="b", name="slow")]
        plan = ExecutionPlan.from_workflow(
            build_chain(*nodes), dispatcher=build_dispatcher(definition)
        )
        result = await _arun(plan, ExecutionSettings(concurrency=3))

        assert Counter(map(_key, result)) == Counter(map(_key, ITEMS))
        assert 1 < peak <= 3

    @async_test
    async def test_async_concurrency_runs_sync_pipes_on_worker_threads(self) -> None:
        threads, plan = _thread_probe()
        result = await _arun(plan, ExecutionSettings(concurrency=2))

        assert Counter(map(_key, result)) == Counter(map(_key, ITEMS))
        assert len(threads) == len(ITEMS)
        assert get_ident() not in threads

    @async_test
    async def test_async_inline_executor_runs_sync_pipes_on_the_loop_thread(
        self,
    ) -> None:
        threads, plan = _thread_probe()
        settings = ExecutionSettings(executor="inline", concurrency=2)
        result = await _arun(plan, settings)

        assert Counter(map(_key, result)) == Counter(map(_key, ITEMS))
        assert set(threads) == {get_ident()}

    @async_test
    async def test_async_run_refuses_the_process_executor(self) -> None:
        threads, plan = _thread_probe()
        settings = ExecutionSettings(executor="process", concurrency=2)

        async with AsyncExecution(settings=settings) as execution:
            with pytest.raises(InvalidPipelineError, match="synchronous execution"):
                await execution.arun(plan, source=ITEMS)

        assert threads == []

    @pytest.mark.parametrize("ordered", [False, True])
    @async_test
    async def test_async_early_close_stops_pulling_the_source(self, ordered) -> None:
        pulled: list[int] = []

        async def tracked():
            for item in ITEMS:
                pulled.append(item["x"])
                yield item

        plan = _hash_plan("hash", "hash")
        settings = ExecutionSettings(concurrency=2, ordered=ordered)
        first: dict = {}

        async with AsyncExecution(settings=settings) as execution:
            stream = cast(
                "AsyncGenerator", await execution.arun(plan, source=tracked())
            )
            first = await anext(stream)
            await stream.aclose()

        assert first["x"] in pulled
        assert len(pulled) < len(ITEMS)
