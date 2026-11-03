"""Path and closeable I/O typing contracts and their closer getters."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import is_async_callable, isinstance_strict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ._resource import Cleanup
    from ._wrappers import Func

type PathLike = str | Path
type Closeable = SyncCloseable | AsyncCloseable
type Closer = Func[object | Awaitable[object]]

ASYNC_CLOSE_MSG = (
    "a value whose only close is async cannot be closed under `for`; produce it "
    "with an async resource factory or lifecycle, or iterate with `async for`"
)
ASYNC_CLEANUP_MSG = (
    "an async resource cleanup runs under `for` only for a value an async factory "
    "produced; make the factory async, or iterate with `async for`"
)


@runtime_checkable
class SyncCloseable(Protocol):
    def close(self) -> object | None: ...


@runtime_checkable
class AsyncCloseable(Protocol):
    async def aclose(self) -> object | None: ...


PathLikeType: tuple[type[str], type[Path]] = (str, Path)


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

    if isinstance_strict(value, SyncCloseable) and not is_async_callable(value.close):
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

    if isinstance_strict(value, AsyncCloseable):
        closer = value.aclose
    elif isinstance_strict(value, SyncCloseable) and is_async_callable(value.close):
        closer = value.close

    return closer


def resolve_closer[T](
    value: T,
    cleanup: Cleanup[T] | Literal[False] | None = None,
    *,
    is_async: bool | None = None,
) -> Closer | None:
    """
    Resolves the way an owner closes ``value``, if any.

    A ``cleanup`` is bound to the value in place of its own close. Under a sync owner
    (``is_async=False``) an async cleanup, or a value whose only close is async, is
    rejected. An async owner (``True``) prefers the async close. An owner of either
    kind (``None``) prefers the sync one.

    Args:

        value: The owned value.
        cleanup: The cleanup to call with ``value``, ``False`` to leave it open, or
            ``None`` for the value's own close.
        is_async: Whether the owner closes on an event loop, or ``None`` for either.

    Returns:

        The closer to call, or ``None`` when ``cleanup`` is ``False`` or the value
        has no close.

    Raises:

        InvalidPipelineError: If a sync owner would need an event loop to close
            ``value`` or run ``cleanup``.

    Examples:

        >>> class Client:
        ...     def close(self):
        ...         pass
        ...     async def aclose(self):
        ...         pass
        >>>
        >>> resolve_closer(Client(), is_async=True).__name__
        'aclose'
        >>> resolve_closer(Client()).__name__
        'close'
        >>> resolve_closer(Client(), False)
        >>> resolve_closer(1)

    """
    if cleanup is False:
        closer = None
    elif cleanup is not None:
        if is_async is False and is_async_callable(cleanup):
            raise InvalidPipelineError(ASYNC_CLEANUP_MSG)

        closer = partial(cleanup, value)
    elif is_async is False:
        closer = get_sync_closer(value)

        if closer is None and get_async_closer(value) is not None:
            raise InvalidPipelineError(ASYNC_CLOSE_MSG)
    else:
        sync_closer, async_closer = get_sync_closer(value), get_async_closer(value)

        if is_async:
            closer = sync_closer if async_closer is None else async_closer
        else:
            closer = async_closer if sync_closer is None else sync_closer

    return closer


def require_closer[T](
    value: T,
    cleanup: Cleanup[T] | Literal[False] | None = None,
    *,
    is_async: bool | None = None,
) -> Closer | None:
    """
    Requires a way to close an owned resource value, and gets it.

    The closer is chosen as ``resolve_closer`` does; a value with no close and no
    ``cleanup`` is an error here rather than a value left open.

    Args:

        value: The owned resource value.
        cleanup: The cleanup to call with ``value``, ``False`` to leave it open, or
            ``None`` for the value's own close.
        is_async: Whether the owner closes on an event loop, or ``None`` for either.

    Returns:

        The closer to call, or ``None`` when ``cleanup`` is ``False``.

    Raises:

        TypeError: If the value has no close and no ``cleanup`` is given.
        InvalidPipelineError: If a sync owner would need an event loop to close
            ``value`` or run ``cleanup``.

    Examples:

        >>> from io import StringIO
        >>>
        >>> require_closer(StringIO()).__name__
        'close'
        >>> require_closer(StringIO(), False)
        >>> require_closer(1)
        Traceback (most recent call last):
        ...
        TypeError: Must provide a Closeable value or cleanup function ...

    """
    closer = resolve_closer(value, cleanup, is_async=is_async)

    if cleanup is not False and closer is None:
        msg = "Must provide a Closeable value or cleanup function for riko owned "
        msg += f"resources. Not a {type(value).__name__}. If this value's lifecycle is "
        msg += "externally managed, use Resource.from_external(...) instead."
        raise TypeError(msg)

    return closer
