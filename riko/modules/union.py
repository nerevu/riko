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
from logging import Logger
from typing import Any, cast

import pygogo as gogo

from riko.dotdict import DotDict
from riko.types.configs import DynamicConf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = Opts()
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: object
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
    _others = DotDict(kwargs).get("others", [])
    others = cast(Iterable[Stream], _others)
    return chain(stream, chain.from_iterable(others))


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    An operator that asynchronously merges multiple source streams together.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        others (List[Iter(dict)]): List of streams to join

    Returns:
        Awaitable: iterator of the merged streams

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     items = ({'x': x} for x in range(5))
        ...     other1 = ({'x': x + 5} for x in range(5))
        ...     other2 = ({'x': x + 10} for x in range(5))
        ...     result = await async_pipe(items, others=[other1, other2])
        ...     print(len(list(result)))
        >>>
        >>> run(main)
        15

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
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
