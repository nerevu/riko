# vim: sw=4:ts=4:expandtab
"""
Lazy, concurrent, merging, and reducing helpers over async iterables.

The helpers come in two families, categorized by their prefix. An ``a<name>`` helper
has a sync counterpart of the same name (a builtin or a sibling here) and does what
that counterpart does, over an async iterable and without concurrency: ``alist``,
``amap``, ``aiter_sentinel``, ``aauto_close``. An ``async_<name>`` helper has no same-
named sync twin and adds async machinery. E.g., running an async ``func`` concurrently
(``async_map``, ``async_map_stream``), awaiting a reducer (``async_reduce``), or
adapting a sync iterable (``async_iter``).

Choosing a mapper: ``amap`` applies a sync ``func`` as items are read; ``async_map``
awaits an async ``func`` over every item at once and returns the list in source order;
``async_map_stream`` and ``async_map_ordered_stream`` do the same as a bounded stream,
in completion or source order, for large or unbounded sources.

Examples:

    Basic usage::

        >>> from riko import async_map, run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> run(async_map, double, range(3))
        [0, 2, 4]

"""

from __future__ import annotations

import warnings
from collections.abc import AsyncIterable
from contextlib import aclosing, suppress
from typing import TYPE_CHECKING, Self, cast, overload

from riko.base._config import DEF_CONCURRENCY_LIMIT
from riko.types._io import ASYNC_CLEANUP_MSG, get_sync_closer, resolve_closer

from ._backend import (
    CapacityLimiter,
    MemoryObjectSendStream,
    Semaphore,
    async_sleep,
    checkpoint,
    create_memory_object_stream,
)
from ._util import (
    maybe_aclosing,
    maybe_async,
    maybe_closing,
    open_task_group,
    require_value,
)

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Callable,
        Iterable,
        Iterator,
    )

    from riko.types._streams import AnyIterable

    from ._backend import MemoryObjectReceiveStream


async def async_iter[T](
    source: Iterable[T], cooperative: bool = False
) -> AsyncGenerator[T, None]:
    """
    Converts a sync iterable into an async generator.

    Use ``as_async`` instead when *source* may already be async. It returns such a
    source's iterator as it is and wraps a sync one here.

    Closing the generator early also closes the sync iterator, just as closing
    :func:`as_async` of an async iterable closes that iterable.

    Args:

        source: The sync iterable to wrap.

    Kwargs:

        cooperative: Yield control before each item so concurrent tasks (e.g., a
            timeout) can run (default: False).

    Yields:

        Each item of *source* in order.

    Examples:

        >>> from riko import alist, run
        >>>
        >>> run(alist, async_iter(range(3)))
        [0, 1, 2]

    """
    with maybe_closing(iter(source)) as items:
        for item in items:
            if cooperative:
                await async_sleep(0)

            yield item


def as_async[T](source: AnyIterable[T], cooperative: bool = False) -> AsyncIterator[T]:
    """
    Adapts *source* to an ``AsyncIterator``.

    Use ``alist`` or ``materialize`` instead to drain *source* rather than iterate it.

    Args:

        source: A sync or async iterable.

    Kwargs:

        cooperative: For a sync *source*, yield control before each item so
            concurrent tasks (e.g. a timeout) can run (default: False).

    Returns:

        The async iterator of an already-async *source*, else *source* wrapped
            via :func:`async_iter`.

    Examples:

        >>> from riko import alist, run
        >>>
        >>> stream = as_async([1, 2])
        >>> run(alist, stream)
        [1, 2]

    """
    if isinstance(source, AsyncIterable):
        result = aiter(source)
    else:
        result = async_iter(source, cooperative=cooperative)

    return result


