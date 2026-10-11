# vim: sw=4:ts=4:expandtab
"""
Concurrent mapping, merging, and reduction helpers for async code.

``async_map`` preserves source order after concurrent execution, while streaming
helpers yield incrementally for large or unbounded inputs.

Examples:

    Basic usage::

        >>> from riko import async_map, run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def main():
        ...     print(await async_map(double, range(3)))
        >>>
        >>> run(main)
        [0, 2, 4]

"""

from __future__ import annotations

from collections.abc import AsyncIterable
from contextlib import aclosing
from functools import partial
from typing import TYPE_CHECKING, cast, overload

from riko.base._constants import DEF_CONCURRENCY_LIMIT
from riko.types._sentinels import MISSING

from ._backend import (
    CapacityLimiter,
    MemoryObjectSendStream,
    Semaphore,
    async_sleep,
    checkpoint,
    create_memory_object_stream,
    create_task_group,
)
from ._util import maybe_aclosing, maybe_async

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Callable,
        Iterable,
    )

    from riko.types._streams import AnyIterable


def _cap[T, S](
    func: Callable[[T], Awaitable[S]], budget: Semaphore | None
) -> Callable[[T], Awaitable[S]]:
    """
    Caps *func*'s concurrency against a shared *budget* semaphore.

    Sharing one budget across the leaf ``async_map*`` calls bounds their
    combined in-flight calls. Nested fan-out (a collection over
    several item streams) cannot multiply the call count.

    Budget the leaf I/O only, never an outer coordinating call: a call holding
    a slot while its own children wait for slots is a classic deadlock. So the
    outer fan-out stays unbudgeted and only the leaves draw from the budget.

    Returns:

        *func* wrapped to acquire *budget* per call, or *func* unchanged when
        *budget* is ``None``.

    """
    wrapped: Callable[[T], Awaitable[S]]

    if budget is None:
        wrapped = func
    else:

        async def _wrapped(item: T) -> S:
            async with budget:
                return await func(item)

        wrapped = _wrapped

    return wrapped


def as_async[T](source: AnyIterable[T], cooperative: bool = False) -> AsyncIterator[T]:
    """
    Adapts *source* to an ``AsyncIterator``.

    Args:

        source: A sync or async iterable.

        cooperative: For a sync *source*, yield control before each item so
            concurrent tasks (e.g. a timeout) can run (default: False).

    Returns:

        The async iterator of an already-async *source*, else *source* wrapped
            via :func:`async_iter`.

    Examples:

        >>> from riko import run
        >>>
        >>> stream = as_async([1, 2])
        >>>
        >>> async def main():
        ...     print([x async for x in stream])
        >>>
        >>> run(main)
        [1, 2]

    """
    if isinstance(source, AsyncIterable):
        result = aiter(source)
    else:
        result = async_iter(source, cooperative=cooperative)

    return result


async def async_iter[T](
    elements: Iterable[T], cooperative: bool = False
) -> AsyncGenerator[T, None]:
    """
    Converts a sync iterable into an async generator.

    Args:

        elements: The sync iterable to wrap.

        cooperative: Yield control (``async_sleep(0)``) before each item
            so concurrent tasks (e.g. a timeout) can run (default: False).

    Yields:

        Each element from *elements* in order.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     print([x async for x in async_iter(range(3))])
        >>>
        >>> run(main)
        [0, 1, 2]

    """
    for item in elements:
        if cooperative:
            await async_sleep(0)

        yield item


@overload
async def coop_reduce[T, S](  # noqa: E704
    func: Callable[[T, S], T], content: Iterable[S], initial: T
) -> T: ...
@overload  # noqa: E302
async def coop_reduce[T, S](  # noqa: E704
    func: Callable[[T | S | None, S], T], content: Iterable[S], initial: None = ...
) -> T | S | None: ...
async def coop_reduce[T, S](  # noqa: E302 # pyright: ignore[reportInconsistentOverload]
    func: Callable[[T | S | None, S], T], content: Iterable[S], initial: T | None = None
) -> T | S | None:
    """
    Reduces *content* with *func* while yielding control between steps.

    Args:

        func: A two-argument reducer, e.g. ``lambda x, y: x + y``.

        content: The sequence to reduce.

        initial: Starting accumulator value. When ``None`` (default) the first element
            is consumed as the starting value (``None`` if *content* is empty).

    Returns:

        The final accumulated value.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     print(await coop_reduce(lambda x, y: x + y, range(5)))
        >>>
        >>> run(main)
        10

    """
    items = iter(content)
    value: T | S | None = next(items, None) if initial is None else initial

    for item in items:
        value = func(value, item)
        await checkpoint()

    return value


