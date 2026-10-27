# vim: sw=4:ts=4:expandtab
"""
Adapts streams and callables across the synchronous/asynchronous boundary.

Both the sync and the async execution share these helpers to type a pipe callable's raw
return value as the item stream the execution plan guarantees it to be and to
re-expose one side's stream to the other without materializing it. They are
private to the runtime and belong to no supported surface.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Generator, Iterable, Iterator
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Protocol, cast

from riko.bado._util import maybe_aclosing
from riko.base._guards import is_listlike
from riko.base._sentinels import MISSING, MissingType
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.types._wrappers import (
    require_async_wrapper,
    require_single_output,
    require_sync_wrapper,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from riko.types._streams import Item, Items
    from riko.types._wrappers import (
        AnyModuleWrapper,
        AsyncModuleWrapper,
        AsyncModuleWrapperOutput,
        ModuleWrapper,
        SyncModuleWrapper,
    )

    from ._prepared import ResolvedModule


class LoopCall(Protocol):
    """Runs an awaitable-returning callable to completion from a worker thread."""

    def __call__[R](self, func: Callable[[], Awaitable[R]], /) -> R: ...


class WorkerCall(Protocol):
    """Runs a blocking callable off the event loop and awaits its result."""

    def __call__[R, *Ts](
        self, func: Callable[[*Ts], R], /, *args: *Ts
    ) -> Awaitable[R]: ...


type Drain[T] = Callable[[AsyncIterable[T]], Iterator[T]]

_FUNC_META = ("__name__", "__qualname__", "__doc__")


def require_stream[T](
    value: Iterator[T] | Iterator[Iterator[T]], pipe: ModuleWrapper
) -> Iterator[T]:
    """
    Narrows a synchronous pipe's raw return value to its item stream.

    A pipe's call signature admits a stream of streams, so the narrowing is
    earned by checking the pipe's declared module type rather than by reading
    what it yields; nothing is consumed here.

    Args:

        value: The raw return value of ``pipe``.
        pipe: The wrapper that produced ``value``.

    Returns:

        ``value`` as a lazy item stream.

    Raises:

        InvalidPipelineError: If ``pipe`` is a multi-output splitter.

    """
    require_single_output(pipe)
    return cast("Iterator[T]", iter(value))


def require_async_stream[T](
    value: AsyncModuleWrapperOutput[T], pipe: ModuleWrapper
) -> AsyncIterator[T]:
    """
    Narrows an asynchronous pipe's raw return value to its async item stream.

    The async counterpart of ``require_stream``: the pipe's declared module type
    earns the narrowing, and nothing is consumed here.

    Args:

        value: The raw return value of ``pipe``.
        pipe: The wrapper that produced ``value``.

    Returns:

        ``value`` as a lazy async item stream.

    Raises:

        InvalidPipelineError: If ``pipe`` is a multi-output splitter.

    """
    require_single_output(pipe)
    return cast("AsyncIterator[T]", aiter(value))


# TODO: isnt this just listize?
def normalize_items[T](value: T | Iterable[T]) -> Iterable[T]:
    """
    Normalizes a synchronous seed to the item stream it denotes.

    A mapping or primitive is one item; any other iterable already is the stream.
    Async and awaitable seeds are resolved by the execution that owns the loop.

    Args:

        value: One item or an item stream.

    Returns:

        The item stream ``value`` denotes.

    Examples:

        >>> normalize_items({"x": 1})
        [{'x': 1}]
        >>> normalize_items([{"x": 1}, {"x": 2}])
        [{'x': 1}, {'x': 2}]

    """
    return value if is_listlike(value) else [cast("T", value)]


def _close_generator(value: object) -> None:
    """Closes ``value`` when it is a generator, releasing anything it holds."""
    if isinstance(value, Generator):
        value.close()


def async_drain[T](source: AsyncIterable[T], call: LoopCall) -> Iterator[T]:
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


def _next_or_missing[T](iterator: Iterator[T]) -> T | MissingType:
    """Gets the next item from ``iterator``, or ``MISSING`` once it is exhausted."""
    return next(iterator, MISSING)


async def pull_stream[T](
    closeable: object,
    iterator: Iterator[T],
    *upstreams: AsyncIterator[object],
    pull: WorkerCall,
    close: WorkerCall,
) -> AsyncIterator[T]:
    """
    Re-exposes a blocking item stream as a lazy async item stream.

    Args:

        closeable: The pipe's return value whose closure releases what the stream holds.

        iterator: The synchronous item stream to read.

        upstreams: The async streams ``iterator`` reads. Closed once ``closeable`` is
            closed (even when closing it fails).

        pull: Runs a blocking callable off the event loop.

        close: Runs the final closure off the event loop (even while the execution is
            shutting down).

    Yields:

        Each item ``iterator`` produces, in order.

    """
    async with AsyncExitStack() as stack:
        for upstream in upstreams:
            await stack.enter_async_context(maybe_aclosing(upstream))

        try:
            while not isinstance(
                item := await pull(_next_or_missing, iterator), MissingType
            ):
                yield item
        finally:
            await close(_close_generator, closeable)


def _copy_wrapper_meta(
    target: Callable[..., object], source: ModuleWrapper, *, isasync: bool
) -> None:
    """
    Stamps ``source``'s discovery metadata onto ``target`` as sync or async.

    ``target`` also takes whichever of ``source``'s name, qualified name, and
    docstring it carries. ``__wrapped__`` is left unset so an ``unwrap``-based guard
    cannot see past the adapter to a callable of the other kind (sync or async).

    Args:

        target: The adapter function to annotate.
        source: The wrapped pipe whose metadata is copied.
        isasync: Whether the adapter presents the asynchronous interface.

    """
    stamp_wrapper_meta(
        target,
        name=source.name,
        module_type=source.type,
        subtype=source.subtype,
        subtypes=source.subtypes,
        pollable=source.pollable,
        loopable=source.loopable,
        isasync=isasync,
        sequential_inputs=source.sequential_inputs,
    )

    for attr in _FUNC_META:
        if hasattr(source, attr):
            setattr(target, attr, getattr(source, attr))


def _materialize(
    embed: SyncModuleWrapper, item: Item | None, kwargs: dict[str, object]
) -> list[Item]:
    """Runs a blocking embed for one parent item and collects everything it yields."""
    return list(require_stream(embed(item, **kwargs), embed))


def adapt_embed[T](embed: AsyncModuleWrapper, drain: Drain[T]) -> SyncModuleWrapper:
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

    def wrapper(item: T | None = None, **kwargs: object) -> Iterator[T]:
        output = cast("AsyncModuleWrapperOutput[T]", embed(item, **kwargs))
        stream = require_async_stream(output, embed)
        return drain(stream)

    _copy_wrapper_meta(wrapper, embed, isasync=False)
    return require_sync_wrapper(wrapper)


def async_adapt_embed(
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
    return require_async_wrapper(wrapper)


def select_embed[T](
    embed: ResolvedModule, *, host_isasync: bool, run_sync: WorkerCall, drain: Drain[T]
) -> AnyModuleWrapper:
    """
    Chooses a loop embed's callable to match whether its host pipe runs sync or async.

    Args:

        embed: The embed module resolved alongside the loop node.
        host_isasync: Whether the loop pipe runs asynchronously.
        run_sync: Runs a sync-only embed off the event loop under an async host.
        drain: Pulls an async-only embed's output stream under a sync host.

    Returns:

        The embed's native callable for the host (sync or async), or a wrapper
        adapting its callable from the sync or async counterpart.

    """
    if host_isasync:
        pipe = embed.select_async()

        if embed.is_async_pipe(pipe):
            result = pipe
        else:
            result = async_adapt_embed(pipe, run_sync)
    else:
        sync_pipe = embed.select_sync()

        if embed.is_async_pipe(sync_pipe):
            result = adapt_embed(sync_pipe, drain)
        else:
            result = sync_pipe

    return result


__all__ = [
    "adapt_embed",
    "async_adapt_embed",
    "async_drain",
    "normalize_items",
    "pull_stream",
    "require_async_stream",
    "require_stream",
    "select_embed",
]