async def amap[T, S](
    func: Callable[[T], S], source: AsyncIterable[T]
) -> AsyncGenerator[S, None]:
    """
    Applies *func* to each item of an async *source* lazily.

    The async twin of the ``map`` builtin for one iterable. *source* is read as it is
    consumed and never closed here. The caller that owns it closes it.

    Use ``async_map`` instead when *func* is async and every result fits in a list. Use
    ``async_map_stream`` to run an async *func* concurrently while streaming.

    Args:

        func: A sync function applied to each item.
        source: The async items to map over.

    Yields:

        ``func`` of each item, in source order.

    Examples:

        >>> from riko import alist, run
        >>>
        >>> run(alist, amap(str, as_async([1, 2])))
        ['1', '2']

    """
    async for item in source:
        yield func(item)


async def async_flatten[T](
    source: AsyncGenerator[Iterable[T], None],
) -> AsyncGenerator[T, None]:
    """
    Flattens the batches an async generator produces into one ordered stream.

    Closes *source* and the batch being read when the flattened stream is exhausted,
    closed early, or fails. A concurrent mapper's in-flight calls stop with it.

    Use ``async_merge`` instead to drain concurrently when each batch is itself an
    async iterable.

    Args:

        source: An async generator of batches.

    Yields:

        Each item of every batch, in batch order.

    Examples:

        >>> from riko import alist, run
        >>>
        >>> async def pairs():
        ...     yield (1, 2)
        ...     yield (3,)
        >>>
        >>> run(alist, async_flatten(pairs()))
        [1, 2, 3]

    """
    async with aclosing(source) as batches:
        async for batch in batches:
            with maybe_closing(batch):
                for item in batch:
                    yield item


async def alist[T](source: AnyIterable[T]) -> list[T]:
    """
    Collects a sync or async iterable into a list.

    Use ``materialize`` instead when the drained items are read once as a sync
    iterator rather than kept as a list.

    Args:

        source: A sync or async iterable.

    Returns:

        The items of *source* in order.

    Examples:

        >>> from riko import alist, as_async, run
        >>>
        >>> run(alist, as_async([1, 2]))
        [1, 2]

    """
    return [item async for item in as_async(source)]


async def apeek[T](
    source: AnyIterable[T], n: int
) -> tuple[tuple[T, ...], AsyncIterator[T]]:
    """
    Reads up to *n* items of a sync or async iterable ahead without losing them.

    Args:

        source: A sync or async iterable.
        n: The most items to read ahead.

    Returns:

        The items read ahead, and an async iterator over every item of *source* in
            order, starting with them.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     head, stream = await apeek(as_async("abc"), 2)
        ...     print(head, await alist(stream))
        >>>
        >>> run(main)
        ('a', 'b') ['a', 'b', 'c']

    """
    stream = as_async(source)
    head: list[T] = []

    if n > 0:
        async for value in stream:
            head.append(value)

            if len(head) >= n:
                break

    async def replay() -> AsyncIterator[T]:
        for value in head:
            yield value

        async for value in stream:
            yield value

    return tuple(head), replay()


async def materialize[T](source: AnyIterable[T]) -> Iterator[T]:
    """
    Collects a sync or async iterable into a sync iterator.

    Use ``alist`` instead when the items are indexed, counted, or read more than once.

    Args:

        source: A sync or async iterable.

    Returns:

        An iterator over the items of *source* in order.

    Examples:

        >>> from riko import as_async, run
        >>>
        >>> next(run(materialize, as_async([1, 2])))
        1

    """
    return iter(await alist(source))


async def aiter_sentinel[T, R, S](
    func: Callable[[Iterator[T]], Awaitable[R | S]],
    source: Iterable[T],
    sentinel_type: type[S],
) -> AsyncIterator[R]:
    """
    Streams each ``func`` result from ``source`` until ``func`` returns a sentinel.

    The two-argument ``iter`` for an async ``func``, except the sentinel is matched by
    type rather than by equality.

    Use ``async_iter`` instead to stream a sync iterable's items as they are. This pulls
    them through an async ``func`` and stops at its sentinel.

    Args:

        func: Returns the next result from the iterator over ``source``.
        source: The items ``func`` reads.
        sentinel_type: The sentinel result type.

    Yields:

        Each ``func`` result before the sentinel.

    Examples:

        >>> from riko import alist, run
        >>>
        >>> async def pull(items):
        ...     return next(items, None)
        >>>
        >>> source = [1, 2, None, 3]
        >>> stream = aiter_sentinel(pull, source, type(None))
        >>> run(alist, stream)
        [1, 2]

    """
    stream = iter(source)

    while not isinstance(item := await func(stream), sentinel_type):
        yield cast("R", item)