def async_reduce[T, S](
    func: Callable[[T, S], T | Awaitable[T]],
    content: Iterable[S],
    initial: T | None = None,
) -> Awaitable[T]:
    """
    Reduces *content* with *func*.

    The reducer is awaited only when it returns an awaitable.

    Args:

        func: A two-argument reducer.

        content: The sequence to reduce.

        initial: Starting accumulator value. When ``None`` (default) consumes the first
            element as the starting value.

    Returns:

        The final accumulated value.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     print(await async_reduce(lambda x, y: x + y, range(5)))
        >>>
        >>> run(main)
        10

    """
    content = iter(content)
    value = next(content) if initial is None else initial

    async def work(async_func, content, value):
        for item in content:
            value = await maybe_async(async_func, value, item)

        return value

    return work(func, content, value)


async def async_map[T, S](
    func: Callable[[T], Awaitable[S]],
    content: Iterable[T],
    limit: int = 0,
    *,
    budget: Semaphore | None = None,
    **kwargs: object,
) -> list[S]:
    """
    Maps *func* over *content* concurrently.

    Args:

        func: An async function applied to each element.

        content: The items to map over.

        limit: Maximum number of concurrent calls. ``0`` (the default) runs them all
            at once.

        budget: A semaphore shared across maps that caps how many calls run at
            once in total. A permit is held only while *func* runs (default: None).

        **kwargs: Extra keyword arguments forwarded to *func*.

    Returns:

        The results, in iteration order.

    Examples:

        >>> from riko import run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def main():
        ...     print(await async_map(double, range(3)))
        >>>
        >>> run(main)
        [0, 2, 4]

    """
    if limit < 0:
        raise ValueError("limit cannot be negative")

    _func = _cap(partial(func, **kwargs) if kwargs else func, budget)
    items = list(content)
    results: list[S | object] = [MISSING] * len(items)
    limiter = CapacityLimiter(limit) if limit else None

    async def work(index: int, item: T) -> None:
        if limiter is None:
            results[index] = await _func(item)
        else:
            async with limiter:
                results[index] = await _func(item)

    async with create_task_group() as tg:
        for index, item in enumerate(items):
            tg.start_soon(work, index, item)

    return [cast("S", r) for r in results if r is not MISSING]


