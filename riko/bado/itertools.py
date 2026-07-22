# vim: sw=4:ts=4:expandtab
"""
Provides asynchronous ports of various builtin itertools functions.

Examples:
    basic usage::

        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.bado.itertools import async_map, async_reduce, async_broadcast
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def square(x):
        ...     return x ** 2
        >>>
        >>> async def run(reactor):
        ...     mapped = await async_map(double, range(3))
        ...     reduced = await async_reduce(lambda x, y: x + y, range(5))
        ...     broadcast = await async_broadcast(4, double, square)
        ...     print(mapped, reduced, broadcast)
        >>>
        >>> if _issync:
        ...     print([0, 2, 4], 10, [8, 16])
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        [0, 2, 4] 10 [8, 16]

"""

from collections.abc import Awaitable, Callable, Coroutine, Iterable
from functools import partial
from inspect import isawaitable, iscoroutine
from itertools import repeat, starmap
from typing import (
    TYPE_CHECKING,
    Any,
    TypeVar,
    TypeVarTuple,
    Union,
    Unpack,
    cast,
    overload,
)

from riko import bado
from riko.bado import defer, gather_results, real_task
from riko.bado.mock import FakeReactor

if TYPE_CHECKING:
    from twisted.internet.defer import Deferred
    from twisted.internet.task import Cooperator

T = TypeVar("T")
S = TypeVar("S")
Ts = TypeVarTuple("Ts")


def get_task() -> "Cooperator":
    """
    Returns a Cooperator for scheduling cooperative async work.

    Uses a :class:`~riko.bado.mock.FakeReactor`-backed scheduler when
    ``reactor.fake`` is ``True`` (i.e. during tests), otherwise returns a
    real :class:`twisted.internet.task.Cooperator`.

    Returns:
        Cooperator: A Twisted Cooperator instance.

    Examples:
        >>> from riko.bado import _issync
        >>> if _issync:
        ...     True
        ... else:
        ...     from twisted.internet.task import Cooperator
        ...     isinstance(get_task(), Cooperator)
        True

    """
    if bado.reactor.fake:
        scheduler = partial(FakeReactor().callLater, FakeReactor._DELAY)
        task = real_task.Cooperator(scheduler=scheduler)
    else:
        task = real_task.Cooperator()

    return task


async def coop_reduce[T, S](
    func: Callable[[T, S], T], content: Iterable[S], initial: T | None = None
) -> T | S | None:
    """
    Reduces *iterable* with *func* using Twisted cooperative multitasking.

    Each reduction step yields control back to the reactor so other async
    work can proceed between steps.

    Args:
        func (callable): A two-argument reducer, e.g. ``lambda x, y: x + y``.
        iterable (Iterable): The sequence to reduce.
        initializer (Any): Starting accumulator value. When ``None`` (default)
            the first element of *iterable* is consumed as the seed.

    Returns:
        Awaitable[Any]: The final accumulated value.

    Examples:
        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     result = await coop_reduce(lambda x, y: x + y, range(5))
        ...     print(result)
        >>>
        >>> if _issync:
        ...     10
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        10

    """
    task = get_task()
    content = iter(content)
    value = next(content) if initial is None else initial
    result = {"value": value}

    def work(func, content, value):
        for item in content:
            result["value"] = value = func(value, item)
            yield

    _task = task.cooperate(work(func, content, value))
    await _task.whenDone()
    return result["value"]


def async_reduce[T, S](
    func: Callable[[T, S], T | Awaitable[T]],
    content: Iterable[S],
    initial: T | None = None,
) -> Awaitable[T]:
    """
    Reduces *iterable* with *func*, which may be sync or async.

    Unlike :func:`coop_reduce`, this does not yield between steps; the entire
    reduction runs in a single pass. The reducer is awaited only when it
    returns an awaitable (checked via :func:`inspect.isawaitable`).

    Args:
        func (callable): A two-argument reducer that may return a plain
            value or an awaitable.

        iterable (Iterable): The sequence to reduce.
        initializer (Any): Starting accumulator value. When ``None`` (default)
            the first element of *iterable* is consumed as the seed.

    Returns:
        Awaitable[Any]: The final accumulated value.

    Examples:
        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     result = await async_reduce(lambda x, y: x + y, range(5))
        ...     print(result)
        >>>
        >>> if _issync:
        ...     10
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        10

    """
    content = iter(content)
    value = next(content) if initial is None else initial

    async def work(async_func, content, value):
        for item in content:
            result = async_func(value, item)
            value = (await result) if isawaitable(result) else result

        return value

    return work(func, content, value)


