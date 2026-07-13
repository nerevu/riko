# vim: sw=4:ts=4:expandtab
"""
Provides functions for splitting a stream into identical copies

Use split when you want to perform different operations on data from the same
stream. The Union module is the reverse of Split, it merges multiple input
streams into a single combined stream.

Examples:
    basic usage::

        >>> from riko.modules.split import pipe
        >>>
        >>> stream1, stream2 = pipe({'x': x} for x in range(5))
        >>> next(stream1)
        {'x': 0}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Iterator
from copy import deepcopy

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types.general import Defaults, Opts, Stream

from . import splitter

OPTS: Opts = {"extract": "splits", "ptype": BasicCastType.INT, "objectify": False}
DEFAULTS: Defaults = {"splits": 2}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream: Stream, splits: int, tuples, **kwargs) -> Iterator[Stream]:
    """
    Parses the pipe content

    Args:
        stream (Iter[dict]): The source stream. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        splits (int): the number of copies to create.

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, splits)
            `item` is an element in the source stream (a DotDict instance)
            and `splits` is an int. Note: this shares the `stream` iterator,
            so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Yields:
        Iter(dict): a stream of items

    Examples:
        >>> from itertools import repeat
        >>>
        >>> conf = {'splits': 3}
        >>> kwargs = {'conf': conf}
        >>> stream = (({'x': x}) for x in range(5))
        >>> tuples = zip(stream, repeat(conf))
        >>> stream1, stream2, stream3 = parser(stream, conf['splits'], tuples, **kwargs)
        >>> next(stream1)
        {'x': 0}

    """
    source = list(stream)

    for _ in range(splits):
        yield map(deepcopy, source)


@splitter(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> Iterator[Stream]:
    """
    An operator that asynchronously and eagerly splits a stream into identical
    copies. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source stream.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'splits'.

            splits (int): the number of copies to create (default: 2).

    Returns:
        Deferred: twisted.internet.defer.Deferred iterable of streams

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     result = await async_pipe({'x': x} for x in range(5))
        ...     print(next(next(result)))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {'x': 0}

    """
    return parser(*args, **kwargs)


@splitter(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Iterator[Stream]:
    """
    An operator that eagerly splits a stream into identical copies.
    Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source stream.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'splits'.

            splits (int): the number of copies to create (default: 2).

    Yields:
        Iter(dict): a stream of items

    Examples:
        >>> items = [{'x': x} for x in range(5)]
        >>> stream1, stream2 = pipe(items)
        >>> next(stream1)
        {'x': 0}
        >>> next(stream2)
        {'x': 0}
        >>> len(list(pipe(items, conf={'splits': '3'})))
        3

    """
    return parser(*args, **kwargs)
