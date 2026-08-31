# vim: sw=4:ts=4:expandtab
"""
Splits a stream into identical copies.

Use split when you want to perform different operations on data from the same
stream. The union module is the reverse of split, it merges multiple input
streams into a single combined stream.

Not lazy: handing out independent copies requires the whole stream up front, so
the source is materialized and each branch replays it. For lazy fan-out use
named ``send``/``receive`` channels instead. Each branch deep copies its items,
so mutating one branch never affects another.

Examples:
    Basic usage::

        >>> from riko.modules.split import pipe
        >>>
        >>> stream1, stream2 = pipe({"x": x} for x in range(5))
        >>> next(stream1)
        {'x': 0}

Attributes:
    OPTS: Splitter wrapper options.
    DEFAULTS: Default splitter configuration.

"""

from collections.abc import Iterator
from copy import deepcopy
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types._options import Defaults, Opts
from riko.types._streams import Stream
from riko.types._wrappers import PipeTuples

from . import splitter

OPTS: Opts = {"extract": "splits", "ptype": BasicCastType.INT, "objectify": False}
DEFAULTS: Defaults = {"splits": 2}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, splits: int, tuples: PipeTuples, **kwargs: object
) -> Iterator[Stream]:
    """
    Yields ``splits`` independent copies of the source stream.

    Args:
        stream: The source stream. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        splits: The number of copies to create.

        tuples: Iterable of tuples of (item, splits) `item` is an element in the source
            stream. Note: this shares the `stream` iterator, so consuming it will
            consume `stream` as well.

    Yields:
        One stream per split. Each stream replays a deep copy of every source item.

    Examples:
        >>> from itertools import repeat
        >>>
        >>> conf = {"splits": 3}
        >>> kwargs = {"conf": conf}
        >>> stream = (({"x": x}) for x in range(5))
        >>> tuples = zip(stream, repeat(conf))
        >>> stream1, stream2, stream3 = parser(stream, conf["splits"], tuples, **kwargs)
        >>> next(stream1)
        {'x': 0}

    """
    source = list(stream)

    for _ in range(splits):
        yield map(deepcopy, source)


@splitter(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Iterator[Stream]:
    """
    Asynchronously splits a stream into identical copies.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            splits (int): The number of copies to create. Cast to an int, so a
                numeric string is accepted (default: 2).

        context (Context): the execution context

    Yields:
        One stream per split. Each stream yields a deep copy of every source item, so
        the branches can be consumed independently and in any order.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({"x": x} for x in range(5))
        ...     print(next(next(result)))
        >>>
        >>> run(main)
        {'x': 0}

    """
    return parser(*args, **kwargs)


@splitter(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Iterator[Stream]:
    """
    Splits a stream into identical copies.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            splits (int): The number of copies to create. Cast to an int, so a
                numeric string is accepted (default: 2).

        context (Context): the execution context

    Yields:
        One stream per split. Each stream yields a deep copy of every source item, so
        the branches can be consumed independently and in any order.

    Examples:
        >>> items = [{"x": x} for x in range(5)]
        >>> stream1, stream2 = pipe(items)
        >>> next(stream1)
        {'x': 0}
        >>> next(stream2)
        {'x': 0}
        >>> len(list(pipe(items, conf={"splits": "3"})))
        3

    """
    return parser(*args, **kwargs)
