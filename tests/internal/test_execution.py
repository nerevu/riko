# vim: sw=4:ts=4:expandtab
"""Provides internal tests for executions, resources, pools, and mapping policy."""

from __future__ import annotations

from collections import Counter
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
    nullcontext,
)
from dataclasses import dataclass
from functools import partial
from itertools import pairwise
from multiprocessing import cpu_count
from threading import Event as ThreadEvent
from threading import Thread, get_ident
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest

from riko.bado._backend import (
    Event,
    async_sleep,
    asyncify,
    create_task_group,
    fail_after,
)
from riko.base._config import settings as config
from riko.base.exceptions import InvalidPipelineError, PipelineStateError
from riko.base.warnings import ResourceInterpretationWarning
from riko.definitions._context import Context
from riko.definitions._execution import ExecutionSettings
from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._resource_definition import (
    OneShotResource,
    Resource,
    ReusableResource,
)
from riko.definitions._workflow import Workflow
from riko.definitions.modules import ModuleDefinition
from riko.execution import _sync_execution
from riko.execution._async_execution import AsyncExecution
from riko.execution._mapping import (
    AsyncPolicy,
    SyncPolicy,
    is_mappable,
    resolve_async_policy,
    resolve_sync_policy,
)
from riko.execution._pools import PoolHandle, get_worker_cnt, open_pool
from riko.execution._prepared import ExecutionPlan
from riko.execution._resource_view import ResourceView
from riko.execution._sync_execution import SyncExecution
from riko.modules._decorators import operator
from riko.runtime._resolver import dispatcher
from riko.types._enums import Executor
from riko.types._resource import FactoryKind, get_factory_kind
from riko.types._workflow import Endpoint
from tests import async_test
from tests._execution import build_dispatcher

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from riko.types._events import EventSink
    from riko.types._resource import LifecycleFactory, ValueFactory
    from riko.types._streams import Stream
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper


class _SyncClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _AsyncClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


CLIENT_CLASSES = [
    pytest.param(_SyncClient, id="sync-client"),
    pytest.param(_AsyncClient, id="async-client"),
]


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


_CREDENTIAL = "microsoft/cif"


_SCALAR = 42


class _Connection:
    def __init__(self):
        self.opened = True

    @property
    def closed(self):
        return not self.opened

    def close(self):
        self.opened = False


class _AsyncConnection(_Connection):
    async def aclose(self):
        self.opened = False


def close_connection(conn: _Connection):
    conn.close()


async def close_async_connection(conn: _AsyncConnection):
    await conn.aclose()


def sync_callable_factory():
    return _Connection()


async def async_callable_factory():
    return _AsyncConnection()


def sync_gen_factory(credential: str | None = None):
    connection = _Connection()
    print(f"\nCreating a fresh sync db using {connection}")
    yield connection
    print("\nClosing sync db...")


async def async_gen_factory(credential: str | None = None):
    connection = _AsyncConnection()
    print(f"\nCreating a fresh async db using {connection}")
    yield connection
    print("\nClosing async db...")


@contextmanager
def sync_cm_factory(credential: str | None = None):
    connection = _Connection()
    print(f"Setting up sync db using {connection}")

    try:
        yield connection
    finally:
        print("Cleaning sync db...")


@asynccontextmanager
async def async_cm_factory(credential: str | None = None):
    connection = _AsyncConnection()
    print(f"Setting up async db using {connection}")

    try:
        yield connection
    finally:
        print("Cleaning async db...")


connection = pytest.fixture(sync_callable_factory)


def _check_opened(acquired: object, value: object | None) -> None:
    if value is None:
        assert acquired
    else:
        assert acquired is value

    if isinstance(acquired, _Connection):
        assert acquired.opened


def _check_closed(resource, acquired: object, value: object | None) -> None:
    if value is not None and isinstance(acquired, _Connection):
        assert acquired.closed is not resource.external
        acquired.opened = True  # reopen so the same value can be acquired again


def _test_open_close(resource, value: object | None = None):
    acquired: object = None

    with SyncExecution() as execution:
        acquired = execution.acquire(resource)
        _check_opened(acquired, value)

    _check_closed(resource, acquired, value)


async def _async_test_open_close(resource, value: object | None = None):
    acquired: object = None

    async with AsyncExecution() as execution:
        acquired = await execution.aacquire(resource)
        _check_opened(acquired, value)

    _check_closed(resource, acquired, value)


def _test_credential_and_lazy(resource):
    assert resource.credential == _CREDENTIAL
    assert resource.lazy


def _test_metadata(
    resource,
    typ: type,
    *,
    external: bool,
    reusable: bool,
    classification: FactoryKind | None = None,
):
    assert isinstance(resource, typ)
    assert resource.external == external
    assert resource.reusable == reusable

    if classification is not None:
        assert resource.kind is classification


ITEMS = [{"x": x} for x in range(20)]


def _workflow(nodes, edges=(), resources=()) -> Workflow:
    last = nodes[-1].id
    outputs = {"default": Endpoint(last, "out")}
    return Workflow(nodes=nodes, outputs=outputs, edges=edges, resources=resources)


def _chain(*nodes):
    pairs = pairwise(nodes)
    edges = [StreamEdge(Endpoint(a.id, "out"), Endpoint(b.id, "in")) for a, b in pairs]
    return _workflow(list(nodes), edges=tuple(edges))


def _loopable(func) -> Any:
    func.loopable = True
    func.type = "processor"
    return func


