# vim: sw=4:ts=4:expandtab
"""
Provides utility helpers for the Riko async runtime.

Examples:

    Basic usage::

        >>> from riko import async_return, run
        >>>
        >>> async def main():
        ...     print(await async_return("riko"))
        >>>
        >>> run(main)
        riko

"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import partial
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, Literal, cast, overload

from riko.types._sentinels import MISSING

from ._backend import AsyncClient, Path, create_task_group

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable

    from ._backend import HTTPXResponse


async def async_get(url: str, **kwargs: Any) -> HTTPXResponse:
    """
    Fetches ``url`` via httpx and follows redirects.

    A ``timeout`` of ``0`` means no timeout, which mirrors the sync backend.

    """
    if kwargs.get("timeout") == 0:
        kwargs["timeout"] = None

    async with AsyncClient(follow_redirects=True) as client:
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
    path = Path(url.replace("file://", ""))
    return await (path.read_bytes() if binary else path.read_text(encoding))


async def async_json(response: HTTPXResponse) -> dict[str, Any]:
    """Parses the JSON body of ``response``."""
    return response.json()


async def async_return[T](value: T, **_: Any) -> T:
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

    async with create_task_group() as tg:
        for index, awaitable in enumerate(aws):
            tg.start_soon(collect, index, awaitable)

    return [r for r in results if r is not MISSING]


async def as_awaitable[T](value: T | Awaitable[T]) -> T:
    return cast("T", (await value)) if isawaitable(value) else value


async def maybe_deferred[T](
    func: Callable[..., T | Awaitable[T]], *args: Any, **kwargs: object
) -> T:
    """Calls ``func`` and awaits its result only when it is awaitable."""
    return await as_awaitable(func(*args, **kwargs))


@asynccontextmanager
async def maybe_aclosing[T](iterator: T) -> AsyncGenerator[T, None]:
    """
    Closes *iterator* on exit when it has an ``aclose`` method.

    Unlike :func:`contextlib.aclosing`, an iterator without ``aclose`` (such as a
    plain async iterator) passes through untouched, so callers needn't check first.

    Args:

        iterator: The async iterator to close on exit.

    Yields:

        *iterator* itself.

    Examples:

        >>> from riko import run
        >>>
        >>> async def gen():
        ...     yield 1
        ...     yield 2
        >>>
        >>> async def main():
        ...     async with maybe_aclosing(gen()) as items:
        ...         async for item in items:
        ...             break
        ...
        ...     print(item, items.ag_running, items.ag_frame)
        >>>
        >>> run(main)
        1 False None

    """
    try:
        yield iterator
    finally:
        if (aclose := getattr(iterator, "aclose", None)) is not None:
            await aclose()


def async_partial(f, **kwargs):
    """Binds ``kwargs`` to ``f`` for later awaiting via :func:`maybe_deferred`."""
    return partial(maybe_deferred, f, **kwargs)
