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
from typing import TYPE_CHECKING, Literal, Self, TypedDict, Unpack, cast, overload

from attrs import define, evolve, field

from riko.base._config import settings
from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import (
    ASYNC_CLEANUP_MSG,
    ASYNC_CLOSE_MSG,
    get_async_closer,
    get_sync_closer,
    is_async_callable,
    is_awaitable,
    require_value,
)
from riko.base._logging import get_logger
from riko.base._require_guards import as_timeout, require_timeout
from riko.base._sentinels import MISSING, MissingType
from riko.types._io import resolve_closer, resolve_user_agent

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
    timeout: float = settings.fetch_timeout,
    user_agent: UserAgentLike | None = None,
) -> HTTPXResponse:
    """
    Fetches ``url`` via httpx and follows redirects.

    Args:

        url: The address to fetch.

    Kwargs:

        params: Query parameters added to ``url``.

        timeout: Seconds to wait before giving up (default: ``RIKO_FETCH_TIMEOUT``,
            30 seconds). ``inf`` waits forever.

        user_agent: The HTTP ``User-Agent`` to send. A ``UserAgent`` member selects an
            agent of that kind (default: "riko/<version>").

    Returns:

        The final response after any redirects.

    Raises:

        ValueError: If ``timeout`` is 0, negative, or NaN.

        httpx.HTTPStatusError: If the final response reports a client or server error (a
            4xx or 5xx status).

    """
    _timeout = as_timeout(require_timeout(timeout))
    headers = {"User-Agent": resolve_user_agent(user_agent)}

    async with AsyncClient(follow_redirects=True, headers=headers) as client:
        response = await client.get(url, params=params, timeout=_timeout)
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


async def async_json(response: HTTPXResponse) -> dict[str, object]:  # noqa: RUF029 (async by contract)
    """Parses the JSON body of ``response``."""
    return response.json()


async def async_return[T](value: T, **_: object) -> T:  # noqa: RUF029 (async by contract)
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


class _RunnerOptions(TypedDict, total=False):
    """The execution settings ``async_runner.using`` may change."""

    inline: bool
    limiter: CapacityLimiter | None
    abandon_on_cancel: bool


@define(frozen=True, kw_only=True)
class async_runner:  # noqa: N801
    """
    Calls a sync or async callable and awaits its result if it is awaitable.

    An async callable is always awaited on the event loop. A blocking one runs on the
    event loop when ``inline`` is set, and on a worker thread otherwise. An awaitable a
    blocking callable returns is awaited once it is handed back.

    Arguments given to a call or to ``partial`` always belong to the callee. Only the
    constructor and ``using`` change how the call runs. ``maybe_async`` is the inline
    runner and ``asyncify`` the worker-thread one.

    Kwargs:

        inline: Whether a blocking callable runs on the event loop.

        limiter: Caps the number of worker threads a non-inline call may hold. ``None``
            uses the default.

        abandon_on_cancel: Whether cancelling the caller abandons a worker-thread call.
            If set, the worker finishes on its own. Any error it raises afterwards is
            logged as a warning.

    Examples:

        >>> import threading
        >>> from riko import run
        >>>
        >>> def locate(value, inline=None):
        ...     on_main = threading.current_thread() is threading.main_thread()
        ...     return f"{value=}, {inline=}, {on_main=}"
        >>>
        >>> async def main():
        ...     print(await maybe_async(locate, 1))
        ...     print(await maybe_async.using(inline=False)(locate, 2))
        ...     print(await asyncify(locate, 3, inline="callee"))
        ...
        ...     call = async_partial(locate, inline="bound")
        ...     print(await call(4))
        >>>
        >>> run(main)
        value=1, inline=None, on_main=True
        value=2, inline=None, on_main=False
        value=3, inline='callee', on_main=False
        value=4, inline='bound', on_main=True

    """

    inline: bool = True
    limiter: CapacityLimiter | None = None
    abandon_on_cancel: bool = False

    async def __call__[T, **P](
        self, func: Callable[P, T | Awaitable[T]], /, *args: P.args, **kwargs: P.kwargs
    ) -> T:
        """
        Runs ``func`` with the given arguments and awaits its result.

        Args:

            func: The callable to run.
            args: Positional arguments passed to ``func``.

        Kwargs:

            kwargs: Keyword arguments passed to ``func``.

        Returns:

            The value ``func`` returns. It is awaited when awaitable.

        """
        if self.inline:
            result = await as_awaitable(func(*args, **kwargs))
        elif is_async_callable(func):
            result = await func(*args, **kwargs)
        else:
            call = _AbandonableCall(partial(func, **kwargs))
            cancels = self.abandon_on_cancel
            worker = _asyncify(call, abandon_on_cancel=cancels, limiter=self.limiter)

            try:
                returned = await worker(*args)
            finally:
                call.abandoned = not call.done

            result = await as_awaitable(returned)

        return result

    def using(self, **options: Unpack[_RunnerOptions]) -> Self:
        """
        Builds a runner with ``options`` in place of its current settings.

        Kwargs:

            options: The settings to change (the rest are kept).

        Returns:

            The reconfigured runner.

        """
        return evolve(self, **options)

    def partial[T](
        self, func: Callable[..., T | Awaitable[T]], /, *args: object, **kwargs: object
    ) -> AsyncFunc[T]:
        """
        Builds a deferred call of ``func`` that this runner awaits.

        Args:

            func: The callable to run.
            args: Positional arguments passed to ``func``.

        Kwargs:

            kwargs: Keyword arguments passed to ``func``.

        Returns:

            An async callable taking ``func``'s remaining arguments.

        """
        return cast("AsyncFunc[T]", partial(self.__call__, func, *args, **kwargs))


