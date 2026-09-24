# vim: sw=4:ts=4:expandtab
"""
Provides guarded access to the optional Riko async runtime.

Examples:

    Basic usage::

        >>> from riko import backend, isasync, issync
        >>>
        >>> backend in {"anyio", "empty"}
        True
        >>> isasync is not issync
        True

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol, Unpack, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

type AsyncBackend = Literal["anyio", "empty"]


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
    BlockingPortal: Any = None
    CancelScope: type | None = None
    CapacityLimiter: type | None = None
    Event: type | None = None
    HTTPXResponse: Any = None
    Semaphore: type | None = None
    start_blocking_portal: Callable[..., Any] | None = None
    MemoryObjectReceiveStream: Any = None
    MemoryObjectSendStream: Any = None
    NamedTemporaryFile: Any = None
    Path: Any = None
    async_chain: Callable[..., Any] = lambda *_, **_kw: None
    async_get: Callable[..., Any] = lambda *_, **_kw: None
    async_json: Callable[..., Any] = lambda *_, **_kw: None
    async_read: Callable[..., Any] = lambda *_, **_kw: None
    async_partial: Callable[..., Any] = lambda *_, **_kw: None
    async_return: Callable[..., Any] = lambda *_, **_kw: None
    async_sleep: Callable[..., Any] = lambda *_, **_kw: None
    asyncify: Callable[..., Any] = lambda *_, **_kw: None
    backend: AsyncBackend = "empty"
    create_memory_object_stream: Callable[..., Any] | None = None
    create_task_group: Callable[..., Any] | None = None
    fail_after: Callable[..., Any] | None = None
    gather_results: Callable[..., Any] = lambda *_, **_kw: None
    lowlevel: Any = None
    async_open: Callable[..., Any] = lambda *_, **_kw: None

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
    from anyio.itertools import chain as async_chain
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
    "BlockingPortal",
    "CancelScope",
    "CapacityLimiter",
    "Event",
    "HTTPXResponse",
    "MemoryObjectReceiveStream",
    "MemoryObjectSendStream",
    "NamedTemporaryFile",
    "Path",
    "Semaphore",
    "async_chain",
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
    "run",
    "start_blocking_portal",
]
