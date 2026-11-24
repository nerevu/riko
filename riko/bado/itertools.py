# vim: sw=4:ts=4:expandtab
"""
Lazy, concurrent, merging, and reducing helpers over async iterables.

The helpers come in two families, categorized by their prefix:

  - ``a<name>`` helper: has a sync counterpart of the same name (a builtin or another
    riko helper) and does what that counterpart does, over an async iterable and without
    concurrency: ``alist``, ``amap``, ``aiter_sentinel``, ``aauto_close``.

  - ``async_<name>`` helper: has no same-named sync twin and adds async machinery. E.g.,
    running an async ``func`` concurrently (``async_map``, ``async_map_stream``),
    awaiting a reducer (``async_reduce``), or adapting a sync iterable (``async_iter``).

Choosing a mapper: ``amap`` applies a sync ``func`` as items are read; ``async_map``
awaits an async ``func`` over every item at once and returns the list in source order.
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
from collections import deque
from collections.abc import AsyncIterable
from contextlib import aclosing
from itertools import count
from math import inf, isinf
from types import AsyncGeneratorType, GeneratorType
from typing import TYPE_CHECKING, Self, cast, overload

from riko.base._config import DEF_CONCURRENCY_LIMIT, Limit, require_limit
from riko.base._exceptions import PipelineStateError
from riko.base._iterutils import (
    TeeRead,
    _TeeState,
    auto_close,
    has_open_resource,
    is_lagging,
    log_cleanup_failure,
    require_idle,
)
from riko.base._logging import get_logger
from riko.base._sentinels import MISSING, MissingType
from riko.types._io import resolve_closer

from ._backend import (
    CancelScope,
    CapacityLimiter,
    Event,
    MemoryObjectSendStream,
    Semaphore,
    async_sleep,
    checkpoint,
    create_memory_object_stream,
    get_current_task,
)
from ._util import maybe_aclosing, maybe_async, maybe_closing, open_task_group

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Callable,
        Iterable,
        Iterator,
    )
    from logging import Logger

    from riko.types._streams import AnyIterable, AsyncStreamOf

    from ._backend import MemoryObjectReceiveStream

logger: Logger = get_logger(__name__)


async def _gen_paced[T](stream: Iterator[T], cooperative: bool) -> AsyncGenerator[T]:
    """Streams a sync iterator's items and optionally pauses between yields."""
    for item in stream:
        if cooperative:
            await async_sleep(0)

        yield item


def async_iter[T](source: Iterable[T], cooperative: bool = False) -> aauto_close[T]:
    """
    Converts a sync iterable into an async stream that closes it when it ends.

    Use ``as_async`` instead when *source* may already be async. It returns such a
    source's iterator as it is and wraps a sync one here.

    Closing the stream, even before its first read, also closes the sync iterator.
    Similar to how closing :func:`as_async` of an async iterable closes that iterable.

    Args:

        source: The sync iterable to wrap.

    Kwargs:

        cooperative: Yield control before each item so concurrent tasks (e.g., a
            timeout) can run (default: False).

    Returns:

        An async stream of each item of *source* in order.

    Examples:

        >>> from riko import run
        >>>
        >>> run(alist, async_iter(range(3)))
        [0, 1, 2]

    """
    stream = iter(source)
    return aauto_close(_gen_paced(stream, cooperative), stream)


def as_async[T](source: AnyIterable[T], cooperative: bool = False) -> AsyncStreamOf[T]:
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

        >>> from riko import run
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


def amap[T, S](func: Callable[[T], S], source: AsyncIterable[T]) -> aauto_close[S]:
    """
    Applies *func* to each item of an async *source* lazily.

    The async twin of the ``map`` builtin for one iterable. Reads *source* as it is
    consumed and closes it once it is exhausted, closed (even before its first read), or
    fails.

    Use ``async_map`` instead when *func* is async and every result fits in a list. Use
    ``async_map_stream`` to run an async *func* concurrently while streaming.

    Args:

        func: A sync function applied to each item.
        source: The async items to map over.

    Returns:

        An async stream of ``func`` of each item, in source order.

    Examples:

        >>> from riko import run
        >>>
        >>> run(alist, amap(str, as_async([1, 2])))
        ['1', '2']

        # Closing early closes the source
        >>> from io import StringIO
        >>>
        >>> async def first():
        ...     f = StringIO("hi")
        ...     mapped = amap(str.upper, as_async(f))
        ...     item = await anext(mapped)
        ...     await mapped.aclose()
        ...     print((item, f.closed))
        >>>
        >>> run(first)
        ('HI', True)

    """
    stream = aiter(source)
    return aauto_close((func(item) async for item in stream), stream)


