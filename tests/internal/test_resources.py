# vim: sw=4:ts=4:expandtab
"""Provides internal tests for acquiring and closing execution resources."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager, contextmanager
from functools import partial
from threading import Event as ThreadEvent
from threading import get_ident
from typing import TYPE_CHECKING, Any
from urllib.request import urlopen

import pytest

from riko.bado._backend import (
    CancelScope,
    Event,
    async_sleep,
    create_task_group,
    fail_after,
)
from riko.bado._util import asyncify
from riko.base._exceptions import InvalidPipelineError
from riko.definitions._context import Context
from riko.definitions._resource_definition import Resource
from riko.definitions._settings import ExecutionSettings
from riko.execution._async_execution import AsyncExecution
from riko.execution._resource_view import ResourceView
from riko.execution._sync_execution import SyncExecution
from riko.io import async_url_open
from tests import ROUND_TRIPS, async_test, skipif_sync
from tests._loopback import loopback_url
from tests._resources import (
    CLEANED,
    VALUE_FACTORIES,
    WRAPPED_VALUES,
    AsyncConnection,
    Connection,
    async_callable_factory,
    async_cm_factory,
    async_gen_factory,
    sync_cm_factory,
    sync_gen_factory,
    wrapped_async_cm_factory,
    wrapped_async_gen_factory,
    wrapped_sync_cm_factory,
    wrapped_sync_gen_factory,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Generator

    from riko.types._resource import LifecycleFactory, ValueFactory

_BODY = "<rss><channel><item><title>hi</title></item></channel></rss>"
_CONTENT_TYPE = "application/xml"


@contextmanager
def _needs_arg(ctx: object) -> Generator[object]:
    yield ctx


_LIFECYCLE_NEEDS_ARG = lambda: Resource.from_lifecycle(_needs_arg)


def _fail() -> object:
    raise RuntimeError("boom")


_FAILING_VALUE = Resource.from_factory(_fail, cleanup=False)


async def _afail() -> object:
    raise RuntimeError("boom")


_AFAILING_VALUE = Resource.from_factory(_afail, cleanup=False)

LIFECYCLE_FACTORIES = [
    sync_gen_factory,
    async_gen_factory,
    sync_cm_factory,
    async_cm_factory,
    wrapped_sync_gen_factory,
    wrapped_async_gen_factory,
    wrapped_sync_cm_factory,
    wrapped_async_cm_factory,
]


class _FalsyCleanup:
    """A falsy cleanup callable: only the literal ``False`` opts out of cleanup."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def __bool__(self) -> bool:
        return False

    def __call__(self, value: object) -> None:
        self.events.append(value)


class _AsyncClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _AsyncCloseClient:
    """A client whose only ``close()`` is an async function."""

    def __init__(self) -> None:
        self.events: list[str] = []

    async def close(self) -> None:
        self.events.append("close")


CLIENT_CLASSES = [
    pytest.param(Connection, id="sync-client"),
    pytest.param(_AsyncClient, id="async-client"),
]


def _check_opened(acquired: object, value: object | None) -> None:
    if value is None:
        assert isinstance(acquired, Connection)
    else:
        assert acquired is value

    if isinstance(acquired, Connection):
        assert acquired.opened


def _check_closed(resource, acquired: object) -> None:
    if isinstance(acquired, Connection):
        assert acquired.closed is not resource.external
        acquired.opened = True  # reopen so the same value can be acquired again


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
            except (TypeError, RuntimeError) as error:
                outcomes.append(error)

    return outcomes


async def _value() -> str:
    return "value"


def _build_awaitable() -> Awaitable[str]:
    return _value()


def _sync_http_client(url: str, events: list[str]):
    def connect():
        response = urlopen(url)  # noqa: S310
        try:
            yield response
        finally:
            response.close()
            events.append("closed")

    return connect


