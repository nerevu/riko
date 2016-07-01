# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.reverse
~~~~~~~~~~~~~~~~~~~~
Provides functions for flipping the order of all items in a stream.

Examples:
    basic usage::

        >>> from riko.modules.reverse import pipe
        >>> next(pipe({'x': x} for x in range(5))) == {'x': 4}
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import operator
import pygogo as gogo

# disable `dictize` since we do not need to access the configuration
OPTS = {'dictize': False}
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
        >>> from itertools import repeat
        >>>
        >>> kwargs = {}
        >>> stream = ({'x': x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> next(parser(stream, None, tuples, **kwargs)) == {'x': 4}
        True
    """
    return reversed(list(stream))


@operator(isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """An aggregator that asynchronously reverses the order of source items in
    a stream. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the number of
            counted items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x) == {'x': 4})
        ...     items = ({'x': x} for x in range(5))
        ...     d = async_pipe(items)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        True
    """
    return parser(*args, **kwargs)


@operator(**OPTS)
def pipe(*args, **kwargs):
    """An operator that eagerly reverses the order of source items in a stream.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Yields:
        dict: an item

    Examples:
        >>> items = ({'x': x} for x in range(5))
        >>> next(pipe(items)) == {'x': 4}
        True
    """
    return parser(*args, **kwargs)
