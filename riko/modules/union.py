# vim: sw=4:ts=4:expandtab
"""
Provides functions for merging separate sources into a single stream of items.

Examples:
    basic usage::

        >>> from riko.modules.union import pipe
        >>>
        >>> items = ({'x': x} for x in range(5))
        >>> other1 = ({'x': x + 5} for x in range(5))
        >>> other2 = ({'x': x + 10} for x in range(5))
        >>> len(list(pipe(items, others=[other1, other2])))
        15

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Iterable
from itertools import chain
from typing import cast

import pygogo as gogo

from riko import Objconf
from riko.dotdict import DotDict
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS = Opts()
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


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

    Kwargs:
        others (List[Iter(dict)]): List of streams to join

    Returns:
        Iter(dict): The output stream

    Examples:
        >>> from itertools import repeat
        >>>
        >>> stream = ({'x': x} for x in range(5))
        >>> other1 = ({'x': x + 5} for x in range(5))
        >>> other2 = ({'x': x + 10} for x in range(5))
        >>> kwargs = {'others': [other1, other2]}
        >>> tuples = zip(stream, repeat(None))
        >>> len(list(parser(stream, None, tuples, **kwargs)))
        15

    """
    kwargs = DotDict(kwargs)
    others = cast(Iterable[Stream], kwargs["others"])
    return chain(stream, chain.from_iterable(others))


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> Stream:
    """
    An operator that asynchronously merges multiple source streams together.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        others (List[Iter(dict)]): List of streams to join

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the merged streams

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     items = ({'x': x} for x in range(5))
        ...     other1 = ({'x': x + 5} for x in range(5))
        ...     other2 = ({'x': x + 10} for x in range(5))
        ...     result = await async_pipe(items, others=[other1, other2])
        ...     print(len(list(result)))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        15

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Stream:
    """
    An operator that merges multiple streams together.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        others (List[Iter(dict)]): List of streams to join

    Yields:
        dict: a merged stream item

    Examples:
        >>> items = ({'x': x} for x in range(5))
        >>> other1 = ({'x': x + 5} for x in range(5))
        >>> other2 = ({'x': x + 10} for x in range(5))
        >>> len(list(pipe(items, others=[other1, other2])))
        15

    """
    return parser(*args, **kwargs)