def _async_http_client(url: str, events: list[str]):
    async def connect():
        try:
            async with async_url_open(url) as stream:
                yield stream
        finally:
            events.append("closed")

    return connect


def _test_open_close(resource, value: object | None = None):
    acquired: object = None

    with SyncExecution() as execution:
        acquired = execution.acquire(resource)
        _check_opened(acquired, value)

    _check_closed(resource, acquired)


FAILED_ACQUISITIONS = [
    pytest.param(_LIFECYCLE_NEEDS_ARG, TypeError, id="lifecycle"),
    pytest.param(lambda: _FAILING_VALUE, RuntimeError, id="value"),
]


async def _adb(events: list[str]) -> AsyncGenerator[str]:
    try:
        yield "value"
    finally:
        events.append("cleanup")


async def _ahang(_value: object) -> None:
    await async_sleep(1)


async def _ahang_db() -> AsyncGenerator[str]:
    try:
        yield "value"
    finally:
        await async_sleep(1)


async def _acleanup(_value: object) -> None:
    pass


def _counted(produced: list[int]) -> object:
    produced.append(1)
    return object()


SYNC_ASYNC_REJECTIONS = [
    pytest.param(
        lambda produced: Resource.from_factory(
            partial(_counted, produced), cleanup=_acleanup
        ),
        "async",
        id="async-cleanup-before-producer",
    ),
    pytest.param(
        lambda _: Resource(Connection(), cleanup=_acleanup),
        "async resource cleanup",
        id="async-cleanup-of-a-value",
    ),
    pytest.param(
        lambda _: Resource(_AsyncClient()), "only close is async", id="async-only-value"
    ),
    pytest.param(
        lambda _: Resource(_AsyncCloseClient()),
        "only close is async",
        id="async-close-value",
    ),
]


def _async_cleanup(events: list[str]):
    async def acleanup(_value: object) -> None:
        events.append("cleanup")

    return acleanup


def _awaitable_cleanup(events: list[str]):
    acleanup = _async_cleanup(events)

    def cleanup(value: object) -> Awaitable[None]:
        return acleanup(value)

    return cleanup


SYNC_BRIDGED_CLEANUPS = [
    pytest.param(
        lambda events: Resource.from_lifecycle(partial(_adb, events)),
        id="async-lifecycle",
    ),
    pytest.param(
        lambda events: Resource.from_factory(_value, cleanup=_async_cleanup(events)),
        id="async-cleanup",
    ),
    pytest.param(
        lambda events: Resource.from_factory(
            _value, cleanup=_awaitable_cleanup(events)
        ),
        id="awaitable-cleanup-result",
    ),
]


SYNC_HANGING_CLEANUPS = [
    pytest.param(
        lambda: Resource.from_factory(_value, cleanup=_ahang), id="async-cleanup"
    ),
    pytest.param(lambda: Resource.from_lifecycle(_ahang_db), id="async-lifecycle"),
]


AWAITABLE_CLEANUPS = [
    pytest.param(lambda cleanup: Resource(Connection(), cleanup=cleanup), id="value"),
    pytest.param(
        lambda cleanup: Resource.from_factory(lambda: "value", cleanup=cleanup),
        id="value-factory",
    ),
]


class _DualClient:
    def __init__(self) -> None:
        self.events: list[str] = []

    def close(self) -> None:
        self.events.append("close")

    async def aclose(self) -> None:
        self.events.append("aclose")


_BRIDGED_VALUE_FACTORIES = [
    pytest.param(*row.values, id=row.id, marks=skipif_sync if row.id == "async" else ())
    for row in VALUE_FACTORIES
]

_BRIDGED_LIFECYCLE_FACTORIES = [
    pytest.param(
        f, id=f.__name__, marks=skipif_sync if f.__name__.startswith("async") else ()
    )
    for f in LIFECYCLE_FACTORIES
]


