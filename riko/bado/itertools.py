# vim: sw=4:ts=4:expandtab
"""
riko.bado.itertools
~~~~~~~~~~~~~~~~~~~~
Async primitives for the async runtime.

``async_map`` maps an async function over an iterable with optional bounded
concurrency; ``coop_reduce``/``async_reduce`` reduce cooperatively; ``async_iter``
adapts a sync iterable into an async generator. Available when the ``async`` extra
is installed; the functions are importable regardless but only run under an async
runtime.

``async_map_stream`` and ``async_merge`` share one arrival-order engine
(``_pool_stream``): a fixed worker pool pulls from an unbuffered input stream (so
the source is only advanced as workers free up) and per-item output flows through
a bounded output stream. An unbounded source with a slow consumer therefore
suspends upstream instead of materializing everything — in-flight memory stays
within ``limit + buffer`` items. ``async_map_stream`` maps an async function over
each source item (one result per item); ``async_merge`` drains each source feed
(many records per feed), interleaving records across feeds as they arrive.
``async_map_ordered_stream`` is the in-order variant of ``async_map_stream`` (a
sliding window of per-item slots consumed in submission order) for the same bound.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable, Awaitable, Callable, Iterable
from functools import partial
from inspect import isawaitable
from typing import cast, overload

from riko import DEF_CONNECTION_COUNT
from riko.bado import (
    CapacityLimiter,
    MemoryObjectSendStream,
    Semaphore,
    async_sleep,
    checkpoint,
    create_memory_object_stream,
    create_task_group,
)


def _cap[T, S](
    func: Callable[[T], Awaitable[S]], budget: Semaphore | None
) -> Callable[[T], Awaitable[S]]:
    """
    Wrap *func* so each call acquires a shared *budget* semaphore, or return it
    unchanged when *budget* is ``None``. A single budget shared across the *leaf*
    ``async_map*`` calls caps their *combined* in-flight concurrency, so nested
    fan-out (e.g. a collection fanning out over sources whose items each fan out)
    cannot multiply the connection count.

    Apply the budget to the leaf work (the actual concurrent I/O), **not** to
    every level: a coordinating outer call that holds a budget slot while its
    children also need slots deadlocks (classic hold-and-wait). The outer fan-out
    stays unbudgeted; only the shared leaf operations draw from the budget.
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


def _as_async[T](source: AsyncIterable[T] | Iterable[T]) -> AsyncIterable[T]:
    return source if isinstance(source, AsyncIterable) else async_iter(source)


async def async_iter[T](
    elements: Iterable[T], cooperative: bool = False
) -> AsyncGenerator[T, None]:
    """
    Converts a sync iterable into an async generator.

    Useful when an async consumer requires an ``AsyncIterable`` but the source
    is a plain sync iterable.

    Args:
        elements (Iterable): The sync iterable to wrap.
        cooperative (bool): Yield control (``async_sleep(0)``) before each item
            so concurrent tasks (e.g. a timeout) can run (default: False).

    Yields:
        Any: Each element from *elements* in order.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def main():
        ...     print([x async for x in async_iter(range(3))])
        >>>
        >>> if issync:
        ...     [0, 1, 2]
        ... else:
        ...     run(main)
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
    Reduces *content* with *func*, yielding control between steps.

    Args:
        func (callable): A two-argument reducer, e.g. ``lambda x, y: x + y``.
        content (Iterable): The sequence to reduce.
        initial (Any): Starting accumulator value. When ``None`` (default) the
            first element is consumed as the seed (``None`` if *content* is empty).

    Returns:
        Any: The final accumulated value.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def main():
        ...     print(await coop_reduce(lambda x, y: x + y, range(5)))
        >>>
        >>> if issync:
        ...     10
        ... else:
        ...     run(main)
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
    Reduces *content* with *func*, which may be sync or async.

    Unlike :func:`coop_reduce`, the entire reduction runs in a single pass. The
    reducer is awaited only when it returns an awaitable.

    Args:
        func (callable): A two-argument reducer that may return a plain value or
            an awaitable.
        content (Iterable): The sequence to reduce.
        initial (Any): Starting accumulator value. When ``None`` (default) the
            first element is consumed as the seed.

    Returns:
        Awaitable[Any]: The final accumulated value.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def main():
        ...     print(await async_reduce(lambda x, y: x + y, range(5)))
        >>>
        >>> if issync:
        ...     10
        ... else:
        ...     run(main)
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
    Maps *func* over *content* concurrently, returning results in order.

    Args:
        func (callable): An async function applied to each element.
        content (Iterable): The items to map over.
        connections (int): Maximum number of concurrent calls. ``0`` (default)
            runs them all at once.
        **kwargs: Extra keyword arguments forwarded to *func*.

    Returns:
        list: Results in iteration order.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def main():
        ...     print(await async_map(double, range(3)))
        >>>
        >>> if issync:
        ...     [0, 2, 4]
        ... else:
        ...     run(main)
        [0, 2, 4]

    """
    if connections < 0:
        raise ValueError("connections cannot be negative")

    _func = _cap(partial(func, **kwargs) if kwargs else func, budget)
    _missing = object()
    items = list(content)
    results: list[S | object] = [_missing] * len(items)
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

    return [cast(S, r) for r in results if r is not _missing]