async def _gen_sliced[T](stream: AsyncIterator[T], stop: int) -> AsyncGenerator[T]:
    """Streams at most ``stop`` items of an async iterator."""
    for _ in range(stop):
        item = await anext(stream, MISSING)

        if isinstance(item, MissingType):
            break

        yield item


def aislice[T](source: AsyncIterable[T], stop: int) -> aauto_close[T]:
    """
    Takes the first *stop* items of an async *source* lazily.

    The async twin of ``itertools.islice`` with only a stop. Closes *source* once
    *stop* items are taken; or when the slice is exhausted, closed (even before its
    first read), or fails.

    Args:

        source: The async items to slice.
        stop: The most items to take.

    Returns:

        An async stream of at most ``stop`` items, in source order.

    Examples:

        >>> from riko import run
        >>>
        >>> run(alist, aislice(as_async(range(5)), 2))
        [0, 1]

    """
    stream = aiter(source)
    return aauto_close(_gen_sliced(stream, stop), stream)


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

        >>> from riko import run
        >>>
        >>> async def pairs():
        ...     yield (1, 2)
        ...     yield (3,)
        >>>
        >>> run(alist, async_flatten(pairs()))
        [1, 2, 3]

    """
    async with aclosing(source):
        async for batch in source:
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

        >>> from riko import run
        >>>
        >>> run(alist, as_async([1, 2]))
        [1, 2]

    """
    return [item async for item in as_async(source)]


async def materialize[T](source: AnyIterable[T]) -> Iterator[T]:
    """
    Collects a sync or async iterable into a sync iterator.

    Use ``alist`` instead when the items are indexed, counted, or read more than once.

    Args:

        source: A sync or async iterable.

    Returns:

        An iterator over the items of *source* in order.

    Examples:

        >>> from riko import run
        >>>
        >>> next(run(materialize, as_async([1, 2])))
        1

    """
    return iter(await alist(source))


async def aiter_sentinel[T, R, S](
    func: Callable[[Iterator[T]], Awaitable[R | S]],
    source: Iterable[T],
    sentinel_type: type[S],
) -> AsyncStreamOf[R]:
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

        >>> from riko import run
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


