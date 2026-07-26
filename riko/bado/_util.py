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
from functools import partial
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, cast

try:
    import anyio
    import httpx
except ImportError:
    anyio = httpx = None

if TYPE_CHECKING:
    from httpx import Response


async def async_get(url: str, **kwargs: Any) -> "Response":
    if kwargs.get("timeout") == 0:
        kwargs["timeout"] = None

    async with httpx.AsyncClient(follow_redirects=True) as client:
        return await client.get(url, **kwargs)


async def async_json(response: "Response") -> dict[str, Any]:
    return response.json()


async def async_return[T](value: T) -> T:
    return value


async def gather_results[T](awaitables: Iterable[Awaitable[T]], **_: object) -> list[T]:
    aws = list(awaitables)
    results: list[T | None] = [None] * len(aws)

    async def collect(index: int, awaitable: Awaitable[T]) -> None:
        results[index] = await awaitable

    async with anyio.create_task_group() as tg:
        for index, awaitable in enumerate(aws):
            tg.start_soon(collect, index, awaitable)

    return [r for r in results if r is not None]


async def maybe_deferred[T](func: Callable[..., T], *args: Any, **kwargs: object) -> T:
    result = func(*args, **kwargs)
    return cast(T, (await result)) if isawaitable(result) else result


def async_partial(f, **kwargs):
    return partial(maybe_deferred, f, **kwargs)
