# vim: sw=4:ts=4:expandtab
"""Provides internal tests for executions and their resources."""

from __future__ import annotations

import gc
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
    contextmanager,
    nullcontext,
)
from functools import partial
from itertools import count
from logging import WARNING
from math import inf
from threading import Event as ThreadEvent
from threading import get_ident
from time import perf_counter
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
from riko.bado.itertools import as_async
from riko.base._exceptions import InvalidPipelineError, PipelineStateError
from riko.base._sentinels import MISSING
from riko.coercion._canonical import IdentityAccumulator, IdentityDomain
from riko.definitions._context import Context
from riko.definitions._nodes import CallableNode, ModuleNode, StreamEdge
from riko.definitions._resource_definition import Resource
from riko.definitions._settings import ExecutionSettings
from riko.definitions._workflow_definition import Workflow
from riko.execution._async_execution import AsyncExecution
from riko.execution._execution import _NullEventSink
from riko.execution._prepared import ExecutionPlan
from riko.execution._provenance import (
    PLACEHOLDER,
    NodeProvenance,
    _TableProvenance,
    agen_result_envelopes,
    arun_tracked_item,
    gen_result_envelopes,
    run_tracked_item,
)
from riko.execution._resource_view import ResourceView
from riko.execution._sync_execution import SyncExecution
from riko.io import async_url_open
from riko.parsing._dotdict import DotDict
from riko.runtime._pipeline import Pipeline
from riko.runtime._resolver import dispatcher
from riko.types._enums import IdentityMode
from riko.types._feed import Metadata, _ItemEnvelope, build_generation
from riko.types._workflow import Endpoint, NodeId
from riko.types.modules import (
    FilterConf,
    FilterConfRule,
    ItemBuilderConf,
    SortConf,
    SortConfRule,
    TruncateConf,
)
from tests import ROUND_TRIPS, async_test, skipif_issync
from tests._execution import RecordingSink
from tests._loopback import loopback_url
from tests._resources import (
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
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Generator,
        Iterator,
        Sequence,
    )

    from riko.types._feed import Identity
    from riko.types._resource import LifecycleFactory, ValueFactory
    from riko.types._streams import Item, ItemOrValue

type _Result = tuple[Item, Identity]

_BODY = "<rss><channel><item><title>hi</title></item></channel></rss>"
_CONTENT_TYPE = "application/xml"


@contextmanager
def _needs_arg(ctx: object) -> Generator[object]:
    yield ctx


_LIFECYCLE_NEEDS_ARG = lambda: Resource.from_lifecycle(_needs_arg)

_FEED_SEED: list[Item] = [
    {"i": index, "content": content}
    for index, content in enumerate(("a b", "c", "a", "d e"))
]

_SCALAR_SEED: list[ItemOrValue] = ["a b", "c", "a"]
_CONTAINS_A = FilterConfRule(field="content", op="contains", value="a")
_HASH = Pipeline.from_module("hash")
_FILTER = Pipeline.from_module("filter", conf=FilterConf({"rule": _CONTAINS_A}))