async def _aacquire_twice(resource: Resource[Any]) -> list[object]:
    """Acquires ``resource`` twice in an async execution, keeping each outcome."""
    outcomes: list[object] = []

    async with AsyncExecution() as execution:
        for _ in range(2):
            try:
                outcomes.append(await execution.aacquire(resource))
            except (TypeError, RuntimeError) as error:
                outcomes.append(error)

    return outcomes


async def _async_test_open_close(resource, value: object | None = None):
    acquired: object = None

    async with AsyncExecution() as execution:
        acquired = await execution.aacquire(resource)
        _check_opened(acquired, value)

    _check_closed(resource, acquired)


AFAILED_ACQUISITIONS = [
    pytest.param(_LIFECYCLE_NEEDS_ARG, TypeError, id="lifecycle"),
    pytest.param(lambda: _AFAILING_VALUE, RuntimeError, id="value"),
]

ASYNC_NATIVE_CLOSES = [
    pytest.param(_DualClient, ["aclose"], id="dual-client-aclose"),
    pytest.param(_AsyncCloseClient, ["close"], id="async-close"),
]

HTTP_CLIENTS = [
    pytest.param(_sync_http_client, b"<item>", id="sync-client"),
    pytest.param(_async_http_client, "<item>", id="async-client"),
]