maybe_async = async_runner()
asyncify = async_runner(inline=False)
async_partial = maybe_async.partial


@overload
def syncify[T](func: Awaitable[T], /) -> T: ...
@overload
def syncify[T, **P](
    func: Callable[P, Awaitable[T]], /, *args: P.args, **kwargs: P.kwargs
) -> T: ...
def syncify[T, **P](
    func: Awaitable[T] | Callable[P, Awaitable[T]], /, *args: P.args, **kwargs: P.kwargs
) -> T:
    """
    Runs an awaitable-returning callable to completion on the event loop from a worker.

    A bare awaitable is only awaited. The worker thread must have been started from
    that event loop, through ``asyncify`` or the backend's own worker helpers. There is
    no fallback to a fresh event loop. The blocking twin of ``asyncify``.

    Args:

        func: The callable whose awaitable result is awaited on the event loop, or an
            awaitable to await directly.

        args: Positional arguments forwarded to a callable ``func``.

    Kwargs:

        kwargs: Keyword arguments forwarded to a callable ``func``.

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
        >>> run(asyncify, syncify, double(4))
        8

    """

    async def await_func() -> T:
        if callable(func):
            result = await func(*args, **kwargs)
        else:
            result = await func

        return result

    return run_from_thread(await_func)


def run_bridged[T](
    func: Func[T | Awaitable[T]], bridge: Callable[[Awaitable[T]], T] | None = None
) -> None:
    """
    Runs ``func`` without a loop and awaits awaitable result through ``bridge``.

    Args:

        func: The value's close method or bound cleanup, from ``resolve_closer``.

    Kwargs:

        bridge: Runs an awaitable to completion on the event loop the value runs on.

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


async def amap_values[K, V, R](
    func: Callable[[V], Awaitable[R]], item: Mapping[K, V]
) -> dict[K, R]:
    """
    Applies an async function to each mapping value.

    Args:

        func: The async transform applied to each value.
        item: The source mapping.

    Returns:

        A new dict with the same keys, in the same order, holding the awaited
        transformed values.

    Examples:

        >>> from riko import run
        >>>
        >>> async def double(value):
        ...     return value * 2
        >>>
        >>> run(amap_values, double, {"a": 1, "b": 2})
        {'a': 2, 'b': 4}

    """
    return {key: await func(value) for key, value in item.items()}


class maybe_closing[T]:  # noqa: N801
    """
    Closes ``value`` on exit when it has a ``close`` method.

    Unlike :func:`contextlib.closing`, a value with no closer (such as a plain
    iterator) passes through untouched. Callers needn't check first. Entering returns
    ``value``.

    Args:

        value: The value to close on exit.

    Raises:

        InvalidPipelineError: If ``value`` can only close asynchronously, or its
            ``close`` returns an awaitable, since there is no event loop to await it on.

    Examples:

        >>> def gen():
        ...     yield 1
        ...     yield 2
        >>>
        >>> def main():
        ...     with maybe_closing(gen()) as stream:
        ...         for item in stream:
        ...             break
        ...
        ...     print(item, stream.gi_running, stream.gi_frame)
        >>>
        >>> main()
        1 False None

    """

    __slots__ = ("value",)

    def __init__(self, value: T) -> None:
        self.value = value

        if get_sync_closer(value) is None and get_async_closer(value) is not None:
            raise InvalidPipelineError(ASYNC_CLOSE_MSG)

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
