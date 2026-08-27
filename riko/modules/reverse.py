# vim: sw=4:ts=4:expandtab
"""
Flips the order of all items in a stream.

Not lazy: reversing needs the last item first, so the source is materialized
into memory and cannot be unbounded.

Examples:
    Basic usage::

        >>> from riko.modules.reverse import pipe
        >>>
        >>> next(pipe({"x": x} for x in range(5)))
        {'x': 4}

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko.types.configs import DynamicConf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = Opts()
DEFAULTS: Defaults = Defaults({})
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Returns the stream in reverse order.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: The pipe configuration. Unused.

        tuples: Iterable of (item, objconf). `item` is an element in the source stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

    Returns:
        The source items in reverse order.

    Examples:
        >>> from itertools import repeat
        >>>
        >>> stream = ({"x": x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> next(parser(stream, None, tuples))
        {'x': 4}

    """
    return reversed(list(stream))


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously reverses the order of source items in a stream.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:
        items (Items): The source stream.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "reverse").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     items = ({"x": x} for x in range(5))
        ...     result = await async_pipe(items)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'x': 4}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Reverses the order of source items in a stream.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:
        items (Items): The source stream.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "reverse").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> items = ({"x": x} for x in range(5))
        >>> next(pipe(items))
        {'x': 4}

    """
    return parser(*args, **kwargs)