_TOKENS = Pipeline.from_module(
    "tokenizer", conf={"delimiter": " "}, options={"emit": True}
)

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

    def test_sync_repeated_close_does_not_reraise_cleanup_error(self) -> None:
        calls: list[str] = []

        def boom() -> None:
            calls.append("cleanup")
            raise RuntimeError("cleanup failed")

        execution = SyncExecution()
        execution.queue_callback(boom)

        with pytest.raises(RuntimeError, match="cleanup failed"):
            execution.close()

        assert execution.close() is False
        assert calls == ["cleanup"]

    @skipif_issync
    def test_sync_portal_bridges_to_async(self) -> None:
        result = None

        async def double(value: int) -> int:
            return value * 2

        with SyncExecution() as execution:
            result = execution.run_async(double, 21)

        assert result == 42

    def test_sync_default_event_sink_is_noop(self) -> None:
        with SyncExecution() as execution:
            execution.emit("ignored")
            assert isinstance(execution.events, _NullEventSink)

    def test_sync_execution_dispatches_to_event_sink(self) -> None:
        sink = RecordingSink()

        with SyncExecution(events=sink) as execution:
            execution.emit("a")
            execution.emit("b")

        assert sink.events == ["a", "b"]

    def test_each_execution_owns_its_event_sink(self) -> None:
        first = RecordingSink()
        second = RecordingSink()

        with (
            SyncExecution(events=first) as outer,
            SyncExecution(events=second) as inner,
        ):
            outer.emit("one")
            inner.emit("two")
            outer.emit("three")

        assert (first.events, second.events) == (["one", "three"], ["two"])

    def test_settings_supply_the_event_sink_and_shutdown_timeout(self) -> None:
        sink, explicit = RecordingSink(), RecordingSink()
        settings = ExecutionSettings(event_sink=sink, shutdown_timeout=1.5)
        assert SyncExecution(settings=settings).events is sink
        assert SyncExecution(events=explicit, settings=settings).events is explicit
        assert AsyncExecution(settings=settings).shutdown_timeout == pytest.approx(1.5)

    def test_sync_enter_after_close_raises(self) -> None:
        execution = SyncExecution()
        execution.close()

        with pytest.raises(
            PipelineStateError, match="the execution in state 'closing'"
        ):
            execution.enter_context(nullcontext(1))

    def test_sync_cleanup_error_is_grouped_with_primary_error(self) -> None:
        # A plain cleanup callback cannot replace the execution's own error: both
        # survive, the primary first.
        def boom() -> None:
            raise RuntimeError("cleanup failed")

        def run() -> None:
            with SyncExecution() as execution:
                execution.queue_callback(boom)
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
        execution.queue_async_callback(boom)

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

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(body)
                await ready.wait()
                tg.cancel_scope.cancel()

        assert events == ["resource-closed"]

    @async_test
    async def test_async_sync_callback_runs_on_close(self) -> None:
        calls: list[str] = []

        async with AsyncExecution() as execution:
            execution.queue_callback(calls.append, "closed")

        assert calls == ["closed"]

    @async_test
    async def test_async_infinite_shutdown_timeout_waits_out_cleanup(self) -> None:
        done: list[bool] = []

        async def slow() -> None:
            await async_sleep(0.1)
            done.append(True)

        with fail_after(1):
            async with AsyncExecution(shutdown_timeout=inf) as execution:
                execution.queue_async_callback(slow)

        assert done == [True]

    @pytest.mark.timeout(2)
    @async_test
    async def test_async_shutdown_timeout_abandons_a_blocking_sync_cleanup(
        self, caplog
    ) -> None:
        release = ThreadEvent()

        def fail_late(_value: object) -> None:
            release.wait(1)
            raise ValueError("late")

        start = perf_counter()

        with caplog.at_level(WARNING, logger="riko"), pytest.raises(TimeoutError):
            async with AsyncExecution(shutdown_timeout=0.05) as execution:
                execution.register_owned(object(), fail_late, inline=False)

        assert perf_counter() - start < 1
        release.set()

        with fail_after(1):
            while not caplog.records:
                await async_sleep(0.01)

        assert "abandoned" in caplog.records[0].getMessage()

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
            assert isinstance(execution.events, _NullEventSink)

    @async_test
    async def test_async_execution_dispatches_to_event_sink(self) -> None:
        sink = RecordingSink()

        async with AsyncExecution(events=sink) as execution:
            execution.emit("a")
            execution.emit("b")

        assert sink.events == ["a", "b"]

    @async_test
    async def test_async_cleanup_error_is_grouped_with_primary_error(self) -> None:
        async def boom() -> None:
            raise RuntimeError("cleanup failed")

        async def run() -> None:
            async with AsyncExecution() as execution:
                execution.queue_async_callback(boom)
                raise ValueError("primary")

        with pytest.raises(ExceptionGroup) as info:
            await run()

        primary, cleanup = info.value.exceptions
        assert isinstance(primary, ValueError)
        assert isinstance(cleanup, RuntimeError)

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
            await async_sleep(1)

        async def run() -> None:
            async with AsyncExecution(shutdown_timeout=0.05) as execution:
                execution.queue_async_callback(slow)
                raise ValueError("primary")

        with pytest.raises(ExceptionGroup) as info:
            await run()

        primary, expired = info.value.exceptions
        assert isinstance(primary, ValueError)
        assert isinstance(expired, TimeoutError)


