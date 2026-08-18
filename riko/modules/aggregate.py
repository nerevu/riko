# vim: sw=4:ts=4:expandtab
"""
Provides functions for performing an arbitrary (user-defined) function on a stream

Examples:
    basic usage::

        >>> from riko.modules.aggregate import pipe
        >>>
        >>> items = [{'x': x} for x in range(5)]
        >>> func = lambda stream: ({'y': item['x'] + 3} for item in stream)
        >>> next(pipe(items, func=func))
        {'y': 3}

"""

from collections.abc import Callable
from inspect import iscoroutinefunction
from logging import Logger
from typing import Any, cast

import pygogo as gogo

from riko._iterutils import listize
from riko.types.configs import AggregateObjconf
from riko.types.general import Defaults, Item, PipeTuples, Stream

from . import operator

DEFAULTS: Defaults = Defaults()
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    stream: Stream, objconf: AggregateObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Parses the pipe content asynchronously

    Args:
        stream: The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf: the item independent configuration (an Objectify
            instance).

        tuples: Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs: Keyword arguments.

    Returns:
        Iter(dict): The output stream

    Examples:
        >>> from itertools import repeat
        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda stream: ({'y': item['x'] + 3} for item in stream)
        ...     stream = ({'x': x} for x in range(5))
        ...     tuples = zip(stream, repeat(None))
        ...     result = await async_parser(stream, None, tuples, func=func)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'y': 3}

    """
    func = cast(Callable[[Stream], Item], kwargs["func"])
    result = await func(stream) if iscoroutinefunction(func) else func(stream)
    listed = listize(result)
    return iter(cast(list[Item], listed))


def parser(
    stream: Stream, objconf: AggregateObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Parses the pipe content

    Args:
        stream: The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf: the item independent configuration (an Objectify
            instance).

        tuples: Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs: Keyword arguments.

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
    func = cast(Callable[[Stream], Item], kwargs["func"])
    result = func(stream)
    listed = listize(result)
    return iter(cast(list[Item], listed))


@operator(DEFAULTS, isasync=True)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    An operator that asynchronously performs an arbitrary (user-defined) function on
    a stream.

    Args:
        items: The source.
        kwargs: The keyword arguments passed to the wrapper

    Kwargs:
        func: User defined function to apply to the stream.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda stream: ({'y': item['x'] + 3} for item in stream)
        ...     items = ({'x': x} for x in range(5))
        ...     result = await async_pipe(items, func=func)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'y': 3}

    """
    return await async_parser(*args, **kwargs)


@operator(DEFAULTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    An operator that performs an arbitrary (user-defined) function on a stream.

    Args:
        items: The source.
        kwargs: The keyword arguments passed to the wrapper

    Kwargs:
        func: User defined function to apply to the stream.

    Examples:
        >>> items = [{'x': x} for x in range(5)]
        >>> func = lambda stream: ({'y': item['x'] + 3} for item in stream)
        >>> next(pipe(items, func=func))
        {'y': 3}

    """
    return parser(*args, **kwargs)