class aauto_close[T]:  # noqa: N801
    """
    Passes ``source`` through so it closes ``closables`` when iteration ends.

    The async twin of ``auto_close``. Closes each closable on exhaustion, an early
    close, or an exception. Also closes the source when it is closable. An ``aclose``
    before the first read releases everything. A value with no close (including
    ``None``) is skipped.

    Use ``maybe_aclosing`` instead when the handle is consumed inside one ``async with``
    block. This wrapper is for a handle whose consumption is deferred.

    E.g., a parser that returns a lazy iterator over an open file keeps the file alive
    until the caller drains it. An ``async with`` block would close it before the first
    read. Pass a second closable when a seekable copy is read but the original fetch
    must still be released.

    Args:

        source: The items to yield.
        closables: The values closed once iteration finishes.

    Kwargs:

        inline: Whether a sync close runs on the event loop rather than a worker.
            Abandons a worker's close if the caller is cancelled. In that case, the
            worker finishes on its own.

    Warns:

        ResourceWarning: If a wrapper holding a resource (not just generators or other
            wrappers) is read from but garbage collected before it finishes or closes.

    Raises:

        Exception: Whatever a failing close raises, once every closable has been
            closed.

        ExceptionGroup: If several fail. A close failure after a read error is noted
            on that error instead.

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

    __slots__ = ("_open", "_started", "closables", "inline", "source")

    def __init__(
        self, source: AsyncIterable[T], *closables: object, inline: bool = True
    ) -> None:
        self.source: AsyncIterator[T] = aiter(source)
        self.closables: tuple[object, ...] = closables
        self.inline: bool = inline
        self._open = [True]
        self._started: bool = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        self._started = True

        try:
            item = await anext(self.source)
        except StopAsyncIteration:
            await self.aclose()
            raise
        except BaseException as primary:
            try:
                with CancelScope(shield=True):
                    await self.aclose()
            except Exception as failure:  # noqa: BLE001 (noted on the primary)
                log_cleanup_failure(primary, failure, "closing the source")

            raise

        return item

    def __del__(self) -> None:
        """Warns when a started but unclosed wrapper holds a resource."""
        started = getattr(self, "_started", False) and getattr(self, "_open", None)
        values = (getattr(self, "source", None), *getattr(self, "closables", ()))
        ignored = (GeneratorType, AsyncGeneratorType, auto_close, aauto_close)

        if started and has_open_resource(values, *ignored):
            msg = "unclosed aauto_close stream. Exhaust or close it"
            warnings.warn(msg, ResourceWarning, source=self, stacklevel=1)

    async def aclose(self) -> None:
        """
        Closes the source and each closable (closing again does nothing).

        Raises:

            Exception: Whatever the one failing close raises.
            ExceptionGroup: If several closes fail.

        """
        failures: list[Exception] = []

        try:
            # A single atomic pop, so concurrent callers close only once.
            self._open.pop()
        except IndexError:
            pass
        else:
            runner = maybe_async.using(inline=self.inline, abandon_on_cancel=True)

            for value in (self.source, *self.closables):
                if (closer := resolve_closer(value, is_async=True)) is not None:
                    try:
                        await runner(closer)
                    except Exception as error:  # noqa: BLE001 (raised after the loop)
                        failures.append(error)

        if len(failures) == 1:
            raise failures[0]
        elif failures:
            raise ExceptionGroup("multiple errors during aauto_close", failures)


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


async def _reduce_seeded[T, S](
    func: Callable[[T, S], T | Awaitable[T]], items: Iterator[S], value: T
) -> T:
    """Reduces the remaining ``items`` onto ``value``, awaiting each awaitable step."""
    for item in items:
        value = await maybe_async(func, value, item)

    return value


@overload
def async_reduce[T, S](
    func: Callable[[T, S], T | Awaitable[T]], source: Iterable[S], initial: T
) -> Awaitable[T]: ...
@overload
def async_reduce[T](
    func: Callable[[T, T], T | Awaitable[T]], source: Iterable[T], initial: None = ...
) -> Awaitable[T]: ...
def async_reduce(
    func: Callable[..., object], source: Iterable[object], initial: object = None
) -> Awaitable[object]:
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
    return _reduce_seeded(func, items, value)


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
    limit: Limit = DEF_CONCURRENCY_LIMIT,
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

        limit: Maximum number of concurrent calls: an integer greater than 0, or
            ``math.inf`` for no limit (default: ``DEF_CONCURRENCY_LIMIT``, 16).

        budget: A shared cap on simultaneous calls (semaphore), or ``None`` to cap each
            map by its own ``limit``. Never share it with an outer map whose *func*
            starts an inner map. Once the outer calls fill every slot, the inner calls
            they await never get one and may deadlock. A call holds a slot only while
            *func* runs (default: None).

        **kwargs: Extra keyword arguments forwarded to *func*.

    Returns:

        The results, in source order.

    Raises:

        TypeError: If ``limit`` is neither an integer nor ``math.inf``.
        ValueError: If ``limit`` is 0 or negative.

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
    limit = require_limit(limit)

    async def call(item: T) -> S:
        return await func(item, **kwargs)

    _func = _cap(call if kwargs else func, budget)
    items = list(source)
    results: dict[int, S] = {}
    limiter = None if isinf(limit) else CapacityLimiter(limit)

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

        budget: A shared cap on simultaneous calls (semaphore), or ``None`` to cap each
            map by its own ``limit``. Never share it with an outer map whose *func*
            starts an inner map. Once the outer calls fill every slot, the inner calls
            they await never get one and may deadlock. A call holds a slot only while
            *func* runs (default: None).

    Returns:

        A completion-order stream of each ``func(item)`` result.

    Examples:

        >>> from riko import run
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

        budget: A shared cap on simultaneous calls (semaphore), or ``None`` to cap each
            map by its own ``limit``. Never share it with an outer map whose *func*
            starts an inner map. Once the outer calls fill every slot, the inner calls
            they await never get one and may deadlock. A call holds a slot only while
            *func* runs (default: None).

    Yields:

        Each ``func(item)`` result, in *source* order.

    Examples:

        >>> from riko import run
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


def async_flat_map[T, S](
    func: Callable[[T], Awaitable[Iterable[S]]],
    source: AnyIterable[T],
    *,
    ordered: bool,
    limit: int = DEF_CONCURRENCY_LIMIT,
    budget: Semaphore | None = None,
) -> AsyncGenerator[S, None]:
    """
    Maps an async *func* over *source* concurrently and flattens each call's batch.

    Args:

        func: An async function returning a batch of results for one input item.
        source: The items to map over.

    Kwargs:

        ordered: Whether batches keep *source* order rather than completion order.
        limit: Maximum number of concurrent calls (default: ``DEF_CONCURRENCY_LIMIT``).
        budget: A shared cap on simultaneous calls (default: None).

    Returns:

        A flat stream of every batch's results.

    Examples:

        >>> from riko import run
        >>>
        >>> async def pair(x):
        ...     return [x, x]
        >>>
        >>> run(alist, async_flat_map(pair, range(2), ordered=True))
        [0, 0, 1, 1]

    """
    mapper = async_map_ordered_stream if ordered else async_map_stream
    return async_flatten(mapper(func, source, limit=limit, budget=budget))


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

        >>> from riko import run
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


class AsyncTeeBranch[T]:
    """
    One ``AsyncTee`` branch: an async iterator that releases its buffer on close.

    Created by ``AsyncTee.branch``. Exhausting or closing the branch drops its buffer.
    Once every branch has done so, the tee closes its source. Closing a branch while
    its consumer waits on another task's read ends once that read returns.
    """

    __slots__ = ("_key", "_tee")

    def __init__(self, tee: AsyncTee[T], key: int) -> None:
        self._tee = tee
        self._key = key

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        try:
            item = await self._tee._apull(self._key)
        except StopAsyncIteration:
            await self._tee._adrop(self._key)
            raise

        return item

    async def aclose(self) -> None:
        """Drops the branch and its buffer (closing again does nothing)."""
        await self._tee._adrop(self._key)


class AsyncTee[T]:
    """
    Shares one async iterator among branches pulled in any order; a lagging one buffers.

    The async twin of ``Tee``. Each upstream item is pulled once, by whichever branch
    first asks for it. It is queued for every other open branch. Nothing is ever
    dropped. A branch that falls more than ``max_lag`` items behind fails the tee
    instead. Create every branch before reading any. Branches may be read from
    different tasks, one consumer per branch.

    The source closes as soon as it is exhausted or fails, and buffered items still
    drain. An upstream error reaches every branch once it has drained what it queued.
    Every later read raises it again.

    An overflow or a failed copy discards every buffer and fails every branch at once.
    Closing the last branch while another task is reading upstream returns at once. The
    source closes once that read returns. Closing a branch while its consumer waits on
    another task's read ends after that read. Cancel the consumer for a prompt exit.

    Args:

        source: The items to share.

    Kwargs:

        isolate: Gives every branch but the first reader a deep copy.
        max_lag: The most items a branch may have queued (default: no bound).

    Raises:

        PipelineError: If

            - A branch would queue more than ``max_lag`` items
            - An item cannot be copied
            - Another consumer's upstream read was cancelled or interrupted.

        PipelineStateError: If a branch is created after the first read or after
            close, or the source reads a branch that has nothing queued.

        TypeError: If ``max_lag`` is neither an integer nor ``math.inf``.
        ValueError: If ``max_lag`` is 0 or negative.

    Examples:

        >>> from riko import run
        >>>
        >>> async def gen_items():
        ...     yield {"n": 1}
        ...     yield {"n": 2}
        >>>
        >>> async def read_both():
        ...     tee = AsyncTee(gen_items(), isolate=True)
        ...     first, second = tee.branch(), tee.branch()
        ...     print(await alist(first))
        ...     print(await alist(second))
        >>>
        >>> run(read_both)
        [{'n': 1}, {'n': 2}]
        [{'n': 1}, {'n': 2}]

    """

    __slots__ = (
        "_advancer",
        "_buffers",
        "_error",
        "_isolate",
        "_keys",
        "_max_lag",
        "_read_done",
        "_source",
        "_state",
    )

    def __init__(
        self, source: AsyncIterable[T], *, isolate: bool = False, max_lag: Limit = inf
    ) -> None:
        self._max_lag = require_limit(max_lag, "max_lag")
        self._source: aauto_close[T] = aauto_close(source)
        self._isolate = isolate
        self._buffers: dict[int, deque[T]] = {}
        self._keys = count()
        self._advancer: int | None = None
        self._read_done: Event | None = None
        self._state = _TeeState.IDLE
        self._error: Exception | None = None

    def _require_buffer(self, key: int) -> deque[T]:
        if (buffer := self._buffers.get(key)) is None:
            raise StopAsyncIteration

        if not buffer:
            if self._error is not None:
                raise self._error

            if self._state is _TeeState.DONE:
                raise StopAsyncIteration

            if self._advancer is not None and self._advancer == get_current_task().id:
                raise PipelineStateError("advancing", "read", subject="tee")

        return buffer

    def _publish(self, read: TeeRead[T]) -> None:
        read.deliver(self._buffers)

        if read.error is not None:
            self._error = read.error

        if read.done and self._state is _TeeState.READING:
            self._state = _TeeState.DONE

        self._advancer = None

        if (read_done := self._read_done) is not None:
            self._read_done = None
            read_done.set()

    async def _aclose_source(self, error: Exception | None = None) -> None:
        try:
            with CancelScope(shield=True):
                await self._source.aclose()
        except BaseException as failure:
            log_cleanup_failure(error, failure, "closing the source")

            if not isinstance(failure, Exception):
                raise

    async def _aadvance(self, key: int, *, full: bool) -> None:
        read = TeeRead[T]()
        interrupted: BaseException | None = None

        try:
            if full:
                read = TeeRead[T].from_lag(self._max_lag)
            else:
                try:
                    item = await anext(self._source)
                except StopAsyncIteration:
                    read = TeeRead[T](done=True)
                except Exception as read_error:  # noqa: BLE001 (latched, re-raised)
                    read = TeeRead[T](error=read_error)
                else:
                    # Reads keys after the read so branches closed by then get no copy.
                    others = tuple(k for k in tuple(self._buffers) if k != key)
                    read = TeeRead.from_item(item, key, *others, isolate=self._isolate)
        except BaseException as exc:  # noqa: BLE001 (re-raised below)
            interrupted = exc
            read = TeeRead[T].from_interrupt(exc)
        finally:
            self._publish(read)

        if read.error is not None:
            await self._aclose_source(read.error)

        # A close requested during the read was left to this reader
        if self._state is _TeeState.CLOSED:
            await self._aclose_source()

        if interrupted is not None:
            raise interrupted
        elif read.error is not None:
            raise read.error

    async def _apull(self, key: int) -> T:
        await checkpoint()

        while not (buffer := self._require_buffer(key)):
            if self._advancer is None:
                self._advancer = get_current_task().id
                self._state = _TeeState.READING
                full = is_lagging(self._buffers, key, self._max_lag)
                await self._aadvance(key, full=full)
            else:
                if self._read_done is None:
                    self._read_done = Event()

                await self._read_done.wait()

        return buffer.popleft()

    async def _adrop(self, key: int) -> None:
        dropped = self._buffers.pop(key, None) is not None

        if dropped and not self._buffers:
            await self.aclose()

    def branch(self) -> AsyncTeeBranch[T]:
        """
        Builds a new branch that yields every item the tee reads.

        Returns:

            The branch.

        Raises:

            PipelineStateError: If the tee has started reading or has closed.

        """
        require_idle(self._state)
        key = next(self._keys)
        self._buffers[key] = deque()
        return AsyncTeeBranch(self, key)

    async def aclose(self) -> None:
        """
        Closes the source and ends every branch.

        While another task is reading upstream, returns at once and leaves the close
        to that reader.

        Raises:

            Exception: Whatever closing the source raises.

        """
        self._buffers.clear()
        deferred = self._advancer is not None
        self._state = _TeeState.CLOSED

        if not deferred:
            with CancelScope(shield=True):
                await self._source.aclose()