def _hash_plan(*names):
    nodes = [ModuleNode(id=f"n{i}", name=name) for i, name in enumerate(names)]
    return ExecutionPlan.from_workflow(_chain(*nodes), dispatcher)


def _key(item):
    return tuple(sorted(item.items()))


class TestSyncExecution:
    def test_sync_exit_stack_unwinds_on_error(self) -> None:
        events: list[str] = []

        @contextmanager
        def track(name: str):
            events.append(f"open {name}")
            try:
                yield name
            finally:
                events.append(f"close {name}")

        def fail() -> None:
            with SyncExecution() as execution:
                execution.enter_context(track("a"))
                raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            fail()

        assert events == ["open a", "close a"]

    def test_sync_resource_sees_primary_error(self) -> None:
        seen: list[str] = []

        @contextmanager
        def watcher():
            try:
                yield
            except RuntimeError:
                seen.append("saw RuntimeError")
                raise

        def run() -> None:
            with SyncExecution() as execution:
                execution.enter_context(watcher())
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            run()

        assert seen == ["saw RuntimeError"]

    def test_sync_resource_can_suppress_primary_error(self) -> None:
        reached: list[str] = []

        @contextmanager
        def swallow():
            try:
                yield
            except RuntimeError:
                pass

        with SyncExecution() as execution:
            execution.enter_context(swallow())
            raise RuntimeError("boom")

        reached.append("after")
        assert reached == ["after"]

    def test_sync_enter_after_close_raises(self) -> None:
        execution = SyncExecution()
        execution.close()

        with pytest.raises(
            PipelineStateError, match="the execution in state 'closing'"
        ):
            execution.enter_context(nullcontext(1))

    def test_sync_repeated_close_does_not_reraise_cleanup_error(self) -> None:
        calls: list[str] = []

        def boom() -> None:
            calls.append("cleanup")
            raise RuntimeError("cleanup failed")

        execution = SyncExecution()
        execution.callback(boom)

        with pytest.raises(RuntimeError, match="cleanup failed"):
            execution.close()

        assert execution.close() is False
        assert calls == ["cleanup"]

    def test_sync_cleanup_error_is_grouped_with_primary_error(self) -> None:
        # A plain cleanup callback cannot replace the execution's own error: both
        # survive, the primary first.
        def boom() -> None:
            raise RuntimeError("cleanup failed")

        def run() -> None:
            with SyncExecution() as execution:
                execution.callback(boom)
                raise ValueError("primary")

        with pytest.raises(ExceptionGroup) as info:
            run()

        primary, cleanup = info.value.exceptions
        assert isinstance(primary, ValueError)
        assert isinstance(cleanup, RuntimeError)

    def test_sync_native_context_manager_may_replace_primary_error(self) -> None:
        # A real __exit__ keeps its Python semantics: it may raise a different
        # exception in place of the primary one, and that replacement is raised bare.
        @contextmanager
        def replace():
            try:
                yield
            except ValueError as error:
                raise KeyError("replaced") from error

        def run() -> None:
            with SyncExecution() as execution:
                execution.enter_context(replace())
                raise ValueError("primary")

        with pytest.raises(KeyError, match="replaced") as info:
            run()

        assert isinstance(info.value.__cause__, ValueError)

    @async_test
    async def test_sync_portal_bridges_to_async(self) -> None:
        result = None

        async def double(value: int) -> int:
            return value * 2

        with SyncExecution() as execution:
            result = execution.run_async(double, 21)

        assert result == 42

    def test_sync_default_event_sink_is_noop(self) -> None:
        with SyncExecution() as execution:
            execution.emit("ignored")

    def test_sync_execution_dispatches_to_event_sink(self) -> None:
        sink = _RecordingSink()

        with SyncExecution(events=sink) as execution:
            execution.emit("a")
            execution.emit("b")

        assert sink.events == ["a", "b"]

    def test_each_execution_owns_its_event_sink(self) -> None:
        first = _RecordingSink()
        second = _RecordingSink()

        with SyncExecution(events=first) as execution:
            execution.emit("one")

        with SyncExecution(events=second) as execution:
            execution.emit("two")

        assert (first.events, second.events) == (["one"], ["two"])