class TestResourceAcquisition:
    def test_sync_cleanup_closes_a_dual_client_with_close(self) -> None:
        client = _DualClient()

        with SyncExecution() as execution:
            execution.acquire(Resource(client))

        assert client.events == ["close"]

    @pytest.mark.parametrize(("build", "error"), FAILED_ACQUISITIONS)
    def test_failed_acquisition_is_memoized(self, build, error) -> None:
        """A failed factory runs once; a second acquire replays the same error."""
        first, second = _acquire_twice(build())
        assert isinstance(first, error)
        assert second is first

    @skipif_sync
    def test_awaitable_from_sync_factory_is_awaited(self) -> None:
        resource = Resource.from_factory(_build_awaitable, cleanup=False)
        assert _acquire_twice(resource) == ["value", "value"]

    @pytest.mark.parametrize("client_class", CLIENT_CLASSES)
    def test_sync_acquire_external_resource_is_borrowed(
        self, client_class: type[Connection | _AsyncClient]
    ) -> None:
        client = client_class()

        with SyncExecution() as execution:
            acquired = execution.acquire(Resource.from_external(client))
            assert acquired is client

        assert client.closed is False

    def test_sync_acquire_value_factory_without_cleanup(self) -> None:
        client = Connection()

        with SyncExecution() as execution:
            acquired = execution.acquire(
                Resource.from_factory(lambda: client, cleanup=False)
            )
            assert acquired is client

        assert client.closed is False

    def test_sync_acquire_factory_cleanup_is_authoritative(self) -> None:
        client = Connection()
        events: list[str] = []

        with SyncExecution() as execution:
            execution.acquire(
                Resource.from_factory(
                    lambda: client, cleanup=lambda _: events.append("x")
                )
            )

        assert events == ["x"]
        assert client.closed is False

    def test_sync_acquire_runs_a_falsy_cleanup_callable(self) -> None:
        cleanup = _FalsyCleanup()

        with SyncExecution() as execution:
            execution.acquire(Resource.from_factory(lambda: "value", cleanup=cleanup))

        assert cleanup.events == ["value"]

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

    def test_sync_partial_acquisition_unwinds(self) -> None:
        client = Connection()

        def run() -> None:
            with SyncExecution() as execution:
                execution.acquire(Resource(client))
                execution.acquire(_FAILING_VALUE)

        with pytest.raises(RuntimeError, match="boom"):
            run()

        assert client.closed is True

    def test_factory_receives_mutable_arguments(self):
        received: dict[str, Any] = {}
        client = Connection()

        def factory(*args: object, **kwargs: object):
            received.update(args=args, kwargs=kwargs)
            yield object()

        resource = Resource.from_factory(
            factory, ["arg"], client, headers={"accept": ["json"]}
        )

        with SyncExecution() as execution:
            execution.acquire(resource)

        tags, passed_client = received["args"]
        headers = received["kwargs"]["headers"]
        assert tags == ["arg"]
        assert passed_client is client
        assert isinstance(headers, dict)
        assert headers["accept"] == ["json"]

    @pytest.mark.parametrize(("fixture", "kwargs"), WRAPPED_VALUES)
    def test_owned_and_external_resources_wrap_a_value(self, fixture, kwargs, request):
        value = request.getfixturevalue(fixture)
        CLEANED.clear()
        _test_open_close(Resource(value, **kwargs), value)
        _test_open_close(Resource.from_external(value), value)
        assert CLEANED == ([value] if kwargs else [])

    def test_context_borrows_an_external_resource(self, external_resource):
        context = Context().with_resource("value", external_resource)
        _test_open_close(context.resources["value"])

    def test_context_manager_lifecycle_opens_and_closes(self, sync_contextmanager):
        _test_open_close(Resource.from_lifecycle(sync_contextmanager))

    @pytest.mark.parametrize("factory", _BRIDGED_LIFECYCLE_FACTORIES)
    def test_lifecycle_factory_opens_and_closes[T](self, factory: LifecycleFactory[T]):
        context = Context().with_resource("factory", factory)
        _test_open_close(context.resources["factory"])
        _test_open_close(Resource.from_lifecycle(factory))
        _test_open_close(Resource.from_factory(factory))

    @pytest.mark.parametrize(("factory", "cleanup"), _BRIDGED_VALUE_FACTORIES)
    def test_value_factory_opens_and_closes[T](self, factory: ValueFactory[T], cleanup):
        _test_open_close(Resource.from_factory(factory, cleanup=cleanup))

    @pytest.mark.simulated_network
    def test_sync_external_http_client_cleaned_up_on_failure(self) -> None:
        events: list[str] = []

        def run() -> None:
            with (
                loopback_url(_BODY, content_type=_CONTENT_TYPE) as url,
                SyncExecution() as execution,
            ):
                execution.acquire(
                    Resource.from_lifecycle(_sync_http_client(url, events))
                )
                execution.acquire(_FAILING_VALUE)

        with pytest.raises(RuntimeError, match="boom"):
            run()

        assert events == ["closed"]

    @pytest.mark.parametrize(("build", "match"), SYNC_ASYNC_REJECTIONS)
    def test_sync_acquire_rejects_an_async_resource(self, build, match) -> None:
        """A sync execution refuses async-only resources before producing a value."""
        produced: list[int] = []

        with SyncExecution() as execution:
            resource = build(produced)

            with pytest.raises(InvalidPipelineError, match=match):
                execution.acquire(resource)

        assert produced == []

    @pytest.mark.parametrize("build", AWAITABLE_CLEANUPS)
    def test_sync_cleanup_rejects_an_awaitable_cleanup_result(self, build) -> None:
        events: list[str] = []

        with (
            pytest.raises(InvalidPipelineError, match="async resource cleanup"),
            SyncExecution() as execution,
        ):
            execution.acquire(build(_awaitable_cleanup(events)))

        assert events == []

    @skipif_sync
    @pytest.mark.parametrize("build", SYNC_BRIDGED_CLEANUPS)
    def test_sync_bridges_the_cleanup_of_an_async_produced_value(self, build) -> None:
        events: list[str] = []
        acquired = None

        with SyncExecution() as execution:
            acquired = execution.acquire(build(events))
            assert events == []

        assert acquired == "value"
        assert events == ["cleanup"]

    @skipif_sync
    @pytest.mark.simulated_network
    def test_sync_external_async_http_client_bridged(self) -> None:
        events: list[str] = []

        with loopback_url(_BODY, content_type=_CONTENT_TYPE) as url:
            with SyncExecution() as execution:
                execution.acquire(
                    Resource.from_lifecycle(_async_http_client(url, events))
                )
                assert events == []

            assert events == ["closed"]

    def test_sync_acquire_lone_cleanup_error_raises_bare(self) -> None:
        execution = SyncExecution()
        execution.acquire(Resource(_BadClient()))

        with pytest.raises(RuntimeError, match="cleanup failed"):
            execution.close()

    @skipif_sync
    @pytest.mark.parametrize("build", SYNC_HANGING_CLEANUPS)
    def test_sync_bridged_cleanup_expiry_is_raised_at_exit(self, build) -> None:
        settings = ExecutionSettings(shutdown_timeout=0.05)

        with pytest.raises(TimeoutError), SyncExecution(settings=settings) as execution:
            execution.acquire(build())

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="resolving a resource's credential reference for its factory is not "
        "yet implemented",
    )
    def test_sync_acquire_passes_a_credential_reference_to_its_factory(self) -> None:
        received: dict[str, object] = {}

        def factory(credential: object = None) -> Generator[object]:
            received["credential"] = credential
            yield object()

        resource = Resource.from_lifecycle(factory, credential="microsoft/cif")

        with SyncExecution() as execution:
            execution.acquire(resource)

        assert received["credential"] is not None


