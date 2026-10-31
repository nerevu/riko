# vim: sw=4:ts=4:expandtab
"""Closes the resource values an execution owns."""

from __future__ import annotations

from inspect import iscoroutine
from typing import TYPE_CHECKING, Literal, cast

from riko.bado._util import as_awaitable, maybe_async
from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import is_awaitable
from riko.types._io import is_async_closeable

from ._execution import asyncify_call

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from riko.types._io import SyncCloseable
    from riko.types._resource import Cleanup


def close_resource[T](
    cleanup: Cleanup[T] | Literal[False] | None, value: T
) -> Awaitable[None] | None:
    """
    Closes an owned resource's value.

    A ``cleanup`` override is called with the value, ``False`` leaves the value
    open, and ``None`` invokes the value's own ``close()``.

    Args:

        cleanup: The resource's cleanup override.
        value: The resource value to close.

    Returns:

        Whatever ``cleanup`` returns. A caller can await an awaitable result.

    Examples:

        >>> class Client:
        ...     closed = False
        ...     def close(self):
        ...         self.closed = True
        >>>
        >>> closed, kept = Client(), Client()
        >>> close_resource(None, closed)
        >>> close_resource(False, kept)
        >>> closed.closed, kept.closed
        (True, False)

    """
    result = None

    if cleanup is None:
        cast("SyncCloseable", value).close()
    elif cleanup is not False:
        result = cleanup(value)

    return result


async def aclose_resource[T](
    cleanup: Cleanup[T] | Literal[False] | None, value: T
) -> None:
    """
    Closes an owned resource's value with a preference of ``aclose()`` over ``close()``.

    A ``cleanup`` override is called (and awaited when async) with the value,
    ``False`` leaves the value open, and ``None`` invokes the value's own
    ``aclose()`` or ``close()``.

    Args:

        cleanup: The resource's cleanup override.
        value: The resource value to close.

    """
    if cleanup is False:
        pass
    elif cleanup is not None:
        await maybe_async(cleanup, value)
    elif is_async_closeable(value):
        await value.aclose()
    else:
        cast("SyncCloseable", value).close()


def close_with[T](cleanup: Callable[[T], object], value: T) -> None:
    """
    Closes a resource value with a sync cleanup under sync execution.

    Args:

        cleanup: The sync cleanup to call with the value.
        value: The resource value to close.

    Raises:

        InvalidPipelineError: If ``cleanup`` returns an awaitable, which a sync
            execution cannot await.

    """
    result = cleanup(value)

    if is_awaitable(result):
        if iscoroutine(result):
            result.close()

        raise InvalidPipelineError("async resource cleanup requires async execution")


async def aclose_with[T](cleanup: Callable[[T], object], value: T) -> None:
    """
    Closes a resource value with a sync cleanup on a worker thread.

    An awaitable the cleanup returns is awaited on the event loop.

    Args:

        cleanup: The sync cleanup to call with the value.
        value: The resource value to close.

    """
    await as_awaitable(await asyncify_call(cleanup, value))


__all__ = ["aclose_resource", "aclose_with", "close_resource", "close_with"]