async def _pool_stream[T, S](
    source: AsyncIterable[T] | Iterable[T],
    drain: Callable[[T, MemoryObjectSendStream[S]], Awaitable[None]],
    *,
    limit: int,
    buffer: int,
) -> AsyncGenerator[S, None]:
    """
    Arrival-order worker pool shared by :func:`async_map_stream` and
    :func:`async_merge`.

    A single ``feed`` task pushes each item of *source* into an unbuffered input
    stream; a fixed pool of *limit* workers pulls from it and calls *drain* with
    the item and a *buffer*-sized output stream. *drain* sends zero or more
    results per item — one for a map (``async_map_stream``), many for a feed
    (``async_merge``). The unbuffered input means the source only advances as
    workers free up, so in-flight memory stays within ``limit`` open items plus
    ``buffer`` queued results. Results are yielded in *arrival* order (whichever
    worker sends first), not source order.

    Args:
        source (AsyncIterable | Iterable): Items to hand to the worker pool.
        drain (callable): ``async (item, out) -> None`` — does the per-item work
            and ``await out.send(...)`` for each result to emit.
        limit (int): Number of concurrent workers (must be >= 1).
        buffer (int): Size of the completed-results queue (must be >= 0).

    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    elif buffer < 0:
        raise ValueError("buffer cannot be negative")

    item_send, item_recv = create_memory_object_stream[T](max_buffer_size=0)
    result_send, result_recv = create_memory_object_stream[S](max_buffer_size=buffer)

    async def feed() -> None:
        async with item_send:
            async for item in _as_async(source):
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
    Map *func* over *source* concurrently, yielding results as they complete.

    At most *limit* calls run at once (a fixed worker pool over an unbuffered
    input stream) and at most *buffer* completed results are queued; together
    they bound in-flight memory for large or unbounded sources. An optional
    *budget* semaphore, shared across nested calls, caps their combined
    concurrency below the per-call *limit*. Output is *arrival* order; for
    source order use :func:`async_map_ordered_stream`.

    Args:
        func (callable): An async function applied to each source item.
        source (AsyncIterable | Iterable): The items to map over.
        limit (int): Maximum number of concurrent calls (default:
            ``DEF_CONNECTION_COUNT``).
        buffer (int): Size of the completed-results queue (default: 0).
        budget (Semaphore): Optional shared concurrency budget (default: None).

    Yields:
        Any: Each ``func(item)`` result, in completion order.

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
        >>> if issync:
        ...     [0, 2, 4, 6]
        ... else:
        ...     run(main)
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
    Map *func* over *source* concurrently, yielding results in *source order*.

    The source is consumed a bounded ``limit + buffer`` window at a time; each
    window is mapped concurrently via :func:`async_map` (order-preserving) and its
    results yielded before the next window is read. So output order matches input
    order, in-flight memory stays within the window, and — unlike a persistent
    worker pool — no task group spans a ``yield``, keeping early ``aclose`` clean.
    An optional *budget* semaphore, shared across nested calls, caps their
    combined concurrency.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    elif buffer < 0:
        raise ValueError("buffer cannot be negative")

    window = max(limit + buffer, 1)
    batch: list[T] = []

    async for item in _as_async(source):
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
    Merge many async feeds into one stream, yielding records as they arrive.

    Like :func:`async_map_stream`, but each *source item is a feed* rather than a
    single value: a fixed pool of at most *limit* workers each drains one feed at
    a time, and every record flows through a bounded *buffer*-sized output stream
    — so records interleave across feeds as soon as they are produced, rather than
    one whole feed at a time. In-flight memory stays within ``limit`` open feeds
    plus ``buffer`` queued records. Output order is *arrival* order, not feed
    order. Each feed is ``aclose``d as its worker finishes it (or when the merge
    is closed early), so no feed lingers to a GC finalizer.

    Args:
        feeds (AsyncIterable | Iterable): The async feeds to merge.
        limit (int): Maximum number of feeds drained concurrently (default:
            ``DEF_CONNECTION_COUNT``).
        buffer (int): Size of the merged-records queue (default: 0).

    Yields:
        Any: Each record from every feed, in arrival order.

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
        >>> if issync:
        ...     [1, 2, 3, 4]
        ... else:
        ...     run(main)
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