class TestAsyncExecution:
    @async_test
    async def test_async_exit_stack_unwinds_lifo(self) -> None:
        events: list[str] = []

        @asynccontextmanager
        async def track(name: str):
            events.append(f"open {name}")
            try:
                yield name
            finally:
                events.append(f"close {name}")

        async with AsyncExecution() as execution:
            await execution.enter_async_context(track("a"))
            await execution.enter_async_context(track("b"))

        assert events == ["open a", "open b", "close b", "close a"]

    @async_test
    async def test_async_repeated_close_does_not_reraise_cleanup_error(self) -> None:
        calls: list[str] = []

        async def boom() -> None:
            calls.append("cleanup")
            raise RuntimeError("cleanup failed")

        execution = AsyncExecution()
        execution.push_async_callback(boom)

        with pytest.raises(RuntimeError, match="cleanup failed"):
            await execution.aclose()

        await execution.aclose()
        assert calls == ["cleanup"]

    @async_test
    async def test_async_ambient_cancellation_still_unwinds(self) -> None:
        events: list[str] = []
        ready = Event()

        @contextmanager
        def resource():
            try:
                yield
            finally:
                events.append("resource-closed")

        async def body() -> None:
            async with AsyncExecution() as execution:
                execution.enter_context(resource())
                ready.set()
                await async_sleep(3600)

        async with create_task_group() as tg:
            tg.start_soon(body)
            await ready.wait()
            tg.cancel_scope.cancel()

        assert events == ["resource-closed"]

    @async_test
    async def test_async_cleanup_error_is_grouped_with_primary_error(self) -> None:
        async def boom() -> None:
            raise RuntimeError("cleanup failed")

        async def run() -> None:
            async with AsyncExecution() as execution:
                execution.push_async_callback(boom)
                raise ValueError("primary")

        with pytest.raises(ExceptionGroup) as info:
            await run()

        primary, cleanup = info.value.exceptions
        assert isinstance(primary, ValueError)
        assert isinstance(cleanup, RuntimeError)

    @async_test
    async def test_async_shutdown_budget_expiry_is_grouped_with_primary_error(
        self,
    ) -> None:
        # Exhausting the shutdown budget during teardown is a cleanup failure
        # reported beside the execution's own error, not a replacement for it.
        async def slow() -> None:
            await async_sleep(3600)

        async def run() -> None:
            async with AsyncExecution(shutdown_timeout=0.05) as execution:
                execution.push_async_callback(slow)
                raise ValueError("primary")

        with pytest.raises(ExceptionGroup) as info:
            await run()

        primary, expired = info.value.exceptions
        assert isinstance(primary, ValueError)
        assert isinstance(expired, TimeoutError)

    @async_test
    async def test_async_run_sync_bridges_to_worker(self) -> None:
        result = None

        async with AsyncExecution() as execution:
            result = await execution.run_sync(pow, 2, 10)

        assert result == 1024

    @async_test
    async def test_async_default_event_sink_is_noop(self) -> None:
        async with AsyncExecution() as execution:
            execution.emit("ignored")

    @async_test
    async def test_async_execution_dispatches_to_event_sink(self) -> None:
        sink = _RecordingSink()

        async with AsyncExecution(events=sink) as execution:
            execution.emit("a")
            execution.emit("b")

        assert sink.events == ["a", "b"]


class _BadClient:
    def close(self) -> None:
        raise RuntimeError("cleanup failed")


class TestResourceAcquisition:
    @pytest.mark.parametrize("client_class", CLIENT_CLASSES)
    def test_sync_acquire_external_resource_is_borrowed(
        self, client_class: type[_SyncClient | _AsyncClient]
    ) -> None:
        client = client_class()

        with SyncExecution() as execution:
            acquired = execution.acquire(Resource.from_external(client))
            assert acquired is client

        assert client.closed is False

    def test_sync_acquire_owned_value_closes(self) -> None:
        client = _SyncClient()

        with SyncExecution() as execution:
            execution.acquire(Resource(client))

        assert client.closed is True

    def test_sync_acquire_lifecycle_generator(self) -> None:
        events: list[str] = []

        def db():
            events.append("open")
            try:
                yield "value"
            finally:
                events.append("close")

        with SyncExecution() as execution:
            acquired = execution.acquire(Resource.from_lifecycle(db))
            assert acquired == "value"
            assert events == ["open"]

        assert events == ["open", "close"]

    def test_sync_acquire_value_factory_runs_cleanup(self) -> None:
        events: list[str] = []

        def make() -> str:
            return "value"

        def cleanup(value: str) -> None:
            events.append(f"cleanup {value}")

        with SyncExecution() as execution:
            acquired = execution.acquire(Resource.from_factory(make, cleanup=cleanup))
            assert acquired == "value"

        assert events == ["cleanup value"]

    def test_sync_acquire_value_factory_without_cleanup(self) -> None:
        client = _SyncClient()

        with SyncExecution() as execution:
            acquired = execution.acquire(
                Resource.from_factory(lambda: client, cleanup=False)
            )
            assert acquired is client

        assert client.closed is False

    def test_sync_acquire_factory_cleanup_is_authoritative(self) -> None:
        client = _SyncClient()
        events: list[str] = []

        with SyncExecution() as execution:
            execution.acquire(
                Resource.from_factory(
                    lambda: client, cleanup=lambda _: events.append("x")
                )
            )

        assert events == ["x"]
        assert client.closed is False

    @async_test
    async def test_sync_acquire_async_value_factory_bridges(self) -> None:
        acquired = None

        async def make() -> str:
            return "value"

        with SyncExecution() as execution:
            acquired = execution.acquire(Resource.from_factory(make, cleanup=False))

        assert acquired == "value"

    def test_sync_acquire_is_single_flight(self) -> None:
        calls: list[int] = []
        first, second = float("nan"), float("nan")

        def make() -> object:
            calls.append(1)
            return object()

        with SyncExecution() as execution:
            resource = Resource.from_factory(make, cleanup=False)
            first = execution.acquire(resource)
            second = execution.acquire(resource)

        assert first is second
        assert len(calls) == 1

    def test_sync_acquire_memoizes_failure(self) -> None:
        calls: list[int] = []

        def make() -> object:
            calls.append(1)
            raise RuntimeError("boom")

        with SyncExecution() as execution:
            resource = Resource.from_factory(make, cleanup=False)

            with pytest.raises(RuntimeError, match="boom"):
                execution.acquire(resource)

            with pytest.raises(RuntimeError, match="boom"):
                execution.acquire(resource)

        assert len(calls) == 1

    def test_sync_partial_acquisition_unwinds(self) -> None:
        client = _SyncClient()

        def failing() -> object:
            raise RuntimeError("boom")

        def run() -> None:
            with SyncExecution() as execution:
                execution.acquire(Resource(client))
                execution.acquire(Resource.from_factory(failing, cleanup=False))

        with pytest.raises(RuntimeError, match="boom"):
            run()

        assert client.closed is True

    def test_sync_acquire_lone_cleanup_error_raises_bare(self) -> None:
        execution = SyncExecution()
        execution.acquire(Resource(_BadClient()))

        with pytest.raises(RuntimeError, match="cleanup failed"):
            execution.close()

    def test_sync_acquire_async_lifecycle_rejected(self) -> None:
        async def db():
            yield "value"

        with SyncExecution() as execution, pytest.raises(InvalidPipelineError):
            execution.acquire(Resource.from_lifecycle(db))

    def test_sync_async_cleanup_rejected_before_producer(self) -> None:
        produced: list[int] = []

        def make() -> object:
            produced.append(1)
            return object()

        async def cleanup(_value: object) -> None:
            pass

        with SyncExecution() as execution:
            resource = Resource.from_factory(make, cleanup=cleanup)

            with pytest.raises(InvalidPipelineError, match="async"):
                execution.acquire(resource)

        assert produced == []

    def test_sync_owned_async_only_value_rejected(self) -> None:
        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="async"),
        ):
            execution.acquire(Resource(_AsyncClient()))


