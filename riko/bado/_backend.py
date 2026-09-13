# vim: sw=4:ts=4:expandtab
"""
riko.bado._backend
~~~~~~~~~~~~~~~~~~

Private guarded backend facade for Riko's async runtime.

Riko internals import AnyIO/httpx runtime primitives from this module rather
than importing those dependencies directly. This module is private and carries
no SemVer compatibility guarantee.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, Unpack, cast

type Backends = Literal["anyio", "empty"]


class Run(Protocol):
    """The call signature of the async entry point, ``run``."""

    def __call__[*PosArgsT, T](  # noqa: E704
        self, func: Callable[[Unpack[PosArgsT]], Awaitable[T]], *args: *PosArgsT
    ) -> T: ...


try:
    import anyio
    from httpx import Response as HTTPXResponse
except ImportError:
    AsyncClient: Any = None
    CapacityLimiter: type | None = None
    HTTPXResponse: Any = None
    Semaphore: type | None = None
    MemoryObjectReceiveStream: Any = None
    MemoryObjectSendStream: Any = None
    NamedTemporaryFile: Any = None
    Path: Any = None
    async_get: Callable[..., Any] = lambda *_, **_kw: None
    async_json: Callable[..., Any] = lambda *_, **_kw: None
    async_read: Callable[..., Any] = lambda *_, **_kw: None
    async_partial: Callable[..., Any] = lambda *_, **_kw: None
    async_return: Callable[..., Any] = lambda *_, **_kw: None
    async_sleep: Callable[..., Any] = lambda *_, **_kw: None
    asyncify: Callable[..., Any] = lambda *_, **_kw: None
    backend: Backends = "empty"
    create_memory_object_stream: Callable[..., Any] | None = None
    create_task_group: Callable[..., Any] | None = None
    fail_after: Callable[..., Any] | None = None
    gather_results: Callable[..., Any] = lambda *_, **_kw: None
    lowlevel: Any = None
    maybe_deferred: Callable[..., Any] = lambda *_, **_kw: None
    async_open: Callable[..., Any] = lambda *_, **_kw: None

    async def checkpoint() -> None:
        return None

    def _run[*PosArgsT, T](
        func: Callable[[Unpack[PosArgsT]], Awaitable[T]], *args: *PosArgsT
    ) -> T:
        return cast(T, None)

    run: Run = _run
else:
    from anyio import (
        CapacityLimiter,
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
    from anyio.lowlevel import checkpoint
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from asyncer import asyncify
    from httpx import AsyncClient

    backend = "anyio"
    run: Run = anyio.run

issync: bool = backend == "empty"
isasync: bool = not issync

__all__ = [
    "AsyncClient",
    "CapacityLimiter",
    "HTTPXResponse",
    "MemoryObjectReceiveStream",
    "MemoryObjectSendStream",
    "NamedTemporaryFile",
    "Path",
    "Semaphore",
    "async_get",
    "async_json",
    "async_open",
    "async_partial",
    "async_read",
    "async_return",
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
    "maybe_deferred",
    "run",
]
