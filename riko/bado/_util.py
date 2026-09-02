# vim: sw=4:ts=4:expandtab
"""
riko.bado._util
~~~~~~~~~~~~~~~

AnyIO + httpx implementations used by :mod:`riko.bado._backend`.

This module is private. Optional dependency handling and the sync-only fallback
are provided by :mod:`riko.bado._backend`.
"""

from collections.abc import Awaitable, Callable, Iterable
from functools import partial
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, Literal, cast, overload

from riko.types._sentinels import MISSING

try:
    import anyio
    import httpx
except ImportError:
    anyio = httpx = None

if TYPE_CHECKING:
    from httpx import Response


async def async_get(url: str, **kwargs: Any) -> "Response":
    """
    Fetches ``url`` via httpx and follows redirects.

    A ``timeout`` of ``0`` means no timeout, which mirrors the sync backend.

    """
    if kwargs.get("timeout") == 0:
        kwargs["timeout"] = None

    async with httpx.AsyncClient(follow_redirects=True) as client:
        return await client.get(url, **kwargs)


@overload
async def async_read(  # noqa: E704
    url: str, binary: Literal[True], encoding: str | None = ...
) -> bytes: ...
@overload  # noqa: E302
async def async_read(  # noqa: E704
    url: str, binary: Literal[False] = ..., encoding: str | None = ...
) -> str: ...
async def async_read(  # noqa: E302
    url: str, binary: bool = False, encoding: str | None = None
) -> bytes | str:
    """Reads a local ``file://`` path as bytes or text."""
    path = anyio.Path(url.replace("file://", ""))
    return await (path.read_bytes() if binary else path.read_text(encoding))


async def async_json(response: "Response") -> dict[str, Any]:
    """Returns the parsed JSON body of ``response``."""
    return response.json()


async def async_return[T](value: T) -> T:
    """Wraps ``value`` in an awaitable, for uniform ``await`` call sites."""
    return value


async def gather_results[T](awaitables: Iterable[Awaitable[T]], **_: object) -> list[T]:
    """
    Runs ``awaitables`` concurrently, returning results in submission order.

    A legitimate ``None`` result is preserved (the unfilled slot is marked with
    ``MISSING``, not ``None``), so the output aligns with the inputs.

    """
    aws = list(awaitables)
    results: list[Any] = [MISSING] * len(aws)

    async def collect(index: int, awaitable: Awaitable[T]) -> None:
        results[index] = await awaitable

    async with anyio.create_task_group() as tg:
        for index, awaitable in enumerate(aws):
            tg.start_soon(collect, index, awaitable)

    return [r for r in results if r is not MISSING]


async def maybe_deferred[T](func: Callable[..., T], *args: Any, **kwargs: object) -> T:
    """Calls ``func`` and awaits its result only when it is awaitable."""
    result = func(*args, **kwargs)
    return cast(T, (await result)) if isawaitable(result) else result


def async_partial(f, **kwargs):
    """Binds ``kwargs`` to ``f`` for later awaiting via :func:`maybe_deferred`."""
    return partial(maybe_deferred, f, **kwargs)
