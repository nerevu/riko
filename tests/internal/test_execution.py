# vim: sw=4:ts=4:expandtab
"""Provides internal tests for executions and their resources."""

from __future__ import annotations

from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
    nullcontext,
)
from dataclasses import dataclass
from functools import partial, wraps
from threading import Event as ThreadEvent
from threading import get_ident
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest

from riko.bado._backend import (
    Event,
    async_sleep,
    asyncify,
    create_task_group,
    fail_after,
)
from riko.base.exceptions import (
    InvalidPipelineError,
    PipelineStateError,
    ResourceInterpretationWarning,
)
from riko.definitions._context import Context
from riko.definitions._resource_definition import (
    OneShotResource,
    Resource,
    ReusableResource,
)
from riko.execution._async_execution import AsyncExecution
from riko.execution._resource_teardown import aclose_resource
from riko.execution._resource_view import ResourceView
from riko.execution._sync_execution import SyncExecution
from riko.modules._decorators import operator
from riko.types._io import is_closeable
from riko.types._resource import (
    AsyncLifecyclePlan,
    ResourceStrategy,
    SyncLifecyclePlan,
    ValueFactoryPlan,
    build_factory_plan,
    build_lifecycle_plan,
)
from tests import async_test, skipif_issync

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator

    from riko.types._resource import LifecycleFactory, ValueFactory
    from riko.types._streams import Stream


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


def _passthrough[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return func(*args, **kwargs)

    return wrapper


wrapped_sync_gen_factory = _passthrough(sync_gen_factory)
wrapped_async_gen_factory = _passthrough(async_gen_factory)
wrapped_sync_cm_factory = _passthrough(sync_cm_factory)
wrapped_async_cm_factory = _passthrough(async_cm_factory)
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
    classification: type | None = None,
):
    assert isinstance(resource, typ)
    assert resource.external == external
    assert resource.reusable == reusable

    if classification is not None:
        assert isinstance(resource.plan, classification)


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
    async def test_async_sync_callback_runs_on_close(self) -> None:
        calls: list[str] = []

        async with AsyncExecution() as execution:
            execution.callback(calls.append, "closed")

        assert calls == ["closed"]

    @async_test
    async def test_async_native_context_manager_may_replace_primary_error(self) -> None:
        @asynccontextmanager
        async def replace():
            try:
                yield
            except ValueError as error:
                raise KeyError("replaced") from error

        async def run() -> None:
            async with AsyncExecution() as execution:
                await execution.enter_async_context(replace())
                raise ValueError("primary")

        with pytest.raises(KeyError, match="replaced") as info:
            await run()

        assert isinstance(info.value.__cause__, ValueError)

    @async_test
    async def test_async_shutdown_timeout_expiry_is_grouped_with_primary_error(
        self,
    ) -> None:
        # Exhausting the shutdown timeout during teardown is a cleanup failure
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


def _acquire_twice(resource: Resource[Any]) -> list[object]:
    """Acquires ``resource`` twice in one execution, keeping each value or error."""
    outcomes: list[object] = []

    with SyncExecution() as execution:
        for _ in range(2):
            try:
                outcomes.append(execution.acquire(resource))
            except TypeError as error:
                outcomes.append(error)

    return outcomes


async def _aacquire_twice(resource: Resource[Any]) -> list[object]:
    """Acquires ``resource`` twice in an async execution, keeping each outcome."""
    outcomes: list[object] = []

    async with AsyncExecution() as execution:
        for _ in range(2):
            try:
                outcomes.append(await execution.aacquire(resource))
            except TypeError as error:
                outcomes.append(error)

    return outcomes


async def _value() -> str:
    return "value"


def _build_awaitable() -> Awaitable[str]:
    return _value()


@contextmanager
def _needs_arg(ctx: object) -> Generator[object]:
    yield ctx


