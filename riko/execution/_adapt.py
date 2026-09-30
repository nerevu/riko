# vim: sw=4:ts=4:expandtab
"""
Adapts streams and callables across the synchronous/asynchronous boundary.

Both the sync and the async execution share these helpers to type a node's raw
output as the item stream the execution plan guarantees it to be and to
re-expose one side's stream to the other without materializing it. They are
private to the runtime and belong to no supported surface.
"""

from __future__ import annotations

from collections.abc import Generator
from itertools import chain
from typing import TYPE_CHECKING, Any, cast

from riko.types._guards import require_single_output
from riko.types._sentinels import MISSING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from riko.types._streams import AsyncItems, AsyncStream, Item, Items, Stream
    from riko.types._wrappers import (
        AsyncModuleWrapper,
        AsyncSplitterWrapperOutput,
        AsyncWrapperOutput,
        ModuleWrapper,
        SyncModuleWrapper,
        SyncSplitterWrapperOutput,
        SyncWrapperOutput,
    )

type LoopCall = Callable[[Callable[[], Any]], Any]
type WorkerCall = Callable[..., Awaitable[Any]]
type Drain = Callable[[AsyncItems], Stream]

_WRAPPER_META = ("name", "type", "subtype", "subtypes", "pollable", "loopable")
_FUNC_META = ("__name__", "__qualname__", "__doc__")


def require_stream(
    value: SyncWrapperOutput | SyncSplitterWrapperOutput, pipe: ModuleWrapper
) -> Stream:
    """
    Narrows a synchronous pipe's raw output to the item stream it produces.

    A pipe's call signature admits a stream of streams, so the narrowing is
    earned by checking the pipe's declared module type rather than by reading
    what it yields; nothing is consumed here.

    Args:

        value: The raw output of ``pipe``.
        pipe: The wrapper that produced ``value``.

    Returns:

        ``value`` as a lazy item stream.

    Raises:

        InvalidPipelineError: If ``pipe`` is a multi-output splitter.

    """
    require_single_output(pipe)
    return cast("Stream", iter(value))


def require_async_stream(
    value: AsyncWrapperOutput | AsyncSplitterWrapperOutput, pipe: ModuleWrapper
) -> AsyncStream:
    """
    Narrows an asynchronous pipe's raw output to the async item stream it produces.

    The async counterpart of ``require_stream``: the pipe's declared module type
    earns the narrowing, and nothing is consumed here.

    Args:

        value: The raw output of ``pipe``.
        pipe: The wrapper that produced ``value``.

    Returns:

        ``value`` as a lazy async item stream.

    Raises:

        InvalidPipelineError: If ``pipe`` is a multi-output splitter.

    """
    require_single_output(pipe)
    return cast("AsyncStream", aiter(value))


def _close_generator(value: object) -> None:
    """Closes ``value`` when it is a generator, releasing anything it holds."""
    if isinstance(value, Generator):
        value.close()


def drain_async(source: AsyncItems, call: LoopCall) -> Stream:
    """
    Re-exposes an async stream as a lazy synchronous item stream.

    Args:

        source: The async stream to read.
        call: Runs an awaitable-returning callable to completion on the event
            loop from the calling thread.

    Yields:

        Each item ``source`` produces, in order.

    """
    iterator = aiter(source)

    while True:
        try:
            item = call(iterator.__anext__)
        except StopAsyncIteration:
            break
        else:
            yield item


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
    return list(require_stream(embed(item, **kwargs), embed))


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
        return drain(require_async_stream(embed(item, **kwargs), embed))

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
        materialized: list[Item] = await run_sync(_materialize, embed, item, kwargs)
        return materialized

    _copy_wrapper_meta(wrapper, embed, isasync=True)
    return cast("AsyncModuleWrapper", wrapper)


__all__ = [
    "adapt_embed_for_async",
    "adapt_embed_for_sync",
    "drain_async",
    "pull_stream",
    "require_async_stream",
    "require_stream",
]