async_connection = pytest.fixture(async_callable_factory)


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


async def _async_test_open_close(resource, value: object | None = None):
    acquired: object = None

    async with AsyncExecution() as execution:
        acquired = await execution.aacquire(resource)
        _check_opened(acquired, value)

    _check_closed(resource, acquired)


def _fail() -> object:
    raise RuntimeError("boom")


async def _afail() -> object:
    raise RuntimeError("boom")


FAILED_ACQUISITIONS = [
    pytest.param(_LIFECYCLE_NEEDS_ARG, TypeError, id="lifecycle"),
    pytest.param(
        lambda: Resource.from_factory(_fail, cleanup=False), RuntimeError, id="value"
    ),
]
AFAILED_ACQUISITIONS = [
    pytest.param(_LIFECYCLE_NEEDS_ARG, TypeError, id="lifecycle"),
    pytest.param(
        lambda: Resource.from_factory(_afail, cleanup=False), RuntimeError, id="value"
    ),
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
        id="async-cleanup-of-owned-value",
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


def _awaitable_cleanup(events: list[str]):
    async def acleanup(_value: object) -> None:
        events.append("cleanup")

    def cleanup(value: object) -> Awaitable[None]:
        return acleanup(value)

    return cleanup


def _async_cleanup(events: list[str]):
    async def acleanup(_value: object) -> None:
        events.append("cleanup")

    return acleanup


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
    pytest.param(lambda cleanup: Resource(Connection(), cleanup=cleanup), id="owned"),
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

    @skipif_issync
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

    @skipif_issync
    def test_sync_acquire_async_value_factory_bridges(self) -> None:
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
        client = Connection()

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
        _test_open_close(Resource(value, **kwargs), value)
        _test_open_close(Resource.from_external(value), value)

    def test_context_borrows_an_external_resource(self, external_resource):
        context = Context().with_resource("value", external_resource)
        _test_open_close(context.resources["value"])

    def test_context_manager_lifecycle_opens_and_closes(self, sync_contextmanager):
        _test_open_close(Resource.from_lifecycle(sync_contextmanager))

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

    @skipif_issync
    @pytest.mark.parametrize("build", SYNC_BRIDGED_CLEANUPS)
    def test_sync_bridges_the_cleanup_of_an_async_produced_value(self, build) -> None:
        events: list[str] = []
        acquired = None

        with SyncExecution() as execution:
            acquired = execution.acquire(build(events))
            assert events == []

        assert acquired == "value"
        assert events == ["cleanup"]

    @skipif_issync
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

    @skipif_issync
    @pytest.mark.parametrize("build", SYNC_HANGING_CLEANUPS)
    def test_sync_bridged_cleanup_expiry_is_raised_at_exit(self, build) -> None:
        settings = ExecutionSettings(shutdown_timeout=0.05)

        with pytest.raises(TimeoutError), SyncExecution(settings=settings) as execution:
            execution.acquire(build())


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

    # Sync twin: test_owned_and_external_resources_wrap_a_value[closeable]
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


def _chars(value: str) -> Iterator[str]:
    return iter(value)


def _achars(value: str) -> AsyncIterator[str]:
    return as_async(value)


def _root(index: int = 0, value: object = "a") -> _ItemEnvelope[object]:
    return _ItemEnvelope.from_parent(PLACEHOLDER, "source", value, index)


RESULT_ENVELOPE_RULES = [
    pytest.param(IdentityMode.PRESERVE, "xy", True, id="preserve-many"),
    pytest.param(IdentityMode.DERIVE, "x", False, id="derive-one"),
    pytest.param(IdentityMode.DERIVE, "xy", False, id="derive-many"),
    pytest.param(IdentityMode.COMBINE, "x", False, id="combine-one"),
    pytest.param(None, "x", True, id="undeclared-one"),
    pytest.param(None, "xy", False, id="undeclared-two"),
    pytest.param(None, "xyz", False, id="undeclared-three"),
    pytest.param(None, "", False, id="undeclared-none"),
]


class TestResultEnvelopes:
    @pytest.mark.parametrize("values", ["a", "ab"])
    @pytest.mark.parametrize("identity", [*IdentityMode, None])
    def test_placeholder_results_are_roots(self, identity, values):
        envelopes = list(gen_result_envelopes("fetch", values, PLACEHOLDER, identity))
        expected = [("fetch", i) for i in range(len(values))]
        assert [env.generation for env in envelopes] == expected
        assert all(env.item_key is MISSING for env in envelopes)

    @pytest.mark.parametrize(("identity", "values", "preserves"), RESULT_ENVELOPE_RULES)
    def test_identity_rule_per_input_item(self, identity, values, preserves):
        parent = _root()
        envelopes = list(gen_result_envelopes("n", values, parent, identity))

        if preserves:
            expected = [parent.generation] * len(values)
        else:
            expected = [
                build_generation("n", parent.generation, i) for i in range(len(values))
            ]

        assert [env.value for env in envelopes] == list(values)
        assert [env.generation for env in envelopes] == expected

    def test_undeclared_mode_reads_two_results_ahead(self):
        pulled: list[int] = []

        def gen_values():
            for value in count():
                pulled.append(value)
                yield value

        envelopes = gen_result_envelopes("n", gen_values(), _root())
        assert next(envelopes).value == 0
        assert pulled == [0, 1]

    def test_preserve_keeps_the_input_identity(self):
        parent = _ItemEnvelope("a", "key", ("n", 0), Metadata({"seen": True}))
        [envelope] = gen_result_envelopes("upper", ["A"], parent, IdentityMode.PRESERVE)
        assert envelope == _ItemEnvelope("A", "key", ("n", 0), parent.observation)

    @pytest.mark.parametrize("identity", [IdentityMode.DERIVE, None])
    def test_derive_indexes_results_within_each_parent(self, identity):
        first, second = _root(0), _root(1)
        derived = [
            [
                env.generation
                for env in gen_result_envelopes("split", "xy", parent, identity)
            ]
            for parent in (first, second)
        ]
        assert derived == [
            [build_generation("split", parent.generation, i) for i in range(2)]
            for parent in (first, second)
        ]
        assert len({*derived[0], *derived[1]}) == 4

    def test_derived_results_keep_the_parent_observation(self):
        parent = _ItemEnvelope(
            "a", generation=("n", 0), observation=Metadata({"seen": True})
        )
        [envelope] = gen_result_envelopes("split", ["x"], parent, IdentityMode.DERIVE)
        assert envelope.item_key is MISSING
        assert envelope.observation is parent.observation

    @pytest.mark.parametrize("placeholder", [False, True])
    @pytest.mark.parametrize(("identity", "values", "preserves"), RESULT_ENVELOPE_RULES)
    @async_test
    async def test_async_results_match_sync_results(
        self, identity, values, preserves, placeholder
    ):
        parent = PLACEHOLDER if placeholder else _root()
        expected = list(gen_result_envelopes("n", values, parent, identity))
        envelopes = agen_result_envelopes("n", values, parent, identity)
        assert [env async for env in envelopes] == expected

    @pytest.mark.parametrize("round_trip", ROUND_TRIPS)
    def test_tracked_item_call_round_trips(self, round_trip):
        call = partial(run_tracked_item, _chars, "split", None)
        envelopes = round_trip(call)(_root(value="ab"))
        assert envelopes == list(gen_result_envelopes("split", "ab", _root(value="ab")))

    @async_test
    async def test_async_tracked_item_call_matches_sync(self):
        parent = _ItemEnvelope.from_parent(PLACEHOLDER, "fetch", "ab")
        expected = run_tracked_item(_chars, "split", None, parent)
        envelopes = await arun_tracked_item(_achars, "split", None, parent)
        assert envelopes == expected


def _dotdicts(count: int) -> list[_ItemEnvelope[DotDict]]:
    return [
        _ItemEnvelope.from_parent(PLACEHOLDER, "source", DotDict({"i": i}), i)
        for i in range(count)
    ]


class TestNodeProvenance:
    def test_passed_through_values_keep_their_envelopes(self):
        envelopes = _dotdicts(3)
        provenance = NodeProvenance.from_identity("reverse", IdentityMode.PRESERVE)
        values = list(provenance.gen_values(envelopes))
        results = list(provenance.gen_envelopes(reversed(values)))
        assert results == envelopes[::-1]
        assert all(
            r.value is e.value for r, e in zip(results, envelopes[::-1], strict=True)
        )

    def test_a_value_read_twice_gets_its_envelopes_back_in_order(self):
        value = DotDict({"i": 0})
        envelopes = [
            _ItemEnvelope.from_parent(PLACEHOLDER, "source", value, i) for i in range(2)
        ]
        provenance = NodeProvenance.from_identity("filter", IdentityMode.PRESERVE)
        values = list(provenance.gen_values(envelopes))
        results = list(provenance.gen_envelopes(values))
        assert [env.generation for env in results] == [
            env.generation for env in envelopes
        ]

    def test_new_values_derive_from_the_last_input(self):
        envelopes = _dotdicts(2)
        provenance = NodeProvenance.from_identity("join", IdentityMode.PRESERVE)
        values = list(provenance.gen_values(envelopes))
        copies = [DotDict(v) for v in values if isinstance(v, DotDict)]
        results = list(provenance.gen_envelopes(copies))
        last = envelopes[-1].generation
        assert [env.generation for env in results] == [
            ("join", last, 0),
            ("join", last, 1),
        ]

    def test_new_values_before_any_input_are_roots(self):
        provenance = NodeProvenance.from_identity("join", None)
        [result] = provenance.gen_envelopes([DotDict()])
        assert result.generation == ("join", 0)

    def test_unreferenceable_values_derive_from_their_input(self):
        envelopes = [_root(i, f"v{i}") for i in range(2)]
        provenance = NodeProvenance.from_identity("upper", IdentityMode.PRESERVE)
        results = list(provenance.gen_envelopes(provenance.gen_values(envelopes)))
        assert [env.value for env in results] == ["v0", "v1"]
        assert [env.generation for env in results] == [
            ("upper", env.generation, k) for k, env in enumerate(envelopes)
        ]

    def test_dropped_values_free_their_entries(self):
        provenance = _TableProvenance("filter")
        values = provenance.gen_values(_dotdicts(100))
        kept = [v for v in values if isinstance(v, DotDict) and v["i"] % 10 == 0]
        gc.collect()
        assert len(provenance._table) == len(kept) == 10

    def test_closing_the_output_frees_every_entry(self):
        provenance = _TableProvenance("filter")
        envelopes = _dotdicts(3)
        values = list(provenance.gen_values(envelopes))
        results = provenance.gen_envelopes(values)
        next(results)
        results.close()
        assert not provenance._table

    def test_combine_ignores_passed_through_values(self):
        envelopes = _dotdicts(2)
        provenance = NodeProvenance.from_identity("count", IdentityMode.COMBINE)
        values = list(provenance.gen_values(envelopes))
        results = list(provenance.gen_envelopes(values))
        assert {env.generation for env in results}.isdisjoint(
            env.generation for env in envelopes
        )

    def test_combine_identity_folds_every_contributor(self):
        def combine(envelopes):
            provenance = NodeProvenance.from_identity("count", IdentityMode.COMBINE)
            values = list(provenance.gen_values(envelopes))
            return next(provenance.gen_envelopes([len(values)])).generation

        contributors = IdentityAccumulator(IdentityDomain.GENERATION)

        for env in (_root(0), _root(1)):
            contributors.add(env.generation)

        assert combine([_root(0), _root(1)]) == ("count", contributors.digest(), 0)
        assert combine([_root(0), _root(1)]) != combine([_root(0), _root(2)])

    def test_closing_the_output_closes_the_wrapped_stream(self):
        closed: list[bool] = []

        def gen_values():
            try:
                yield from (DotDict({"i": i}) for i in range(3))
            finally:
                closed.append(True)

        results = NodeProvenance.from_identity(
            "filter", IdentityMode.PRESERVE
        ).gen_envelopes(gen_values())
        next(results)
        results.close()
        assert closed == [True]

    @async_test
    async def test_closing_the_async_output_closes_the_wrapped_stream(self):
        closed: list[bool] = []

        async def agen_values():
            try:
                for i in range(3):
                    yield DotDict({"i": i})
            finally:
                closed.append(True)

        provenance = NodeProvenance.from_identity("filter", IdentityMode.PRESERVE)
        results = provenance.agen_envelopes(agen_values())
        await anext(results)
        await results.aclose()
        assert closed == [True]

    @async_test
    async def test_async_twins_match_the_sync_rule(self):
        envelopes = _dotdicts(3)
        provenance = NodeProvenance.from_identity("reverse", IdentityMode.PRESERVE)
        values = [value async for value in provenance.agen_values(envelopes)]
        results = [env async for env in provenance.agen_envelopes(values[::-1])]
        assert results == envelopes[::-1]


def _get_seed_index(value: Item) -> int:
    """Gets the position of the seed item ``value`` came from."""
    index = dict(value).get("i")

    if not isinstance(index, int):
        raise TypeError(f"{value!r} has no seed index")

    return index


def _feed(pipeline: Pipeline, seed: Sequence[ItemOrValue]) -> list[_Result]:
    """Runs ``pipeline`` the way a pipeline run does and keeps each identity."""
    plan = ExecutionPlan.from_workflow(pipeline.workflow, dispatcher)
    results: list[_Result] = []

    with SyncExecution(settings=pipeline.settings) as execution:
        stream = execution.run_envelopes(plan, seed=seed)
        results = [(env.value, env.generation) for env in stream]

    return results


async def _afeed(pipeline: Pipeline, seed: Sequence[ItemOrValue]) -> list[_Result]:
    """The async twin of ``_feed``."""
    plan = ExecutionPlan.from_workflow(pipeline.workflow, dispatcher)
    results: list[_Result] = []

    async with AsyncExecution(settings=pipeline.settings) as execution:
        stream = await execution.arun_envelopes(plan, seed=seed)
        results = [(env.value, env.generation) async for env in stream]

    return results


def _copy_item(item: Item, part: object) -> Item:
    return item.copy()


def _build_fan_in_copy() -> Workflow:
    """Builds a preserving callable node fed a second stream (a whole-stream run)."""
    a = ModuleNode(
        id="a",
        name="itembuilder",
        conf=ItemBuilderConf({"attrs": [{"key": "x", "value": "1"}]}),
    )
    b = ModuleNode(
        id="b",
        name="itembuilder",
        conf=ItemBuilderConf({"attrs": [{"key": "y", "value": "2"}]}),
    )
    c = CallableNode(id="c", name="copy_item", fn=_copy_item, identity="preserve")
    edges = (
        StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("c", "in:part")),
    )
    outputs = {"default": Endpoint("c", "out")}
    return Workflow(nodes=[a, b, c], edges=edges, outputs=outputs)


