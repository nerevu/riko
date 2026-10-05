# vim: sw=4:ts=4:expandtab
"""Tests for settings-driven per-item concurrency in sync and async executions."""

from collections import Counter
from itertools import pairwise
from threading import Thread, get_ident
from typing import TYPE_CHECKING, Any, cast

import pytest

from riko.bado._backend import async_sleep
from riko.base._config import settings as config
from riko.base.exceptions import InvalidPipelineError
from riko.definitions._execution import ExecutionSettings
from riko.definitions._workflow import ModuleNode, StreamEdge, Workflow
from riko.definitions.modules import ModuleDefinition
from riko.execution import _execution
from riko.execution._execution import AsyncExecution, SyncExecution
from riko.execution._mapping import (
    AsyncPolicy,
    SyncPolicy,
    is_mappable,
    resolve_async_policy,
    resolve_sync_policy,
)
from riko.execution._pools import PoolHandle, get_worker_cnt
from riko.execution._resources import Resource
from riko.execution.context import Context
from riko.runtime._execution_plan import build_execution_plan
from riko.runtime._module_registry import ModuleRegistry
from riko.runtime._resolver import ResolverDispatcher
from riko.runtime._workflows import workflow_resolver
from riko.types._enums import Executor
from riko.types._workflow import Endpoint
from tests import async_test

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from riko.types._events import EventSink
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper

ITEMS = [{"x": x} for x in range(20)]


def _workflow(nodes, edges=(), resources=()):
    keyed = {node.id: node for node in nodes}
    last = nodes[-1].id
    outputs = {"default": Endpoint(last, "out")}
    return Workflow(nodes=keyed, outputs=outputs, edges=edges, resources=resources)


def _chain(*nodes):
    pairs = pairwise(nodes)
    edges = [StreamEdge(Endpoint(a.id, "out"), Endpoint(b.id, "in")) for a, b in pairs]
    return _workflow(list(nodes), edges=tuple(edges))


def _dispatcher(*definitions):
    registry = ModuleRegistry()

    for definition in definitions:
        registry.register(definition)

    return ResolverDispatcher(registry, workflow_resolver)


def _loopable(func) -> Any:
    func.loopable = True
    func.type = "processor"
    return func


def _hash_plan(*names):
    nodes = [ModuleNode(id=f"n{i}", name=name) for i, name in enumerate(names)]
    return build_execution_plan(_chain(*nodes))


def _run_sync(plan, settings=None, source=ITEMS):
    kwargs = {} if settings is None else {"settings": settings}
    execution = SyncExecution(**kwargs)
    result: list = []

    with execution:
        result = list(execution.run(plan, source=source))

    return result


def _key(item):
    return tuple(sorted(item.items()))


@pytest.fixture
def opened(monkeypatch):
    calls: list[tuple[Executor, int]] = []
    original = _execution.open_pool

    def record(executor, workers):
        calls.append((executor, workers))
        return original(executor, workers)

    monkeypatch.setattr(_execution, "open_pool", record)
    return calls


@pytest.fixture
def released(monkeypatch):
    calls: list[str] = []
    close, terminate = PoolHandle.close, PoolHandle.terminate

    def record_close(self):
        calls.append("close")
        close(self)

    def record_terminate(self):
        calls.append("terminate")
        terminate(self)

    monkeypatch.setattr(PoolHandle, "close", record_close)
    monkeypatch.setattr(PoolHandle, "terminate", record_terminate)
    return calls


SYNC_POLICIES = [
    ({}, SyncPolicy(Executor.INLINE, None)),
    ({"concurrency": 4}, SyncPolicy(Executor.THREAD, 4)),
    ({"concurrency": 1}, SyncPolicy(Executor.INLINE, None)),
    ({"executor": "inline"}, SyncPolicy(Executor.INLINE, None)),
    ({"executor": "inline", "concurrency": 4}, SyncPolicy(Executor.INLINE, None)),
    ({"executor": "thread", "concurrency": 3}, SyncPolicy(Executor.THREAD, 3)),
    ({"executor": "process", "concurrency": 2}, SyncPolicy(Executor.PROCESS, 2)),
    (
        {"executor": "thread"},
        SyncPolicy(Executor.THREAD, get_worker_cnt(0, threads=True)),
    ),
    (
        {"executor": "process"},
        SyncPolicy(Executor.PROCESS, get_worker_cnt(0, threads=False)),
    ),
]

