# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.udf
~~~~~~~~~~~~~~~~
Provides functions for performing an arbitrary (user-defined) function on stream
items.

Examples:
    basic usage::

        >>> from riko.modules.udf import pipe
        >>>
        >>> items = [{'x': x} for x in range(5)]
        >>> func = lambda item: {'y': item['x'] + 3}
        >>> next(pipe(items, func=func))
        {'y': 3}
"""
from . import operator
import pygogo as gogo

logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream, objconf, tuples, **kwargs):
    """Parses the pipe content

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
        >>> func = lambda item: {'y': item['x'] + 3}
        >>> stream = ({'x': x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> next(parser(stream, None, tuples, func=func))
        {'y': 3}
    """
    return map(kwargs["func"], stream)


@operator(isasync=True)
def async_pipe(*args, **kwargs):
    """An operator that asynchronously performs an arbitrary (user-defined) function on
    items of a stream.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): User defined function to apply to each stream item.

    Returns:
        Deferred: twisted.internet.defer.Deferred truncated stream

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
        ...     func = lambda item: {'y': item['x'] + 3}
        ...     items = ({'x': x} for x in range(5))
        ...     d = async_pipe(items, func=func)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {'y': 3}
    """
    return parser(*args, **kwargs)


@operator()
def pipe(*args, **kwargs):
    """An operator that performs an arbitrary (user-defined) function on items of a
    stream.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): User defined function to apply to each stream item.

    Yields:
        dict: an item

    Examples:
        >>> items = [{'x': x} for x in range(5)]
        >>> func = lambda item: {'y': item['x'] + 3}
        >>> next(pipe(items, func=func))
        {'y': 3}
    """
    return parser(*args, **kwargs)