def _seed_target(pipeline: Pipeline) -> NodeId:
    plan = ExecutionPlan.from_workflow(pipeline.workflow, dispatcher)
    return plan.require_seed_target("default")


def _roots(pipeline: Pipeline, results: list[_Result]) -> list[bool]:
    """Whether each result keeps the identity of the seed item it came from."""
    target = _seed_target(pipeline)
    return [
        generation == build_generation(target, MISSING, _get_seed_index(value))
        for value, generation in results
    ]


def _multiset(results: list[_Result]) -> list[tuple[str, str]]:
    return sorted((repr(sorted(value.items())), repr(gen)) for value, gen in results)


# Pipelines that pass each seed item on, so every result keeps its seed identity.
PRESERVING_PIPELINES = [
    pytest.param(_HASH, 4, id="processor"),
    pytest.param(_HASH | _HASH, 4, id="processor-chain"),
    pytest.param(_FILTER, 2, id="seeded-filter"),
    pytest.param(_HASH | _FILTER, 2, id="filter"),
    pytest.param(
        Pipeline.from_module("truncate", conf=TruncateConf(count=2)), 2, id="truncate"
    ),
    pytest.param(
        Pipeline.from_module(
            "sort", conf=SortConf({"rule": SortConfRule(field="i", dir="desc")})
        ),
        4,
        id="sort",
    ),
    pytest.param(Pipeline.from_module("union"), 4, id="union"),
    pytest.param(_HASH.map(lambda item: {**item, "m": 1}), 4, id="map"),
    pytest.param(Pipeline().map(lambda item: item) | _FILTER, 2, id="seeded-map"),
    pytest.param(Pipeline().map(dict) | _FILTER, 2, id="fresh-dict-map"),
]
# Pipelines over scalar seed items, with the seed positions of the items they keep.
SCALAR_PIPELINES = [
    pytest.param(_FILTER, [0, 2], id="filter"),
    pytest.param(
        Pipeline.from_module("truncate", conf=TruncateConf(count=2)),
        [0, 1],
        id="truncate",
    ),
]
# Pipelines whose results run on a worker pool or the async execution.
PARALLEL_PIPELINES = [
    pytest.param(_HASH.with_execution(concurrency=2, ordered=False), id="threads"),
    pytest.param(
        _HASH.with_execution(executor="process"),
        id="processes",
        marks=pytest.mark.timeout(5),
    ),
    pytest.param(_TOKENS.with_execution(concurrency=2), id="derived-threads"),
]
# Pipelines whose async run yields the same identities as their sync run.
ASYNC_PARITY_PIPELINES = [
    pytest.param(_TOKENS, id="derived"),
    pytest.param(_HASH.with_execution(concurrency=2, ordered=False), id="threads"),
    pytest.param(_TOKENS.with_execution(concurrency=2), id="derived-threads"),
]