async def _wrap[S](result: Awaitable[S]) -> S:
    """
    Awaits a general awaitable and returns its result as a coroutine.

    :func:`~twisted.internet.defer.ensureDeferred` only accepts coroutines or
    Deferreds — not arbitrary awaitables (e.g. objects that implement
    ``__await__`` without being a coroutine). This shim bridges the gap by
    wrapping any awaitable in a proper coroutine that ``ensureDeferred`` can
    consume, enabling objects like :class:`~riko.collections.AsyncPipe` to be
    passed through the Twisted Deferred machinery.

    Args:
        result (Awaitable[S]): Any awaitable, including objects whose class
            defines ``__await__`` (such as :class:`~riko.collections.AsyncPipe`).

    Returns:
        S: The value produced by awaiting *result*.

    Examples:
        >>> from inspect import iscoroutine
        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> class AwaitableBox:
        ...     def __init__(self, val):
        ...         self._val = val
        ...
        ...     def __await__(self):
        ...         async def inner():
        ...             return self._val
        ...
        ...         return inner().__await__()
        >>>
        >>> iscoroutine(AwaitableBox(42))
        False
        >>> c = _wrap(AwaitableBox(42))
        >>> iscoroutine(c)
        True
        >>> c.close()

    """
    return await result


@overload
def ensure_deferred(result: "Deferred[S]") -> "Deferred[S]": ...  # noqa: E704
@overload  # noqa: E302
def ensure_deferred[S](  # noqa: E704
    result: Coroutine[Any, Any, S],
) -> "Deferred[S]": ...
@overload
def ensure_deferred[S](result: Awaitable[S]) -> "Deferred[S]": ...  # noqa: E704
def ensure_deferred[S](  # noqa: E302
    result: Union["Deferred[S]", Coroutine[Any, Any, S], Awaitable[S]],
) -> "Deferred[S]":
    """
    Wraps *result* in a Twisted Deferred if it is not already one.

    Handles three cases in order:

    - **Deferred**: returned unchanged.
    - **Coroutine** (result of an ``async def`` call): wrapped via
      :func:`~twisted.internet.defer.ensureDeferred`.
    - **General awaitable** (object with ``__await__`` but not a coroutine,
      e.g. :class:`~riko.collections.AsyncPipe`): first wrapped in
      :func:`_wrap` to produce a coroutine, then passed to ``ensureDeferred``.

    Args:
        result (Deferred[S] | Awaitable[S]): The value to wrap.

    Returns:
        Deferred[S]: A Deferred that resolves to the awaited value, or
            *result* unchanged if it is already a Deferred.

    Examples:
        >>> from inspect import iscoroutine, isawaitable
        >>> from riko.bado import _issync
        >>> from twisted.internet.defer import Deferred
        >>>
        >>> async def coro():
        ...     return 42
        >>>
        >>> class AwaitableBox:
        ...     def __init__(self, val):
        ...         self._val = val
        ...
        ...     def __await__(self):
        ...         async def inner():
        ...             return self._val
        ...
        ...         return inner().__await__()
        >>>
        >>> if _issync:
        ...     True
        ...     False
        ...     True
        ... else:
        ...     isinstance(ensure_deferred(Deferred()), Deferred)
        ...     c = coro(); isinstance(c, Deferred); c.close()
        ...     isinstance(ensure_deferred(coro()), Deferred)
        True
        False
        True
        >>>
        >>> if _issync:
        ...     True
        ...     False
        ... else:
        ...     box = AwaitableBox(42)
        ...     isinstance(box, Deferred)
        ...     isinstance(ensure_deferred(box), Deferred)
        False
        True

    """
    if isinstance(result, defer.Deferred):
        deferred = result
    elif iscoroutine(result):
        deferred = defer.ensureDeferred(result)
    elif isawaitable(result):
        deferred = defer.ensureDeferred(_wrap(result))
    else:
        raise TypeError(f"Result {result} is not awaitable or Deferred")

    return deferred