class auto_close[T]:  # noqa: N801
    """
    Passes ``source`` through so it closes ``closeables`` when iteration ends.

    Closes each closeable on exhaustion, an early close, or an exception. Also closes
    ``source`` if it is closeable. A ``close`` before the first read releases
    everything. A value with no close (including ``None``) is skipped.

    Use ``maybe_closing`` instead when the handle is consumed inside one ``with`` block.
    This wrapper is for a handle whose consumption is deferred.

    E.g., a parser that returns a lazy iterator over an open file keeps the file alive
    until the caller drains it. A ``with`` block would close it before the first read.
    Pass a second closeable when a seekable copy is read but the original fetch must
    still be released.

    Args:

        source: The items to yield.
        closeables: The values closed once iteration finishes.

    Warns:

        ResourceWarning: If a wrapper is read from but garbage collected before it
            finishes or closes. It then closes, as an unclosed file does.

    Raises:

        InvalidPipelineError: If a close returns an awaitable since there is no event
            loop.

    Examples:

        >>> from io import StringIO
        >>>
        >>> f = StringIO("hi")
        >>> list(auto_close(f, f))
        ['hi']
        >>> f.closed
        True

        # Closing before the first read
        >>> g = StringIO("hi")
        >>> auto_close(g, g).close()
        >>> g.closed
        True

    """

    __slots__ = ("_closed", "_started", "closeables", "source")

    def __init__(self, source: Iterable[T], *closeables: object) -> None:
        self.source: Iterator[T] = iter(source)
        self.closeables: tuple[object, ...] = closeables
        self._closed = False
        self._started = False

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        self._started = True

        try:
            item = next(self.source)
        except BaseException:
            self.close()
            raise

        return item

    def __del__(self) -> None:
        """Warns and closes when a started wrapper is collected before it closes."""
        if getattr(self, "_started", False) and not getattr(self, "_closed", True):
            msg = "unclosed auto_close stream. Exhaust it or close it"
            warnings.warn(msg, ResourceWarning, source=self, stacklevel=1)

            with suppress(Exception):
                self.close()

    def close(self) -> None:
        """Closes the source and each closeable, once."""
        if not self._closed:
            self._closed = True

            for value in (self.source, *self.closeables):
                closer = get_sync_closer(value)
                if closer is not None and (result := closer()) is not None:
                    require_value(result, ASYNC_CLEANUP_MSG)


