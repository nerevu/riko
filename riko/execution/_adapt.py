# vim: sw=4:ts=4:expandtab
"""
Adapts streams and callables across the synchronous/asynchronous boundary.

Both the sync and the async execution share these helpers. They re-expose one side's
stream or loop embed to the other without materializing it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from functools import partial
from typing import TYPE_CHECKING, Protocol, Self

from riko.bado._util import maybe_async
from riko.bado.itertools import aauto_close, aiter_sentinel
from riko.base._exceptions import InvalidPipelineError
from riko.base._iterutils import log_failure
from riko.base._sentinels import MISSING, MissingType
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.types._io import resolve_closer
from riko.types._streams import require_async_stream
from riko.types._wrappers import Func, require_async_wrapper, require_sync_wrapper

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


class Bridge(Protocol):
    """Runs an awaitable to completion on an event loop and returns its result."""

    def __call__[R](self, value: Awaitable[R], /) -> R: ...


class WorkerCall(Protocol):
    """Runs a blocking callable off the event loop and awaits its result."""

    def __call__[R, **P](
        self, func: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
    ) -> Awaitable[R]: ...


class to_sync[T]:  # noqa: N801
    """
    Reads an async stream from sync code, then closes the stream.

    Exhausting, failing, or closing the result closes ``stream``.

    Args:

        bridge: Runs an awaitable to completion on the event loop that runs
            ``stream`` and returns its result.

        stream: The async iterator to read.

    Raises:

        Exception: Whatever closing ``stream`` raises. A close failure after a read
            error is noted on that error instead.

    Examples:

        >>> from riko import as_async, run
        >>> from riko.bado._util import asyncify, syncify
        >>>
        >>> stream = to_sync(syncify, as_async([1, 2]))
        >>> run(asyncify, list, stream)
        [1, 2]

    """

    __slots__ = ("_bridge", "_open", "stream")

    def __init__(self, bridge: Bridge, stream: AsyncIterator[T]) -> None:
        self._bridge = bridge
        self.stream = stream
        self._open = [True]

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        try:
            item = self._bridge(maybe_async(anext, self.stream))
        except StopAsyncIteration:
            self.close()
            raise StopIteration from None
        except BaseException as primary:
            try:
                self.close()
            except Exception as failure:  # noqa: BLE001 (noted on the primary)
                log_failure(primary, failure, "closing the stream")

            raise

        return item

    def close(self) -> None:
        """Closes ``stream`` on its event loop (closing again does nothing)."""
        try:
            # A single atomic pop, so concurrent callers close only once.
            self._open.pop()
        except IndexError:
            pass
        else:
            if (closer := resolve_closer(self.stream, is_async=True)) is not None:
                self._bridge(maybe_async(closer))


def _next_or_missing[T](stream: Iterator[T]) -> T | MissingType:
    """Gets the next item from ``stream``, or ``MISSING`` once it is exhausted."""
    return next(stream, MISSING)


def to_async[T](
    func: WorkerCall, stream: Iterator[T], *, inline: bool = False
) -> aauto_close[T]:
    """
    Reads a blocking stream from async code, then closes the stream.

    Exhausting, failing, or closing the result closes ``stream``.

    Args:

        func: Runs a blocking callable off the event loop.
        stream: The synchronous iterator to read.

    Kwargs:

        inline: Whether to run ``stream``'s close on the event loop instead of a worker.

    Returns:

        The async stream over ``stream`` that pulls one item per request.

    Examples:

        >>> from riko import alist, run
        >>> from riko.bado._util import asyncify
        >>>
        >>> stream = to_async(asyncify, iter([1, 2]))
        >>> run(alist, stream)
        [1, 2]

    """
    pulled = aiter_sentinel(partial(func, _next_or_missing), stream, MissingType)
    return aauto_close(pulled, stream, inline=inline)


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
        return to_sync(require_async_stream(embed(item, **kwargs), embed.name))

    _copy_wrapper_meta(wrapper, embed, is_async=False)
    return require_sync_wrapper(wrapper)


def async_adapt_embed(
    embed: SyncModuleWrapper, run_sync: WorkerCall
) -> AsyncModuleWrapper:
    """
    Wraps a sync-only loop embed as an asynchronous one.

    The caller gets a callable with the asynchronous calling convention that
    carries the embed's discovery metadata, so the loop machinery treats it as a
    native async embed. The embed's per-item results are collected off the event
    loop, which the per-parent result count keeps bounded.

    Args:

        embed: The blocking pipe to run per parent item.
        run_sync: Runs a blocking callable off the event loop.

    Returns:

        An asynchronous embed whose per-item results are produced on a worker.

    """

    async def wrapper(item: Item | None = None, **kwargs: object) -> list[object]:
        return await run_sync(_materialize, embed, item, kwargs)

    _copy_wrapper_meta(wrapper, embed, is_async=True)
    return require_async_wrapper(wrapper)


def select_embed(
    embed: ResolvedModule,
    *,
    host_is_async: bool,
    run_sync: WorkerCall,
    to_sync: Drain[object],
) -> AnyModuleWrapper:
    """
    Chooses a loop embed's callable to match whether its host pipe runs sync or async.

    Args:

        embed: The resolved embed module, with its sync and async callables.

    Kwargs:

        host_is_async: Whether the loop pipe runs asynchronously.
        run_sync: Runs a sync-only embed off the event loop under an async host.
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
            result = async_adapt_embed(sync_pipe, run_sync)
        else:
            raise InvalidPipelineError(NO_PIPE_MSG.format(embed.name))
    elif (sync_pipe := embed.sync_pipe) is not None:
        result = sync_pipe
    elif (async_pipe := embed.async_pipe) is not None:
        result = adapt_embed(async_pipe, to_sync)
    else:
        raise InvalidPipelineError(NO_PIPE_MSG.format(embed.name))

    return result


__all__ = ["adapt_embed", "async_adapt_embed", "select_embed", "to_async", "to_sync"]