ASYNC_POLICIES = [
    ({}, AsyncPolicy(None, False)),
    ({"concurrency": 4}, AsyncPolicy(4, False)),
    ({"executor": "inline"}, AsyncPolicy(config.connection_count, True)),
    ({"executor": "inline", "concurrency": 3}, AsyncPolicy(3, True)),
    ({"executor": "thread"}, AsyncPolicy(config.connection_count, False)),
    ({"executor": "thread", "concurrency": 3}, AsyncPolicy(3, False)),
]


@pytest.mark.parametrize(("kwargs", "expected"), SYNC_POLICIES)
def test_sync_policy_table(kwargs, expected) -> None:
    assert resolve_sync_policy(ExecutionSettings(**kwargs)) == expected


def test_sync_policy_without_concurrency_is_bounded_and_parallel() -> None:
    for executor in ("thread", "process"):
        workers = resolve_sync_policy(ExecutionSettings(executor=executor)).workers
        assert workers is not None
        assert workers > 1


@pytest.mark.parametrize(("kwargs", "expected"), ASYNC_POLICIES)
def test_async_policy_table(kwargs, expected) -> None:
    assert resolve_async_policy(ExecutionSettings(**kwargs)) == expected


def test_async_policy_refuses_the_process_executor() -> None:
    settings = ExecutionSettings(executor="process", concurrency=2)

    with pytest.raises(InvalidPipelineError, match="requires synchronous execution"):
        resolve_async_policy(settings)


def test_prepared_node_reports_loopable() -> None:
    plan = _hash_plan("hash", "count")
    assert plan.nodes["n0"].loopable is True
    assert plan.nodes["n1"].loopable is False


def test_can_map_refuses_stream_valued_inputs() -> None:
    node = _hash_plan("hash").nodes["n0"]
    assert is_mappable(node, {"emit": True, "embed": len})
    assert not is_mappable(node, {"side": iter(())})
    assert not is_mappable(node, {"others": [iter(())]})


def test_sync_run_without_settings_opens_no_pool(opened) -> None:
    plan = _hash_plan("hash")
    assert len(_run_sync(plan)) == len(ITEMS)
    assert opened == []


@pytest.mark.slow
def test_sync_auto_concurrency_maps_on_a_thread_pool(opened, released) -> None:
    plan = _hash_plan("hash", "hash")
    expected = _run_sync(plan)
    result = _run_sync(plan, ExecutionSettings(concurrency=4))

    assert Counter(map(_key, result)) == Counter(map(_key, expected))
    assert opened == [(Executor.THREAD, 4)]
    assert released == ["close"]


@pytest.mark.slow
def test_sync_ordered_concurrency_keeps_source_order() -> None:
    plan = _hash_plan("hash", "hash")
    settings = ExecutionSettings(concurrency=4, ordered=True)
    assert _run_sync(plan, settings) == _run_sync(plan)


@pytest.mark.slow
def test_sync_thread_executor_sizes_its_pool_from_the_machine(opened) -> None:
    plan = _hash_plan("hash")
    _run_sync(plan, ExecutionSettings(executor="thread"))
    assert opened == [(Executor.THREAD, get_worker_cnt(0, threads=True))]


def test_sync_inline_executor_never_opens_a_pool(opened) -> None:
    plan = _hash_plan("hash")
    settings = ExecutionSettings(executor="inline", concurrency=4)
    assert _run_sync(plan, settings) == _run_sync(plan)
    assert opened == []


@pytest.mark.slow
def test_sync_process_executor_maps_items(opened) -> None:
    plan = _hash_plan("hash")
    settings = ExecutionSettings(executor="process", concurrency=2)
    result = _run_sync(plan, settings)

    assert Counter(map(_key, result)) == Counter(map(_key, _run_sync(plan)))
    assert opened == [(Executor.PROCESS, 2)]


def test_sync_non_loopable_node_is_never_mapped(opened) -> None:
    plan = _hash_plan("count")
    assert _run_sync(plan, ExecutionSettings(concurrency=4)) == [{"count": 20}]
    assert opened == []


