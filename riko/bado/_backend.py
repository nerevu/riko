# vim: sw=4:ts=4:expandtab
"""Provides guarded access to the optional Riko async runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, Unpack, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from riko.types._wrappers import Func

type AsyncBackend = Literal["anyio", "empty"]


class Run(Protocol):
    """The call signature of the async entry point, ``run``."""

    def __call__[*PosArgsT, T](
        self, func: Callable[[Unpack[PosArgsT]], Awaitable[T]], *args: *PosArgsT
    ) -> T: ...


try:
    import anyio
    from asyncer import asyncify
    from httpx import Response as HTTPXResponse
except ImportError:
    AsyncClient: object = None
    BlockingPortal: object = None
    CancelScope: type | None = None
    CapacityLimiter: type | None = None
    Event: type | None = None
    HTTPStatusError: type[Exception] | None = None
    HTTPXResponse: object = None
    MemoryObjectReceiveStream: object = None
    MemoryObjectSendStream: object = None
    NamedTemporaryFile: object = None
    Path: object = None
    Semaphore: type | None = None
    TimeoutException: type[Exception] | None = None
    async_chain: Func[object] = lambda *_, **_kw: None
    async_open: Func[object] = lambda *_, **_kw: None
    async_sleep: Func[object] = lambda *_, **_kw: None
    asyncify: Func[object] = lambda *_, **_kw: None
    backend: AsyncBackend = "empty"
    create_memory_object_stream: Func[object] | None = None
    create_task_group: Func[object] | None = None
    fail_after: Func[object] | None = None
    gather_results: Func[object] = lambda *_, **_kw: None
    lowlevel: object = None
    run_from_thread: Func[object] = lambda *_, **_kw: None
    start_blocking_portal: Func[object] = lambda *_, **_kw: None

    async def checkpoint() -> None:
        return None

    def _run[*PosArgsT, T](
        func: Callable[[Unpack[PosArgsT]], Awaitable[T]], *args: *PosArgsT
    ) -> T:
        return cast("T", None)

    run: Run = _run
else:
    from anyio import (
        CancelScope,
        CapacityLimiter,
        Event,
        NamedTemporaryFile,
        Path,
        Semaphore,
        create_memory_object_stream,
        create_task_group,
        fail_after,
        lowlevel,
    )
    from anyio import open_file as async_open
    from anyio import sleep as async_sleep
    from anyio.from_thread import BlockingPortal, start_blocking_portal
    from anyio.from_thread import run as run_from_thread
    from anyio.itertools import chain as async_chain
    from anyio.lowlevel import checkpoint
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from httpx import AsyncClient, HTTPStatusError, TimeoutException

    backend = "anyio"
    run: Run = anyio.run

issync: bool = backend == "empty"
isasync: bool = not issync

__all__ = [
    "AsyncClient",
    "BlockingPortal",
    "CancelScope",
    "CapacityLimiter",
    "Event",
    "HTTPStatusError",
    "HTTPXResponse",
    "MemoryObjectReceiveStream",
    "MemoryObjectSendStream",
    "NamedTemporaryFile",
    "Path",
    "Semaphore",
    "TimeoutException",
    "async_chain",
    "async_open",
    "async_sleep",
    "asyncify",
    "backend",
    "checkpoint",
    "create_memory_object_stream",
    "create_task_group",
    "fail_after",
    "gather_results",
    "isasync",
    "issync",
    "lowlevel",
    "run",
    "run_from_thread",
    "start_blocking_portal",
]
