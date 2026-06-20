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

from collections.abc import Awaitable, Callable
from inspect import iscoroutinefunction
from typing import cast

import pygogo as gogo

from riko import Objconf, listize
from riko.types.general import Defaults, ItemArg, PipeTuples, Stream

from . import operator

DEFAULTS = Defaults()
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
    func = cast(Callable[[Stream], ItemArg], kwargs["func"])
    result = func(stream)
    return iter(listize(result))


async def async_parser(
    stream: Stream, objconf: Objconf, tuples: PipeTuples, **kwargs
) -> Stream:
    func = cast(
        Callable[[Stream], ItemArg | Awaitable[ItemArg]],
        kwargs["func"],
    )

    if iscoroutinefunction(func):
        result = await func(stream)
    else:
        result = func(stream)

    return iter(listize(result))


@operator(DEFAULTS, isasync=True)
def async_pipe(*args, **kwargs) -> Stream:
    """
    An operator that asynchronously performs an arbitrary (user-defined) function on
    a stream.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): User defined function to apply to the stream.

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     func = lambda stream: ({'y': item['x'] + 3} for item in stream)
        ...     items = ({'x': x} for x in range(5))
        ...     result = await async_pipe(items, func=func)
        ...     print(next(result))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {'y': 3}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS)
def pipe(*args, **kwargs) -> Stream:
    """
    An operator that performs an arbitrary (user-defined) function on a stream.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): User defined function to apply to the stream.

    Examples:
        >>> items = [{'x': x} for x in range(5)]
        >>> func = lambda stream: ({'y': item['x'] + 3} for item in stream)
        >>> next(pipe(items, func=func))
        {'y': 3}

    """
    return parser(*args, **kwargs)
