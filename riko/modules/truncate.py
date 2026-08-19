# vim: sw=4:ts=4:expandtab
"""
Returns a specified number of items from a stream.

Contrast this with the tail module, which also limits the number of items, but
returns items from the bottom of the stream.

Lazy: consumption stops once ``count`` items have been yielded, so the rest of
the source is never read.

Examples:
    Basic usage::

        >>> from riko.modules.truncate import pipe
        >>>
        >>> items = ({"x": x} for x in range(5))
        >>> len(list(pipe(items, conf={"count": "4"})))
        4

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from itertools import islice
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types.configs import TruncateObjconf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = {"ptype": BasicCastType.INT}
DEFAULTS: Defaults = {"start": 0, "count": 0}

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: TruncateObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Returns the ``count`` items beginning at ``start``.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: The pipe configuration, containing `start` and `count`.

        tuples: Iterable of tuples of (item, objconf) `item` is an element in the
            source stream and `objconf` is the item configuration. Note: this shares
            the `stream` iterator, so consuming it will consume `stream` as well.

    Returns:
        A lazy slice of the source, empty when ``count`` is 0.

    Examples:
        >>> from meza.fntools import Objectify
        >>> from itertools import repeat
        >>>
        >>> kwargs = {"count": 4, "start": 0}
        >>> objconf = Objectify(kwargs)
        >>> stream = ({"x": x} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> len(list(parser(stream, objconf, tuples, **kwargs)))
        4

    """
    start = int(objconf.start)
    stop = start + int(objconf.count)
    return islice(stream, start, stop)


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously returns a specified number of items from a stream.

    Lazy: the source is read only until ``count`` items have been yielded.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            start (int): The number of leading items to skip (default: 0).

            count (int): The number of items to keep. Cast to an int, so a
                numeric string is accepted. The stream is empty when it is 0
                (default: 0).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "truncate").

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
        ...     result = await async_pipe(items, conf={"count": 4})
        ...     print(len(list(result)))
        >>>
        >>> run(main)
        4

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Returns a specified number of items from a stream.

    Lazy: the source is read only until ``count`` items have been yielded.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            start (int): The number of leading items to skip (default: 0).

            count (int): The number of items to keep. Cast to an int, so a
                numeric string is accepted. The stream is empty when it is 0
                (default: 0).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "truncate").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> items = [{"x": x} for x in range(5)]
        >>> len(list(pipe(items, conf={"count": "4"})))
        4
        >>> stream = pipe(items, conf={"count": "2", "start": "2"})
        >>> next(stream)
        {'x': 2}

    """
    return parser(*args, **kwargs)
