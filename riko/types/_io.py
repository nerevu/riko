"""Path and closeable I/O typing contracts and their guards."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from typing_extensions import TypeIs

from riko.base._guards import is_async_callable, isinstance_strict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

type PathLike = str | Path
type Closeable = SyncCloseable | AsyncCloseable


@runtime_checkable
class SyncCloseable(Protocol):
    def close(self) -> object | None: ...


@runtime_checkable
class AsyncCloseable(Protocol):
    async def aclose(self) -> object | None: ...


PathLikeType: tuple[type[str], type[Path]] = (str, Path)


def is_sync_closeable(val: object) -> TypeIs[SyncCloseable]:
    return isinstance_strict(val, SyncCloseable)


def is_async_closeable(val: object) -> TypeIs[AsyncCloseable]:
    return isinstance_strict(val, AsyncCloseable)


def is_closeable(val: object) -> TypeIs[Closeable]:
    return is_sync_closeable(val) or is_async_closeable(val)


def get_sync_closer(value: object) -> Callable[[], object] | None:
    """
    Gets the method that closes ``value`` without an event loop.

    An async def ``close`` is rejected.

    Args:

        value: The value to inspect.

    Returns:

        The value's synchronous ``close``, or ``None`` when it has none.

    Examples:

        >>> from io import StringIO
        >>>
        >>> f = StringIO()
        >>> get_sync_closer(f)()
        >>> f.closed, get_sync_closer(1)
        (True, None)

    """
    closer = None

    if is_sync_closeable(value) and not is_async_callable(value.close):
        closer = value.close

    return closer


def get_async_closer(value: object) -> Callable[[], Awaitable[object]] | None:
    """
    Gets the method that closes ``value`` on an event loop.

    ``aclose`` is preferred over an async def ``close``.

    Args:

        value: The value to inspect.

    Returns:

        The value's ``aclose`` or async ``close``, or ``None`` when it has neither.

    Examples:

        >>> class Client:
        ...     async def close(self):
        ...         pass
        >>>
        >>> get_async_closer(Client()).__name__, get_async_closer(1)
        ('close', None)

    """
    closer = None

    if is_async_closeable(value):
        closer = value.aclose
    elif is_sync_closeable(value) and is_async_callable(value.close):
        closer = value.close

    return closer
