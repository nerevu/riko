# vim: sw=4:ts=4:expandtab
"""
Provides functions for returning items from a stream until a certain amount of
time has passed.

Contrast this with the truncate module, which also limits the number of items,
but returns items based on a count.

Examples:
    basic usage::

        >>> from time import sleep
        >>> from riko.modules.timeout import pipe
        >>>
        >>> def gen_items():
        ...     for x in range(50):
        ...         sleep(1)
        ...         yield {'x': x}
        >>>
        >>> len(list(pipe(gen_items(), conf={'seconds': '3'})))
        3

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import signal
from collections.abc import Iterable, Iterator
from datetime import timedelta
from types import FrameType
from typing import Self, TypeVar, cast

import pygogo as gogo

from riko import Objconf
from riko.cast import BasicCastType
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = {"ptype": BasicCastType.INT}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger

items = ("days", "hours", "microseconds", "milliseconds", "minutes", "seconds", "weeks")

T = TypeVar("T")


class TimeoutIterator(Iterator[T]):
    def __init__(self, elements: Iterable[T], timeout: int = 0) -> None:
        self.iter: Iterator[T] = iter(elements)
        self.timeout = timeout
        self.timedout: bool = False
        self.started: bool = False

    def _handler(self, _: int, frame: FrameType | None) -> None:
        self.timedout = True

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        if self.timedout:
            raise StopIteration
        elif not self.started:
            signal.signal(signal.SIGALRM, self._handler)
            signal.alarm(self.timeout)
            self.started = True
        try:
            return next(self.iter)
        except StopIteration:
            signal.alarm(0)
            self.timedout = True
            raise


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
        >>> from itertools import repeat, count
        >>>
        >>> kwargs = {'seconds': 3}
        >>> objconf = Objectify(kwargs)
        >>>
        >>> def gen_stream():
        ...     for x in count():
        ...         sleep(1)
        ...         yield {'x': x}
        >>>
        >>> stream = gen_stream()
        >>> tuples = zip(stream, repeat(objconf))
        >>> len(list(parser(stream, objconf, tuples, **kwargs)))
        3

    """
    # objconf only parses on __getitem__
    td_kwargs = cast(dict[str, int], {k: objconf[k] for k in objconf if k})
    time = int(timedelta(**td_kwargs).total_seconds())
    return TimeoutIterator(stream, time)


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> Stream:
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
        >>> from time import sleep
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def gen_items():
        ...     for x in range(50):
        ...         sleep(1)
        ...         yield {'x': x}
        >>>
        >>> async def run(reactor):
        ...     result = await async_pipe(gen_items(), conf={'seconds': '3'})
        ...     print(len(list(result)))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        3

    """
    return parser(*args, **kwargs)


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
        >>> from time import sleep
        >>>
        >>> def gen_items():
        ...     for x in range(50):
        ...         sleep(1)
        ...         yield {'x': x}
        >>>
        >>> len(list(pipe(gen_items(), conf={'seconds': '3'})))
        3

    """
    return parser(*args, **kwargs)
