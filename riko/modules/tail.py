# vim: sw=4:ts=4:expandtab
"""
Provides functions for truncating a stream to the last N items.

Contrast this with the Truncate module, which limits the output to the first N
items.

Examples:
    basic usage::

        >>> from riko.modules.tail import pipe
        >>>
        >>> items = ({'x': x} for x in range(5))
        >>> next(pipe(items, conf={'count': 2}))
        {'x': 3}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections import deque

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types.configs import TailObjconf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = {"ptype": BasicCastType.INT}
DEFAULTS = Defaults({})
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: TailObjconf, tuples: PipeTuples, **kwargs
) -> Stream:
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
        List(dict): The output stream

    Examples:
        >>> from meza.fntools import Objectify
        >>> from itertools import repeat
        >>>
        >>> kwargs = {'count': 2}
        >>> objconf = Objectify(kwargs)
        >>> stream = ({'x': x} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> next(parser(stream, objconf, tuples, **kwargs))
        {'x': 3}

    """
    yield from deque(stream, int(objconf.count))


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> Stream:
    """
    An operator that asynchronously truncates a stream to the last N items.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'count'.

            count (int): desired stream length

    Returns:
        Awaitable: truncated stream

    Examples:
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     items = ({'x': x} for x in range(5))
        ...     result = await async_pipe(items, conf={'count': 2})
        ...     print(next(result))
        >>>
        >>> run(main)
        {'x': 3}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Stream:
    """
    An operator that truncates a stream to the last N items.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'count'.

            count (int): desired stream length

    Yields:
        dict: an item

    Examples:
        >>> items = [{'x': x} for x in range(5)]
        >>> next(pipe(items, conf={'count': 2}))
        {'x': 3}

    """
    return parser(*args, **kwargs)
