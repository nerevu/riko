# vim: sw=4:ts=4:expandtab
"""
riko.bado.itertools
~~~~~~~~~~~~~~~~~~~~

Concurrency helpers for the async runtime.

These map an async function over an iterable, merge async feeds, adapt sync
iterables for async consumers, and reduce cooperatively. They are importable
without the ``async`` extra but only run under an async runtime.

The mapping helpers differ in how they trade result ordering against memory:

- ``async_map``: bounded-concurrency map, results in source order; collects
  every result before returning.
- ``async_map_stream``: streaming map, results in completion order.
- ``async_map_ordered_stream``: streaming map, results in source order.
- ``async_merge``: interleaves many async feeds into one stream, records in
  arrival order.

The streaming variants bound in-flight memory, so they suit large or unbounded
sources; ``async_map`` is eager. ``async_iter`` wraps a sync iterable as an
async generator, and ``coop_reduce``/``async_reduce`` reduce with cooperative
checkpoints.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable, Awaitable, Callable, Iterable
from functools import partial
from inspect import isawaitable
from typing import cast, overload

from riko._constants import DEF_CONNECTION_COUNT
from riko.bado._backend import (
    CapacityLimiter,
    MemoryObjectSendStream,
    Semaphore,
    async_sleep,
    checkpoint,
    create_memory_object_stream,
    create_task_group,
)
from riko.types._sentinels import MISSING


def _cap[T, S](
    func: Callable[[T], Awaitable[S]], budget: Semaphore | None
) -> Callable[[T], Awaitable[S]]:
    """
    Caps *func*'s concurrency against a shared *budget* semaphore.

    Sharing one budget across the leaf ``async_map*`` calls bounds their
    combined in-flight connections. Nested fan-out (a collection over
    sources of items) cannot multiply the connection count.

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


