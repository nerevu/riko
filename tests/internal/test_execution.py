# vim: sw=4:ts=4:expandtab
"""Tests for the private execution lifetime primitives."""

from contextlib import asynccontextmanager, contextmanager, nullcontext
from urllib.request import urlopen

import pytest

from riko.bado import async_sleep
from riko.base.exceptions import InvalidPipelineError, PipelineStateError
from riko.io import async_url_open
from riko.runtime._execution import AsyncExecution, SyncExecution
from riko.runtime._resources import Resource
from tests import async_test
from tests._loopback import loopback_url

_BODY = "<rss><channel><item><title>hi</title></item></channel></rss>"
_CONTENT_TYPE = "application/xml"


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


class _BadClient:
    def close(self) -> None:
        raise RuntimeError("cleanup failed")


def test_sync_exit_stack_unwinds_lifo() -> None:
    events: list[str] = []

    @contextmanager
    def track(name: str):
        events.append(f"open {name}")
        try:
            yield name
        finally:
            events.append(f"close {name}")

    with SyncExecution() as execution:
        execution.enter_context(track("a"))
        execution.enter_context(track("b"))

    assert events == ["open a", "open b", "close b", "close a"]


def test_sync_exit_stack_unwinds_on_error() -> None:
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


def test_sync_enter_after_close_raises() -> None:
    execution = SyncExecution()
    execution.close()

    with pytest.raises(PipelineStateError):
        execution.enter_context(nullcontext(1))


def test_sync_cleanup_error_is_grouped() -> None:
    def boom() -> None:
        raise RuntimeError("cleanup failed")

    execution = SyncExecution()
    execution.callback(boom)

    with pytest.raises(ExceptionGroup) as caught:
        execution.close()

    assert isinstance(caught.value.exceptions[0], RuntimeError)


@async_test
async def test_sync_portal_bridges_to_async() -> None:
    async def double(value: int) -> int:
        return value * 2

    with SyncExecution() as execution:
        result = execution.run_async(double, 21)

    assert result == 42


@async_test
async def test_async_exit_stack_unwinds_lifo() -> None:
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
async def test_async_joins_tasks_before_resource_teardown() -> None:
    events: list[str] = []

    @contextmanager
    def resource():
        try:
            yield
        finally:
            events.append("resource-closed")

    async def worker() -> None:
        events.append("task-done")

    async with AsyncExecution() as execution:
        execution.enter_context(resource())
        execution.spawn(worker)

    assert events == ["task-done", "resource-closed"]


@async_test
async def test_async_failure_cancels_tasks_and_unwinds() -> None:
    events: list[str] = []

    @contextmanager
    def resource():
        try:
            yield
        finally:
            events.append("resource-closed")

    async def forever() -> None:
        await async_sleep(3600)

    async def fail() -> None:
        async with AsyncExecution() as execution:
            execution.enter_context(resource())
            execution.spawn(forever)
            raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await fail()

    assert events == ["resource-closed"]


@async_test
async def test_async_run_sync_bridges_to_worker() -> None:
    async with AsyncExecution() as execution:
        result = await execution.run_sync(pow, 2, 10)

    assert result == 1024


def test_sync_acquire_external_sync_resource_is_borrowed() -> None:
    client = _SyncClient()

    with SyncExecution() as execution:
        acquired = execution.acquire(Resource.from_external(client))
        assert acquired is client

    assert client.closed is False


def test_sync_acquire_external_async_resource_is_borrowed() -> None:
    client = _AsyncClient()

    with SyncExecution() as execution:
        acquired = execution.acquire(Resource.from_external(client))
        assert acquired is client

    assert client.closed is False


@async_test
async def test_async_acquire_external_sync_resource_is_borrowed() -> None:
    client = _SyncClient()

    async with AsyncExecution() as execution:
        acquired = await execution.aacquire(Resource.from_external(client))
        assert acquired is client

    assert client.closed is False


@async_test
async def test_async_acquire_external_async_resource_is_borrowed() -> None:
    client = _AsyncClient()

    async with AsyncExecution() as execution:
        acquired = await execution.aacquire(Resource.from_external(client))
        assert acquired is client

    assert client.closed is False


def test_sync_acquire_owned_value_closes() -> None:
    client = _SyncClient()

    with SyncExecution() as execution:
        execution.acquire(Resource(client))

    assert client.closed is True


@async_test
async def test_async_acquire_owned_value_closes() -> None:
    client = _AsyncClient()

    async with AsyncExecution() as execution:
        await execution.aacquire(Resource(client))

    assert client.closed is True


def test_sync_acquire_lifecycle_generator() -> None:
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


@async_test
async def test_async_acquire_async_lifecycle_generator() -> None:
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
async def test_async_acquire_sync_lifecycle_on_async_execution() -> None:
    events: list[str] = []

    def db():
        try:
            yield "value"
        finally:
            events.append("close")

    async with AsyncExecution() as execution:
        acquired = await execution.aacquire(Resource.from_lifecycle(db))
        assert acquired == "value"

    assert events == ["close"]


