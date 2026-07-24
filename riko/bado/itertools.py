# vim: sw=4:ts=4:expandtab
"""
riko.bado.itertools
~~~~~~~~~~~~~~~~~~~~
Async itertools for riko pipes (anyio-backed).

``async_map`` maps an async function over an iterable with optional bounded
concurrency; ``coop_reduce``/``async_reduce`` reduce cooperatively; ``async_iter``
adapts a sync iterable into an async generator. Available when the ``async`` extra
is installed; the functions are importable regardless but only run under an async
runtime.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from functools import partial
from inspect import isawaitable
from typing import Any, overload

from riko.bado import CapacityLimiter, async_sleep, checkpoint, create_task_group


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
        >>> from riko.bado import issync, run
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
    func: Callable[[T, S], T], content: Iterable[S], initial: None = ...
) -> T | None: ...
async def coop_reduce[T, S](  # noqa: E302
    func: Callable[[T, S], T], content: Iterable[S], initial: T | None = None
) -> T | None:
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
        >>> from riko.bado import issync, run
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
    value: Any = next(items, None) if initial is None else initial

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
        >>> from riko.bado import issync, run
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
    **kwargs: Any,
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
        >>> from riko.bado import issync, run
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
    _func = partial(func, **kwargs) if kwargs else func
    items = list(content)
    results: list[Any] = [None] * len(items)
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

    return results
