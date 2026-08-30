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

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from logging import Logger
from typing import Any

import pygogo as gogo

from riko._iterutils import listize
from riko.modules._prepare import require_arg
from riko.types._configs import AggregateObjconf
from riko.types._options import Defaults
from riko.types._streams import Item, Items, Stream
from riko.types._wrappers import PipeTuples

from . import operator

DEFAULTS: Defaults = Defaults()
logger: Logger = gogo.Gogo(__name__, monolog=True).logger

type AggregateResult = Item | Items


async def async_parser(
    stream: Stream,
    objconf: AggregateObjconf,
    tuples: PipeTuples,
    *,
    func: Callable[[Stream], AggregateResult | Awaitable[AggregateResult]]
    | None = None,
    **kwargs: object,
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

        func: The function to apply to the stream. Awaited when it is an async
            function. Required.

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
    func = require_arg(func, "func", "aggregate", strict=True)
    unawaited = func(stream)
    result = await unawaited if isawaitable(unawaited) else unawaited
    return iter(listize(result))


def parser(
    stream: Stream,
    objconf: AggregateObjconf,
    tuples: PipeTuples,
    *,
    func: Callable[[Stream], AggregateResult] | None = None,
    **kwargs: object,
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

        func: The function to apply to the stream. Required.

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
    func = require_arg(func, "func", "aggregate", strict=True)
    result = func(stream)
    return iter(listize(result))


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
