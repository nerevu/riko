# vim: sw=4:ts=4:expandtab
"""
Adapts streams and callables across the synchronous/asynchronous boundary.

Both the sync and the async execution share these helpers to enforce the item
stream contract at a node boundary and to re-expose one side's stream to the
other without materializing it. They are private to the runtime and belong to
no supported surface.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Iterator
from itertools import chain
from typing import TYPE_CHECKING, Any, cast

from riko.bado._backend import async_chain
from riko.bado.itertools import as_async
from riko.base.exceptions import InvalidPipelineError
from riko.types._sentinels import MISSING

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Awaitable, Callable

    from riko.types._streams import (
        AsyncItems,
        AsyncStream,
        AsyncStreams,
        Item,
        Items,
        Stream,
        Streams,
    )
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper

type LoopCall = Callable[[Callable[[], Any]], Any]
type WorkerCall = Callable[..., Awaitable[Any]]
type Drain = Callable[[AsyncItems | AsyncStreams], Stream]

_WRAPPER_META = ("name", "type", "subtype", "subtypes", "pollable", "loopable")
_FUNC_META = ("__name__", "__qualname__", "__doc__")


def require_items(value: Items | Streams | Iterable[Item | Items]) -> Stream:
    """
    Re-chains ``value`` as an item stream, rejecting a stream of streams.

    Args:

        value: The raw output of a pipe, which must yield items.

    Returns:

        An item stream equivalent to ``value``, including its first item.

    Raises:

        InvalidPipelineError: If the first value produced is itself a stream.

    """
    stream = iter(value)

    try:
        first = next(stream)
    except StopIteration:
        result = iter(())
    else:
        if isinstance(first, Iterator):
            raise InvalidPipelineError("Splitter nodes not yet implemented")

        result = cast("Stream", chain((first,), stream))

    return result


async def arequire_items(value: AsyncIterable[Item | Items]) -> AsyncStream:
    """
    Re-chains ``value`` as an async item stream, rejecting a stream of streams.

    Args:

        value: The raw output of an async pipe, which must yield items.

    Returns:

        An async item stream equivalent to ``value``, including its first item.

    Raises:

        InvalidPipelineError: If the first value produced is itself a stream.

    """
    stream = aiter(value)

    try:
        first = await anext(stream)
    except StopAsyncIteration:
        result = as_async(iter(()))
    else:
        if isinstance(first, Iterator):
            raise InvalidPipelineError("Splitter nodes not yet implemented")

        result = cast("AsyncStream", async_chain((first,), stream))

    return result


def _close_generator(value: object) -> None:
    """Closes ``value`` when it is a generator, releasing anything it holds."""
    if isinstance(value, Generator):
        value.close()


def drain_async(source: AsyncItems | AsyncStreams, call: LoopCall) -> Stream:
    """
    Re-exposes an async stream as a lazy synchronous item stream.

    Args:

        source: The async stream to read.
        call: Runs an awaitable-returning callable to completion on the event
            loop from the calling thread.

    Yields:

        Each item ``source`` produces, in order.

    Raises:

        InvalidPipelineError: If an item produced is itself a stream.

    """
    iterator = aiter(source)

    while True:
        try:
            item = call(iterator.__anext__)
        except StopAsyncIteration:
            break
        else:
            yield next(require_items([item]))


async def pull_stream(
    iterator: Stream, closeable: object, pull: WorkerCall, close: WorkerCall
) -> AsyncStream:
    """
    Re-exposes a blocking item stream as a lazy async item stream.

    Args:

        iterator: The synchronous item stream to read.
        closeable: The pipe output whose closure releases what the stream holds.
        pull: Runs a blocking callable off the event loop.
        close: Runs the final closure off the event loop, including while the
            execution is shutting down.

    Yields:

        Each item ``iterator`` produces, in order.

    """
    try:
        while (item := await pull(next, iterator, MISSING)) is not MISSING:
            yield item
    finally:
        await close(_close_generator, closeable)


def _copy_wrapper_meta(
    target: Callable[..., object], source: object, *, isasync: bool
) -> None:
    """
    Stamps ``source``'s discovery metadata onto ``target`` in the given mode.

    Attributes ``source`` does not carry are skipped, and ``__wrapped__`` is left
    unset so an ``unwrap``-based guard cannot see past the adapter to a callable
    of the other mode.

    Args:

        target: The adapter function to annotate.
        source: The wrapped pipe whose metadata is copied.
        isasync: Whether the adapter presents the asynchronous interface.

    """
    for attr in chain(_WRAPPER_META, _FUNC_META):
        if hasattr(source, attr):
            setattr(target, attr, getattr(source, attr))

    setattr(target, "isasync", isasync)  # noqa: B010


def _materialize(
    embed: SyncModuleWrapper, item: Item | None, kwargs: dict[str, object]
) -> list[Item]:
    """Runs a blocking embed for one parent item and collects everything it yields."""
    return cast("list[Item]", list(embed(item, **kwargs)))


def adapt_embed_for_sync(embed: AsyncModuleWrapper, drain: Drain) -> SyncModuleWrapper:
    """
    Wraps an async-only loop embed as a synchronous one.

    The caller gets a callable with the synchronous calling convention that
    carries the embed's discovery metadata, so the loop machinery treats it as a
    native sync embed.

    Args:

        embed: The asynchronous pipe to run per parent item.
        drain: Consumes an async stream from the thread the loop pipe runs on.

    Returns:

        A synchronous embed whose per-item stream is drained through ``drain``.

    """

    def wrapper(item: Item | None = None, **kwargs: object) -> Stream:
        return drain(cast("AsyncItems", embed(item, **kwargs)))

    _copy_wrapper_meta(wrapper, embed, isasync=False)
    return cast("SyncModuleWrapper", wrapper)


def adapt_embed_for_async(
    embed: SyncModuleWrapper, run_sync: WorkerCall
) -> AsyncModuleWrapper:
    """
    Wraps a sync-only loop embed as an asynchronous one.

    The caller gets a callable with the asynchronous calling convention that
    carries the embed's discovery metadata, so the loop machinery treats it as a
    native async embed. Each parent item's results are collected off the event
    loop, which the per-parent result count keeps bounded.

    Args:

        embed: The blocking pipe to run per parent item.
        run_sync: Runs a blocking callable off the event loop.

    Returns:

        An asynchronous embed whose per-item results are produced on a worker.

    """

    async def wrapper(item: Item | None = None, **kwargs: object) -> Items:
        return cast("Items", await run_sync(_materialize, embed, item, kwargs))

    _copy_wrapper_meta(wrapper, embed, isasync=True)
    return cast("AsyncModuleWrapper", wrapper)


__all__ = [
    "adapt_embed_for_async",
    "adapt_embed_for_sync",
    "arequire_items",
    "drain_async",
    "pull_stream",
    "require_items",
]
