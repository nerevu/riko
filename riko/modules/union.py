# vim: sw=4:ts=4:expandtab
"""
Merges separate sources into a single stream of items.

Lazy: the source and every ``others`` stream are chained, not materialized.

Examples:
    Basic usage::

        >>> from riko.modules.union import pipe
        >>>
        >>> items = ({"x": x} for x in range(5))
        >>> other1 = ({"x": x + 5} for x in range(5))
        >>> other2 = ({"x": x + 10} for x in range(5))
        >>> len(list(pipe(items, others=[other1, other2])))
        15

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from collections.abc import Iterable
from itertools import chain
from logging import Logger
from typing import Any, cast

import pygogo as gogo

from riko.dotdict import DotDict
from riko.types.configs import DynamicConf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = Opts()
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Chains the source and every ``others`` stream into one stream.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: The pipe configuration. Unused.

        tuples: Iterable of (item, objconf). `item` is an element in the source stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

        others: Streams to append after the source. Defaults to no streams.

    Returns:
        A lazy chain of the source followed by each stream in ``others``.

    Examples:
        >>> from itertools import repeat
        >>>
        >>> stream = ({"x": x} for x in range(5))
        >>> other1 = ({"x": x + 5} for x in range(5))
        >>> other2 = ({"x": x + 10} for x in range(5))
        >>> kwargs = {"others": [other1, other2]}
        >>> tuples = zip(stream, repeat(None))
        >>> len(list(parser(stream, None, tuples, **kwargs)))
        15

    """
    _others = DotDict(kwargs).get("others", [])
    others = cast(Iterable[Stream], _others)
    return chain(stream, chain.from_iterable(others))


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously merges multiple source streams together.

    Lazy: streams are chained, not materialized.

    Args:
        items (Items): The source stream.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        others (list[Items]): Streams appended after ``items`` (default: none).

        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "union").

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
        ...     other1 = ({"x": x + 5} for x in range(5))
        ...     other2 = ({"x": x + 10} for x in range(5))
        ...     result = await async_pipe(items, others=[other1, other2])
        ...     print(len(list(result)))
        >>>
        >>> run(main)
        15

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Merges multiple source streams together.

    Lazy: streams are chained, not materialized.

    Args:
        items (Items): The source stream.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        others (list[Items]): Streams appended after ``items`` (default: none).

        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "union").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> items = ({"x": x} for x in range(5))
        >>> other1 = ({"x": x + 5} for x in range(5))
        >>> other2 = ({"x": x + 10} for x in range(5))
        >>> len(list(pipe(items, others=[other1, other2])))
        15

    """
    return parser(*args, **kwargs)
