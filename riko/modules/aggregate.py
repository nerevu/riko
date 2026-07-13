# vim: sw=4:ts=4:expandtab
"""
riko.modules.aggregate
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for performing an arbitrary (user-defined) function on stream
items.

Examples:
    basic usage::

        >>> from riko.modules.aggregate import pipe
        >>>
        >>> items = [{'x': x} for x in range(5)]
        >>> func = lambda stream: ({'y': item['x'] + 3} for item in stream)
        >>> next(pipe(items, func=func))
        {'y': 3}

"""

import pygogo as gogo

from . import operator

logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream, objconf, tuples, **kwargs):
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
        >>> from itertools import repeat
        >>>
        >>> func = lambda stream: ({'y': item['x'] + 3} for item in stream)
        >>> stream = ({'x': x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> next(parser(stream, None, tuples, func=func))
        {'y': 3}

    """
    # TODO: this should work even when func returns a list
    return kwargs["func"](stream)


@operator(isasync=True)
def async_pipe(*args, **kwargs):
    """
    An operator that asynchronously performs an arbitrary (user-defined) function on
    stream items.

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
        ...     func = lambda stream: ({'y': item['x'] + 3} for item in stream)
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
    """
    An operator that performs an arbitrary (user-defined) function on stream items.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): User defined function to apply to each stream item.

    Yields:
        dict: an item

    Examples:
        >>> items = [{'x': x} for x in range(5)]
        >>> func = lambda stream: ({'y': item['x'] + 3} for item in stream)
        >>> next(pipe(items, func=func))
        {'y': 3}

    """
    return parser(*args, **kwargs)
