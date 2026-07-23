# vim: sw=4:ts=4:expandtab
"""
riko.bado
~~~~~~~~~
AnyIO-backed async runtime for riko pipes.

Async support is available when the ``async`` extra (``anyio`` + ``httpx``) is
installed; otherwise ``backend == "empty"`` and riko runs sync-only. ``run`` is
the entry point for async doctests/examples (``run(main)`` where ``main`` is a
no-argument coroutine function) — anyio needs no reactor.
"""

from functools import partial

try:
    import anyio
except ImportError:
    run = Path = None
    async_sleep = async_get = async_json = async_return = lambda *_: None
    gather_results = maybe_deferred = lambda *_: None
    CapacityLimiter = None
    create_memory_object_stream = None
    create_task_group = None
    lowlevel = None

    async def checkpoint() -> None:
        return None
else:
    from anyio import (
        CapacityLimiter,
        Path,
        create_memory_object_stream,
        create_task_group,
        lowlevel,
    )
    from anyio import sleep as async_sleep
    from anyio.lowlevel import checkpoint

    from riko.bado._util import (
        async_get,
        async_json,
        async_return,
        gather_results,
        maybe_deferred,
    )

    run = anyio.run


backend = "empty" if run is None else "anyio"
async_partial = lambda f, **kwargs: partial(maybe_deferred, f, **kwargs)  # noqa: E731
issync = backend == "empty"
isasync = not issync

__all__ = [
    "CapacityLimiter",
    "Path",
    "async_get",
    "async_json",
    "async_partial",
    "async_return",
    "async_sleep",
    "backend",
    "checkpoint",
    "create_memory_object_stream",
    "create_task_group",
    "gather_results",
    "isasync",
    "issync",
    "lowlevel",
    "maybe_deferred",
    "run",
]