class TestRunEnvelopes:
    """Test the identity each result of an envelope run keeps."""

    @pytest.mark.parametrize(("pipeline", "length"), PRESERVING_PIPELINES)
    def test_run_envelopes_keeps_each_seed_item_s_identity(
        self, pipeline, length
    ) -> None:
        results = _feed(pipeline, _FEED_SEED)
        assert len(results) == length
        assert all(_roots(pipeline, results))

    @pytest.mark.parametrize(("pipeline", "indexes"), SCALAR_PIPELINES)
    def test_run_envelopes_keeps_each_scalar_seed_item_s_identity(
        self, pipeline, indexes
    ) -> None:
        target = _seed_target(pipeline)
        generations = [gen for _, gen in _feed(pipeline, _SCALAR_SEED)]
        assert generations == [build_generation(target, MISSING, i) for i in indexes]

    def test_run_envelopes_keeps_each_identity_of_a_repeated_item(self) -> None:
        pipeline = Pipeline.from_module("truncate", conf=TruncateConf(count=2))
        target = _seed_target(pipeline)
        item = DotDict({"content": "a"})
        generations = [gen for _, gen in _feed(pipeline, [item, item])]
        assert generations == [build_generation(target, MISSING, i) for i in (0, 1)]

    def test_run_envelopes_derives_tokens_from_their_own_item(self) -> None:
        target = _seed_target(_TOKENS)
        results = _feed(_TOKENS, _FEED_SEED)
        extended = _feed(_TOKENS, [*_FEED_SEED, {"i": 4, "content": "f g"}])
        parents = [build_generation(target, MISSING, i) for i in (0, 0, 1, 2, 3, 3)]
        indexes = [0, 1, 0, 0, 0, 1]
        expected = list(map(partial(build_generation, target), parents, indexes))
        assert [generation for _, generation in results] == expected
        assert extended[: len(results)] == results

    def test_run_envelopes_combines_a_count_into_one_new_item(self) -> None:
        count_pipeline = Pipeline.from_module("count")
        [(value, generation)] = _feed(count_pipeline, _FEED_SEED)
        assert value == {"count": 4}
        assert _feed(count_pipeline, _FEED_SEED) == [(value, generation)]
        assert not any(_roots(count_pipeline, [({"i": 0}, generation)]))

    def test_run_envelopes_derives_a_declared_map_result(self) -> None:
        pipeline = _HASH.map(lambda item: {**item, "m": 1}, identity="derive")
        target = _seed_target(pipeline)
        node_id = pipeline.workflow.outputs["default"].node
        results = _feed(pipeline, _FEED_SEED)
        expected = [
            build_generation(node_id, build_generation(target, MISSING, i), 0)
            for i in range(4)
        ]
        assert [generation for _, generation in results] == expected

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="a declared identity mode on a node fed a secondary input stream is "
        "not yet implemented",
    )
    def test_run_envelopes_keeps_a_fan_in_node_s_declared_identity(self) -> None:
        plan = ExecutionPlan.from_workflow(_build_fan_in_copy(), dispatcher)
        results: list[_Result] = []

        with SyncExecution() as execution:
            stream = execution.run_envelopes(plan)
            results = [(env.value, env.generation) for env in stream]

        [(value, generation)] = results
        assert value == {"x": "1"}
        assert generation == build_generation("a", MISSING, 0)

    @pytest.mark.parametrize("pipeline", PARALLEL_PIPELINES)
    def test_run_envelopes_on_workers_matches_a_sequential_run(self, pipeline) -> None:
        sequential = pipeline.with_execution(concurrency=None, executor=None)
        expected = _multiset(_feed(sequential, _FEED_SEED))
        assert _multiset(_feed(pipeline, _FEED_SEED)) == expected


