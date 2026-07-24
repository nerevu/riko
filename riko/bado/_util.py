# vim: sw=4:ts=4:expandtab
"""
riko.bado.util
~~~~~~~~~~~~~~
AnyIO + httpx implementations of the bado async primitives, plus async
utilities. Requires the ``async`` extra; :mod:`riko.bado` guards the import and
falls back to sync-only stubs when it is absent. ``run`` is the entry point
(``run(main)`` where ``main`` is a no-argument coroutine function).
"""

from collections.abc import Awaitable, Callable, Iterable
from inspect import isawaitable
from typing import Any

try:
    import anyio
    import httpx
except ImportError:
    anyio = httpx = None


async def async_get(url: str, **kwargs) -> Any:
    if kwargs.get("timeout") == 0:
        kwargs["timeout"] = None

    async with httpx.AsyncClient(follow_redirects=True) as client:
        return await client.get(url, **kwargs)


async def async_json(response: Any) -> Any:
    return response.json()


async def async_return[T](value: T) -> T:
    return value


async def gather_results[T](awaitables: Iterable[Awaitable[T]], **_: Any) -> list[T]:
    aws = list(awaitables)
    results: list[Any] = [None] * len(aws)

    async def collect(index: int, awaitable: Awaitable[T]) -> None:
        results[index] = await awaitable

    async with anyio.create_task_group() as tg:
        for index, awaitable in enumerate(aws):
            tg.start_soon(collect, index, awaitable)

    return results


async def maybe_deferred(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    result = func(*args, **kwargs)
    return (await result) if isawaitable(result) else result