class TestResourceAcquisition:
    @skipif_issync
    def test_awaitable_from_sync_factory_is_awaited(self) -> None:
        resource = Resource.from_factory(_build_awaitable, cleanup=False)
        assert _acquire_twice(resource) == ["value", "value"]

    def test_failed_lifecycle_factory_replays_its_error(self) -> None:
        first, second = _acquire_twice(Resource.from_lifecycle(_needs_arg))
        assert isinstance(first, TypeError)
        assert second is first

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


ACLOSE_CASES = [
    pytest.param(False, False, id="left-open"),
    pytest.param(_SyncClient.close, True, id="sync-cleanup"),
    pytest.param(None, True, id="sync-close"),
]


class TestAsyncResourceAcquisition:
    @async_test
    async def test_async_awaitable_from_sync_factory_is_awaited(self) -> None:
        resource = Resource.from_factory(_build_awaitable, cleanup=False)
        assert await _aacquire_twice(resource) == ["value", "value"]

    @async_test
    async def test_async_failed_lifecycle_factory_replays_its_error(self) -> None:
        first, second = await _aacquire_twice(Resource.from_lifecycle(_needs_arg))
        assert isinstance(first, TypeError)
        assert second is first

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

    @async_test
    async def test_async_acquire_memoizes_failure(self) -> None:
        calls: list[int] = []

        async def make() -> object:
            calls.append(1)
            raise RuntimeError("boom")

        async with AsyncExecution() as execution:
            resource = Resource.from_factory(make, cleanup=False)

            with pytest.raises(RuntimeError, match="boom"):
                await execution.aacquire(resource)

            with pytest.raises(RuntimeError, match="boom"):
                await execution.aacquire(resource)

        assert len(calls) == 1

    @pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
    @async_test
    async def test_async_owned_value_cleanup_is_authoritative(self, is_async) -> None:
        client = _SyncClient()
        events: list[str] = []

        async def acleanup(_: object) -> None:
            events.append("x")

        cleanup = acleanup if is_async else lambda _: events.append("x")

        async with AsyncExecution() as execution:
            await execution.aacquire(Resource(client, cleanup=cleanup))

        assert events == ["x"]
        assert client.closed is False

    @pytest.mark.parametrize(("cleanup", "closed"), ACLOSE_CASES)
    @async_test
    async def test_aclose_resource(self, cleanup, closed) -> None:
        client = _SyncClient()
        await aclose_resource(cleanup, client)
        assert client.closed is closed

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

        with pytest.raises(TypeError, match="Cleanup is not allowed"):
            Resource.from_factory(factory, cleanup=False)

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
            pytest.param(sync_gen_factory, SyncLifecyclePlan, id="sync-gen"),
            pytest.param(async_gen_factory, AsyncLifecyclePlan, id="async-gen"),
            pytest.param(sync_cm_factory, SyncLifecyclePlan, id="sync-cm"),
            pytest.param(async_cm_factory, AsyncLifecyclePlan, id="async-cm"),
            pytest.param(
                wrapped_sync_gen_factory, SyncLifecyclePlan, id="wraps-sync-gen"
            ),
            pytest.param(
                wrapped_async_gen_factory, AsyncLifecyclePlan, id="wraps-async-gen"
            ),
            pytest.param(
                wrapped_sync_cm_factory, SyncLifecyclePlan, id="wraps-sync-cm"
            ),
            pytest.param(
                wrapped_async_cm_factory, AsyncLifecyclePlan, id="wraps-async-cm"
            ),
        ],
    )
    def test_resource_metadata[T](
        self, factory: LifecycleFactory[T], classification: type
    ):
        assert isinstance(build_lifecycle_plan(factory), classification)
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
        [
            sync_gen_factory,
            async_gen_factory,
            sync_cm_factory,
            async_cm_factory,
            wrapped_sync_gen_factory,
            wrapped_async_gen_factory,
            wrapped_sync_cm_factory,
            wrapped_async_cm_factory,
        ],
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
        ("factory", "cleanup", "is_async"),
        [
            (sync_callable_factory, close_connection, False),
            (async_callable_factory, close_async_connection, True),
        ],
    )
    def test_resource_metadata[T](
        self, factory: ValueFactory[T], cleanup, is_async: bool
    ):
        plan = build_factory_plan(factory, cleanup=cleanup)
        assert isinstance(plan, ValueFactoryPlan)
        assert plan.is_async is is_async
        test_metadata = partial(_test_metadata, typ=ReusableResource, reusable=True)

        resource = Resource.from_external(factory)
        test_metadata(resource, external=True)

        resource = Resource.from_factory(factory, cleanup=cleanup)
        test_metadata(resource, external=False, classification=ValueFactoryPlan)

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