def test_sync_node_with_stream_input_is_never_mapped(opened) -> None:
    def joiner(items, side=None, **_):
        yield from items

        if side is not None:
            yield from side

    def source(_items=None, **_):
        yield {"t": "side"}

    dispatcher = _dispatcher(
        ModuleDefinition(name="side", sync_pipe=cast("SyncModuleWrapper", source)),
        ModuleDefinition(name="joiner", sync_pipe=_loopable(joiner)),
    )
    side = ModuleNode(id="s", name="side")
    joined = ModuleNode(id="j", name="joiner")
    edge = StreamEdge(Endpoint("s", "out"), Endpoint("j", "in:side"))
    workflow = _workflow([side, joined], edges=(edge,))
    plan = build_execution_plan(workflow, dispatcher=dispatcher)
    settings = ExecutionSettings(concurrency=4)

    expected = [{"forever": True}, {"t": "side"}]
    assert _run_sync(plan, settings, None) == expected
    assert opened == []


@pytest.mark.slow
def test_sync_pool_terminates_when_a_mapped_item_fails(released) -> None:
    def explode(item, **_):
        if item["x"] == 3:
            raise ValueError("boom")

        return iter([item])

    dispatcher = _dispatcher(
        ModuleDefinition(name="explode", sync_pipe=_loopable(explode))
    )
    workflow = _workflow([ModuleNode(id="n", name="explode")])
    plan = build_execution_plan(workflow, dispatcher=dispatcher)

    with pytest.raises(ValueError, match="boom"):
        _run_sync(plan, ExecutionSettings(concurrency=2))

    assert released == ["terminate"]


@pytest.mark.slow
def test_sync_pool_terminates_when_the_stream_is_closed_early(released) -> None:
    plan = _hash_plan("hash")

    with SyncExecution(settings=ExecutionSettings(concurrency=2)) as execution:
        stream = cast("Generator", execution.run(plan, source=ITEMS))
        next(stream)
        stream.close()

    assert released == ["terminate"]


@pytest.mark.slow
@pytest.mark.parametrize("ordered", [False, True])
def test_sync_chained_mapping_reads_the_source_on_demand(ordered) -> None:
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

    assert not worker.is_alive(), "chained mapped nodes deadlocked on the shared pool"
    assert len(pulled) <= 2 * concurrency + 1


def test_sync_mapping_waits_for_the_first_pull(opened) -> None:
    plan = _hash_plan("hash")

    with SyncExecution(settings=ExecutionSettings(concurrency=2)) as execution:
        execution.run(plan, source=ITEMS)

    assert opened == []


def _loop_dispatcher(embed_pipe=None):
    def fakeloop(item, **_):
        return iter([item])

    up = embed_pipe or cast("AsyncModuleWrapper", lambda item, **_: item)
    return _dispatcher(
        ModuleDefinition(name="fakeloop", sync_pipe=_loopable(fakeloop)),
        ModuleDefinition(name="up", async_pipe=up),
    )


def test_process_executor_refuses_a_resource_node(opened) -> None:
    node = ModuleNode(id="h", name="hash", resources={"slot": "primary"})
    workflow = _workflow([node], resources=("primary",))
    plan = build_execution_plan(workflow)
    context = Context().with_resource("primary", Resource.from_external(object()))
    settings = ExecutionSettings(executor="process", concurrency=2)
    execution = SyncExecution(context, settings=settings)

    with execution, pytest.raises(InvalidPipelineError, match="node 'h' cannot run"):
        execution.run(plan, source=ITEMS)

    assert opened == []


def test_process_executor_refuses_a_cross_mode_embed(opened) -> None:
    node = ModuleNode(id="loop", name="fakeloop", embed={"name": "up", "conf": {}})
    plan = build_execution_plan(_workflow([node]), dispatcher=_loop_dispatcher())
    settings = ExecutionSettings(executor="process", concurrency=2)
    execution = SyncExecution(settings=settings)

    with execution, pytest.raises(InvalidPipelineError, match="node 'loop' cannot run"):
        execution.run(plan, source=ITEMS)

    assert opened == []


def test_process_executor_refuses_an_unpicklable_pipe(opened) -> None:
    def local(item, **_):
        return iter([item])

    dispatcher = _dispatcher(ModuleDefinition(name="local", sync_pipe=_loopable(local)))
    workflow = _workflow([ModuleNode(id="n", name="local")])
    plan = build_execution_plan(workflow, dispatcher=dispatcher)
    settings = ExecutionSettings(executor="process", concurrency=2)
    execution = SyncExecution(settings=settings)

    with (
        execution,
        pytest.raises(InvalidPipelineError, match="node 'n' cannot run") as info,
    ):
        execution.run(plan, source=ITEMS)

    assert info.value.__cause__ is not None
    assert opened == []