class TestAsyncResourceAcquisition:
    @pytest.mark.parametrize("client_class", CLIENT_CLASSES)
    @async_test
    async def test_async_acquire_external_resource_is_borrowed(
        self, client_class: type[_SyncClient | _AsyncClient]
    ) -> None:
        client = client_class()

        async with AsyncExecution() as execution:
            acquired = await execution.aacquire(Resource.from_external(client))
            assert acquired is client

        assert client.closed is False

    @async_test
    async def test_async_acquire_owned_value_closes(self) -> None:
        client = _AsyncClient()

        async with AsyncExecution() as execution:
            await execution.aacquire(Resource(client))

        assert client.closed is True

    @async_test
    async def test_async_acquire_async_lifecycle_generator(self) -> None:
        events: list[str] = []

        async def db():
            events.append("open")
            try:
                yield "value"
            finally:
                events.append("close")

        async with AsyncExecution() as execution:
            acquired = await execution.aacquire(Resource.from_lifecycle(db))
            assert acquired == "value"
            assert events == ["open"]

        assert events == ["open", "close"]

    @async_test
    async def test_async_worker_adapts_sync_lifecycle_off_loop(self) -> None:
        threads: dict[str, int] = {}

        def db():
            threads["enter"] = get_ident()
            try:
                yield "value"
            finally:
                threads["exit"] = get_ident()

        loop_thread = get_ident()

        async with AsyncExecution() as execution:
            acquired = await execution.aacquire(Resource.from_lifecycle(db))
            assert acquired == "value"

        assert threads["enter"] != loop_thread
        assert threads["exit"] != loop_thread

    @async_test
    async def test_async_worker_adapts_sync_factory_and_cleanup_off_loop(self) -> None:
        threads: dict[str, int] = {}

        def make() -> str:
            threads["factory"] = get_ident()
            return "value"

        def cleanup(value: str) -> None:
            threads["cleanup"] = get_ident()

        loop_thread = get_ident()

        async with AsyncExecution() as execution:
            acquired = await execution.aacquire(
                Resource.from_factory(make, cleanup=cleanup)
            )
            assert acquired == "value"

        assert threads["factory"] != loop_thread
        assert threads["cleanup"] != loop_thread

    @async_test
    async def test_async_worker_adapts_owned_sync_close_off_loop(self) -> None:
        threads: dict[str, int] = {}

        class _Recording:
            def close(self) -> None:
                threads["close"] = get_ident()

        client = _Recording()
        loop_thread = get_ident()

        async with AsyncExecution() as execution:
            acquired = await execution.aacquire(Resource(client))
            assert acquired is client

        assert threads["close"] != loop_thread

    @async_test
    async def test_async_acquire_async_value_factory(self) -> None:
        events: list[str] = []

        async def make() -> str:
            return "value"

        async def cleanup(value: str) -> None:
            events.append("cleanup")

        async with AsyncExecution() as execution:
            acquired = await execution.aacquire(
                Resource.from_factory(make, cleanup=cleanup)
            )
            assert acquired == "value"

        assert events == ["cleanup"]

    @async_test
    async def test_async_acquire_is_single_flight(self) -> None:
        calls: list[int] = []
        results: list[object] = []
        gate = Event()

        async def make() -> object:
            calls.append(1)
            await gate.wait()
            return object()

        async with AsyncExecution() as execution:
            resource = Resource.from_factory(make, cleanup=False)

            async def grab() -> None:
                results.append(await execution.aacquire(resource))

            async with create_task_group() as tg:
                tg.start_soon(grab)
                tg.start_soon(grab)
                await async_sleep(0)
                gate.set()

        assert len(calls) == 1
        assert results[0] is results[1]

    @async_test
    async def test_async_acquire_teardown_on_failure(self) -> None:
        events: list[str] = []

        async def db():
            try:
                yield "value"
            finally:
                events.append("close")

        async def fail() -> None:
            async with AsyncExecution() as execution:
                await execution.aacquire(Resource.from_lifecycle(db))
                raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await fail()

        assert events == ["close"]

    @pytest.mark.xfail(
        strict=True,
        reason="an async execution enters and exits a sync lifecycle resource on "
        "whichever worker threads are free, so a thread-bound client can be closed "
        "on a thread other than the one that opened it",
    )
    @async_test
    async def test_async_sync_lifecycle_resource_exits_on_its_entry_thread(
        self,
    ) -> None:
        threads: dict[str, int] = {}
        started, release = ThreadEvent(), ThreadEvent()

        def lifecycle() -> Generator[str]:
            threads["enter"] = get_ident()

            try:
                yield "client"
            finally:
                threads["exit"] = get_ident()

        def occupy() -> None:
            started.set()
            release.wait()

        async def aoccupy() -> None:
            await asyncify(occupy)()

        with fail_after(10):
            async with create_task_group() as tg:
                try:
                    async with AsyncExecution() as execution:
                        await execution.aacquire(Resource.from_lifecycle(lifecycle))
                        tg.start_soon(aoccupy)

                        while not started.is_set():
                            await async_sleep(0.01)
                finally:
                    release.set()

        assert threads["exit"] == threads["enter"]


