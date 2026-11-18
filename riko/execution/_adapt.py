# vim: sw=4:ts=4:expandtab
"""
Adapts streams and callables across the synchronous/asynchronous boundary.

Both the sync and the async execution share these helpers. They re-expose one side's
stream or loop embed to the other without materializing it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from functools import partial
from typing import TYPE_CHECKING, Protocol

from riko.bado.itertools import aiter_sentinel
from riko.base._exceptions import InvalidPipelineError
from riko.base._sentinels import MISSING, MissingType
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.types._wrappers import (
    AsyncFunc,
    Func,
    require_async_wrapper,
    require_sync_wrapper,
)

from ._prepared import NO_PIPE_MSG

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from riko.types._streams import Item
    from riko.types._wrappers import (
        AnyModuleWrapper,
        AsyncModuleWrapper,
        ModuleWrapper,
        SyncModuleWrapper,
    )

    from ._prepared import ResolvedModule

type Drain[T] = Callable[[AsyncIterator[T]], Iterator[T]]

_FUNC_META = ("__name__", "__qualname__", "__doc__")


class LoopCall(Protocol):
    """Runs an awaitable-returning callable to completion from a worker thread."""

    def __call__[R](self, func: AsyncFunc[R], /) -> R: ...


class WorkerCall(Protocol):
    """Runs a blocking callable off the event loop and awaits its result."""

    def __call__[R, *Ts](
        self, func: Callable[[*Ts], R], /, *args: *Ts
    ) -> Awaitable[R]: ...


def to_sync[T](call: LoopCall, stream: AsyncIterator[T]) -> Iterator[T]:
    """
    Re-exposes an async stream as a lazy synchronous item stream.

    The caller owns ``stream`` and should close it. This only reads it.

    Args:

        call: Runs an awaitable-returning callable to completion on the event loop from
            the calling thread.

        stream: The async iterator to read.

    Yields:

        Each item ``stream`` produces.

    """
    while True:
        try:
            item = call(stream.__anext__)
        except StopAsyncIteration:
            break
        else:
            yield item


def _next_or_missing[T](stream: Iterator[T]) -> T | MissingType:
    """Gets the next item from ``stream``, or ``MISSING`` once it is exhausted."""
    return next(stream, MISSING)


def pull_stream[T](func: WorkerCall, stream: Iterator[T]) -> AsyncIterator[T]:
    """
    Re-exposes a blocking item stream as a lazy async item stream.

    The caller owns ``stream`` and should close it. This only reads it.

    Args:

        func: Runs a blocking callable off the event loop.
        stream: The synchronous iterator to read.

    Returns:

        The async stream over ``stream`` that pulls one item per request.

    """
    return aiter_sentinel(partial(func, _next_or_missing), stream, MissingType)


def _copy_wrapper_meta(
    target: Func[object], source: ModuleWrapper, *, is_async: bool
) -> None:
    """
    Stamps ``source``'s discovery metadata onto ``target`` as sync or async.

    ``target`` also takes whichever of ``source``'s name, qualified name, and
    docstring it carries. ``__wrapped__`` is left unset so an ``unwrap``-based guard
    cannot see past the adapter to a callable of the other kind (sync or async).

    Args:

        target: The adapter function to annotate.
        source: The pipe callable whose metadata is copied.

    Kwargs:

        is_async: Whether the adapter is an ``async_pipe``.

    """
    stamp_wrapper_meta(
        target,
        name=source.name,
        module_type=source.type,
        subtype=source.subtype,
        subtypes=source.subtypes,
        pollable=source.pollable,
        loopable=source.loopable,
        is_async=is_async,
        sequential_inputs=source.sequential_inputs,
        input_schemas=getattr(source, "input_schemas", None),
        dependencies=getattr(source, "dependencies", None),
    )

    for attr in _FUNC_META:
        if hasattr(source, attr):
            setattr(target, attr, getattr(source, attr))


def _materialize(
    embed: SyncModuleWrapper, item: Item | None, kwargs: dict[str, object]
) -> list[object]:
    """Runs a blocking embed for one parent item and collects everything it yields."""
    return list(embed(item, **kwargs))


def adapt_embed(embed: AsyncModuleWrapper, to_sync: Drain[object]) -> SyncModuleWrapper:
    """
    Wraps an async-only loop embed as a synchronous one.

    The caller gets a callable with the synchronous calling convention that
    carries the embed's discovery metadata, so the loop machinery treats it as a
    native sync embed.

    Args:

        embed: The asynchronous pipe to run per parent item.
        to_sync: Consumes an async stream from the thread the loop pipe runs on.

    Returns:

        A synchronous embed whose per-item stream is drained through ``to_sync``.

    """

    def wrapper(item: object = None, **kwargs: object) -> Iterator[object]:
        return to_sync(aiter(embed(item, **kwargs)))

    _copy_wrapper_meta(wrapper, embed, is_async=False)
    return require_sync_wrapper(wrapper)


def async_adapt_embed(
    embed: SyncModuleWrapper, to_async: WorkerCall
) -> AsyncModuleWrapper:
    """
    Wraps a sync-only loop embed as an asynchronous one.

    The caller gets a callable with the asynchronous calling convention that
    carries the embed's discovery metadata, so the loop machinery treats it as a
    native async embed. The embed's per-item results are collected off the event
    loop, which the per-parent result count keeps bounded.

    Args:

        embed: The blocking pipe to run per parent item.
        to_async: Runs a blocking callable off the event loop.

    Returns:

        An asynchronous embed whose per-item results are produced on a worker.

    """

    async def wrapper(item: Item | None = None, **kwargs: object) -> list[object]:
        return await to_async(_materialize, embed, item, kwargs)

    _copy_wrapper_meta(wrapper, embed, is_async=True)
    return require_async_wrapper(wrapper)


def select_embed(
    embed: ResolvedModule,
    *,
    host_is_async: bool,
    to_async: WorkerCall,
    to_sync: Drain[object],
) -> AnyModuleWrapper:
    """
    Chooses a loop embed's callable to match whether its host pipe runs sync or async.

    Args:

        embed: The resolved embed module, with its sync and async callables.

    Kwargs:

        host_is_async: Whether the loop pipe runs asynchronously.
        to_async: Runs a sync-only embed off the event loop under an async host.
        to_sync: Pulls an async-only embed's output stream under a sync host.

    Returns:

        The embed's callable for the host's mode, else a wrapper adapting its other
        callable.

    Raises:

        InvalidPipelineError: If the embed has neither a sync nor an async callable.

    """
    if host_is_async:
        if (async_pipe := embed.async_pipe) is not None:
            result: AnyModuleWrapper = async_pipe
        elif (sync_pipe := embed.sync_pipe) is not None:
            result = async_adapt_embed(sync_pipe, to_async)
        else:
            raise InvalidPipelineError(NO_PIPE_MSG.format(embed.name))
    elif (sync_pipe := embed.sync_pipe) is not None:
        result = sync_pipe
    elif (async_pipe := embed.async_pipe) is not None:
        result = adapt_embed(async_pipe, to_sync)
    else:
        raise InvalidPipelineError(NO_PIPE_MSG.format(embed.name))

    return result


__all__ = ["adapt_embed", "async_adapt_embed", "pull_stream", "select_embed", "to_sync"]
