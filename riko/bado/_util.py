# vim: sw=4:ts=4:expandtab
"""
Provides utility helpers for the Riko async runtime.

Examples:

    Basic usage::

        >>> from riko import async_return, run
        >>>
        >>> run(async_return, "riko")
        'riko'

"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from inspect import iscoroutine
from math import inf
from typing import TYPE_CHECKING, Literal, overload

from attrs import define, field

from riko.base._config import settings
from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import is_async_callable, is_awaitable
from riko.base._logging import get_logger
from riko.base._sentinels import MISSING, MissingType
from riko.types._io import (
    ASYNC_CLEANUP_MSG,
    get_sync_closer,
    resolve_closer,
    resolve_user_agent,
)

from ._backend import (
    AsyncClient,
    CapacityLimiter,
    Path,
    create_task_group,
    run_from_thread,
)
from ._backend import asyncify as _asyncify

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Mapping
    from logging import Logger

    from anyio import CapacityLimiter
    from anyio.abc import TaskGroup

    from riko.types._enums import UserAgentLike
    from riko.types._wrappers import AsyncFunc, Func

    from ._backend import HTTPXResponse

logger: Logger = get_logger(__name__)


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
    timeout: float | None = settings.fetch_timeout,
    user_agent: UserAgentLike | None = None,
) -> HTTPXResponse:
    """
    Fetches ``url`` via httpx and follows redirects.

    Args:

        url: The address to fetch.

    Kwargs:

        params: Query parameters added to ``url``.

        timeout: Seconds to wait before giving up (default: ``RIKO_FETCH_TIMEOUT``,
            30 seconds). ``0``, ``inf``, or ``None`` waits forever.

        user_agent: The HTTP ``User-Agent`` to send. A ``UserAgent`` member selects an
            agent of that kind (default: "riko/<version>").

    Returns:

        The final response after any redirects.

    Raises:

        httpx.HTTPStatusError: If the final response reports a client or server error (a
            4xx or 5xx status).

    """
    resolved = None if timeout in {0, inf} else timeout
    headers = {"User-Agent": resolve_user_agent(user_agent)}

    async with AsyncClient(follow_redirects=True, headers=headers) as client:
        response = await client.get(url, params=params, timeout=resolved)
        response.raise_for_status()

    return response


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


def require_value[T](result: T | Awaitable[T], msg: str) -> T:
    """
    Requires ``result`` not to be awaitable.

    A rejected coroutine is closed before the error is raised. It is never left
    unawaited.

    Args:

        result: The call's result.
        msg: The error message for an awaitable result.

    Returns:

        ``result``.

    Raises:

        InvalidPipelineError: If ``result`` is awaitable.

    Examples:

        >>> require_value(3, "unused")
        3
        >>> require_value(async_return(3), "use `async for`")
        Traceback (most recent call last):
        ...
        riko.exceptions.InvalidPipelineError: Invalid pipeline: use `async for`

    """
    if is_awaitable(result):
        if iscoroutine(result):
            result.close()

        raise InvalidPipelineError(msg)

    return result


async def as_awaitable[T](value: T | Awaitable[T]) -> T:
    return (await value) if is_awaitable(value) else value


@define(eq=False)
class _AbandonableCall[T]:
    """A blocking call that warns when it raises after its caller stopped waiting."""

    func: Func[T]
    done: bool = field(default=False, init=False)
    abandoned: bool = field(default=False, init=False)

    def __call__(self, *args: object) -> T:
        try:
            return self.func(*args)
        except Exception:
            if self.abandoned:
                msg = "a call abandoned at cancellation raised after its caller left"
                logger.warning(msg, exc_info=True)

            raise
        finally:
            self.done = True


async def asyncify[T](
    func: Func[T | Awaitable[T]],
    *args: object,
    limiter: CapacityLimiter | None = None,
    abandon_on_cancel: bool = False,
    **kwargs: object,
) -> T:
    """
    Runs a blocking callable on a worker thread and awaits its result.

    An async ``func`` is awaited on the event loop instead. An awaitable a blocking
    ``func`` returns is awaited once the worker hands it back. With
    ``abandon_on_cancel`` set, cancelling the caller stops the wait while the worker
    finishes on its own; an error it raises afterwards is logged as a warning.

    Args:

        func: The callable to run.
        args: Positional arguments forwarded to ``func``.

    Kwargs:

        limiter: Caps the worker threads held at once, or ``None`` for the default.
        abandon_on_cancel: Whether cancellation stops the wait for a blocking ``func``.
        kwargs: Keyword arguments forwarded to ``func``.

    Returns:

        The value ``func`` returns, awaited when it is awaitable.

    Examples:

        >>> import threading
        >>> from riko import run
        >>>
        >>> get_name = lambda: threading.current_thread().name
        >>> main_name = threading.main_thread().name
        >>> run(asyncify, get_name) == main_name
        False

    """
    if is_async_callable(func):
        result = await func(*args, **kwargs)
    else:
        call = _AbandonableCall(partial(func, **kwargs))
        worker = _asyncify(call, abandon_on_cancel=abandon_on_cancel, limiter=limiter)

        try:
            returned = await worker(*args)
        finally:
            call.abandoned = not call.done

        result = await as_awaitable(returned)

    return result


def syncify[**P, T](
    func: Callable[P, Awaitable[T]], *args: P.args, **kwargs: P.kwargs
) -> T:
    """
    Runs an awaitable-returning callable to completion on the event loop from a worker.

    The worker thread must have been started from that event loop, through
    ``asyncify`` or the backend's own worker helpers. There is no fallback to a
    fresh event loop. The blocking twin of ``asyncify``.

    Args:

        func: The callable whose awaitable result is awaited on the event loop.
        args: Positional arguments forwarded to ``func``.

    Kwargs:

        kwargs: Keyword arguments forwarded to ``func``.

    Returns:

        The awaited value.

    Examples:

        >>> from riko import run
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> run(asyncify, syncify, double, 21)
        42

    """

    async def await_func() -> T:
        return await func(*args, **kwargs)

    return run_from_thread(await_func)


async def maybe_async[T](
    func: Func[T | Awaitable[T]],
    *args: object,
    inline: bool = True,
    limiter: CapacityLimiter | None = None,
    abandon_on_cancel: bool = False,
    **kwargs: object,
) -> T:
    """
    Calls ``func`` and awaits its result only when it is awaitable.

    With ``inline`` unset, a blocking ``func`` runs on a worker thread instead of the
    event loop. An async ``func`` is awaited either way.

    Args:

        func: The callable to run.
        args: Positional arguments forwarded to ``func``.

    Kwargs:

        inline: Whether a blocking ``func`` runs on the event loop.
        limiter: Caps the worker threads a non-inline call may hold.
        abandon_on_cancel: Whether cancellation stops the wait for a non-inline call.
        kwargs: Keyword arguments forwarded to ``func``.

    Returns:

        The result, awaited when ``func`` returned an awaitable.

    """
    if inline:
        result = await as_awaitable(func(*args, **kwargs))
    else:
        result = await asyncify(
            func, *args, limiter=limiter, abandon_on_cancel=abandon_on_cancel, **kwargs
        )

    return result


def run_bridged[T](
    func: Func[T | Awaitable[T]], bridge: Callable[[Awaitable[T]], T] | None = None
) -> None:
    """
    Runs ``func`` without a loop and awaits awaitable result through ``bridge``.

    Args:

        func: The value's close method or bound cleanup, from ``resolve_closer``.

    Kwargs:

        bridge: Runs an awaitable to completion on the event loop that owns the value.

    Raises:

        InvalidPipelineError: If ``func`` returns an awaitable and there is no
            ``bridge``.

    Examples:

        >>> from io import StringIO
        >>>
        >>> f = StringIO()
        >>> run_bridged(f.close)
        >>> f.closed
        True

    """
    result = func()

    if bridge is not None and is_awaitable(result):
        bridge(result)
    else:
        require_value(result, ASYNC_CLEANUP_MSG)


class maybe_closing[T]:  # noqa: N801
    """
    Closes ``value`` on exit when it has a ``close`` method.

    Unlike :func:`contextlib.closing`, a value with no closer (such as a plain
    iterator) passes through untouched. Callers needn't check first. Entering returns
    ``value``.

    Args:

        value: The value to close on exit.

    Raises:

        InvalidPipelineError: If ``value``'s ``close`` returns an awaitable since there
            is no event loop to await it on.

    Examples:

        >>> def gen():
        ...     yield 1
        ...     yield 2
        >>>
        >>> def main():
        ...     with maybe_closing(gen()) as items:
        ...         for item in items:
        ...             break
        ...
        ...     print(item, items.gi_running, items.gi_frame)
        >>>
        >>> main()
        1 False None

    """

    __slots__ = ("value",)

    def __init__(self, value: T) -> None:
        self.value = value

    def __enter__(self) -> T:
        return self.value

    def __exit__(self, *exc: object) -> None:
        closer = get_sync_closer(self.value)

        if closer is not None and (result := closer()) is not None:
            require_value(result, ASYNC_CLEANUP_MSG)


class maybe_aclosing[T: AsyncIterator[object]]:  # noqa: N801
    """
    Closes ``stream`` on exit when it has an ``aclose`` or ``close`` method.

    Unlike :func:`contextlib.aclosing`, a stream with no closer (such as a plain async
    iterator) passes through untouched. Callers needn't check first. Entering returns
    ``stream``.

    Args:

        stream: The async iterator to close on exit.

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

    __slots__ = ("stream",)

    def __init__(self, stream: T) -> None:
        self.stream = stream

    async def __aenter__(self) -> T:
        return self.stream

    async def __aexit__(self, *exc: object) -> None:
        if (closer := resolve_closer(self.stream, is_async=True)) is not None:
            await maybe_async(closer)


def async_partial[T](
    func: Func[T | Awaitable[T]], *args: object, **kwargs: object
) -> AsyncFunc[T]:
    """
    Applies ``args`` and ``kwargs`` to ``func`` for awaiting via ``maybe_async``.

    ``func``'s arguments are bound in their own partial, so a keyword of ``func`` named
    ``inline``, ``limiter``, or ``abandon_on_cancel`` never reaches ``maybe_async``.
    ``_inline`` and ``_abandon_on_cancel`` set its options instead.
    """
    inline = bool(kwargs.pop("_inline", True))
    abandon_on_cancel = bool(kwargs.pop("_abandon_on_cancel", False))

    call = partial(func, *args, **kwargs)
    return partial(
        maybe_async, call, inline=inline, abandon_on_cancel=abandon_on_cancel
    )
