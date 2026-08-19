# vim: sw=4:ts=4:expandtab
"""
Truncates a stream to the last N items.

Contrast this with the truncate module, which limits the output to the first N
items.

Not lazy in time, but bounded in memory: the whole source must be consumed
before the last item is known, though only ``count`` items are ever held. An
unbounded source never yields.

Examples:
    Basic usage::

        >>> from riko.modules.tail import pipe
        >>>
        >>> items = ({"x": x} for x in range(5))
        >>> next(pipe(items, conf={"count": 2}))
        {'x': 3}

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from collections import deque
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types.configs import TailObjconf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = {"ptype": BasicCastType.INT}
DEFAULTS = Defaults({})

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: TailObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Yields the last ``count`` items of the stream.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: The pipe configuration, containing `count`.

        tuples: Iterable of tuples of (item, objconf) `item` is an element in the
            source stream and `objconf` is the item configuration. Note: this shares
            the `stream` iterator, so consuming it will consume `stream` as well.

    Yields:
        The final ``count`` items, in source order.

    Examples:
        >>> from meza.fntools import Objectify
        >>> from itertools import repeat
        >>>
        >>> kwargs = {"count": 2}
        >>> objconf = Objectify(kwargs)
        >>> stream = ({"x": x} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> next(parser(stream, objconf, tuples, **kwargs))
        {'x': 3}

    """
    yield from deque(stream, int(objconf.count))


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously truncates a stream to the last N items.

    Consumes the whole source before yielding, but holds at most ``count``
    items. Do not use on an unbounded stream.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            count (int): The number of trailing items to keep. Cast to an int,
                so a numeric string is accepted. Required — the stream is empty
                when it is unset.

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "tail").

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
        ...     result = await async_pipe(items, conf={"count": 2})
        ...     print(next(result))
        >>>
        >>> run(main)
        {'x': 3}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Truncates a stream to the last N items.

    Consumes the whole source before yielding, but holds at most ``count``
    items. Do not use on an unbounded stream.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            count (int): The number of trailing items to keep. Cast to an int,
                so a numeric string is accepted. Required — the stream is empty
                when it is unset.

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "tail").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> items = [{"x": x} for x in range(5)]
        >>> next(pipe(items, conf={"count": 2}))
        {'x': 3}

    """
    return parser(*args, **kwargs)