class aauto_close[T]:  # noqa: N801
    """
    Passes ``source`` through so it closes ``closeables`` when iteration ends.

    The async twin of ``auto_close``. Closes each closeable on exhaustion, an early
    close, or an exception. Also closes the source when it is closeable. An ``aclose``
    before the first read releases everything. A value with no close (including
    ``None``) is skipped.

    Use ``maybe_aclosing`` instead when the handle is consumed inside one ``async with``
    block. This wrapper is for a handle whose consumption is deferred.

    E.g., a parser that returns a lazy iterator over an open file keeps the file alive
    until the caller drains it. An ``async with`` block would close it before the first
    read. Pass a second closeable when a seekable copy is read but the original fetch
    must still be released.

    Args:

        source: The items to yield.
        closeables: The values closed once iteration finishes.

    Kwargs:

        inline: Whether a sync close runs on the event loop rather than a worker.

    Warns:

        ResourceWarning: If a wrapper is read from but garbage collected before it
            finishes or closes. It then closes, as an unclosed file does.

    Examples:

        >>> from io import StringIO
        >>> from riko import run
        >>>
        >>> async def read(f):
        ...     yield f.read()
        >>>
        >>> async def drain():
        ...     f = StringIO("hi")
        ...     print([x async for x in aauto_close(read(f), f)], f.closed)
        >>>
        >>> run(drain)
        ['hi'] True

        # Closing before the first read
        >>> async def close_early():
        ...     f = StringIO("hi")
        ...     await aauto_close(read(f), f).aclose()
        ...     print(f.closed)
        >>>
        >>> run(close_early)
        True

    """

    __slots__ = ("_closed", "_started", "closeables", "inline", "source")

    def __init__(
        self, source: AsyncIterable[T], *closeables: object, inline: bool = True
    ) -> None:
        self.source: AsyncIterator[T] = aiter(source)
        self.closeables: tuple[object, ...] = closeables
        self.inline: bool = inline
        self._closed: bool = False
        self._started: bool = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        self._started = True

        try:
            item = await anext(self.source)
        except BaseException:
            await self.aclose()
            raise

        return item

    def __del__(self) -> None:
        """Warns when a started wrapper is garbage collected before it closes."""
        if getattr(self, "_started", False) and not getattr(self, "_closed", True):
            msg = "unclosed aauto_close stream. Exhaust it or close it"
            warnings.warn(msg, ResourceWarning, source=self, stacklevel=1)

    async def aclose(self) -> None:
        """Closes the source and each closeable."""
        if not self._closed:
            self._closed = True

            for value in (self.source, *self.closeables):
                if (closer := resolve_closer(value, is_async=True)) is not None:
                    await maybe_async(closer, inline=self.inline)


@overload
async def coop_reduce[T, S](
    func: Callable[[T, S], T], source: Iterable[S], initial: T
) -> T: ...
@overload
async def coop_reduce[T, S](
    func: Callable[[T | S | None, S], T], source: Iterable[S], initial: None = ...
) -> T | S | None: ...
async def coop_reduce[T, S](  # pyright: ignore[reportInconsistentOverload]
    func: Callable[[T | S | None, S], T], source: Iterable[S], initial: T | None = None
) -> T | S | None:
    """
    Reduces *source* with a sync *func* while yielding control between steps.

    Use ``async_reduce`` instead when *func* is async. This one checkpoints after each
    sync step so concurrent tasks (e.g., a timeout) can run.

    Args:

        func: A two-argument reducer, e.g. ``lambda x, y: x + y``.
        source: The items to reduce.

    Kwargs:

        initial: Starting accumulator value. When ``None`` (default) the first item is
            consumed as the starting value (``None`` if *source* is empty).

    Returns:

        The final accumulated value.

    Examples:

        >>> from riko import run
        >>>
        >>> run(coop_reduce, lambda x, y: x + y, range(5))
        10

    """
    items = iter(source)
    value: T | S | None = next(items, None) if initial is None else initial

    for item in items:
        value = func(value, item)
        await checkpoint()

    return value


@overload
def async_reduce[T, S](
    func: Callable[[T, S], T | Awaitable[T]], source: Iterable[S], initial: T
) -> Awaitable[T]: ...
@overload
def async_reduce[T](
    func: Callable[[T, T], T | Awaitable[T]], source: Iterable[T], initial: None = ...
) -> Awaitable[T]: ...
def async_reduce[T, S](
    func: Callable[[T, S], T | Awaitable[T]],
    source: Iterable[S],
    initial: T | None = None,
) -> Awaitable[T | S]:
    """
    Reduces *source* with *func* and awaits each awaitable result.

    Use ``coop_reduce`` instead for a sync *func* over a large *source*. This one never
    yields control between sync steps.

    Args:

        func: A two-argument sync or async reducer.
        source: The items to reduce.

    Kwargs:

        initial: Starting accumulator value. When ``None`` (default) consumes the first
            item as the starting value.

    Returns:

        The final accumulated value.

    Examples:

        >>> from riko import run
        >>>
        >>> async def add(x, y):
        ...     return x + y
        >>>
        >>> run(async_reduce, add, range(5))
        10

    """
    items = iter(source)
    value = next(items) if initial is None else initial

    async def work(
        async_func: Callable[[T, S], T | Awaitable[T]], items: Iterator[S], value: T | S
    ) -> T | S:
        for item in items:
            value = await maybe_async(async_func, value, item)

        return value

    return work(func, items, value)