def as_async[T](source: AsyncIterable[T] | Iterable[T]) -> AsyncIterable[T]:
    """
    Adapts *source* to an ``AsyncIterable``.

    Args:
        source: A sync or async iterable.

    Returns:
        *source* unchanged when already async-iterable, else wrapped via
            :func:`async_iter`.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> stream = as_async([1, 2])
        >>>
        >>> async def main():
        ...     print([x async for x in stream])
        >>>
        >>> [1, 2] if issync else run(main)
        [1, 2]

    """
    return source if isinstance(source, AsyncIterable) else async_iter(source)


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
        >>> from riko import issync, run
        >>>
        >>> async def main():
        ...     print([x async for x in async_iter(range(3))])
        >>>
        >>> [0, 1, 2] if issync else run(main)
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
            is consumed as the seed (``None`` if *content* is empty).

    Returns:
        The final accumulated value.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def main():
        ...     print(await coop_reduce(lambda x, y: x + y, range(5)))
        >>>
        >>> 10 if issync else run(main)
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
            element as the seed.

    Returns:
        The final accumulated value.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def main():
        ...     print(await async_reduce(lambda x, y: x + y, range(5)))
        >>>
        >>> 10 if issync else run(main)
        10

    """
    content = iter(content)
    value = next(content) if initial is None else initial

    async def work(async_func, content, value):
        for item in content:
            result = async_func(value, item)
            value = (await result) if isawaitable(result) else result

        return value

    return work(func, content, value)


async def async_map[T, S](
    func: Callable[[T], Awaitable[S]],
    content: Iterable[T],
    connections: int = 0,
    *,
    budget: Semaphore | None = None,
    **kwargs: object,
) -> list[S]:
    """
    Maps *func* over *content* concurrently.

    Args:
        func: An async function applied to each element.

        content: The items to map over.

        connections: Maximum number of concurrent calls. ``0`` (default) runs them all
            at once.

        **kwargs: Extra keyword arguments forwarded to *func*.

    Returns:
        The results, in iteration order.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def main():
        ...     print(await async_map(double, range(3)))
        >>>
        >>> [0, 2, 4] if issync else run(main)
        [0, 2, 4]

    """
    if connections < 0:
        raise ValueError("connections cannot be negative")

    _func = _cap(partial(func, **kwargs) if kwargs else func, budget)
    items = list(content)
    results: list[S | object] = [MISSING] * len(items)
    limiter = CapacityLimiter(connections) if connections else None

    async def work(index: int, item: T) -> None:
        if limiter is None:
            results[index] = await _func(item)
        else:
            async with limiter:
                results[index] = await _func(item)

    async with create_task_group() as tg:
        for index, item in enumerate(items):
            tg.start_soon(work, index, item)

    return [cast(S, r) for r in results if r is not MISSING]


async def _pool_stream[T, S](
    source: AsyncIterable[T] | Iterable[T],
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
    feed (``async_merge``).

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
        async with item_send:
            async for item in as_async(source):
                await item_send.send(item)

    async def worker(results, items) -> None:
        async with results, items:
            async for item in items:
                await drain(item, results)

    async with create_task_group() as tg:
        tg.start_soon(feed)

        for _ in range(limit):
            tg.start_soon(worker, result_send.clone(), item_recv.clone())

        result_send.close()
        item_recv.close()

        async with result_recv:
            async for result in result_recv:
                yield result


async def async_map_stream[T, S](
    func: Callable[[T], Awaitable[S]],
    source: AsyncIterable[T] | Iterable[T],
    *,
    limit: int = DEF_CONNECTION_COUNT,
    buffer: int = 0,
    budget: Semaphore | None = None,
) -> AsyncGenerator[S, None]:
    """
    Maps *func* over *source* concurrently as a bounded stream.

    *limit* and *buffer* bound in-flight memory, so this suits large or
    unbounded sources. For source order use :func:`async_map_ordered_stream`.

    Args:
        func: An async function applied to each source item.
        source: The items to map over.
        limit: Maximum number of concurrent calls (default: ``DEF_CONNECTION_COUNT``).
        buffer: Size of the completed-results queue (default: 0).
        budget: Optional shared concurrency budget (default: None).

    Yields:
        Each ``func(item)`` result, in completion order.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def main():
        ...     stream = async_map_stream(double, range(4), limit=2)
        ...     print(sorted([result async for result in stream]))
        >>>
        >>> [0, 2, 4, 6] if issync else run(main)
        [0, 2, 4, 6]

    """
    func = _cap(func, budget)

    async def drain(item: T, results: MemoryObjectSendStream[S]) -> None:
        await results.send(await func(item))

    async for result in _pool_stream(source, drain, limit=limit, buffer=buffer):
        yield result


async def async_map_ordered_stream[T, S](
    func: Callable[[T], Awaitable[S]],
    source: AsyncIterable[T] | Iterable[T],
    *,
    limit: int = 16,
    buffer: int = 0,
    budget: Semaphore | None = None,
) -> AsyncGenerator[S, None]:
    """
    Maps *func* over *source* concurrently in bounded windows.

    Like :func:`async_map_stream`, but order-preserving. The source is mapped in
    bounded windows, so in-flight memory stays within ``limit + buffer`` items.

    Args:
        func: An async function applied to each source item.
        source: The items to map over.
        limit: Maximum number of concurrent calls (default: 16).
        buffer: Extra items per window beyond *limit* (default: 0).
        budget: Optional shared concurrency budget (default: None).

    Yields:
        Each ``func(item)`` result, in *source* order.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def main():
        ...     stream = async_map_ordered_stream(double, range(4), limit=2)
        ...     print([result async for result in stream])
        >>>
        >>> [0, 2, 4, 6] if issync else run(main)
        [0, 2, 4, 6]

    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    elif buffer < 0:
        raise ValueError("buffer cannot be negative")

    window = max(limit + buffer, 1)
    batch: list[T] = []

    async for item in as_async(source):
        batch.append(item)

        if len(batch) >= window:
            for result in await async_map(func, batch, limit, budget=budget):
                yield result

            batch = []

    for result in await async_map(func, batch, limit, budget=budget):
        yield result


async def async_merge[S](
    feeds: AsyncIterable[AsyncIterable[S]] | Iterable[AsyncIterable[S]],
    *,
    limit: int = DEF_CONNECTION_COUNT,
    buffer: int = 0,
) -> AsyncGenerator[S, None]:
    """
    Merges many async feeds into one interleaved stream.

    Like :func:`async_map_stream`, but each source item is a *feed*. Records
    interleave across feeds as they are produced, rather than one feed at a
    time. *limit* and *buffer* bound in-flight memory.

    Args:
        feeds: The async feeds to merge.

        limit: Maximum number of feeds drained concurrently (default:
            ``DEF_CONNECTION_COUNT``).

        buffer: Size of the merged-records queue (default: 0).

    Yields:
        Each record from every feed, in arrival order.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def feed(*items):
        ...     for item in items:
        ...         yield item
        >>>
        >>> async def main():
        ...     merged = async_merge([feed(1, 2), feed(3, 4)], limit=2)
        ...     print(sorted([record async for record in merged]))
        >>>
        >>> [1, 2, 3, 4] if issync else run(main)
        [1, 2, 3, 4]

    """

    async def drain(feed: AsyncIterable[S], results: MemoryObjectSendStream[S]) -> None:
        items = aiter(feed)

        try:
            async for item in items:
                await results.send(item)
        finally:
            if (aclose := getattr(items, "aclose", None)) is not None:
                await aclose()

    async for item in _pool_stream(feeds, drain, limit=limit, buffer=buffer):
        yield item
