# vim: sw=4:ts=4:expandtab
"""Closes the resource values an execution owns."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from riko.bado._util import maybe_async
from riko.types._io import is_async_closeable

if TYPE_CHECKING:
    from riko.types._io import SyncCloseable
    from riko.types._resource import Cleanup


def close_resource[T](cleanup: Cleanup[T] | Literal[False] | None, value: T) -> None:
    """
    Closes an owned resource's value.

    A ``cleanup`` override is called with the value, ``False`` leaves the value
    open, and ``None`` invokes the value's own ``close()``.

    Args:

        cleanup: The resource's teardown override.
        value: The resource value to close.

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
    if cleanup is False:
        pass
    elif cleanup is None:
        cast("SyncCloseable", value).close()
    else:
        cleanup(value)


async def aclose_resource[T](
    cleanup: Cleanup[T] | Literal[False] | None, value: T
) -> None:
    """
    Closes an owned resource's value with a preference of ``aclose()`` over ``close()``.

    A ``cleanup`` override is called (and awaited when async) with the value,
    ``False`` leaves the value open, and ``None`` invokes the value's own
    ``aclose()`` or ``close()``.

    Args:

        cleanup: The resource's teardown override.
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


__all__ = ["aclose_resource", "close_resource"]
