# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.timeout
~~~~~~~~~~~~~~~~~~~~
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
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import signal

from datetime import timedelta
from builtins import *  # noqa pylint: disable=unused-import

from . import operator
import pygogo as gogo

OPTS = {'ptype': 'int'}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


class TimeoutIterator(object):
    def __init__(self, elements, timeout=0):
        self.iter = iter(elements)
        self.timeout = timeout
        self.timedout = False
        self.started = False

    def _handler(self, signum, frame):
        self.timedout = True

    def __iter__(self):
        return self

    def __next__(self):
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
            raise StopIteration


def parser(stream, objconf, tuples, **kwargs):
    """ Parses the pipe content

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
    time = int(timedelta(**objconf).total_seconds())
    return TimeoutIterator(stream, time)


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """An aggregator that asynchronously returns items from a stream until a
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
        >>> def run(reactor):
        ...     callback = lambda x: print(len(list(x)))
        ...     d = async_pipe(gen_items(), conf={'seconds': '3'})
        ...     return d.addCallbacks(callback, logger.error)
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
def pipe(*args, **kwargs):
    """An operator that returns items from a stream until a certain amount of
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