def test_sync_acquire_value_factory_runs_cleanup() -> None:
    events: list[str] = []

    def make() -> str:
        return "value"

    def cleanup(value: str) -> None:
        events.append(f"cleanup {value}")

    with SyncExecution() as execution:
        acquired = execution.acquire(Resource.from_factory(make, cleanup=cleanup))
        assert acquired == "value"

    assert events == ["cleanup value"]


def test_sync_acquire_value_factory_without_cleanup() -> None:
    client = _SyncClient()

    with SyncExecution() as execution:
        acquired = execution.acquire(
            Resource.from_factory(lambda: client, cleanup=False)
        )
        assert acquired is client

    assert client.closed is False


def test_sync_acquire_factory_cleanup_is_authoritative() -> None:
    client = _SyncClient()
    events: list[str] = []

    with SyncExecution() as execution:
        execution.acquire(
            Resource.from_factory(lambda: client, cleanup=lambda _: events.append("x"))
        )

    assert events == ["x"]
    assert client.closed is False


@async_test
async def test_async_acquire_async_value_factory() -> None:
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
async def test_sync_acquire_async_value_factory_bridges() -> None:
    async def make() -> str:
        return "value"

    with SyncExecution() as execution:
        acquired = execution.acquire(Resource.from_factory(make, cleanup=False))

    assert acquired == "value"


def test_sync_acquire_is_single_flight() -> None:
    calls: list[int] = []

    def make() -> object:
        calls.append(1)
        return object()

    with SyncExecution() as execution:
        resource = Resource.from_factory(make, cleanup=False)
        first = execution.acquire(resource)
        second = execution.acquire(resource)

    assert first is second
    assert len(calls) == 1


def test_sync_acquire_memoizes_failure() -> None:
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


def test_sync_partial_acquisition_unwinds() -> None:
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


def test_sync_acquire_cleanup_error_is_grouped() -> None:
    execution = SyncExecution()
    execution.acquire(Resource(_BadClient()))

    with pytest.raises(ExceptionGroup) as caught:
        execution.close()

    assert isinstance(caught.value.exceptions[0], RuntimeError)


def test_sync_acquire_async_lifecycle_rejected() -> None:
    async def db():
        yield "value"

    with SyncExecution() as execution, pytest.raises(InvalidPipelineError):
        execution.acquire(Resource.from_lifecycle(db))


@async_test
async def test_async_acquire_teardown_on_failure() -> None:
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


def test_sync_unacquired_lifecycle_stays_closed() -> None:
    events: list[str] = []

    def db():
        events.append("open")
        yield "value"

    with SyncExecution():
        Resource.from_lifecycle(db, lazy=True)

    assert events == []


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
        async with async_url_open(url) as stream:
            yield stream

        events.append("closed")

    return connect


@pytest.mark.simulated_network
def test_sync_external_http_client_under_sync_execution() -> None:
    events: list[str] = []

    with loopback_url(_BODY, content_type=_CONTENT_TYPE) as url:
        with SyncExecution() as execution:
            response = execution.acquire(
                Resource.from_lifecycle(_sync_http_client(url, events))
            )
            assert b"<item>" in response.read()
            assert events == []

        assert events == ["closed"]


@pytest.mark.simulated_network
@async_test
async def test_sync_external_http_client_under_async_execution() -> None:
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
async def test_async_external_http_client_under_async_execution() -> None:
    events: list[str] = []

    with loopback_url(_BODY, content_type=_CONTENT_TYPE) as url:
        async with AsyncExecution() as execution:
            stream = await execution.aacquire(
                Resource.from_lifecycle(_async_http_client(url, events))
            )
            assert "<item>" in stream.read()
            assert events == []

        assert events == ["closed"]


@pytest.mark.simulated_network
def test_sync_external_async_http_client_rejected() -> None:
    with (
        loopback_url(_BODY, content_type=_CONTENT_TYPE) as url,
        SyncExecution() as execution,
        pytest.raises(InvalidPipelineError, match="async-native"),
    ):
        execution.acquire(Resource.from_lifecycle(_async_http_client(url, [])))


@pytest.mark.simulated_network
def test_sync_external_http_client_torn_down_on_failure() -> None:
    events: list[str] = []

    def failing() -> object:
        raise RuntimeError("boom")

    def run() -> None:
        with (
            loopback_url(_BODY, content_type=_CONTENT_TYPE) as url,
            SyncExecution() as execution,
        ):
            execution.acquire(Resource.from_lifecycle(_sync_http_client(url, events)))
            execution.acquire(Resource.from_factory(failing, cleanup=False))

    with pytest.raises(RuntimeError, match="boom"):
        run()

    assert events == ["closed"]


@pytest.mark.simulated_network
@async_test
async def test_async_external_http_client_torn_down_on_cancellation() -> None:
    events: list[str] = []

    async def forever() -> None:
        await async_sleep(3600)

    async def fail() -> None:
        with loopback_url(_BODY, content_type=_CONTENT_TYPE) as url:
            async with AsyncExecution() as execution:
                await execution.aacquire(
                    Resource.from_lifecycle(_async_http_client(url, events))
                )
                execution.spawn(forever)
                raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await fail()

    assert events == ["closed"]
