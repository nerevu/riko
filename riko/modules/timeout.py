# vim: sw=4:ts=4:expandtab
"""
Returns items from a stream until a certain amount of time has passed.

Contrast this with the truncate module, which also limits the number of items,
but returns items based on a count.

The sync pipe is lazy: items pass through as they arrive and the source is
abandoned once the deadline is reached. The async pipe accepts either a sync
stream or an async ``Feed`` (e.g. an async generator) and is eager — awaiting it
collects items until the deadline, so it returns only once the timeout expires
(bounding even an unbounded source) and holds every collected item in memory.

Examples:
    Basic usage::

        >>> from itertools import count
        >>> from time import sleep
        >>> from riko.modules.timeout import pipe
        >>>
        >>> def gen_stream():
        ...     for x in count():
        ...         sleep(0.1)
        ...         yield {"x": x}
        >>>
        >>> len(list(pipe(gen_stream(), conf={"milliseconds": "250"})))
        2

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from collections.abc import AsyncIterable, AsyncIterator, Generator, Iterable, Iterator
from datetime import timedelta
from logging import Logger
from time import monotonic_ns
from typing import Any, Self, cast

import pygogo as gogo

from riko.bado.itertools import async_iter
from riko.cast import BasicCastType
from riko.types._configs import TimeoutObjconf
from riko.types._options import Defaults, Opts
from riko.types._streams import Feed, Stream
from riko.types._wrappers import PipeTuples

from . import operator

OPTS: Opts = {"ptype": BasicCastType.INT}
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger

MS_PER_SECOND = 1_000
NS_PER_MS = 1_000_000


class AsyncTimeoutIterator[T](AsyncIterator[T]):
    aiter: AsyncIterator[T]
    timeout_ns: int

    def __init__(
        self, elements: AsyncIterable[T] | Iterable[T], timeout_ms: int = 0
    ) -> None:
        if isinstance(elements, AsyncIterable):
            self.aiter = aiter(elements)
        else:
            self.aiter = async_iter(elements, cooperative=True)

        self.timeout_ns = max(timeout_ms, 0) * NS_PER_MS
        self.deadline: int | None = None

    async def _collect(self) -> Iterator[T]:
        return iter([item async for item in self])

    def _raise_if_expired(self) -> None:
        if self.timeout_ns:
            now = monotonic_ns()

            if self.deadline is None:
                self.deadline = now + self.timeout_ns
            elif now >= self.deadline:
                raise StopAsyncIteration

    def __await__(self) -> Generator[None, None, Iterator[T]]:
        return self._collect().__await__()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        self._raise_if_expired()
        item = await anext(self.aiter)
        self._raise_if_expired()
        return item


class TimeoutIterator[T](Iterator[T]):
    timeout_ns: int

    def __init__(self, elements: Iterable[T], timeout_ms: int = 0) -> None:
        self.iter: Iterator[T] = iter(elements)
        self.timeout_ns = max(timeout_ms, 0) * NS_PER_MS
        self.deadline: int | None = None

    def _raise_if_expired(self) -> None:
        if self.timeout_ns:
            now = monotonic_ns()

            if self.deadline is None:
                self.deadline = now + self.timeout_ns
            elif now >= self.deadline:
                raise StopIteration

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        self._raise_if_expired()
        item = next(self.iter)
        self._raise_if_expired()
        return item


async def async_parser(
    stream: Stream | Feed, objconf: TimeoutObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Asynchronously collects items until the configured duration elapses.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming it
            will consume `tuples` as well.

        objconf: The pipe configuration, containing any ``timedelta`` unit.

        tuples: Iterable of tuples of (item, objconf) `item` is an element in the
            source stream and `objconf` is the item configuration. Note: this shares
            the `stream` iterator, so consuming it will consume `stream` as well.

    Returns:
        A sync iterator over the items collected before the deadline. Awaiting
        collects items until the timeout expires or the source ends. So an
        unbounded ``Feed`` is bounded by the deadline, and every collected item
        is held in memory. A total of 0 means no timeout.

    Examples:
        >>> from itertools import count
        >>> from riko import async_sleep, run
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"milliseconds": 250})
        >>>
        >>> async def paginated_api():
        ...     # Paginated API feed — collect records until timeout:
        ...     for page in count():
        ...         await async_sleep(0.1)
        ...         yield {"page": page, "data": f"result_{page}"}
        >>>
        >>> async def main():
        ...     result = await async_parser(paginated_api(), objconf, iter(()))
        ...     print(len(list(result)))
        >>>
        >>> run(main)
        2

    """
    td_kwargs = cast(dict[str, int], {k: objconf[k] for k in objconf if k})
    time_ms = timedelta(**td_kwargs) // timedelta(milliseconds=1)
    return await AsyncTimeoutIterator(stream, time_ms)