async_connection = pytest.fixture(async_callable_factory)


class TestAsyncResourceAcquisition:
    @pytest.mark.parametrize("build", AWAITABLE_CLEANUPS)
    @async_test
    async def test_async_cleanup_awaits_an_awaitable_cleanup_result(self, build):
        events: list[str] = []

        async with AsyncExecution() as execution:
            await execution.aacquire(build(_awaitable_cleanup(events)))

        assert events == ["cleanup"]

    @pytest.mark.parametrize(("build", "expected"), ASYNC_NATIVE_CLOSES)
    @async_test
    async def test_async_cleanup_closes_an_owned_value_natively(self, build, expected):
        client = build()

        async with AsyncExecution() as execution:
            await execution.aacquire(Resource(client))

        assert client.events == expected

    @async_test
    async def test_async_waiter_acquires_after_the_first_acquisition_is_cancelled(
        self,
    ) -> None:
        """A waiter retries the acquisition it waited on once that one is cancelled."""
        started, waiting, never = Event(), Event(), Event()
        calls: list[int] = []
        scopes: list[CancelScope] = []
        outcomes: list[object] = []

        async def connect() -> str:
            calls.append(len(calls))

            if len(calls) == 1:
                started.set()
                await never.wait()

            return "value"

        async def first() -> None:
            with CancelScope() as scope:
                scopes.append(scope)
                await execution.aacquire(resource)

        async def second() -> None:
            waiting.set()
            outcomes.append(await execution.aacquire(resource))

        resource = Resource.from_factory(connect, cleanup=False)

        with fail_after(1):
            async with AsyncExecution() as execution, create_task_group() as group:
                group.start_soon(first)
                await started.wait()
                group.start_soon(second)
                await waiting.wait()
                scopes[0].cancel()

        assert (outcomes, calls) == (["value"], [0, 1])

    @pytest.mark.parametrize(("build", "error"), AFAILED_ACQUISITIONS)
    @async_test
    async def test_async_failed_acquisition_is_memoized(self, build, error) -> None:
        """A failed factory runs once; a second acquire replays the same error."""
        first, second = await _aacquire_twice(build())
        assert isinstance(first, error)
        assert second is first

    @async_test
    async def test_async_awaitable_from_sync_factory_is_awaited(self) -> None:
        resource = Resource.from_factory(_build_awaitable, cleanup=False)
        assert await _aacquire_twice(resource) == ["value", "value"]

    @pytest.mark.parametrize("client_class", CLIENT_CLASSES)
    @async_test
    async def test_async_acquire_external_resource_is_borrowed(
        self, client_class: type[Connection | _AsyncClient]
    ) -> None:
        client = client_class()

        async with AsyncExecution() as execution:
            acquired = await execution.aacquire(Resource.from_external(client))
            assert acquired is client

        assert client.closed is False

    # Sync twin: test_owned_and_external_resources_wrap_a_value[closable]
    @async_test
    async def test_async_acquire_owned_value_closes(self) -> None:
        client = _AsyncClient()

        async with AsyncExecution() as execution:
            await execution.aacquire(Resource(client))

        assert client.closed is True

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
    async def test_async_acquire_runs_a_falsy_cleanup_callable(self) -> None:
        cleanup = _FalsyCleanup()

        async with AsyncExecution() as execution:
            await execution.aacquire(
                Resource.from_factory(lambda: "value", cleanup=cleanup)
            )

        assert cleanup.events == ["value"]

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

            with fail_after(1):
                async with create_task_group() as tg:
                    tg.start_soon(grab)
                    tg.start_soon(grab)
                    await async_sleep(0)
                    gate.set()

        assert len(calls) == 1
        assert results[0] is results[1]

    @pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
    @async_test
    async def test_async_owned_value_cleanup_is_authoritative(self, is_async) -> None:
        client = Connection()
        events: list[str] = []

        async def acleanup(_: object) -> None:
            events.append("x")

        cleanup = acleanup if is_async else lambda _: events.append("x")

        async with AsyncExecution() as execution:
            await execution.aacquire(Resource(client, cleanup=cleanup))

        assert events == ["x"]
        assert client.closed is False

    @pytest.mark.simulated_network
    @pytest.mark.parametrize(("client", "marker"), HTTP_CLIENTS)
    @async_test
    async def test_external_http_client_under_async_execution(
        self, client, marker
    ) -> None:
        events: list[str] = []

        with loopback_url(_BODY, content_type=_CONTENT_TYPE) as url:
            async with AsyncExecution() as execution:
                response = await execution.aacquire(
                    Resource.from_lifecycle(client(url, events))
                )
                assert marker in response.read()
                assert events == []

            assert events == ["closed"]

    @pytest.mark.parametrize("factory", LIFECYCLE_FACTORIES)
    @async_test
    async def test_lifecycle_factory_opens_and_closes[T](
        self, factory: LifecycleFactory[T]
    ):
        context = Context().with_resource("factory", factory)
        await _async_test_open_close(context.resources["factory"])
        await _async_test_open_close(Resource.from_lifecycle(factory))
        await _async_test_open_close(Resource.from_factory(factory))

    @pytest.mark.parametrize(("factory", "cleanup"), VALUE_FACTORIES)
    @async_test
    async def test_value_factory_opens_and_closes[T](
        self, factory: ValueFactory[T], cleanup
    ):
        await _async_test_open_close(Resource.from_factory(factory, cleanup=cleanup))

    @async_test
    async def test_async_constructors_open_and_close(
        self,
        async_connection: AsyncConnection,
        async_contextmanager: AbstractAsyncContextManager[AsyncConnection],
    ):
        await _async_test_open_close(Resource(async_connection), async_connection)

        external = Resource.from_external(async_connection)
        await _async_test_open_close(external, async_connection)

        lifecycle = Resource.from_lifecycle(async_contextmanager)
        await _async_test_open_close(lifecycle)

    @async_test
    async def test_async_acquire_cleanup_on_failure(self) -> None:
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
        raises=AssertionError,
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
            await asyncify(occupy)

        with fail_after(1):
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


class TestResourceView:
    @pytest.mark.parametrize("round_trip", ROUND_TRIPS)
    def test_resource_view_can_be_copied(self, round_trip):
        assert dict(round_trip(ResourceView({"db": 1}))) == {"db": 1}

    def test_resource_view_counts_its_bindings(self):
        assert len(ResourceView({"db": 1, "cache": 2})) == 2
