# vim: sw=4:ts=4:expandtab
"""
riko.bado.streams
~~~~~~~~~~~~~~~~~
AnyIO-backed streaming primitives for the async runtime.

``async_map_stream`` maps an async function over a source with bounded
concurrency and backpressure: a fixed worker pool pulls from an unbuffered input
stream (so the source is only advanced as workers free up) and completed results
flow through a bounded output stream. An unbounded source with a slow consumer
therefore suspends upstream instead of materializing everything — in-flight
memory stays within ``limit + buffer`` items.
"""

from __future__ import annotations

from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Awaitable,
    Callable,
    Iterable,
)

from riko.bado import create_memory_object_stream
from riko.bado.itertools import async_iter, create_task_group


def _as_async[T](source: AsyncIterable[T] | Iterable[T]) -> AsyncIterable[T]:
    resolved = source if isinstance(source, AsyncIterable) else async_iter(source)
    return resolved


async def async_map_stream[T, S](
    func: Callable[[T], Awaitable[S]],
    source: AsyncIterable[T] | Iterable[T],
    *,
    limit: int = 16,
    buffer: int = 0,
) -> AsyncGenerator[S, None]:
    """
    Map *func* over *source* concurrently, yielding results as they complete.

    At most *limit* calls run at once (a fixed worker pool over an unbuffered
    input stream) and at most *buffer* completed results are queued; together
    they bound in-flight memory for large or unbounded sources.
    """
    item_send, item_recv = create_memory_object_stream[T](max_buffer_size=0)
    result_send, result_recv = create_memory_object_stream[S](max_buffer_size=buffer)

    async def feed() -> None:
        async with item_send:
            async for item in _as_async(source):
                await item_send.send(item)

    async def worker(results, items) -> None:
        async with results, items:
            async for item in items:
                await results.send(await func(item))

    async with create_task_group() as tg:
        tg.start_soon(feed)

        for _ in range(limit):
            tg.start_soon(worker, result_send.clone(), item_recv.clone())

        result_send.close()
        item_recv.close()

        async with result_recv:
            async for result in result_recv:
                yield result