def parser(
    stream: Stream, objconf: TimeoutObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Yields items until the configured duration elapses.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: The pipe configuration, containing any ``timedelta`` unit.

        tuples: Iterable of tuples of (item, objconf) `item` is an element in the
            source stream and `objconf` is the item configuration. Note: this shares
            the `stream` iterator, so consuming it will consume `stream` as well.

    Returns:
        A lazy iterator that stops once the deadline passes. A total of 0 means
        no timeout.

    Examples:
        >>> from time import sleep
        >>> from meza.fntools import Objectify
        >>> from itertools import count
        >>>
        >>> objconf = Objectify({"milliseconds": 250})
        >>>
        >>> def gen_stream():
        ...     for x in count():
        ...         sleep(0.1)
        ...         yield {"x": x}
        >>>
        >>> len(list(parser(gen_stream(), objconf, iter(()))))
        2

    """
    # objconf only parses on __getitem__
    td_kwargs = cast(dict[str, int], {k: objconf[k] for k in objconf if k})
    time_ms = timedelta(**td_kwargs) // timedelta(milliseconds=1)
    return TimeoutIterator(stream, time_ms)


@operator(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously returns items from a stream until a certain amount of time has
    passed.

    Not lazy: awaiting collects items until the timeout expires and holds every
    collected item in memory. Accepts either a sync stream or an async ``Feed``
    (e.g. an async generator); an unbounded ``Feed`` is bounded by the deadline.
    Units are additive, so ``seconds`` and ``milliseconds`` together give their
    sum.

    Args:
        items (Items | Feed): The source stream.

        conf (dict): The pipe configuration. Each key is cast to an int, so a
            numeric string is accepted. A total of 0 means no timeout and the
            whole source is returned.

            days (int): Days to wait (default: 0).
            seconds (int): Seconds to wait (default: 0).
            microseconds (int): Microseconds to wait (default: 0).
            milliseconds (int): Milliseconds to wait (default: 0).
            minutes (int): Minutes to wait (default: 0).
            hours (int): Hours to wait (default: 0).
            weeks (int): Weeks to wait (default: 0).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is True
            (default: "timeout").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> from itertools import count
        >>> from riko import async_sleep, run
        >>>
        >>> async def paginated_api():
        ...     for page in count():
        ...         await async_sleep(0.1)
        ...         yield {"page": page}
        >>>
        >>> async def main():
        ...     result = await async_pipe(paginated_api(), conf={"milliseconds": 250})
        ...     print(len(list(result)))
        >>>
        >>> run(main)
        2

    """
    return await async_parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Yields items from a stream until a certain amount of time has passed.

    Lazy: items pass through as they arrive and the source is abandoned once the
    deadline is reached. Units are additive, so ``seconds`` and ``milliseconds``
    together give their sum.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration. Each key is cast to an int, so a
            numeric string is accepted. A total of 0 means no timeout and the
            whole source is returned.

            days (int): Days to wait (default: 0).
            seconds (int): Seconds to wait (default: 0).
            microseconds (int): Microseconds to wait (default: 0).
            milliseconds (int): Milliseconds to wait (default: 0).
            minutes (int): Minutes to wait (default: 0).
            hours (int): Hours to wait (default: 0).
            weeks (int): Weeks to wait (default: 0).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is True
            (default: "timeout").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> from itertools import count
        >>> from time import sleep
        >>>
        >>> def gen_stream():
        ...     for x in count():
        ...         sleep(0.1)
        ...         yield {"x": x}
        >>>
        >>> len(list(pipe(gen_stream(), conf={"milliseconds": "250"})))
        2

    """
    return parser(*args, **kwargs)