def _sync_generator():
    yield _SCALAR


async def _async_generator():
    yield _SCALAR


GENERATOR_FUNCS = [
    pytest.param(_sync_generator, id="sync"),
    pytest.param(_async_generator, id="async"),
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

    @pytest.mark.parametrize("func", GENERATOR_FUNCS)
    def test_generator_object_points_to_from_lifecycle(self, func):
        started = func()
        assert is_closeable(started)

        with pytest.raises(TypeError, match=r"generator object.*from_lifecycle"):
            Resource(started)


RESOURCE_SHAPES = [
    pytest.param(
        lambda: Resource.from_external(_Connection()),
        ResourceStrategy.EXTERNAL,
        False,
        True,
        id="external",
    ),
    pytest.param(
        lambda: Resource(_Connection()), ResourceStrategy.OWNED, False, True, id="owned"
    ),
    pytest.param(
        lambda: Resource.from_factory(sync_callable_factory, cleanup=close_connection),
        ResourceStrategy.VALUE_FACTORY,
        False,
        False,
        id="sync-value-factory",
    ),
    pytest.param(
        lambda: Resource.from_factory(
            async_callable_factory, cleanup=close_async_connection
        ),
        ResourceStrategy.VALUE_FACTORY,
        True,
        False,
        id="async-value-factory",
    ),
    pytest.param(
        lambda: Resource.from_lifecycle(sync_gen_factory),
        ResourceStrategy.LIFECYCLE,
        False,
        False,
        id="sync-lifecycle",
    ),
    pytest.param(
        lambda: Resource.from_lifecycle(async_gen_factory),
        ResourceStrategy.LIFECYCLE,
        True,
        False,
        id="async-lifecycle",
    ),
]


class TestResourceEcosystem:
    @pytest.mark.parametrize(
        ("build", "strategy", "async_native", "has_value"), RESOURCE_SHAPES
    )
    def test_plan_derived_properties(
        self,
        build: Callable[[], Resource[Any]],
        strategy: ResourceStrategy,
        async_native: bool,
        has_value: bool,
    ):
        resource = build()
        assert resource.strategy is strategy
        assert resource.async_native is async_native

        if has_value:
            assert isinstance(resource.value, _Connection)
        else:
            with pytest.raises(AttributeError, match="no value until acquired"):
                _ = resource.value

    def test_context_with_resource_is_immutable_copy(self):
        base = Context(test=True)
        resource = Resource.from_factory(sync_gen_factory)
        derived = base.with_resource("resource", resource)

        assert "resource" not in base.resources
        assert derived.resources["resource"] is resource
        assert derived.test
        assert derived is not base

    def test_classify_rejects_non_resource(self):
        with pytest.raises(TypeError, match="Invalid lifecycle factory"):
            build_lifecycle_plan(_SCALAR)  # pyright: ignore[reportArgumentType]

        with pytest.raises(TypeError, match="Invalid resource factory"):
            Resource.from_factory(_SCALAR)  # pyright: ignore[reportArgumentType]

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
            resource.plan = resource.plan  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            resource.plan.enter = sync_gen_factory  # pyright: ignore[reportAttributeAccessIssue]