async def async_map[T, S](
    func: Callable[[T], Awaitable[S]],
    content: Iterable[T],
    connections: int = 0,
    **kwargs: Any,
) -> list[S]:
    """
    Maps *async_func* over *iterable* concurrently.

    *async_func* may be any async callable. Its return value is wrapped via
    :func:`ensure_deferred` as needed. Items are processed up to *connections*
    workers at a time via cooperative multitasking. If no *connections* are specified,
    all calls are issued at once and their results gathered in order.

    Args:
        async_func (callable): An async function applied to each element.
        iterable (Iterable): The items to map over.
        connections (int): Maximum number of concurrent workers. ``0`` (default)
            runs all at once via ``gatherResults``.
        **kwargs: Extra keyword arguments forwarded to *async_func*.

    Returns:
        Awaitable[list]: A list of results in iteration order.

    Examples:
        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def run(reactor):
        ...     result = await async_map(double, range(3))
        ...     print(result)
        >>>
        >>> if _issync:
        ...     [0, 2, 4]
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        [0, 2, 4]

    """
    if connections and not bado.reactor.fake:
        results = []
        work = (
            ensure_deferred(func(item, **kwargs)).addCallback(results.append)
            for item in content
        )
        deferreds = [get_task().coiterate(work) for _ in range(connections)]
        await gather_results(deferreds, consumeErrors=True)
    else:
        _func = partial(func, **kwargs)
        deferreds = [ensure_deferred(_func(item)) for item in content]
        results = await gather_results(deferreds, consumeErrors=True)

    return cast(list[S], results)


def async_starmap[*Ts, S](
    func: Callable[[Unpack[Ts]], Awaitable[S]],
    content: Iterable[tuple[*Ts]],
) -> Awaitable[list[S]]:
    """
    :func:`itertools.starmap` for async callables.

    Each ``(arg1, arg2, ...)`` tuple from *iterable* is unpacked and passed to
    *async_func*. All results are gathered concurrently.

    Args:
        async_func (callable): An async function that accepts unpacked tuple
            arguments.
        iterable (Iterable[tuple]): An iterable of argument tuples.

    Returns:
        Awaitable[list]: A list of results in iteration order.

    Examples:
        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def add(x, y):
        ...     return x + y
        >>>
        >>> async def run(reactor):
        ...     result = await async_starmap(add, [(1, 2), (3, 4)])
        ...     print(result)
        >>>
        >>> if _issync:
        ...     [3, 7]
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        [3, 7]

    """
    deferreds = [ensure_deferred(d) for d in starmap(func, content)]
    return gather_results(deferreds, consumeErrors=True)


def async_dispatch[T, S](
    split: Iterable[T], *funcs: Callable[[T], Awaitable[S]], **kwargs: Any
) -> Awaitable[list[S]]:
    """
    Dispatches each item in *split* to the corresponding function in *async_funcs*.

    Pairs ``split[i]`` with ``async_funcs[i]`` and calls each pair via
    :func:`async_starmap`. Shorter of the two sequences determines the number
    of calls (``zip`` semantics with ``strict=False``).

    Args:
        split (Iterable): Items to dispatch, one per function.
        *async_funcs (callable): Async functions, each receiving one item.

    Returns:
        Awaitable[list]: A list of results in iteration order.

    Examples:
        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def negate(x):
        ...     return -x
        >>>
        >>> async def run(reactor):
        ...     result = await async_dispatch([4, 5], double, negate)
        ...     print(result)
        >>>
        >>> if _issync:
        ...     [8, -5]
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        [8, -5]

    """
    return async_starmap(lambda item, f: f(item), zip(split, funcs, strict=False))


def async_broadcast[T, S](
    item: T, *funcs: Callable[[T], Awaitable[S]], **kwargs: Any
) -> Awaitable[list[S]]:
    """
    Broadcasts *item* to every function in *async_funcs* concurrently.

    Each function in *async_funcs* receives the same *item*. Results are
    gathered via :func:`async_dispatch`.

    Args:
        item (Any): The value to pass to every function.
        *async_funcs (callable): Async functions that each receive *item*.

    Returns:
        Awaitable[list]: A list of results in iteration order.

    Examples:
        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def double(x):
        ...     return x * 2
        >>>
        >>> async def triple(x):
        ...     return x * 3
        >>>
        >>> async def run(reactor):
        ...     result = await async_broadcast(5, double, triple)
        ...     print(result)
        >>>
        >>> if _issync:
        ...     [10, 15]
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        [10, 15]

    """
    return async_dispatch(repeat(item), *funcs, **kwargs)