class TestLifecycleFactory:
    @pytest.mark.parametrize(
        "factory",
        [sync_gen_factory, async_gen_factory, sync_cm_factory, async_cm_factory],
    )
    def test_raises[T](self, factory: LifecycleFactory[T]):
        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource(factory)

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource.from_external(factory)

    @pytest.mark.parametrize(
        "factory",
        [sync_gen_factory, async_gen_factory, sync_cm_factory, async_cm_factory],
    )
    def test_credential_and_lazy_carried[T](self, factory: LifecycleFactory[T]):
        context = Context().with_resource(
            "factory", factory, credential=_CREDENTIAL, lazy=True
        )
        resource = context.resources["factory"]
        _test_credential_and_lazy(resource)

        resource = Resource.from_lifecycle(factory, credential=_CREDENTIAL, lazy=True)
        _test_credential_and_lazy(resource)

        resource = Resource.from_factory(factory, credential=_CREDENTIAL, lazy=True)
        _test_credential_and_lazy(resource)

    @pytest.mark.parametrize(
        ("factory", "classification"),
        [
            (sync_gen_factory, FactoryKind.SYNC_GEN_FACTORY),
            (async_gen_factory, FactoryKind.ASYNC_GEN_FACTORY),
            (sync_cm_factory, FactoryKind.SYNC_CM_FACTORY),
            (async_cm_factory, FactoryKind.ASYNC_CM_FACTORY),
        ],
    )
    def test_resource_metadata[T](
        self, factory: LifecycleFactory[T], classification: FactoryKind
    ):
        assert get_factory_kind(factory) is classification
        test_metadata = partial(_test_metadata, classification=classification)

        context = Context().with_resource("factory", factory)
        resource = context.resources["factory"]
        test_metadata(resource, ReusableResource, external=False, reusable=True)

        resource = Resource.from_lifecycle(factory)
        test_metadata(resource, OneShotResource, external=False, reusable=False)

        resource = Resource.from_factory(factory)
        test_metadata(resource, ReusableResource, external=False, reusable=True)

    @pytest.mark.parametrize(
        "factory",
        [sync_gen_factory, async_gen_factory, sync_cm_factory, async_cm_factory],
    )
    @async_test
    async def test_resource_opens_and_closes[T](self, factory: LifecycleFactory[T]):
        context = Context().with_resource("factory", factory)
        await _async_test_open_close(context.resources["factory"])
        await _async_test_open_close(Resource.from_lifecycle(factory))
        await _async_test_open_close(Resource.from_factory(factory))


class TestValueFactory:
    @pytest.mark.parametrize("factory", [sync_callable_factory, async_callable_factory])
    def test_raises[T](self, factory: ValueFactory[T]):
        with pytest.raises(TypeError, match=r"Invalid resource factory.*one-shot"):
            Context().with_resource(  # pyright: ignore[reportCallIssue]
                "factory",
                factory,  # pyright: ignore[reportArgumentType]
            )

        with pytest.raises(TypeError, match="Must provide a Closeable value"):
            Resource(factory)

        with pytest.raises(TypeError, match="Invalid lifecycle factory"):
            Resource.from_lifecycle(factory)  # pyright: ignore[reportArgumentType]

        with pytest.raises(TypeError, match=r"ValueFactory requires.*cleanup function"):
            Resource.from_factory(factory)  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize(
        ("factory", "cleanup"),
        [
            (sync_callable_factory, close_connection),
            (async_callable_factory, close_async_connection),
        ],
    )
    def test_credential_and_lazy_carried[T](self, factory: ValueFactory[T], cleanup):
        resource = Resource.from_factory(
            factory, cleanup=cleanup, credential=_CREDENTIAL, lazy=True
        )
        _test_credential_and_lazy(resource)

    @pytest.mark.parametrize(
        ("factory", "cleanup", "classification"),
        [
            (
                sync_callable_factory,
                close_connection,
                FactoryKind.SYNC_CALLABLE_FACTORY,
            ),
            (
                async_callable_factory,
                close_async_connection,
                FactoryKind.ASYNC_CALLABLE_FACTORY,
            ),
        ],
    )
    def test_resource_metadata[T](
        self, factory: ValueFactory[T], cleanup, classification: FactoryKind
    ):
        assert get_factory_kind(factory, lifecycle=False) is classification
        test_metadata = partial(_test_metadata, typ=ReusableResource, reusable=True)

        resource = Resource.from_external(factory)
        test_metadata(resource, external=True)

        resource = Resource.from_factory(factory, cleanup=cleanup)
        test_metadata(resource, external=False, classification=classification)

    @pytest.mark.parametrize(
        ("factory", "cleanup"),
        [
            (sync_callable_factory, close_connection),
            (async_callable_factory, close_async_connection),
        ],
    )
    @async_test
    async def test_resource_opens_and_closes[T](
        self, factory: ValueFactory[T], cleanup
    ):
        await _async_test_open_close(Resource.from_factory(factory, cleanup=cleanup))


