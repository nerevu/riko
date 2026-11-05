# vim: sw=4:ts=4:expandtab
"""Provides internal tests for executions and their resources."""

from __future__ import annotations

import copy
import pickle  # noqa: S403
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
    nullcontext,
)
from functools import partial
from math import inf
from threading import Event as ThreadEvent
from threading import get_ident
from typing import TYPE_CHECKING, Any, cast
from urllib.request import urlopen

import pytest

from riko.bado._backend import (
    Event,
    async_sleep,
    asyncify,
    create_task_group,
    fail_after,
)
from riko.base._exceptions import (
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
from riko.definitions._settings import ExecutionSettings
from riko.execution._async_execution import AsyncExecution
from riko.execution._resource_cleanup import aclose_resource
from riko.execution._resource_view import ResourceView
from riko.execution._sync_execution import SyncExecution
from riko.io import async_url_open
from tests import async_test, skipif_issync
from tests._execution import RecordingSink
from tests._loopback import loopback_url
from tests._resources import (
    CREDENTIAL,
    SCALAR,
    VALUE_FACTORIES,
    AsyncConnection,
    Connection,
    async_callable_factory,
    async_cm_factory,
    async_gen_factory,
    check_credential_and_lazy,
    check_metadata,
    sync_callable_factory,
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


class _SyncClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


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


CLIENT_CLASSES = [
    pytest.param(_SyncClient, id="sync-client"),
    pytest.param(_AsyncClient, id="async-client"),
]


connection = pytest.fixture(sync_callable_factory)


def _check_opened(acquired: object, value: object | None) -> None:
    if value is None:
        assert acquired
    else:
        assert acquired is value

    if isinstance(acquired, Connection):
        assert acquired.opened


def _check_closed(resource, acquired: object, value: object | None) -> None:
    if value is not None and isinstance(acquired, Connection):
        assert acquired.closed is not resource.external
        acquired.opened = True  # reopen so the same value can be acquired again


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
        sink = RecordingSink()

        with SyncExecution(events=sink) as execution:
            execution.emit("a")
            execution.emit("b")

        assert sink.events == ["a", "b"]

    def test_each_execution_owns_its_event_sink(self) -> None:
        first = RecordingSink()
        second = RecordingSink()

        with SyncExecution(events=first) as execution:
            execution.emit("one")

        with SyncExecution(events=second) as execution:
            execution.emit("two")

        assert (first.events, second.events) == (["one"], ["two"])

    def test_settings_supply_the_event_sink_and_shutdown_timeout(self) -> None:
        sink, explicit = RecordingSink(), RecordingSink()
        settings = ExecutionSettings(event_sink=sink, shutdown_timeout=1.5)
        assert SyncExecution(settings=settings).events is sink
        assert SyncExecution(events=explicit, settings=settings).events is explicit
        assert AsyncExecution(settings=settings).shutdown_timeout == pytest.approx(1.5)


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
        # Exhausting the shutdown timeout during cleanup is a cleanup failure
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
    async def test_async_infinite_shutdown_timeout_waits_out_cleanup(self) -> None:
        done: list[bool] = []

        async def slow() -> None:
            await async_sleep(0.1)
            done.append(True)

        with fail_after(1):
            async with AsyncExecution(shutdown_timeout=inf) as execution:
                execution.push_async_callback(slow)

        assert done == [True]

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
        sink = RecordingSink()

        async with AsyncExecution(events=sink) as execution:
            execution.emit("a")
            execution.emit("b")

        assert sink.events == ["a", "b"]


def cleanup_contextmanager(_: AbstractContextManager[Connection]):
    pass


async_connection = pytest.fixture(async_callable_factory)


sync_contextmanager = pytest.fixture(sync_cm_factory)


async_contextmanager = pytest.fixture(async_cm_factory)


scalar = pytest.fixture(lambda: SCALAR)


@pytest.fixture
def one_shot_resource(connection: Connection) -> Resource[Connection]:
    return Resource(connection)


@pytest.fixture
def external_resource(connection: Connection):
    return Resource.from_external(connection)


_RESOLVED = "Expected a resolved resource value"
CONTEXT_FACTORY_REJECTIONS = [
    pytest.param("scalar", id="scalar"),
    pytest.param("connection", id="connection"),
    pytest.param("sync_contextmanager", id="sync-context-manager"),
    pytest.param("one_shot_resource", id="one-shot"),
]
RESOLVED_VALUE_REJECTIONS = [
    pytest.param("scalar", "Must provide a Closeable value", id="scalar"),
    pytest.param("sync_contextmanager", _RESOLVED, id="sync-context-manager"),
    pytest.param("one_shot_resource", _RESOLVED, id="one-shot"),
    pytest.param("external_resource", _RESOLVED, id="external"),
]
NON_FACTORY_VALUES = [
    pytest.param("scalar", id="scalar"),
    pytest.param("connection", id="connection"),
    pytest.param("one_shot_resource", id="one-shot"),
    pytest.param("external_resource", id="external"),
]
WRAPPED_VALUES = [
    pytest.param("scalar", {"cleanup": lambda _: None}, id="scalar-with-cleanup"),
    pytest.param("connection", {}, id="closeable"),
]


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


async def _value() -> str:
    return "value"


def _build_awaitable() -> Awaitable[str]:
    return _value()


@contextmanager
def _needs_arg(ctx: object) -> Generator[object]:
    yield ctx


_BODY = "<rss><channel><item><title>hi</title></item></channel></rss>"


_CONTENT_TYPE = "application/xml"


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

    _check_closed(resource, acquired, value)


async def _async_test_open_close(resource, value: object | None = None):
    acquired: object = None

    async with AsyncExecution() as execution:
        acquired = await execution.aacquire(resource)
        _check_opened(acquired, value)

    _check_closed(resource, acquired, value)


ACLOSE_CASES = [
    pytest.param(False, False, id="left-open"),
    pytest.param(_SyncClient.close, True, id="sync-cleanup"),
    pytest.param(None, True, id="sync-close"),
]


def _fail() -> object:
    raise RuntimeError("boom")


async def _afail() -> object:
    raise RuntimeError("boom")


FAILED_ACQUISITIONS = [
    pytest.param(
        lambda: Resource.from_lifecycle(_needs_arg), TypeError, id="lifecycle"
    ),
    pytest.param(
        lambda: Resource.from_factory(_fail, cleanup=False), RuntimeError, id="value"
    ),
]
AFAILED_ACQUISITIONS = [
    pytest.param(
        lambda: Resource.from_lifecycle(_needs_arg), TypeError, id="lifecycle"
    ),
    pytest.param(
        lambda: Resource.from_factory(_afail, cleanup=False), RuntimeError, id="value"
    ),
]


async def _adb() -> AsyncGenerator[str]:
    yield "value"


async def _acleanup(_value: object) -> None:
    pass


def _counted(produced: list[int]) -> object:
    produced.append(1)
    return object()


SYNC_ASYNC_REJECTIONS = [
    pytest.param(lambda _: Resource.from_lifecycle(_adb), None, id="async-lifecycle"),
    pytest.param(
        lambda produced: Resource.from_factory(
            partial(_counted, produced), cleanup=_acleanup
        ),
        "async",
        id="async-cleanup-before-producer",
    ),
    pytest.param(
        lambda _: Resource(_AsyncClient()),
        "closing an async-only",
        id="async-only-value",
    ),
]


def _awaitable_cleanup(events: list[str]):
    async def acleanup(_value: object) -> None:
        events.append("cleanup")

    def cleanup(value: object) -> Awaitable[None]:
        return acleanup(value)

    return cleanup


AWAITABLE_CLEANUPS = [
    pytest.param(lambda cleanup: Resource(_SyncClient(), cleanup=cleanup), id="owned"),
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


class TestResourceAcquisition:
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

    @skipif_issync
    def test_awaitable_from_sync_factory_is_awaited(self) -> None:
        resource = Resource.from_factory(_build_awaitable, cleanup=False)
        assert _acquire_twice(resource) == ["value", "value"]

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

    def test_sync_acquire_runs_a_falsy_cleanup_callable(self) -> None:
        cleanup = _FalsyCleanup()

        with SyncExecution() as execution:
            execution.acquire(Resource.from_factory(lambda: "value", cleanup=cleanup))

        assert cleanup.events == ["value"]

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

    def test_factory_receives_mutable_arguments(self):
        received: dict[str, Any] = {}
        client = _SyncClient()

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

    @pytest.mark.parametrize("fixture", CONTEXT_FACTORY_REJECTIONS)
    def test_context_rejects_a_non_factory_value(self, fixture, request):
        with pytest.raises(TypeError, match="Invalid resource factory"):
            Context().with_resource("value", request.getfixturevalue(fixture))

    @pytest.mark.parametrize(("fixture", "match"), RESOLVED_VALUE_REJECTIONS)
    def test_resource_rejects_an_unresolved_value(self, fixture, match, request):
        with pytest.raises(TypeError, match=match):
            Resource(request.getfixturevalue(fixture))

    @pytest.mark.parametrize("fixture", NON_FACTORY_VALUES)
    def test_factories_reject_a_non_factory_value(self, fixture, request):
        value = request.getfixturevalue(fixture)

        with pytest.raises(TypeError, match="Invalid lifecycle factory"):
            Resource.from_lifecycle(value)

        with pytest.raises(TypeError, match="Invalid resource factory"):
            Resource.from_factory(value)

    @pytest.mark.parametrize(("fixture", "kwargs"), WRAPPED_VALUES)
    def test_owned_and_external_resources_wrap_a_value(self, fixture, kwargs, request):
        value = request.getfixturevalue(fixture)
        owned = Resource(value, **kwargs)
        check_metadata(owned, OneShotResource, external=False, reusable=False)
        _test_open_close(owned, value)

        external = Resource.from_external(value)
        check_metadata(external, ReusableResource, external=True, reusable=True)
        _test_open_close(external, value)

    def test_context_borrows_an_external_resource(self, external_resource):
        context = Context().with_resource("value", external_resource)
        resource = context.resources["value"]
        check_metadata(resource, ReusableResource, external=True, reusable=True)
        _test_open_close(resource)

        with pytest.raises(TypeError, match=r"credential.*lazy.*LifecycleFactory"):
            Context().with_resource(
                "value", external_resource, credential=CREDENTIAL, lazy=True
            )

    def test_context_manager_constructors(self, sync_contextmanager):
        value = sync_contextmanager

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource.from_external(value)

        lifecycle = Resource.from_lifecycle(value)
        check_metadata(lifecycle, OneShotResource, external=False, reusable=False)
        configured = Resource.from_lifecycle(value, credential=CREDENTIAL, lazy=True)
        check_credential_and_lazy(configured)
        _test_open_close(lifecycle)

        with pytest.raises(TypeError, match=r"ValueFactory.*cleanup function"):
            Resource.from_factory(value)

        casted = cast("ValueFactory[AbstractContextManager[Connection]]", value)

        with pytest.warns(ResourceInterpretationWarning, match="context manager"):
            factory = Resource.from_factory(casted, cleanup=cleanup_contextmanager)

        check_metadata(factory, ReusableResource, external=False, reusable=True)

    def test_sync_acquire_lone_cleanup_error_raises_bare(self) -> None:
        execution = SyncExecution()
        execution.acquire(Resource(_BadClient()))

        with pytest.raises(RuntimeError, match="cleanup failed"):
            execution.close()

    @pytest.mark.simulated_network
    def test_sync_external_http_client_cleaned_up_on_failure(self) -> None:
        events: list[str] = []

        def failing() -> object:
            raise RuntimeError("boom")

        def run() -> None:
            with (
                loopback_url(_BODY, content_type=_CONTENT_TYPE) as url,
                SyncExecution() as execution,
            ):
                execution.acquire(
                    Resource.from_lifecycle(_sync_http_client(url, events))
                )
                execution.acquire(Resource.from_factory(failing, cleanup=False))

        with pytest.raises(RuntimeError, match="boom"):
            run()

        assert events == ["closed"]

    @pytest.mark.simulated_network
    def test_sync_external_async_http_client_rejected(self) -> None:
        with (
            loopback_url(_BODY, content_type=_CONTENT_TYPE) as url,
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="async-native"),
        ):
            execution.acquire(Resource.from_lifecycle(_async_http_client(url, [])))


class TestAsyncResourceAcquisition:
    @pytest.mark.parametrize("build", AWAITABLE_CLEANUPS)
    @async_test
    async def test_async_cleanup_awaits_an_awaitable_cleanup_result(self, build):
        events: list[str] = []

        async with AsyncExecution() as execution:
            await execution.aacquire(build(_awaitable_cleanup(events)))

        assert events == ["cleanup"]

    @async_test
    async def test_async_cleanup_closes_a_dual_client_with_aclose(self) -> None:
        client = _DualClient()

        async with AsyncExecution() as execution:
            await execution.aacquire(Resource(client))

        assert client.events == ["aclose"]

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

    @pytest.mark.simulated_network
    @async_test
    async def test_sync_external_http_client_under_async_execution(self) -> None:
        events: list[str] = []

        with loopback_url(_BODY, content_type=_CONTENT_TYPE) as url:
            async with AsyncExecution() as execution:
                response = await execution.aacquire(
                    Resource.from_lifecycle(_sync_http_client(url, events))
                )
                assert b"<item>" in response.read()
                assert events == []

            assert events == ["closed"]

    @pytest.mark.simulated_network
    @async_test
    async def test_async_external_http_client_under_async_execution(self) -> None:
        events: list[str] = []

        with loopback_url(_BODY, content_type=_CONTENT_TYPE) as url:
            async with AsyncExecution() as execution:
                stream = await execution.aacquire(
                    Resource.from_lifecycle(_async_http_client(url, events))
                )
                assert "<item>" in stream.read()
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
    async def test_async_constructor_contract(
        self,
        async_connection: AsyncConnection,
        async_contextmanager: AbstractAsyncContextManager[AsyncConnection],
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
    @pytest.mark.parametrize(
        "duplicate",
        [
            pytest.param(copy.copy, id="copy"),
            pytest.param(copy.deepcopy, id="deepcopy"),
            pytest.param(lambda view: pickle.loads(pickle.dumps(view)), id="pickle"),  # noqa: S301
        ],
    )
    def test_resource_view_can_be_copied(self, duplicate):
        assert dict(duplicate(ResourceView({"db": 1}))) == {"db": 1}

    def test_resource_view_counts_its_bindings(self):
        assert len(ResourceView({"db": 1, "cache": 2})) == 2
