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
from typing import TYPE_CHECKING, Literal, overload

from riko.base._guards import is_awaitable
from riko.base._sentinels import MISSING, MissingType

from ._backend import USE_CLIENT_DEFAULT, AsyncClient, Path, create_task_group

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Mapping

    from anyio.abc import TaskGroup
    from httpx._client import UseClientDefault

    from ._backend import HTTPXResponse


@asynccontextmanager
async def open_task_group() -> AsyncGenerator[TaskGroup, None]:
    """
    Opens a task group that raises a lone failure as itself.

    Several failures still arrive together as an ``ExceptionGroup``.

    Examples:

        >>> from riko import run
        >>>
        >>> async def fail():
        ...     raise ValueError("bad")
        >>>
        >>> async def main():
        ...     async with open_task_group() as tg:
        ...         tg.start_soon(fail)
        >>>
        >>> run(main)
        Traceback (most recent call last):
        ValueError: bad

    """
    error: BaseException | None = None

    try:
        async with create_task_group() as tg:
            yield tg
    except BaseExceptionGroup as group:
        if len(group.exceptions) != 1:
            raise

        error = group.exceptions[0]

    if error is not None:
        raise error


async def async_get(
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    timeout: float | UseClientDefault | None = USE_CLIENT_DEFAULT,
) -> HTTPXResponse:
    """
    Fetches ``url`` via httpx and follows redirects.

    Args:

        url: The address to fetch.

    Kwargs:

        params: Query parameters added to ``url``.
        timeout: Seconds to wait before giving up (default: the client's timeout).
            ``0`` or ``None`` means no timeout, which mirrors the sync backend.

    Returns:

        The final response after any redirects.

    """
    resolved = None if timeout == 0 else timeout

    async with AsyncClient(follow_redirects=True) as client:
        return await client.get(url, params=params, timeout=resolved)


@overload
async def async_read(
    url: str, binary: Literal[True], encoding: str | None = ...
) -> bytes: ...
@overload
async def async_read(
    url: str, binary: Literal[False] = ..., encoding: str | None = ...
) -> str: ...
async def async_read(
    url: str, binary: bool = False, encoding: str | None = None
) -> bytes | str:
    """Reads a local ``file://`` path as bytes or text."""
    path = Path(url.replace("file://", ""))
    return await (path.read_bytes() if binary else path.read_text(encoding))


async def async_json(response: HTTPXResponse) -> dict[str, object]:
    """Parses the JSON body of ``response``."""
    return response.json()


async def async_return[T](value: T, **_: object) -> T:
    """Wraps ``value`` in an awaitable, for uniform ``await`` call sites."""
    return value


async def gather_results[T](awaitables: Iterable[Awaitable[T]], **_: object) -> list[T]:
    """
    Runs ``awaitables`` concurrently, returning results in submission order.

    A legitimate ``None`` result is preserved (the unfilled slot is marked with
    ``MISSING``, not ``None``), so the output aligns with the inputs.

    """
    aws = list(awaitables)
    results: list[T | MissingType] = [MISSING] * len(aws)

    async def collect(index: int, awaitable: Awaitable[T]) -> None:
        results[index] = await awaitable

    async with open_task_group() as tg:
        for index, awaitable in enumerate(aws):
            tg.start_soon(collect, index, awaitable)

    return [r for r in results if not isinstance(r, MissingType)]


async def as_awaitable[T](value: T | Awaitable[T]) -> T:
    return (await value) if is_awaitable(value) else value


async def maybe_async[T](
    func: Callable[..., T | Awaitable[T]], *args: object, **kwargs: object
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


def async_partial[T](
    func: Callable[..., T | Awaitable[T]], **kwargs
) -> Callable[..., Awaitable[T]]:
    """Applies ``kwargs`` to ``func`` for later awaiting via :func:`maybe_async`."""
    return partial(maybe_async, func, **kwargs)