def cleanup_contextmanager(_: AbstractContextManager[_Connection]):
    pass


async_connection = pytest.fixture(async_callable_factory)


sync_contextmanager = pytest.fixture(sync_cm_factory)


async_contextmanager = pytest.fixture(async_cm_factory)


scalar = pytest.fixture(lambda: _SCALAR)


@pytest.fixture
def one_shot_resource(connection: _Connection) -> Resource[_Connection]:
    return Resource(connection)


@pytest.fixture
def external_resource(connection: _Connection):
    return Resource.from_external(connection)


type ValueKind = Literal[
    "scalar", "closeable", "context-manager", "one-shot", "external"
]


@dataclass(frozen=True)
class ValueCase:
    fixture: str
    kind: ValueKind


VALUE_CASES = [
    pytest.param(ValueCase("scalar", "scalar"), id="scalar"),
    pytest.param(ValueCase("connection", "closeable"), id="connection"),
    pytest.param(
        ValueCase("sync_contextmanager", "context-manager"), id="sync-context-manager"
    ),
    pytest.param(ValueCase("one_shot_resource", "one-shot"), id="one-shot"),
    pytest.param(ValueCase("external_resource", "external"), id="external"),
]


class TestValues:
    @pytest.mark.parametrize("case", VALUE_CASES)
    def test_constructor_contract(self, case: ValueCase, request):
        value = request.getfixturevalue(case.fixture)

        if case.kind == "external":
            context = Context().with_resource("value", value)
            resource = context.resources["value"]
            _test_metadata(resource, ReusableResource, external=True, reusable=True)
            _test_open_close(resource)

            with pytest.raises(TypeError, match=r"credential.*lazy.*LifecycleFactory"):
                Context().with_resource(
                    "value", value, credential=_CREDENTIAL, lazy=True
                )
        else:
            with pytest.raises(TypeError, match="Invalid resource factory"):
                Context().with_resource("value", value)

        if case.kind in {"one-shot", "external"}:
            with pytest.raises(TypeError, match="Expected a resolved resource value"):
                Resource(value)
        elif case.kind == "scalar":
            with pytest.raises(TypeError, match="Must provide a Closeable value"):
                Resource(value)

            owned = Resource(value, cleanup=lambda _: None)
            _test_metadata(owned, OneShotResource, external=False, reusable=False)
            _test_open_close(owned, value)

            external = Resource.from_external(value)
            _test_metadata(external, ReusableResource, external=True, reusable=True)
            _test_open_close(external, value)
        elif case.kind == "closeable":
            owned = Resource(value)
            _test_metadata(owned, OneShotResource, external=False, reusable=False)
            _test_open_close(owned, value)

            external = Resource.from_external(value)
            _test_metadata(external, ReusableResource, external=True, reusable=True)
            _test_open_close(external, value)
        else:
            with pytest.raises(TypeError, match="Expected a resolved resource value"):
                Resource(value)

            with pytest.raises(TypeError, match="Expected a resolved resource"):
                Resource.from_external(value)

        if case.kind == "context-manager":
            lifecycle = Resource.from_lifecycle(value)
            _test_metadata(lifecycle, OneShotResource, external=False, reusable=False)

            configured = Resource.from_lifecycle(
                value, credential=_CREDENTIAL, lazy=True
            )
            _test_credential_and_lazy(configured)

            _test_open_close(lifecycle)

            with pytest.raises(TypeError, match=r"ValueFactory.*cleanup function"):
                Resource.from_factory(value)

            casted = cast("ValueFactory[AbstractContextManager[_Connection]]", value)

            with pytest.warns(ResourceInterpretationWarning, match="context manager"):
                factory = Resource.from_factory(casted, cleanup=cleanup_contextmanager)

            _test_metadata(factory, ReusableResource, external=False, reusable=True)
        else:
            with pytest.raises(TypeError, match="Invalid lifecycle factory"):
                Resource.from_lifecycle(value)

            with pytest.raises(TypeError, match="Invalid resource factory"):
                Resource.from_factory(value)

    @async_test
    async def test_async_constructor_contract(
        self,
        async_connection: _AsyncConnection,
        async_contextmanager: AbstractAsyncContextManager[_AsyncConnection],
    ):
        with pytest.raises(TypeError, match="Invalid resource factory"):
            Context().with_resource(  # pyright: ignore[reportCallIssue]
                "value",
                async_contextmanager,  # pyright: ignore[reportArgumentType]
            )

        await _async_test_open_close(Resource(async_connection), async_connection)

        external = Resource.from_external(async_connection)
        await _async_test_open_close(external, async_connection)

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource(async_contextmanager)

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource.from_external(async_contextmanager)

        lifecycle = Resource.from_lifecycle(async_contextmanager)

        await _async_test_open_close(lifecycle)

        with pytest.raises(TypeError, match=r"ValueFactory.*cleanup function"):
            Resource.from_factory(
                async_contextmanager  # pyright: ignore[reportArgumentType]
            )