async def _arun(plan, settings, source=ITEMS):
    execution = AsyncExecution(settings=settings)
    result: list = []

    async with execution:
        stream = await execution.run(plan, source=source)
        result = [item async for item in stream]

    return result


@async_test
async def test_async_concurrency_matches_sequential_results() -> None:
    plan = _hash_plan("hash", "hash")
    expected = await _arun(plan, ExecutionSettings())
    result = await _arun(plan, ExecutionSettings(concurrency=4))
    ordered = await _arun(plan, ExecutionSettings(concurrency=4, ordered=True))

    assert Counter(map(_key, result)) == Counter(map(_key, expected))
    assert ordered == expected


@async_test
async def test_async_concurrency_is_one_ceiling_across_nodes() -> None:
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
    plan = build_execution_plan(_chain(*nodes), dispatcher=_dispatcher(definition))
    result = await _arun(plan, ExecutionSettings(concurrency=3))

    assert Counter(map(_key, result)) == Counter(map(_key, ITEMS))
    assert 1 < peak <= 3


def _thread_probe():
    threads: list[int] = []

    def probe(item, **_):
        threads.append(get_ident())
        return iter([item])

    definition = ModuleDefinition(name="probe", sync_pipe=_loopable(probe))
    workflow = _workflow([ModuleNode(id="n", name="probe")])
    return threads, build_execution_plan(workflow, dispatcher=_dispatcher(definition))


@async_test
async def test_async_concurrency_runs_sync_pipes_on_worker_threads() -> None:
    threads, plan = _thread_probe()
    result = await _arun(plan, ExecutionSettings(concurrency=2))

    assert Counter(map(_key, result)) == Counter(map(_key, ITEMS))
    assert len(threads) == len(ITEMS)
    assert get_ident() not in threads


@async_test
async def test_async_inline_executor_runs_sync_pipes_on_the_loop_thread() -> None:
    threads, plan = _thread_probe()
    settings = ExecutionSettings(executor="inline", concurrency=2)
    result = await _arun(plan, settings)

    assert Counter(map(_key, result)) == Counter(map(_key, ITEMS))
    assert set(threads) == {get_ident()}


@async_test
async def test_async_run_refuses_the_process_executor() -> None:
    threads, plan = _thread_probe()
    settings = ExecutionSettings(executor="process", concurrency=2)

    async with AsyncExecution(settings=settings) as execution:
        with pytest.raises(InvalidPipelineError, match="synchronous execution"):
            await execution.run(plan, source=ITEMS)

    assert threads == []


@pytest.mark.parametrize("ordered", [False, True])
@async_test
async def test_async_early_close_stops_pulling_the_source(ordered) -> None:
    pulled: list[int] = []

    async def tracked():
        for item in ITEMS:
            pulled.append(item["x"])
            yield item

    plan = _hash_plan("hash", "hash")
    settings = ExecutionSettings(concurrency=2, ordered=ordered)
    first: dict = {}

    async with AsyncExecution(settings=settings) as execution:
        stream = cast("AsyncGenerator", await execution.run(plan, source=tracked()))
        first = await anext(stream)
        await stream.aclose()

    assert first["x"] in pulled
    assert len(pulled) < len(ITEMS)


@async_test
async def test_async_early_close_on_an_unbounded_source_is_clean() -> None:
    async def forever():
        count = 0

        while True:
            yield {"x": count}
            count += 1

    plan = _hash_plan("hash")

    for ordered in (False, True):
        settings = ExecutionSettings(concurrency=2, ordered=ordered)

        async with AsyncExecution(settings=settings) as execution:
            stream = cast("AsyncGenerator", await execution.run(plan, source=forever()))
            assert "hash" in await anext(stream)
            await stream.aclose()


class _Sink:
    def emit(self, event: object) -> None:
        pass


def test_settings_supply_the_event_sink_and_shutdown_budget() -> None:
    sink, explicit = cast("EventSink", _Sink()), cast("EventSink", _Sink())
    settings = ExecutionSettings(event_sink=sink, shutdown_timeout=1.5)
    assert SyncExecution(settings=settings).events is sink
    assert SyncExecution(events=explicit, settings=settings).events is explicit
    assert AsyncExecution(settings=settings).shutdown_timeout == pytest.approx(1.5)
