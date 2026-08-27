# vim: sw=4:ts=4:expandtab
"""
Counts the number of items in a stream.

Examples:
    Basic usage::

        >>> from riko.modules.count import pipe
        >>>
        >>> stream = [{"x": x} for x in range(5)]
        >>> next(pipe(stream))["count"]
        5

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from collections.abc import Iterator
from logging import Logger
from typing import Any

import pygogo as gogo

from riko._iterutils import group_by
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = {"extract": "count_key"}
DEFAULTS: Defaults = {"count_key": None}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, count_key: str | None, tuples: PipeTuples, **kwargs: object
) -> int | Iterator[dict[str, int]]:
    """
    Counts items, optionally grouping them by a field.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        count_key: Field to group items before counting

        tuples: Iterable of (item, objconf). `item` is an element in the source stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

    Returns:
        - ``Iterator[{<group>: <count>}]`` when ``count_key`` is set
        - ``<count>`` when ``count_key`` is unset

    Examples:
        >>> from itertools import repeat
        >>>
        >>> stream = ({"x": x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> parser(stream, None, tuples)
        5
        >>> count_key = "word"
        >>> stream = [{"word": "two"}, {"word": "one"}, {"word": "two"}]
        >>> tuples = zip(stream, repeat(count_key))
        >>> counted = parser(stream, count_key, tuples)
        >>> next(counted)
        {'two': 2}
        >>> next(counted)
        {'one': 1}

    """
    if count_key:
        grouped = group_by(stream, count_key)
        counted = ({key: len(group)} for key, group in grouped)
    else:
        counted = len(list(stream))

    return counted


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> int | Iterator[dict[str, int]]:
    """
    Asynchronously counts items in a stream.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            count_key (str): Field to count by. Groups items in the stream by the given
                key and reports a count for each group (default: None).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the count is assigned to. Ignored when ``count_key`` is set
            (the group keys are used instead) or ``emit`` is True (default: "count").

        emit (bool): Whether to emit the count directly rather than assign it.
            Ignored when ``count_key`` is set. Overrides ``assign`` (default: False).

    Yields:
        - ``{<group>: <count>}`` when ``count_key`` is set
        - ``{<assign>: <count>}`` when ``emit`` is False and ``count_key`` is unset
        - ``<count>`` when ``emit`` is True and ``count_key`` is unset

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     items = ({"x": x} for x in range(5))
        ...     result = await async_pipe(items)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'count': 5}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> int | Iterator[dict[str, int]]:
    """
    Counts items in a stream.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            count_key (str): Field to count by. Groups items in the stream by the given
                key and reports a count for each group (default: None).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the count is assigned to. Ignored when ``count_key`` is set
            (the group keys are used instead) or ``emit`` is True (default: "count").

        emit (bool): Whether to emit the count directly rather than assign it.
            Ignored when ``count_key`` is set. Overrides ``assign`` (default: False).

    Yields:
        - ``{<group>: <count>}`` when ``count_key`` is set
        - ``{<assign>: <count>}`` when ``emit`` is False and ``count_key`` is unset
        - ``<count>`` when ``emit`` is True and ``count_key`` is unset

    Examples:
        >>> stream = [{"x": x} for x in range(5)]
        >>> next(pipe(stream, emit=True))
        5
        >>> next(pipe(stream))["count"]
        5
        >>> # Assign the count to "content":
        >>> next(pipe(stream, assign="content"))
        {'content': 5}
        >>> # Count by the "word" field:
        >>> stream = [{"word": "two"}, {"word": "one"}, {"word": "two"}]
        >>> counted = pipe(stream, conf={"count_key": "word"})
        >>> next(counted)
        {'two': 2}
        >>> next(counted)
        {'one': 1}

    """
    return parser(*args, **kwargs)
