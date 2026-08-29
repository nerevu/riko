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
from typing import Any, Protocol, Unpack


class Run(Protocol):
    """The call signature of the async entry point, ``run``."""

    def __call__[*PosArgsT, T](  # noqa: E704
        self, func: Callable[[Unpack[PosArgsT]], Awaitable[T]], *args: *PosArgsT
    ) -> T: ...


run: Run | None = None

try:
    import anyio
except ImportError:
    CapacityLimiter: type | None = None
    Semaphore: type | None = None
    MemoryObjectReceiveStream: Any = None
    MemoryObjectSendStream: Any = None
    NamedTemporaryFile: Any = None
    Path: Any = None
    async_get: Callable[..., Any] = lambda *_args, **_kwargs: None
    async_json: Callable[..., Any] = lambda *_args, **_kwargs: None
    async_read: Callable[..., Any] = lambda *_args, **_kwargs: None
    async_partial: Callable[..., Any] = lambda *_args, **_kwargs: None
    async_return: Callable[..., Any] = lambda *_args, **_kwargs: None
    async_sleep: Callable[..., Any] = lambda *_args, **_kwargs: None
    create_memory_object_stream: Callable[..., Any] | None = None
    create_task_group: Callable[..., Any] | None = None
    fail_after: Callable[..., Any] | None = None
    gather_results: Callable[..., Any] = lambda *_args, **_kwargs: None
    lowlevel: Any = None
    maybe_deferred: Callable[..., Any] = lambda *_args, **_kwargs: None
    open_file: Callable[..., Any] = lambda *_args, **_kwargs: None

    async def checkpoint() -> None:
        return None
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
        open_file,
    )
    from anyio import sleep as async_sleep
    from anyio.lowlevel import checkpoint
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

    run = anyio.run

backend: str = "empty" if run is None else "anyio"
issync: bool = backend == "empty"
isasync: bool = not issync

__all__ = [
    "CapacityLimiter",
    "MemoryObjectReceiveStream",
    "MemoryObjectSendStream",
    "NamedTemporaryFile",
    "Path",
    "Semaphore",
    "async_get",
    "async_json",
    "async_partial",
    "async_read",
    "async_return",
    "async_sleep",
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
    "open_file",
    "run",
]
