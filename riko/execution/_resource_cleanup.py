# vim: sw=4:ts=4:expandtab
"""Closes the values an execution owns."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.bado._util import as_awaitable, maybe_async, require_value
from riko.base._guards import is_async_callable, is_awaitable
from riko.types._io import get_async_closer, get_sync_closer

from ._execution import asyncify_call

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from riko.types._resource import Cleanup
    from riko.types._wrappers import Func

ASYNC_CLOSE_MSG = (
    "a value whose only close is async cannot be closed under `for`; produce it "
    "with an async resource factory or lifecycle, or iterate with `async for`"
)
ASYNC_CLEANUP_MSG = (
    "an async resource cleanup runs under `for` only for a value an async factory "
    "produced; make the factory async, or iterate with `async for`"
)


def _get_closer(
    value: object, *, prefer_async: bool
) -> Callable[[], object | Awaitable[object]] | None:
    """Gets ``value``'s closer, its async one first when ``prefer_async``."""
    sync_closer, async_closer = get_sync_closer(value), get_async_closer(value)

    if prefer_async:
        closer = sync_closer if async_closer is None else async_closer
    else:
        closer = async_closer if sync_closer is None else sync_closer

    return closer


def close_owned[T](
    value: T,
    cleanup: Cleanup[T] | None = None,
    *,
    bridge: Callable[[Awaitable[object]], object] | None = None,
) -> None:
    """
    Closes an owned value without an event loop.

    A ``cleanup`` is called with the value. Otherwise the value's own close is called.
    With a ``bridge`` its async close is preferred, and any awaitable the close
    returns is awaited through the ``bridge``.

    Args:

        value: The value to close.
        cleanup: The cleanup to call with ``value`` in place of its own close.
        bridge: Runs an awaitable to completion on the event loop that owns ``value``.

    Raises:

        InvalidPipelineError: If the close returns an awaitable and there is no
            ``bridge``.

    Examples:

        >>> from io import StringIO
        >>>
        >>> f = StringIO()
        >>> close_owned(f)
        >>> f.closed
        True

    """
    if cleanup is None:
        closer = _get_closer(value, prefer_async=bridge is not None)
        result = None if closer is None else closer()
    else:
        result = cleanup(value)

    if bridge is not None and is_awaitable(result):
        bridge(result)
    else:
        require_value(result, ASYNC_CLEANUP_MSG)


async def _aclose_sync(func: Func[object], *args: object, inline: bool) -> None:
    """Closes with a sync ``func`` on the loop when ``inline``, else on a worker."""
    if inline:
        await maybe_async(func, *args)
    else:
        await as_awaitable(await asyncify_call(func, *args))


async def aclose_owned[T](
    value: T, cleanup: Cleanup[T] | None = None, *, inline: bool = True
) -> None:
    """
    Closes an owned value on the event loop.

    A ``cleanup`` is called with the value. Otherwise the value's async close is
    preferred over its sync one. An awaitable a sync close returns is awaited.

    Args:

        value: The value to close.
        cleanup: The cleanup to call with ``value`` in place of its own close.
        inline: Whether a sync close runs on the event loop rather than on a worker
            thread.

    Examples:

        >>> from io import StringIO
        >>> from riko.bado import run
        >>>
        >>> f = StringIO()
        >>> run(aclose_owned, f)
        >>> f.closed
        True

    """
    if cleanup is None:
        async_closer, sync_closer = get_async_closer(value), get_sync_closer(value)

        if async_closer is not None:
            await async_closer()
        elif sync_closer is not None:
            await _aclose_sync(sync_closer, inline=inline)
    elif is_async_callable(cleanup):
        await cleanup(value)
    else:
        await _aclose_sync(cleanup, value, inline=inline)


__all__ = ["ASYNC_CLEANUP_MSG", "ASYNC_CLOSE_MSG", "aclose_owned", "close_owned"]