def _cap[T, S](
    func: Callable[[T], Awaitable[S]], budget: Semaphore | None
) -> Callable[[T], Awaitable[S]]:
    """
    Caps *func*'s concurrency against a shared *budget*.

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


async def async_map[T, S](
    func: Callable[[T], Awaitable[S]],
    source: Iterable[T],
    *,
    limit: int = DEF_CONCURRENCY_LIMIT,
    budget: Semaphore | None = None,
    **kwargs: object,
) -> list[S]:
    """
    Maps an async *func* over *source* concurrently and collects every result.

    Use ``async_map_stream`` or ``async_map_ordered_stream`` instead for a large or
    unbounded *source*. This one reads the whole source upfront and returns the results
    at once. Use ``amap`` for a sync *func* that needs no concurrency.

    Args:

        func: An async function applied to each item.
        source: The items to map over.

    Kwargs:

        limit: Maximum number of concurrent calls (default: ``DEF_CONCURRENCY_LIMIT``,
            16). ``0`` runs them all at once.

        budget: A limit shared across maps that caps how many calls run at once in
            total. Never share it with an outer map whose *func* starts an inner map.
            Once the outer calls fill every slot, the inner calls they await never get
            one and may deadlock. Give it only to the innermost maps. A call holds a
            slot only while *func* runs (default: None).

        **kwargs: Extra keyword arguments forwarded to *func*.

    Returns:

        The results, in source order.

    Examples:

        >>> from riko import run
        >>>
        >>> async def scale(x, factor=1):
        ...     return x * factor
        >>>
        >>> async def main():
        ...     print(await async_map(scale, range(5), limit=2, factor=3))
        >>>
        >>> run(main)
        [0, 3, 6, 9, 12]

    """
    if limit < 0:
        raise ValueError("limit cannot be negative")

    async def call(item: T) -> S:
        return await func(item, **kwargs)

    _func = _cap(call if kwargs else func, budget)
    items = list(source)
    results: dict[int, S] = {}
    limiter = CapacityLimiter(limit) if limit else None

    async def work(pos: int, item: T) -> None:
        if limiter is None:
            results[pos] = await _func(item)
        else:
            async with limiter:
                results[pos] = await _func(item)

    async with open_task_group() as tg:
        for pos, item in enumerate(items):
            tg.start_soon(work, pos, item)

    return [results[pos] for pos in range(len(items))]


async def _pool_stream[T, S](
    drain: Callable[[T, MemoryObjectSendStream[S]], Awaitable[None]],
    source: AnyIterable[T],
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

        drain: ``async (item, out) -> None`` — does the per-item work
            and ``await out.send(...)`` for each result to emit.

        source: Items to hand to the worker pool.

    Kwargs:

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

    async def worker(
        results: MemoryObjectSendStream[S], items: MemoryObjectReceiveStream[T]
    ) -> None:
        async with results, items:
            async for item in items:
                await drain(item, results)

    async with open_task_group() as tg:
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


def async_map_stream[T, S](
    func: Callable[[T], Awaitable[S]],
    source: AnyIterable[T],
    *,
    limit: int = DEF_CONCURRENCY_LIMIT,
    buffer: int = 0,
    budget: Semaphore | None = None,
) -> AsyncGenerator[S, None]:
    """
    Maps an async *func* over *source* concurrently as a bounded stream.

    *limit* and *buffer* bound in-flight memory. This suits large or unbounded sources.

    Use ``async_map_ordered_stream`` instead when results must keep source order. Use
    ``async_map`` when you want the results in a list.

    Args:

        func: An async function applied to each input item.

        source: The items to map over.

    Kwargs:

        limit: Maximum number of concurrent calls (default: ``DEF_CONCURRENCY_LIMIT``).

        buffer: Size of the completed-results queue (default: 0).

        budget: A limit shared across maps that caps how many calls run at once in
            total. Never share it with an outer map whose *func* starts an inner map.
            Once the outer calls fill every slot, the inner calls they await never get
            one and may deadlock. Give it only to the innermost maps. A call holds a
            slot only while *func* runs (default: None).

    Returns:

        A completion-order stream of each ``func(item)`` result.

    Examples:

        >>> from riko import alist, run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> stream = async_map_stream(double, range(4), limit=2)
        >>> sorted(run(alist, stream))
        [0, 2, 4, 6]

    """
    func = _cap(func, budget)

    async def drain(item: T, results: MemoryObjectSendStream[S]) -> None:
        await results.send(await func(item))

    return _pool_stream(drain, source, limit=limit, buffer=buffer)


async def async_map_ordered_stream[T, S](
    func: Callable[[T], Awaitable[S]],
    source: AnyIterable[T],
    *,
    limit: int = DEF_CONCURRENCY_LIMIT,
    buffer: int = 0,
    budget: Semaphore | None = None,
) -> AsyncGenerator[S, None]:
    """
    Maps an async *func* over *source* concurrently in bounded windows.

    An order-preserving :func:`async_map_stream`. Maps the source in bounded windows.
    In-flight memory stays within ``limit + buffer`` items.

    Use ``async_map_stream`` instead when order does not matter. It starts the next item
    as soon as any call finishes, rather than once per window.

    Args:

        func: An async function applied to each input item.
        source: The items to map over.

    Kwargs:

        limit: Maximum number of concurrent calls (default: ``DEF_CONCURRENCY_LIMIT``).

        buffer: Extra items per window beyond *limit* (default: 0).

        budget: A limit shared across maps that caps how many calls run at once in
            total. Never share it with an outer map whose *func* starts an inner map.
            Once the outer calls fill every slot, the inner calls they await never get
            one and may deadlock. Give it only to the innermost maps. A call holds a
            slot only while *func* runs (default: None).

    Yields:

        Each ``func(item)`` result, in *source* order.

    Examples:

        >>> from riko import alist, run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> stream = async_map_ordered_stream(double, range(4), limit=2)
        >>> run(alist, stream)
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
                for result in await async_map(func, batch, limit=limit, budget=budget):
                    yield result

                batch = []

        for result in await async_map(func, batch, limit=limit, budget=budget):
            yield result