class TestResourceEcosystem:
    def test_context_with_resource_is_immutable_copy(self):
        base = Context(verbose=True)
        resource = Resource.from_factory(sync_gen_factory)
        derived = base.with_resource("resource", resource)

        assert "resource" not in base.resources
        assert derived.resources["resource"] is resource
        assert derived.verbose
        assert derived is not base

    def test_classify_rejects_non_resource(self):
        with pytest.raises(TypeError, match="Invalid lifecycle factory"):
            get_factory_kind(_SCALAR)  # pyright: ignore[reportArgumentType]

    def test_operator_passes_the_supplied_view_through(self, connection: _Connection):
        captured = {}

        @operator()
        def pipe(stream: Stream, objconf, tuples, **kwargs) -> Stream:
            captured["view"] = kwargs.get("resources")
            return stream

        view = ResourceView({"resource": connection})
        list(pipe([{"a": 1}], resources=view))
        assert captured["view"] is view


class TestResourceImmutability:
    """
    Keep resource definitions structurally immutable.

    Fields cannot be reassigned and definition-owned containers are read-only, but
    Riko does not recursively freeze arbitrary referenced values. Do not restore
    public setters; mutable resolved state belongs to the execution layer.
    """

    def test_external_value_fields_are_read_only(self, connection: _Connection):
        resource = Resource.from_external(connection)

        with pytest.raises(AttributeError):
            resource.value = object()  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            resource.credential = "other"  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            resource.lazy = True  # pyright: ignore[reportAttributeAccessIssue]

    def test_referenced_value_is_not_frozen(self, connection: _Connection):
        resource = Resource.from_external(connection)
        connection.opened = False
        assert resource.value is connection

        if isinstance(resource.value, _Connection):
            assert resource.value.closed

    def test_factory_fields_and_containers_are_read_only(self):
        resource = Resource.from_factory(sync_gen_factory)

        with pytest.raises(AttributeError):
            resource.factory = sync_gen_factory  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            resource.kind = FactoryKind.SYNC_GEN_FACTORY  # pyright: ignore[reportAttributeAccessIssue]


class TestWorkerCnt:
    def test_zero_length_uses_the_maximum(self) -> None:
        assert get_worker_cnt(0) == cpu_count() * 2
        assert get_worker_cnt(0, False) == cpu_count()

    def test_small_length_caps_at_the_length(self) -> None:
        assert get_worker_cnt(1) == 1
        assert get_worker_cnt(1, False) == 1

    def test_huge_length_caps_at_the_maximum(self) -> None:
        assert get_worker_cnt(10_000) == cpu_count() * 2
        assert get_worker_cnt(10_000, False) == cpu_count()


@pytest.mark.slow
class TestPoolHandle:
    @pytest.mark.parametrize("release", ["close", "terminate"])
    def test_release_frees_the_pool_once(self, release: str) -> None:
        handle = open_pool(Executor.THREAD, 2)
        assert handle

        getattr(handle, release)()
        assert handle.pool is None
        assert not handle

        getattr(handle, release)()
        assert handle.pool is None

    def test_require_pool_after_release_raises(self) -> None:
        handle = open_pool(Executor.THREAD, 2)
        handle.close()

        match = "cannot reuse the worker pool in state 'closed'"
        with pytest.raises(PipelineStateError, match=match):
            handle.require_pool()


class TestOpenPool:
    @pytest.mark.slow
    @pytest.mark.parametrize("executor", [Executor.THREAD, Executor.PROCESS])
    def test_builds_a_pool(self, executor: Executor) -> None:
        handle = open_pool(executor, 2)

        try:
            assert handle
            assert getattr(handle.pool, "_processes") == 2  # noqa: B009
        finally:
            handle.close()

    @pytest.mark.parametrize("executor", [Executor.INLINE, Executor.AUTO])
    def test_poolless_executors_have_no_pool(self, executor: Executor) -> None:
        with pytest.raises(ValueError, match=executor.value):
            open_pool(executor, 2)


class _Sink:
    def emit(self, event: object) -> None:
        pass


class TestExecutionSettings:
    def test_unknown_executor_lists_the_known_executors(self) -> None:
        message = "ExecutionSettings 'executor': 'bogus'. Expected one of auto, inline"

        with pytest.raises(ValueError, match=message):
            ExecutionSettings(executor="bogus")

    def test_settings_supply_the_event_sink_and_shutdown_budget(self) -> None:
        sink, explicit = cast("EventSink", _Sink()), cast("EventSink", _Sink())
        settings = ExecutionSettings(event_sink=sink, shutdown_timeout=1.5)
        assert SyncExecution(settings=settings).events is sink
        assert SyncExecution(events=explicit, settings=settings).events is explicit
        assert AsyncExecution(settings=settings).shutdown_timeout == pytest.approx(1.5)


SYNC_POLICIES = [
    ({}, SyncPolicy(Executor.INLINE, None)),
    ({"concurrency": 4}, SyncPolicy(Executor.THREAD, 4)),
    ({"concurrency": 1}, SyncPolicy(Executor.INLINE, None)),
    ({"executor": "inline"}, SyncPolicy(Executor.INLINE, None)),
    ({"executor": "inline", "concurrency": 4}, SyncPolicy(Executor.INLINE, None)),
    ({"executor": "thread", "concurrency": 3}, SyncPolicy(Executor.THREAD, 3)),
    ({"executor": "process", "concurrency": 2}, SyncPolicy(Executor.PROCESS, 2)),
    ({"executor": "thread"}, SyncPolicy(Executor.THREAD, 1)),
    ({"executor": "process"}, SyncPolicy(Executor.PROCESS, 1)),
    ({"concurrency": "auto"}, SyncPolicy(Executor.THREAD, get_worker_cnt(0))),
    (
        {"executor": "thread", "concurrency": "auto"},
        SyncPolicy(Executor.THREAD, get_worker_cnt(0, threads=True)),
    ),
    (
        {"executor": "process", "concurrency": "auto"},
        SyncPolicy(Executor.PROCESS, get_worker_cnt(0, threads=False)),
    ),
    ({"executor": "inline", "concurrency": "auto"}, SyncPolicy(Executor.INLINE, None)),
]