class TestAsyncRunEnvelopes:
    """Test the identity each result of an async envelope run keeps."""

    @pytest.mark.parametrize(("pipeline", "length"), PRESERVING_PIPELINES)
    @async_test
    async def test_arun_envelopes_keeps_each_seed_item_s_identity(
        self, pipeline, length
    ) -> None:
        results = await _afeed(pipeline, _FEED_SEED)
        assert results == _feed(pipeline, _FEED_SEED)
        assert len(results) == length

    @pytest.mark.parametrize(("pipeline", "indexes"), SCALAR_PIPELINES)
    @async_test
    async def test_arun_envelopes_keeps_each_scalar_seed_item_s_identity(
        self, pipeline, indexes
    ) -> None:
        target = _seed_target(pipeline)
        results = await _afeed(pipeline, _SCALAR_SEED)
        assert results == _feed(pipeline, _SCALAR_SEED)
        assert [gen for _, gen in results] == [
            build_generation(target, MISSING, i) for i in indexes
        ]

    @pytest.mark.parametrize("pipeline", ASYNC_PARITY_PIPELINES)
    @async_test
    async def test_arun_envelopes_matches_a_sync_run(self, pipeline) -> None:
        expected = _multiset(_feed(pipeline, _FEED_SEED))
        assert _multiset(await _afeed(pipeline, _FEED_SEED)) == expected
