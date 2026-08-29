# vim: sw=4:ts=4:expandtab
"""
riko.bado
~~~~~~~~~

AnyIO-backed async runtime for riko pipes.

Async support is available when the ``async`` extra (``anyio`` + ``httpx``) is
installed; otherwise ``backend == "empty"`` and riko runs sync-only. ``run`` is
the entry point for async doctests/examples (``run(main)`` where ``main`` is a
no-argument async function) — anyio needs no reactor.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, Unpack


class Run(Protocol):
    """The call signature of the async entry point, :data:`run`."""

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
    NamedTemporaryFile: type | None = None
    Path: type | None = None
    async_get: Callable[..., Any] = lambda *_: None
    async_json: Callable[..., Any] = lambda *_: None
    async_read: Callable[..., Any] = lambda *_: None
    async_partial: Callable[..., Any] = lambda *_: None
    async_return: Callable[..., Any] = lambda *_: None
    async_sleep: Callable[..., Any] = lambda *_: None
    create_memory_object_stream: Callable[..., Any] | None = None
    create_task_group: Callable[..., Any] | None = None
    fail_after: Callable[..., Any] | None = None
    gather_results: Callable[..., Any] = lambda *_: None
    lowlevel: Any = None
    maybe_deferred: Callable[..., Any] = lambda *_: None
    open_file: Callable[..., Any] = lambda *_: None

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

    from riko.bado._util import (
        async_get,
        async_json,
        async_partial,
        async_read,
        async_return,
        gather_results,
        maybe_deferred,
    )

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
