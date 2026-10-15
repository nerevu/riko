# vim: sw=4:ts=4:expandtab
"""
Splits a finite stream into independent copies.

The complete source is consumed before the branches are returned, and each
branch receives independent item copies.

Examples:

    Basic usage::

        >>> from riko.modules.split import pipe
        >>>
        >>> stream1, stream2 = pipe({"x": x} for x in range(5))
        >>> next(stream1)
        {'x': 0}

Attributes:

    OPTS: Splitter decoration options.
    DEFAULTS: Default splitter configuration.

"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from riko.base._logging import get_logger
from riko.types._enums import BasicCastType

from ._decorators import splitter

if TYPE_CHECKING:
    from logging import Logger

    from riko.types._options import DecorationOptions, Defaults
    from riko.types._streams import Cascade, Stream
    from riko.types._wrappers import PipeTuples

OPTS: DecorationOptions = {
    "extract": "splits",
    "ptype": BasicCastType.INT,
    "objectify": False,
}
DEFAULTS: Defaults = {"splits": 2}
logger: Logger = get_logger(__name__)


def parser(
    stream: Stream, splits: int, tuples: PipeTuples, **kwargs: object
) -> Cascade:
    """
    Splits the source into ``splits`` independent copies of the stream.

    Args:

        stream: The input stream. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        splits: The number of copies to create.

        tuples: Iterable of tuples of (item, splits) `item` is an element in the source
            stream. Note: this shares the `stream` iterator, so consuming it will
            consume `stream` as well.

    Yields:

        One stream per split. Each stream replays a deep copy of every input item.

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
def async_pipe(*args: Any, **kwargs: object) -> Cascade:
    """
    Asynchronously splits a stream into identical copies.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:

        items (Items): The input stream.

        conf (dict): The module configuration.

            splits (int): The number of copies to create. Cast to an int, so a
                numeric string is accepted (default: 2).

        context (Context): the run environment

    Yields:

        One stream per split. Each stream yields a deep copy of every input item, so
        the branches can be consumed independently and in any order.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = async_pipe({"x": x} for x in range(5))
        ...     print(next(await anext(result)))
        >>>
        >>> run(main)
        {'x': 0}

    """
    return parser(*args, **kwargs)


@splitter(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Cascade:
    """
    Splits a stream into identical copies.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:

        items (Items): The input stream.

        conf (dict): The module configuration.

            splits (int): The number of copies to create. Cast to an int, so a
                numeric string is accepted (default: 2).

        context (Context): the run environment

    Yields:

        One stream per split. Each stream yields a deep copy of every input item, so
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