def async_merge[S](
    source: AnyIterable[AsyncIterable[S]],
    *,
    limit: int = DEF_CONCURRENCY_LIMIT,
    buffer: int = 0,
) -> AsyncGenerator[S, None]:
    """
    Merges many async iterables of items into one interleaved stream.

    Use ``async_flatten`` instead when each batch is a sync iterable to yield in order.

    Like :func:`async_map_stream`, but each input item is itself an async iterable.
    Items interleave across iterables as they are produced, rather than one iterable at
    a time. *limit* and *buffer* bound in-flight memory.

    Args:

        source: The async iterables to merge.

    Kwargs:

        limit: Maximum number of source items drained concurrently (default:
            ``DEF_CONCURRENCY_LIMIT``).

        buffer: Size of the merged-items queue (default: 0).

    Returns:

        An arrival-order stream of each source item.

    Examples:

        >>> from riko import alist, run
        >>>
        >>> async def gen_items(*items):
        ...     for item in items:
        ...         yield item
        >>>
        >>> source = [gen_items(1, 2), gen_items(3, 4)]
        >>> merged = async_merge(source, limit=2)
        >>> sorted(run(alist, merged))
        [1, 2, 3, 4]

    """

    async def drain(
        items: AsyncIterable[S], results: MemoryObjectSendStream[S]
    ) -> None:
        async with maybe_aclosing(aiter(items)) as _items:
            async for item in _items:
                await results.send(item)

    return _pool_stream(drain, source, limit=limit, buffer=buffer)
