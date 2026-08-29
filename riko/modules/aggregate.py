# vim: sw=4:ts=4:expandtab
"""
Applies an arbitrary (user-defined) function to a whole stream.

``func`` receives the entire stream and returns the replacement. Contrast this
with the udf module, which applies a function to each item individually.

Adds no buffering of its own, so laziness is inherited from ``func``: a
generator stays lazy, a list is already materialized.

Examples:
    Basic usage::

        >>> from riko.modules.aggregate import pipe
        >>>
        >>> items = [{"x": x} for x in range(5)]
        >>> func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        >>> next(pipe(items, func=func))
        {'y': 3}

Attributes:
    DEFAULTS: Default operator configuration.

"""

from collections.abc import Callable
from inspect import iscoroutinefunction
from logging import Logger
from typing import Any, cast

import pygogo as gogo

from riko._iterutils import listize
from riko.modules._prepare import require_kwarg
from riko.types._configs import AggregateObjconf
from riko.types._options import Defaults
from riko.types._streams import Item, Stream
from riko.types._wrappers import PipeTuples

from . import operator

DEFAULTS: Defaults = Defaults()
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    stream: Stream, objconf: AggregateObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Asynchronously applies ``func`` to the whole stream.

    A result that is not iterable becomes a single item stream; an iterable is
    passed through unchanged.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: the item independent configuration. Unused.

        tuples: Iterable of (item, objconf). `item` is an element in the source stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

    Kwargs:
        func (callable): The function to apply to the stream. Awaited when it
            is an async function. Required.

    Returns:
        The transformed stream.

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> from itertools import repeat
        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        ...     stream = ({"x": x} for x in range(5))
        ...     tuples = zip(stream, repeat(None))
        ...     result = await async_parser(stream, None, tuples, func=func)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'y': 3}

    """
    func: Callable[[Stream], Item] = require_kwarg(kwargs, "func", "aggregate")
    result = await func(stream) if iscoroutinefunction(func) else func(stream)
    listed = listize(result)
    return iter(cast(list[Item], listed))


def parser(
    stream: Stream, objconf: AggregateObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Applies ``func`` to the whole stream.

    A result that is not iterable becomes a single item stream; an iterable is
    passed through unchanged.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: the item independent configuration. Unused.

        tuples: Iterable of (item, objconf). `item` is an element in the source stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

    Kwargs:
        func (callable): The function to apply to the stream. Required.

    Returns:
        The transformed stream.

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> from itertools import repeat
        >>>
        >>> func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        >>> stream = ({"x": x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> next(parser(stream, None, tuples, func=func))
        {'y': 3}

    """
    func: Callable[[Stream], Item] = require_kwarg(kwargs, "func", "aggregate")
    result = func(stream)
    listed = listize(result)
    return iter(cast(list[Item], listed))


@operator(DEFAULTS, isasync=True)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously applies an arbitrary (user-defined) function to a stream.

    ``func`` is handed the whole stream, not one item at a time. Adds no
    buffering, so laziness is inherited from ``func``.

    Args:
        items (Items): The source stream.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        func (callable): The function to apply to the stream. A result that is
            not iterable becomes a single item stream. Can be either a sync or async
            function. Required.

        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "aggregate").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<result>`` when ``emit`` is True (default)
        - ``{<assign>: <result>}`` when ``emit`` is False

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        ...     items = ({"x": x} for x in range(5))
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
    Applies an arbitrary (user-defined) function to a stream.

    ``func`` is handed the whole stream, not one item at a time. Adds no
    buffering, so laziness is inherited from ``func``.

    Args:
        items (Items): The source stream.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        func (callable): The function to apply to the stream. A result that is
            not iterable becomes a single item stream. Required.

        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "aggregate").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<result>`` when ``emit`` is True (default)
        - ``{<assign>: <result>}`` when ``emit`` is False

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> items = [{"x": x} for x in range(5)]
        >>> func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        >>> next(pipe(items, func=func))
        {'y': 3}

    """
    return parser(*args, **kwargs)