async def _pool_stream[T, S](
    source: AnyIterable[T],
    drain: Callable[[T, MemoryObjectSendStream[S]], Awaitable[None]],
    *,
    limit: int,
    buffer: int,
) -> AsyncGenerator[S, None]:
    """
    Runs *source* through a fixed pool of *limit* workers.

    Backs :func:`async_map_stream` and :func:`async_merge`. A single feeder task
    pushes each *source* item into an unbuffered input stream, and the workers pull
    from it. They *drain* per item with a *buffer*-sized output stream. *drain* sends
    zero or more results per item: one for a map (``async_map_stream``), many for a
    merge (``async_merge``).

    Because the input stream is unbuffered, the source advances only as workers free up.
    This bounds in-flight memory to ``limit`` open items plus ``buffer`` queued results.

    Args:

        source: Items to hand to the worker pool.

        drain: ``async (item, out) -> None`` — does the per-item work
            and ``await out.send(...)`` for each result to emit.

        limit: Number of concurrent workers (must be >= 1).

        buffer: Size of the completed-results queue (must be >= 0).

    Yields:

        Each result *drain* sends, in arrival order.

    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    elif buffer < 0:
        raise ValueError("buffer cannot be negative")

    item_send, item_recv = create_memory_object_stream[T](max_buffer_size=0)
    result_send, result_recv = create_memory_object_stream[S](max_buffer_size=buffer)

    async def feed() -> None:
        async with maybe_aclosing(as_async(source)) as items, item_send:
            async for item in items:
                await item_send.send(item)

    async def worker(results, items) -> None:
        async with results, items:
            async for item in items:
                await drain(item, results)

    try:
        async with create_task_group() as tg:
            tg.start_soon(feed)

            for _ in range(limit):
                tg.start_soon(worker, result_send.clone(), item_recv.clone())

            result_send.close()
            item_recv.close()

            async with result_recv:
                try:
                    async for result in result_recv:
                        yield result
                except GeneratorExit:
                    tg.cancel_scope.cancel()
                    raise
    except BaseExceptionGroup as group:
        single = len(group.exceptions) == 1
        closed = single and isinstance(group.exceptions[0], GeneratorExit)

        if not closed:
            raise

        raise GeneratorExit from None


async def async_map_stream[T, S](
    func: Callable[[T], Awaitable[S]],
    source: AnyIterable[T],
    *,
    limit: int = DEF_CONCURRENCY_LIMIT,
    buffer: int = 0,
    budget: Semaphore | None = None,
) -> AsyncGenerator[S, None]:
    """
    Maps *func* over *source* concurrently as a bounded stream.

    *limit* and *buffer* bound in-flight memory, so this suits large or
    unbounded sources. For source order use :func:`async_map_ordered_stream`.

    Args:

        func: An async function applied to each input item.

        source: The items to map over.

        limit: Maximum number of concurrent calls (default: ``DEF_CONCURRENCY_LIMIT``).

        buffer: Size of the completed-results queue (default: 0).

        budget: A semaphore shared across maps that caps how many calls run at
            once in total. A permit is held only while *func* runs (default: None).

    Yields:

        Each ``func(item)`` result, in completion order.

    Examples:

        >>> from riko import run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def main():
        ...     stream = async_map_stream(double, range(4), limit=2)
        ...     print(sorted([result async for result in stream]))
        >>>
        >>> run(main)
        [0, 2, 4, 6]

    """
    func = _cap(func, budget)

    async def drain(item: T, results: MemoryObjectSendStream[S]) -> None:
        await results.send(await func(item))

    stream = _pool_stream(source, drain, limit=limit, buffer=buffer)

    async with aclosing(stream) as results:
        async for result in results:
            yield result


async def async_map_ordered_stream[T, S](
    func: Callable[[T], Awaitable[S]],
    source: AnyIterable[T],
    *,
    limit: int = DEF_CONCURRENCY_LIMIT,
    buffer: int = 0,
    budget: Semaphore | None = None,
) -> AsyncGenerator[S, None]:
    """
    Maps *func* over *source* concurrently in bounded windows.

    Like :func:`async_map_stream`, but order-preserving. The source is mapped in
    bounded windows, so in-flight memory stays within ``limit + buffer`` items.

    Args:

        func: An async function applied to each input item.

        source: The items to map over.

        limit: Maximum number of concurrent calls (default: ``DEF_CONCURRENCY_LIMIT``).

        buffer: Extra items per window beyond *limit* (default: 0).

        budget: A semaphore shared across maps that caps how many calls run at
            once in total. A permit is held only while *func* runs (default: None).

    Yields:

        Each ``func(item)`` result, in *source* order.

    Examples:

        >>> from riko import run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def main():
        ...     stream = async_map_ordered_stream(double, range(4), limit=2)
        ...     print([result async for result in stream])
        >>>
        >>> run(main)
        [0, 2, 4, 6]

    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    elif buffer < 0:
        raise ValueError("buffer cannot be negative")

    window = max(limit + buffer, 1)
    batch: list[T] = []

    async with maybe_aclosing(as_async(source)) as items:
        async for item in items:
            batch.append(item)

            if len(batch) >= window:
                for result in await async_map(func, batch, limit, budget=budget):
                    yield result

                batch = []

        for result in await async_map(func, batch, limit, budget=budget):
            yield result


async def async_merge[S](
    iterables: AnyIterable[AsyncIterable[S]],
    *,
    limit: int = DEF_CONCURRENCY_LIMIT,
    buffer: int = 0,
) -> AsyncGenerator[S, None]:
    """
    Merges many async iterables of items into one interleaved stream.

    Like :func:`async_map_stream`, but each input item is itself an async
    iterable. Items interleave across iterables as they are produced, rather than
    one iterable at a time. *limit* and *buffer* bound in-flight memory.

    Args:

        iterables: The async iterables to merge.

        limit: Maximum number of iterables drained concurrently (default:
            ``DEF_CONCURRENCY_LIMIT``).

        buffer: Size of the merged-items queue (default: 0).

    Yields:

        Each item from every iterable, in arrival order.

    Examples:

        >>> from riko import run
        >>>
        >>> async def gen_items(*items):
        ...     for item in items:
        ...         yield item
        >>>
        >>> async def main():
        ...     merged = async_merge([gen_items(1, 2), gen_items(3, 4)], limit=2)
        ...     print(sorted([item async for item in merged]))
        >>>
        >>> run(main)
        [1, 2, 3, 4]

    """

    async def drain(
        iterable: AsyncIterable[S], results: MemoryObjectSendStream[S]
    ) -> None:
        async with maybe_aclosing(aiter(iterable)) as items:
            async for item in items:
                await results.send(item)

    async for item in _pool_stream(iterables, drain, limit=limit, buffer=buffer):
        yield item
