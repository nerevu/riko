# vim: sw=4:ts=4:expandtab
"""
Provides functions for returning items from a stream until a certain amount of
time has passed.

Contrast this with the truncate module, which also limits the number of items,
but returns items based on a count.

Examples:
    basic usage::

        >>> from itertools import count
        >>> from time import sleep
        >>> from riko.modules.timeout import pipe
        >>>
        >>> def gen_stream():
        ...     for x in count():
        ...         sleep(0.1)
        ...         yield {'x': x}
        >>>
        >>> len(list(pipe(gen_stream(), conf={'milliseconds': '250'})))
        3

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import threading
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Generator,
    Iterable,
    Iterator,
)
from datetime import timedelta
from typing import Self, TypeVar, cast

import pygogo as gogo

from riko import Objconf
from riko.bado.itertools import ensure_deferred
from riko.bado.util import async_sleep
from riko.cast import BasicCastType
from riko.types.general import Defaults, Opts, PipeTuples, Stream
from riko.types.values import ComplexArg

from . import operator

OPTS: Opts = {"ptype": BasicCastType.INT}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger

items = ("days", "hours", "microseconds", "milliseconds", "minutes", "seconds", "weeks")

T = TypeVar("T", bound=ComplexArg)


class AsyncTimeoutIterator(AsyncIterator[T]):
    def __init__(
        self, elements: AsyncIterable[T] | Iterable[T], timeout: float = 0
    ) -> None:
        if isinstance(elements, AsyncIterable):
            self.aiter = aiter(elements)
        else:
            self.aiter = self._async_iter_sync(elements)

        self.timeout = timeout
        self.timed_out = False
        ensure_deferred(self._expire())

    async def _async_iter_sync(self, elements: Iterable[T]) -> AsyncGenerator[T, None]:
        for item in elements:
            await async_sleep(0)
            yield item

    async def _expire(self) -> None:
        await async_sleep(self.timeout)
        self.timed_out = True

    async def _collect(self) -> Iterator[T]:
        return iter([item async for item in self])

    def __await__(self) -> Generator[None, None, Iterator[T]]:
        return self._collect().__await__()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        if self.timed_out:
            raise StopAsyncIteration
        else:
            return await anext(self.aiter)


class TimeoutIterator(Iterator[T]):
    def __init__(self, elements: Iterable[T], timeout: float = 0) -> None:
        self.iter: Iterator[T] = iter(elements)
        self.timeout = timeout
        self.timedout: bool = False
        self.started: bool = False
        self._timer: threading.Timer | None = None

    def _expire(self) -> None:
        self.timedout = True

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        if self.timedout:
            raise StopIteration
        elif not self.started:
            if self.timeout:
                self._timer = threading.Timer(self.timeout, self._expire)
                self._timer.daemon = True
                self._timer.start()
            self.started = True

        try:
            return next(self.iter)
        except StopIteration:
            if self._timer:
                self._timer.cancel()
            self.timedout = True
            raise


async def async_parser(
    stream: Stream, objconf: Objconf, tuples: PipeTuples, **kwargs
) -> Stream:
    """
    Asynchronously parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf (obj): the item independent configuration (an Objectify
            instance).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Returns:
        Iter(dict): The output stream

    Examples:
        >>> from itertools import count
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.bado.util import async_sleep
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({'milliseconds': 250})
        >>>
        >>> async def paginated_api():
        ...     # Paginated API feed — collect records until timeout:
        ...     for page in count():
        ...         await async_sleep(0.1)
        ...         yield {'page': page, 'data': f'result_{page}'}
        >>>
        >>> async def run(reactor):
        ...     result = await async_parser(paginated_api(), objconf, iter([]))
        ...     print(len(list(result)))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        3

    """
    td_kwargs = cast(dict[str, int], {k: objconf[k] for k in objconf if k})
    time = timedelta(**td_kwargs).total_seconds()
    return await AsyncTimeoutIterator(stream, time)


def parser(stream: Stream, objconf: Objconf, tuples: PipeTuples, **kwargs) -> Stream:
    """
    Parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf (obj): the item independent configuration (an Objectify
            instance).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Returns:
        Iter(dict): The output stream

    Examples:
        >>> from time import sleep
        >>> from meza.fntools import Objectify
        >>> from itertools import count
        >>>
        >>> objconf = Objectify({'milliseconds': 250})
        >>>
        >>> def gen_stream():
        ...     for x in count():
        ...         sleep(0.1)
        ...         yield {'x': x}
        >>>
        >>> len(list(parser(gen_stream(), objconf, iter([]))))
        3

    """
    # objconf only parses on __getitem__
    td_kwargs = cast(dict[str, int], {k: objconf[k] for k in objconf if k})
    time = timedelta(**td_kwargs).total_seconds()
    return TimeoutIterator(stream, time)


@operator(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> Stream:
    """
    An operator that asynchronously returns items from a stream until a
        certain amount of time has passed.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain any of the following
            keys: 'days', 'seconds', 'microseconds', 'milliseconds', 'minutes',
            'hours', 'weeks'.

            days (int): Number of days before signaling a timeout (default: 0)
            seconds (int): Number of seconds before signaling a timeout
                (default: 0)
            microseconds (int): Number of microseconds before signaling a
                timeout (default: 0)
            milliseconds (int): Number of milliseconds before signaling a
                timeout (default: 0)
            minutes (int): Number of minutes before signaling a timeout
                (default: 0)
            hours (int): Number of hours before signaling a timeout
                (default: 0)
            weeks (int): Number of weeks before signaling a timeout
                (default: 0)

    Returns:
        Deferred: twisted.internet.defer.Deferred stream

    Examples:
        >>> from itertools import count
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     items = ({'x': x} for x in count())
        ...     result = await async_pipe(items, conf={'milliseconds': 250})
        ...     print(len(list(result)))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        3

    """
    return await async_parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Stream:
    """
    An operator that returns items from a stream until a certain amount of
        time has passed.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain any of the following
            keys: 'days', 'seconds', 'microseconds', 'milliseconds', 'minutes',
            'hours', 'weeks'.

            days (int): Number of days before signaling a timeout (default: 0)
            seconds (int): Number of seconds before signaling a timeout
                (default: 0)
            microseconds (int): Number of microseconds before signaling a
                timeout (default: 0)
            milliseconds (int): Number of milliseconds before signaling a
                timeout (default: 0)
            minutes (int): Number of minutes before signaling a timeout
                (default: 0)
            hours (int): Number of hours before signaling a timeout
                (default: 0)
            weeks (int): Number of weeks before signaling a timeout
                (default: 0)

    Yields:
        dict: an item

    Examples:
        >>> from itertools import count
        >>> from time import sleep
        >>>
        >>> def gen_stream():
        ...     for x in count():
        ...         sleep(0.1)
        ...         yield {'x': x}
        >>>
        >>> len(list(pipe(gen_stream(), conf={'milliseconds': '250'})))
        3

    """
    return parser(*args, **kwargs)
