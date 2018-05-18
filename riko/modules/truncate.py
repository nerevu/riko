# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.truncate
~~~~~~~~~~~~~~~~~~~~~
Provides functions for returning a specified number of items from a stream.

Contrast this with the tail module, which also limits the number of items,
but returns items from the bottom of the stream.

Examples:
    basic usage::

        >>> from riko.modules.truncate import pipe
        >>>
        >>> items = ({'x': x} for x in range(5))
        >>> len(list(pipe(items, conf={'count': '4'})))
        4

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from itertools import islice

from builtins import *  # noqa pylint: disable=unused-import

from . import operator
import pygogo as gogo

OPTS = {'ptype': 'int'}
DEFAULTS = {'start': 0}
logger = gogo.Gogo(__name__, monolog=True).logger


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
        >>> from meza.fntools import Objectify
        >>> from itertools import repeat
        >>>
        >>> kwargs = {'count': 4, 'start': 0}
        >>> objconf = Objectify(kwargs)
        >>> stream = ({'x': x} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> len(list(parser(stream, objconf, tuples, **kwargs)))
        4
    """
    start = objconf.start
    stop = start + objconf.count
    return islice(stream, start, stop)


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """An aggregator that asynchronously returns a specified number of items
    from a stream.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'count'.
            May contain the key 'start'.

            count (int): desired stream length
            start (int): starting location (default: 0)

    Returns:
        Deferred: twisted.internet.defer.Deferred truncated stream

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(len(list(x)))
        ...     items = ({'x': x} for x in range(5))
        ...     d = async_pipe(items, conf={'count': 4})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        4
    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """An operator that returns a specified number of items from a stream.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'count'.
            May contain the key 'start'.

            start (int): starting location (default: 0)
            count (int): desired stream length

    Yields:
        dict: an item

    Examples:
        >>> items = [{'x': x} for x in range(5)]
        >>> len(list(pipe(items, conf={'count': '4'})))
        4
        >>> stream = pipe(items, conf={'count': '2', 'start': '2'})
        >>> next(stream) == {'x': 2}
        True
    """
    return parser(*args, **kwargs)