ASYNC_POLICIES = [
    ({}, AsyncPolicy(None, False)),
    ({"concurrency": 4}, AsyncPolicy(4, False)),
    ({"executor": "inline"}, AsyncPolicy(1, True)),
    ({"executor": "inline", "concurrency": 3}, AsyncPolicy(3, True)),
    ({"executor": "thread"}, AsyncPolicy(1, False)),
    ({"concurrency": "auto"}, AsyncPolicy(config.concurrency_limit, False)),
    (
        {"executor": "inline", "concurrency": "auto"},
        AsyncPolicy(config.concurrency_limit, True),
    ),
    ({"executor": "thread", "concurrency": 3}, AsyncPolicy(3, False)),
]


class TestMappingPolicy:
    @pytest.mark.parametrize(("kwargs", "expected"), SYNC_POLICIES)
    def test_sync_policy_table(self, kwargs, expected) -> None:
        assert resolve_sync_policy(ExecutionSettings(**kwargs)) == expected

    @pytest.mark.parametrize(("kwargs", "expected"), ASYNC_POLICIES)
    def test_async_policy_table(self, kwargs, expected) -> None:
        assert resolve_async_policy(ExecutionSettings(**kwargs)) == expected

    def test_prepared_node_reports_loopable(self) -> None:
        plan = _hash_plan("hash", "count")
        assert plan.nodes["n0"].loopable is True
        assert plan.nodes["n1"].loopable is False

    def test_can_map_refuses_stream_valued_inputs(self) -> None:
        node = _hash_plan("hash").nodes["n0"]
        assert is_mappable(node, {"emit": True, "embed": len})
        assert not is_mappable(node, {"side": iter(())})
        assert not is_mappable(node, {"others": [iter(())]})

    def test_async_policy_refuses_the_process_executor(self) -> None:
        settings = ExecutionSettings(executor="process", concurrency=2)

        with pytest.raises(
            InvalidPipelineError, match="requires synchronous execution"
        ):
            resolve_async_policy(settings)


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
    original = _sync_execution.open_pool

    def record(executor, workers):
        calls.append((executor, workers))
        return original(executor, workers)

    monkeypatch.setattr(_sync_execution, "open_pool", record)
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

    def test_sync_node_with_stream_input_is_never_mapped(self, opened) -> None:
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
        joined = ModuleNode(id="j", name="joiner")
        edge = StreamEdge(Endpoint("s", "out"), Endpoint("j", "in:side"))
        flow = _workflow([side, joined], edges=(edge,))
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        settings = ExecutionSettings(concurrency=4)

        expected = [{"forever": True}, {"t": "side"}]
        assert _run_sync(plan, settings, None) == expected
        assert opened == []

    @pytest.mark.slow
    def test_sync_pool_terminates_when_a_mapped_item_fails(self, released) -> None:
        def explode(item, **_):
            if item["x"] == 3:
                raise ValueError("boom")

            return iter([item])

        dispatcher = build_dispatcher(
            ModuleDefinition(name="explode", sync_pipe=_loopable(explode))
        )
        flow = _workflow([ModuleNode(id="n", name="explode")])
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        with pytest.raises(ValueError, match="boom"):
            _run_sync(plan, ExecutionSettings(concurrency=2))

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
        node = ModuleNode(id="h", name="hash", resources={"slot": "primary"})
        flow = _workflow([node], resources=("primary",))
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        context = Context().with_resource("primary", Resource.from_external(object()))
        settings = ExecutionSettings(executor="process", concurrency=2)
        execution = SyncExecution(context, settings=settings)

        with (
            execution,
            pytest.raises(InvalidPipelineError, match="node 'h' cannot run"),
        ):
            execution.run(plan, source=ITEMS)

        assert opened == []

    def test_process_executor_refuses_a_cross_mode_embed(self, opened) -> None:
        node = ModuleNode(id="loop", name="fakeloop", embed={"name": "up", "conf": {}})
        plan = ExecutionPlan.from_workflow(
            _workflow([node]), dispatcher=_loop_dispatcher()
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
        flow = _workflow([ModuleNode(id="n", name="local")])
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
    flow = _workflow([ModuleNode(id="n", name="probe")])
    return threads, ExecutionPlan.from_workflow(
        flow, dispatcher=build_dispatcher(definition)
    )


class TestAsyncConcurrency:
    @async_test
    async def test_async_long_sync_only_chain_completes(self) -> None:
        # Each sync-only node holds a worker thread while it pulls its upstream, so
        # a chain longer than the default thread limit must still get a thread each.
        pipe = cast("SyncModuleWrapper", _passthru)
        definition = ModuleDefinition(name="passthru", sync_pipe=pipe)
        nodes = [ModuleNode(id=f"n{i}", name="passthru") for i in range(45)]
        plan = ExecutionPlan.from_workflow(
            _chain(*nodes), dispatcher=build_dispatcher(definition)
        )
        result: list = []

        with fail_after(20):
            async with AsyncExecution() as execution:
                stream = await execution.arun(plan, source=ITEMS[:2])
                result = [item async for item in stream]

        assert result == ITEMS[:2]

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
            _chain(*nodes), dispatcher=build_dispatcher(definition)
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
